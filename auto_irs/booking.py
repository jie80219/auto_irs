"""訂票主流程：程式填表 → 使用者在介面輸入驗證碼 → 程式完成選車次、填資料、確認訂位。"""

from __future__ import annotations

import re
import time as systime
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

from . import page_selectors as S
from .config import TICKET_TYPES, Config
from .ticket import TicketInfo, parse_ticket
from .timeslots import TrainOption, pick_earliest, pick_slot

SCREENSHOT_DIR = Path("screenshots")
TICKET_DIR = Path("tickets")
LOG_FILE = Path("bookings.log")

REFRESH = "__refresh__"


class Outcome(Enum):
    SUCCESS = "success"
    RETRY = "retry"


class StepError(RuntimeError):
    """頁面結構與預期不符，需要使用者手動接手。"""


class Cancelled(RuntimeError):
    """使用者在介面按了停止。"""


class UI(Protocol):
    """訂票流程與介面之間的溝通管道。"""

    def log(self, message: str) -> None: ...

    def ask_captcha(self, image: bytes, timeout: float) -> str | None:
        """顯示驗證碼圖片並等待輸入；回傳驗證碼、REFRESH，逾時回傳 None。"""

    def cancelled(self) -> bool: ...


@dataclass(frozen=True)
class BookingResult:
    info: TicketInfo | None
    image: Path | None
    summary: str


def _check(ui: UI) -> None:
    if ui.cancelled():
        raise Cancelled()


def _screenshot(page: Page, ui: UI, name: str) -> Path | None:
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        ui.log(f"已存截圖：{path}")
        return path
    except Exception:
        return None


def _error_text(page: Page) -> str | None:
    errors = page.locator(S.ERROR_MESSAGE)
    if errors.count() and errors.first.is_visible():
        return errors.first.inner_text().strip() or None
    return None


def _click_label(page: Page, text: str) -> None:
    label = page.locator(f'label:has-text("{text}")').first
    if label.count() == 0:
        raise StepError(f"找不到選項「{text}」")
    label.click()


# ---------- 第一頁 ----------

def fill_search_form(page: Page, cfg: Config) -> None:
    page.goto(S.BOOKING_URL, wait_until="domcontentloaded")
    cookie = page.locator(S.COOKIE_ACCEPT)
    if cookie.count() and cookie.is_visible():
        cookie.click()

    page.select_option(S.START_STATION, label=cfg.from_station)
    page.select_option(S.DEST_STATION, label=cfg.to_station)

    _click_label(page, S.CAR_CLASS_LABEL[cfg.car_class])
    _click_label(page, S.SEAT_PREF_LABEL[cfg.seat_pref])

    # 日期欄位是唯讀的 flatpickr，直接寫入值並觸發 change
    date_str = cfg.travel_date.strftime("%Y/%m/%d")
    page.evaluate(
        """([selector, value]) => {
            document.querySelectorAll(selector).forEach(el => {
                if (el._flatpickr) { el._flatpickr.setDate(value, true); }
                el.value = value;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            });
            const alt = document.querySelector(selector + ' ~ input');
            if (alt) alt.value = value;
        }""",
        [S.DATE_INPUT, date_str],
    )

    slot_values = page.eval_on_selector_all(f"{S.TIME_SELECT} option", "opts => opts.map(o => o.value)")
    slot = pick_slot(slot_values, cfg.depart_after)
    if slot is None:
        raise StepError("無法解析出發時段下拉選單")
    page.select_option(S.TIME_SELECT, value=slot)

    for name, (row, code) in TICKET_TYPES.items():
        page.select_option(S.TICKET_AMOUNT.format(row=row), value=f"{cfg.tickets[name]}{code}")


