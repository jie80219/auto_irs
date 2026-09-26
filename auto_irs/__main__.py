import argparse
import sys
import threading
import webbrowser

from .config import ConfigError, load_identity, mask_id
from .webapp import create_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="auto_irs", description="高鐵訂票介面")
    parser.add_argument("--env", default=".env", help="身分證設定檔路徑（預設 .env）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="不要自動開啟瀏覽器")
    args = parser.parse_args()

    try:
        identity = load_identity(args.env)
    except ConfigError as exc:
        print(f"設定錯誤：{exc}\n請先 cp .env.example .env 並填入身分證字號", file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{args.port}"
    print(f"取票人 {mask_id(identity.id_number)}，介面網址 {url}（Ctrl+C 結束）")
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    create_app(identity).run(host="127.0.0.1", port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
