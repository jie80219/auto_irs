import argparse
import sys

from .booking import run
from .config import ConfigError, load_config


def main() -> int:
    parser = argparse.ArgumentParser(prog="auto_irs", description="高鐵半自動訂票")
    parser.add_argument("--env", default=".env", help="設定檔路徑（預設 .env）")
    parser.add_argument("--check", action="store_true", help="只檢查設定檔，不開瀏覽器")
    args = parser.parse_args()

    try:
        cfg = load_config(args.env)
    except ConfigError as exc:
        print(f"設定錯誤：{exc}", file=sys.stderr)
        return 2

    tickets = "、".join(f"{k}×{v}" for k, v in cfg.tickets.items() if v)
    print(
        f"{cfg.travel_date:%Y/%m/%d} {cfg.from_station}→{cfg.to_station} "
        f"{cfg.depart_after:%H:%M}~{cfg.depart_before:%H:%M} "
        f"{cfg.car_class}/{cfg.seat_pref} {tickets} "
        f"會員：{'是' if cfg.member_id else '否'}"
    )
    if args.check:
        return 0
    return 0 if run(cfg) else 1


if __name__ == "__main__":
    sys.exit(main())