def solve_captcha(page: Page, cfg: Config, ui: UI) -> Outcome:
    """把驗證碼圖片交給介面，由使用者輸入後代為送出，並等到第二頁或錯誤訊息。"""
    while True:
        _check(ui)
        image = page.locator(S.CAPTCHA_IMAGE).screenshot()
        answer = ui.ask_captcha(image, cfg.captcha_timeout_sec)
        _check(ui)
        if answer is None:
            ui.log("等待驗證碼逾時")
            return Outcome.RETRY
        if answer == REFRESH:
            page.locator(S.CAPTCHA_REFRESH).click()
            page.wait_for_timeout(800)
            continue

        captcha = page.locator(S.CAPTCHA_INPUT)
        captcha.fill(answer)
        captcha.press("Enter")
        ui.log("已送出查詢")

        deadline = systime.monotonic() + 20
        while systime.monotonic() < deadline:
            if page.locator(S.TRAIN_RADIO).count():
                return Outcome.SUCCESS
            error = _error_text(page)
            if error:
                ui.log(f"查詢失敗：{error}")
                return Outcome.RETRY
            page.wait_for_timeout(300)
        raise PlaywrightTimeout("送出驗證碼後 20 秒內沒有回應")


# ---------- 第二頁 ----------

def read_trains(page: Page) -> list[TrainOption]:
    raw = page.eval_on_selector_all(
        S.TRAIN_RADIO,
        """radios => radios.map((r, i) => ({
            index: i,
            code: r.getAttribute('QueryCode') || '',
            dep: r.getAttribute('QueryDeparture') || '',
            arr: r.getAttribute('QueryArrival') || '',
            text: (r.closest('label') || r.parentElement).innerText || '',
        }))""",
    )
    trains = []
    for item in raw:
        dep, arr = item["dep"], item["arr"]
        if not dep:
            times = re.findall(r"\b(\d{2}:\d{2})\b", item["text"])
            dep, arr = (times + ["", ""])[:2]
        if not dep:
            continue
        trains.append(
            TrainOption(
                index=item["index"],
                code=item["code"],
                departure=datetime.strptime(dep, "%H:%M").time(),
                arrival=datetime.strptime(arr, "%H:%M").time() if arr else None,
            )
        )
    return trains


def choose_train(page: Page, cfg: Config, ui: UI) -> TrainOption | None:
    trains = read_trains(page)
    if not trains:
        raise StepError("第二頁找不到任何車次")
    chosen = pick_earliest(trains, cfg.depart_after, cfg.depart_before)
    if chosen is None:
        listed = ", ".join(f"{t.code}({t.departure:%H:%M})" for t in trains)
        ui.log(f"沒有符合時間區間的車次，可訂班次：{listed}")
        return None
    page.locator(S.TRAIN_RADIO).nth(chosen.index).check(force=True)
    ui.log(f"選擇車次 {chosen.code}，{chosen.departure:%H:%M} 出發")
    page.locator(S.TRAIN_SUBMIT).click()
    return chosen


# ---------- 第三頁 ----------

def fill_passenger(page: Page, cfg: Config, use_member: bool) -> None:
    page.wait_for_selector(S.ID_INPUT, timeout=15_000)
    page.fill(S.ID_INPUT, cfg.id_number)

    if use_member and cfg.member_id:
        _click_label(page, S.MEMBER_TGO_LABEL)
        same = page.locator(S.MEMBER_SAME_AS_TAKER)
        if cfg.member_id == cfg.id_number and same.count() and same.is_visible():
            same.check()
        else:
            page.locator(S.MEMBER_NUMBER_INPUT).fill(cfg.member_id)

    if cfg.passenger_ids:
        inputs = page.locator(S.PASSENGER_ID_INPUT)
        visible = [inputs.nth(i) for i in range(inputs.count()) if inputs.nth(i).is_visible()]
        if len(visible) < len(cfg.passenger_ids):
            raise StepError(f"確認頁只有 {len(visible)} 個乘客身分證欄位，但填了 {len(cfg.passenger_ids)} 組")
        for field, value in zip(visible, cfg.passenger_ids):
            field.fill(value)

    page.locator(S.AGREE_CHECKBOX).check(force=True)


def confirm_booking(page: Page) -> str | None:
    page.locator(S.CONFIRM_SUBMIT).click()
    deadline = systime.monotonic() + 30
    while systime.monotonic() < deadline:
        match = re.search(S.PNR_TEXT_PATTERN, page.inner_text("body"))
        if match:
            return match[1]
        error = _error_text(page)
        if error:
            raise StepError(f"確認訂位失敗：{error}")
        page.wait_for_timeout(500)
    return None


