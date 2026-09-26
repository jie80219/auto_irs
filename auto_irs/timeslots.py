"""時間相關的純函式：解析高鐵時段代碼、挑選車次。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

_SLOT_PATTERN = re.compile(r"^(\d{1,2})(\d{2})([APN])$")


def parse_slot(value: str) -> time | None:
    """把高鐵時段下拉選單的 value（如 "830A"、"1200N"、"130P"）轉成 time。"""
    match = _SLOT_PATTERN.match(value.strip().upper())
    if not match:
        return None
    hour, minute, suffix = int(match[1]), int(match[2]), match[3]
    if suffix == "N":
        hour = 12
    elif suffix == "A" and hour == 12:
        hour = 0
    elif suffix == "P" and hour != 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def pick_slot(values: list[str], target: time) -> str | None:
    """選出不晚於 target 的最晚時段，讓查詢結果涵蓋 target 之後的班次。"""
    candidates = [(t, v) for v in values if (t := parse_slot(v)) is not None]
    if not candidates:
        return None
    earlier = [c for c in candidates if c[0] <= target]
    return max(earlier)[1] if earlier else min(candidates)[1]


@dataclass(frozen=True)
class TrainOption:
    index: int
    code: str
    departure: time
    arrival: time | None = None


def pick_earliest(trains: list[TrainOption], after: time, before: time) -> TrainOption | None:
    """在出發時間區間內挑最早出發的車次。"""
    in_range = [t for t in trains if after <= t.departure <= before]
    return min(in_range, key=lambda t: t.departure) if in_range else None
