"""解析訂位完成頁的明細文字。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TicketInfo:
    pnr: str
    seats: list[str] = field(default_factory=list)
    pay_deadline: str | None = None
    total: str | None = None

    def summary(self) -> str:
        parts = [f"訂位代號 {self.pnr}"]
        if self.seats:
            parts.append("座位 " + "、".join(self.seats))
        if self.total:
            parts.append(f"TWD {self.total}")
        if self.pay_deadline:
            parts.append(f"付款期限 {self.pay_deadline}")
        return "｜".join(parts)


def parse_ticket(pnr: str, text: str) -> TicketInfo:
    seats = list(dict.fromkeys(re.findall(r"\d{1,2}車\d{1,2}[A-E]", text)))
    deadline = re.search(r"付款期限\s*[:：]\s*(\d{1,2}/\d{1,2})", text)
    total = re.search(r"總票價\s*TWD\s*([\d,]+)", text)
    return TicketInfo(
        pnr=pnr,
        seats=seats,
        pay_deadline=deadline[1] if deadline else None,
        total=total[1] if total else None,
    )