# ---------- 第四頁 ----------

def capture_ticket(page: Page, pnr: str) -> tuple[TicketInfo, Path]:
    """截下「訂位明細」區塊存成 tickets/<日期>-<訂位代號>.png，並解析明細文字。"""
    section = page.evaluate_handle(
        """([title, needles]) => {
            const heading = [...document.querySelectorAll('h1,h2,h3,h4,div,span,p')]
                .find(el => el.childElementCount === 0 && el.textContent.trim() === title);
            let node = heading;
            while (node && !needles.every(n => node.innerText.includes(n))) node = node.parentElement;
            return node && node !== document.body ? node : null;
        }""",
        [S.TICKET_SECTION_TITLE, list(S.TICKET_SECTION_MUST_CONTAIN)],
    ).as_element()

    TICKET_DIR.mkdir(exist_ok=True)
    path = TICKET_DIR / f"{datetime.now():%Y%m%d}-{pnr}.png"
    if section:
        section.screenshot(path=str(path))
        text = section.inner_text()
    else:
        page.screenshot(path=str(path), full_page=True)
        text = page.inner_text("body")
    return parse_ticket(pnr, text), path


# ---------- 整體流程 ----------

def attempt(page: Page, cfg: Config, ui: UI, use_member: bool, dry_run: bool) -> BookingResult | None:
    ui.log("開啟高鐵訂票頁並填寫查詢條件")
    fill_search_form(page, cfg)
    if solve_captcha(page, cfg, ui) is not Outcome.SUCCESS:
        return None

    _check(ui)
    if choose_train(page, cfg, ui) is None:
        return None

    _check(ui)
    fill_passenger(page, cfg, use_member)
    ui.log("已填好取票人資料")
    if dry_run:
        image = _screenshot(page, ui, "dry-run")
        return BookingResult(None, image, "測試模式：已填好取票人資料，未送出訂位")

    pnr = confirm_booking(page)
    if not pnr:
        raise StepError("送出後找不到訂位代號")

    info, image = capture_ticket(page, pnr)
    summary = f"{cfg.travel_date:%Y/%m/%d} {cfg.from_station}→{cfg.to_station} {info.summary()}"
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {summary} {image}\n")
    return BookingResult(info, image, summary)


def wait_until(start_at: datetime, ui: UI) -> None:
    ui.log(f"等到 {start_at:%Y-%m-%d %H:%M} 開始")
    while (remaining := (start_at - datetime.now()).total_seconds()) > 0:
        _check(ui)
        systime.sleep(min(remaining, 0.5))


def run(cfg: Config, ui: UI, *, use_member: bool = True, dry_run: bool = False,
        headless: bool = False) -> BookingResult | None:
    """執行訂票；成功回傳結果，重試用盡回傳 None。StepError / Cancelled 會往外拋。"""
    if cfg.start_at:
        wait_until(cfg.start_at, ui)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(locale="zh-TW", viewport={"width": 1200, "height": 900})
        try:
            for n in range(1, cfg.max_attempts + 1):
                _check(ui)
                ui.log(f"第 {n}/{cfg.max_attempts} 輪")
                try:
                    result = attempt(page, cfg, ui, use_member, dry_run)
                except StepError as exc:
                    _screenshot(page, ui, "step-error")
                    if not headless:
                        ui.log(f"{exc}；瀏覽器保持開啟，可手動完成，按「停止」關閉")
                        while not ui.cancelled():
                            page.wait_for_timeout(500)
                    raise
                except PlaywrightTimeout as exc:
                    _screenshot(page, ui, "timeout")
                    ui.log(f"頁面逾時：{exc}")
                    result = None

                if result:
                    return result
                if n < cfg.max_attempts:
                    ui.log(f"{cfg.retry_interval_sec} 秒後重試")
                    deadline = systime.monotonic() + cfg.retry_interval_sec
                    while systime.monotonic() < deadline:
                        _check(ui)
                        systime.sleep(0.5)
            return None
        finally:
            browser.close()
