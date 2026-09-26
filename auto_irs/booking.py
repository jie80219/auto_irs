"""訂票主流程：程式填表 → 使用者輸入驗證碼 → 程式完成選車次、填資料、確認訂位。"""

from __future__ import annotations

import re
import time as systime
from datetime import datetime
from enum import Enum
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

from . import page_selectors as S
from .config import TICKET_TYPES, Config
from .notify import notify
from .ticket import TicketInfo, parse_ticket
from .timeslots import TrainOption, pick_earliest, pick_slot

SCREENSHOT_DIR = Path("screenshots")
TICKET_DIR = Path("tickets")
LOG_FILE = Path("bookings.log")


class Outcome(Enum):
    SUCCESS = "success"
    RETRY = "retry"


class StepError(RuntimeError):
    """頁面結構與預期不符，需要使用者手動接手。"""


def _screenshot(page: Page, name: str) -> None:
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        print(f"已存截圖：{path}")
    except Exception:
        pass


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

    captcha = page.locator(S.CAPTCHA_INPUT)
    captcha.scroll_into_view_if_needed()
    captcha.click()


def wait_for_captcha(page: Page, cfg: Config) -> Outcome:
    """等使用者輸入驗證碼並送出，偵測進到第二頁或出現錯誤。"""
    notify("高鐵訂票", "請在瀏覽器輸入驗證碼後按 Enter")
    deadline = systime.monotonic() + cfg.captcha_timeout_sec
    while systime.monotonic() < deadline:
        if page.locator(S.TRAIN_RADIO).count():
            return Outcome.SUCCESS
        if page.locator(S.CAPTCHA_INPUT).count():
            error = _error_text(page)
            if error:
                print(f"查詢失敗：{error}")
                return Outcome.RETRY
        page.wait_for_timeout(300)
    notify("高鐵訂票", "等待驗證碼逾時")
    return Outcome.RETRY


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


def choose_train(page: Page, cfg: Config) -> TrainOption | None:
    trains = read_trains(page)
    if not trains:
        raise StepError("第二頁找不到任何車次")
    chosen = pick_earliest(trains, cfg.depart_after, cfg.depart_before)
    if chosen is None:
        listed = ", ".join(f"{t.code}({t.departure:%H:%M})" for t in trains)
        print(f"沒有符合時間區間的車次，可訂班次：{listed}")
        return None
    radio = page.locator(S.TRAIN_RADIO).nth(chosen.index)
    radio.check(force=True)
    print(f"選擇車次 {chosen.code}，{chosen.departure:%H:%M} 出發")
    page.locator(S.TRAIN_SUBMIT).click()
    return chosen


# ---------- 第三頁 ----------

def fill_passenger(page: Page, cfg: Config) -> None:
    page.wait_for_selector(S.ID_INPUT, timeout=15_000)
    page.fill(S.ID_INPUT, cfg.id_number)
    if cfg.phone and page.locator(S.PHONE_INPUT).count():
        page.fill(S.PHONE_INPUT, cfg.phone)
    if cfg.email and page.locator(S.EMAIL_INPUT).count():
        page.fill(S.EMAIL_INPUT, cfg.email)

    if cfg.member_id:
        _click_label(page, S.MEMBER_TGO_LABEL)
        same = page.locator(S.MEMBER_SAME_AS_TAKER)
        if cfg.member_id == cfg.id_number and same.count() and same.is_visible():
            same.check()
        else:
            page.locator(S.MEMBER_NUMBER_INPUT).fill(cfg.member_id)

    page.locator(S.AGREE_CHECKBOX).check(force=True)


def has_unfilled_passenger_ids(page: Page) -> bool:
    """敬老 / 愛心 / 大學生票會要求每位乘客的身分證字號，這些欄位留給使用者自己填。"""
    return page.evaluate(
        """() => [...document.querySelectorAll('input[name*="passengerDataIdNumber"]')]
            .some(el => el.offsetParent !== null && !el.value)"""
    )


def confirm_booking(page: Page, cfg: Config) -> str | None:
    if has_unfilled_passenger_ids(page):
        notify("高鐵訂票", "請在瀏覽器填入乘客身分證字號後按「完成訂位」")
    else:
        page.locator(S.CONFIRM_SUBMIT).click()

    deadline = systime.monotonic() + max(30, cfg.captcha_timeout_sec)
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

def attempt(page: Page, cfg: Config, dry_run: bool = False) -> Outcome:
    fill_search_form(page, cfg)
    result = wait_for_captcha(page, cfg)
    if result is not Outcome.SUCCESS:
        return result

    if choose_train(page, cfg) is None:
        return Outcome.RETRY

    fill_passenger(page, cfg)
    if dry_run:
        _screenshot(page, "dry-run")
        notify("高鐵訂票（測試）", "已填好取票人資料，測試模式不會送出訂位")
        return Outcome.SUCCESS
    pnr = confirm_booking(page, cfg)
    if not pnr:
        raise StepError("送出後找不到訂位代號")

    info, image = capture_ticket(page, pnr)
    summary = f"{cfg.travel_date:%Y/%m/%d} {cfg.from_station}→{cfg.to_station} {info.summary()}"
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {summary} {image}\n")
    print(f"訂位明細截圖：{image}")
    notify("高鐵訂位成功", summary + "，請記得在期限內付款")
    return Outcome.SUCCESS


def wait_until(start_at: datetime) -> None:
    while (remaining := (start_at - datetime.now()).total_seconds()) > 0:
        print(f"\r距離開始還有 {int(remaining)} 秒", end="", flush=True)
        systime.sleep(min(remaining, 1))
    print()


def run(cfg: Config, dry_run: bool = False) -> bool:
    if cfg.start_at:
        wait_until(cfg.start_at)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(locale="zh-TW", viewport={"width": 1200, "height": 900})
        success = False
        try:
            for n in range(1, cfg.max_attempts + 1):
                print(f"=== 第 {n}/{cfg.max_attempts} 輪 ===")
                try:
                    outcome = attempt(page, cfg, dry_run)
                except StepError as exc:
                    _screenshot(page, "step-error")
                    notify("高鐵訂票需要手動處理", str(exc))
                    break
                except PlaywrightTimeout as exc:
                    _screenshot(page, "timeout")
                    print(f"頁面逾時：{exc}")
                    outcome = Outcome.RETRY

                if outcome is Outcome.SUCCESS:
                    success = True
                    break
                if n < cfg.max_attempts:
                    print(f"{cfg.retry_interval_sec} 秒後重試")
                    systime.sleep(cfg.retry_interval_sec)
            else:
                notify("高鐵訂票", f"已嘗試 {cfg.max_attempts} 輪，未訂到符合條件的車票")
        finally:
            try:
                input("瀏覽器保持開啟，可手動檢查或接手。按 Enter 關閉…")
            except EOFError:
                page.wait_for_timeout(180_000)
            browser.close()
        return success
