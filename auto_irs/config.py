"""讀取並驗證 .env 設定。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv

STATIONS = ["南港", "台北", "板橋", "桃園", "新竹", "苗栗", "台中", "彰化", "雲林", "嘉義", "台南", "左營"]
STATION_ALIASES = {"臺北": "台北", "臺中": "台中", "臺南": "台南", "高雄": "左營"}

CAR_CLASSES = {"standard", "business"}
SEAT_PREFS = {"none", "window", "aisle"}

# 票種 → 高鐵表單 ticketPanel 的列索引與代碼
TICKET_TYPES = {
    "adult": (0, "F"),
    "child": (1, "H"),
    "disabled": (2, "W"),
    "elder": (3, "E"),
    "college": (4, "P"),
}

ID_PATTERN = re.compile(r"^[A-Z][12489A-D]\d{8}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    id_number: str
    member_id: str | None
    phone: str | None
    email: str | None
    from_station: str
    to_station: str
    travel_date: date
    depart_after: time
    depart_before: time
    car_class: str
    seat_pref: str
    tickets: dict[str, int]
    start_at: datetime | None
    max_attempts: int
    retry_interval_sec: int
    captcha_timeout_sec: int

    @property
    def total_tickets(self) -> int:
        return sum(self.tickets.values())


def _get(env: dict[str, str], key: str, default: str | None = None) -> str | None:
    value = env.get(key, default)
    if value is None:
        return None
    value = value.strip()
    return value or default


def _require(env: dict[str, str], key: str) -> str:
    value = _get(env, key)
    if not value:
        raise ConfigError(f"{key} 未設定")
    return value


def _parse_id(value: str, key: str) -> str:
    value = value.upper()
    if not ID_PATTERN.match(value):
        raise ConfigError(f"{key} 格式不正確：{value}")
    return value


def _parse_station(value: str, key: str) -> str:
    value = STATION_ALIASES.get(value, value)
    if value not in STATIONS:
        raise ConfigError(f"{key} 不是有效站名：{value}（可用：{' '.join(STATIONS)}）")
    return value


def _parse_time(value: str, key: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise ConfigError(f"{key} 格式需為 HH:MM：{value}") from None


def _parse_int(env: dict[str, str], key: str, default: int, minimum: int = 0) -> int:
    raw = _get(env, key, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} 需為整數：{raw}") from None
    if value < minimum:
        raise ConfigError(f"{key} 不可小於 {minimum}")
    return value


def parse_config(env: dict[str, str]) -> Config:
    id_number = _parse_id(_require(env, "THSR_ID"), "THSR_ID")
    member_raw = _get(env, "THSR_MEMBER_ID")
    member_id = _parse_id(member_raw, "THSR_MEMBER_ID") if member_raw else None

    from_station = _parse_station(_require(env, "FROM_STATION"), "FROM_STATION")
    to_station = _parse_station(_require(env, "TO_STATION"), "TO_STATION")
    if from_station == to_station:
        raise ConfigError("FROM_STATION 與 TO_STATION 不可相同")

    raw_date = _require(env, "TRAVEL_DATE")
    try:
        travel_date = datetime.strptime(raw_date.replace("-", "/"), "%Y/%m/%d").date()
    except ValueError:
        raise ConfigError(f"TRAVEL_DATE 格式需為 YYYY/MM/DD：{raw_date}") from None

    depart_after = _parse_time(_get(env, "DEPART_AFTER", "00:00"), "DEPART_AFTER")
    depart_before = _parse_time(_get(env, "DEPART_BEFORE", "23:59"), "DEPART_BEFORE")
    if depart_after > depart_before:
        raise ConfigError("DEPART_AFTER 不可晚於 DEPART_BEFORE")

    car_class = _get(env, "CAR_CLASS", "standard").lower()
    if car_class not in CAR_CLASSES:
        raise ConfigError(f"CAR_CLASS 需為 {'/'.join(sorted(CAR_CLASSES))}")
    seat_pref = _get(env, "SEAT_PREF", "none").lower()
    if seat_pref not in SEAT_PREFS:
        raise ConfigError(f"SEAT_PREF 需為 {'/'.join(sorted(SEAT_PREFS))}")

    tickets = {
        name: _parse_int(env, f"TICKET_{name.upper()}", 1 if name == "adult" else 0)
        for name in TICKET_TYPES
    }
    total = sum(tickets.values())
    if not 1 <= total <= 10:
        raise ConfigError(f"票數總和需介於 1~10 張，目前為 {total}")

    start_raw = _get(env, "START_AT")
    start_at = None
    if start_raw:
        try:
            start_at = datetime.strptime(start_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ConfigError(f"START_AT 格式需為 YYYY-MM-DD HH:MM:SS：{start_raw}") from None

    return Config(
        id_number=id_number,
        member_id=member_id,
        phone=_get(env, "THSR_PHONE"),
        email=_get(env, "THSR_EMAIL"),
        from_station=from_station,
        to_station=to_station,
        travel_date=travel_date,
        depart_after=depart_after,
        depart_before=depart_before,
        car_class=car_class,
        seat_pref=seat_pref,
        tickets=tickets,
        start_at=start_at,
        max_attempts=_parse_int(env, "MAX_ATTEMPTS", 10, minimum=1),
        retry_interval_sec=_parse_int(env, "RETRY_INTERVAL_SEC", 15, minimum=10),
        captcha_timeout_sec=_parse_int(env, "CAPTCHA_TIMEOUT_SEC", 180, minimum=30),
    )


def load_config(env_file: str | Path = ".env") -> Config:
    load_dotenv(env_file, override=True)
    return parse_config(dict(os.environ))
