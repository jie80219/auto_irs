"""本機網頁介面：選擇行程、輸入驗證碼、查看訂位結果。"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from .booking import REFRESH, Cancelled, StepError, run
from .config import STATIONS, ConfigError, Identity, mask_id, parse_config
from .notify import notify

STATIC_DIR = Path(__file__).parent / "web"
LAST_TRIP_FILE = Path("last_trip.json")
MAX_LOG_LINES = 200


class Job:
    """一次訂票工作：在背景執行緒跑 Playwright，透過這個物件和網頁溝通。"""

    def __init__(self, cfg, *, use_member: bool, dry_run: bool, headless: bool):
        self.cfg = cfg
        self.use_member = use_member
        self.dry_run = dry_run
        self.headless = headless
        self.phase = "running"
        self.logs: list[str] = []
        self.captcha: bytes | None = None
        self.captcha_seq = 0
        self.result = None
        self.error: str | None = None
        self._answers: queue.Queue[str] = queue.Queue()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)

    # ---- 給 booking.run 用的 UI 介面 ----

    def log(self, message: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {message}"
        print(line)
        with self._lock:
            self.logs = (self.logs + [line])[-MAX_LOG_LINES:]

    def ask_captcha(self, image: bytes, timeout: float) -> str | None:
        while not self._answers.empty():
            self._answers.get_nowait()
        with self._lock:
            self.captcha = image
            self.captcha_seq += 1
            self.phase = "captcha"
        notify("高鐵訂票", "請在訂票介面輸入驗證碼")
        try:
            return self._answers.get(timeout=timeout)
        except queue.Empty:
            return None
        finally:
            with self._lock:
                self.captcha = None
                if self.phase == "captcha":
                    self.phase = "running"

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ---- 給網頁 API 用 ----

    def answer(self, value: str) -> None:
        self._answers.put(value)

    def stop(self) -> None:
        self._cancel.set()
        self._answers.put(REFRESH)  # 喚醒正在等驗證碼的執行緒

    @property
    def active(self) -> bool:
        return self.thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            return {
                "phase": self.phase,
                "logs": list(self.logs),
                "captchaSeq": self.captcha_seq if self.captcha else None,
                "result": None if not self.result else {
                    "summary": self.result.summary,
                    "hasImage": bool(self.result.image),
                    "dryRun": self.dry_run,
                },
                "error": self.error,
            }

    def _finish(self, phase: str, error: str | None = None) -> None:
        with self._lock:
            self.phase = phase
            self.error = error

    def _run(self) -> None:
        try:
            result = run(self.cfg, self, use_member=self.use_member,
                         dry_run=self.dry_run, headless=self.headless)
        except Cancelled:
            self.log("已停止")
            self._finish("stopped")
        except StepError as exc:
            notify("高鐵訂票需要手動處理", str(exc))
            self._finish("failed", str(exc))
        except Exception as exc:  # 讓介面顯示任何非預期錯誤
            self.log(f"發生錯誤：{exc!r}")
            self._finish("failed", str(exc))
        else:
            if result:
                self.result = result
                self.log(result.summary)
                title = "高鐵訂票（測試模式）" if self.dry_run else "高鐵訂位成功"
                notify(title, result.summary)
                self._finish("done")
            else:
                msg = f"已嘗試 {self.cfg.max_attempts} 輪，未訂到符合條件的車票"
                notify("高鐵訂票", msg)
                self._finish("failed", msg)


def _load_last_trip() -> dict:
    try:
        return json.loads(LAST_TRIP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def create_app(identity: Identity) -> Flask:
    app = Flask(__name__, static_folder=None)
    state: dict[str, Job | None] = {"job": None}

    def current() -> Job:
        job = state["job"]
        if job is None:
            abort(404)
        return job

    @app.get("/")
    def index():
        return send_file(STATIC_DIR / "index.html")

    @app.get("/api/setup")
    def setup():
        return jsonify({
            "stations": STATIONS,
            "idMasked": mask_id(identity.id_number),
            "memberMasked": mask_id(identity.member_id) if identity.member_id else None,
            "lastTrip": _load_last_trip(),
        })

    @app.post("/api/start")
    def start():
        job = state["job"]
        if job and job.active:
            return jsonify({"error": "已有訂票工作在執行"}), 409
        form = request.get_json(force=True) or {}
        trip = {k: str(v) for k, v in form.get("trip", {}).items()}
        env = {"THSR_ID": identity.id_number, "THSR_MEMBER_ID": identity.member_id or "", **trip}
        try:
            cfg = parse_config(env)
        except ConfigError as exc:
            return jsonify({"error": str(exc)}), 400

        remembered = {k: v for k, v in trip.items() if k not in {"PASSENGER_IDS", "START_AT"}}
        LAST_TRIP_FILE.write_text(json.dumps(remembered, ensure_ascii=False, indent=2), encoding="utf-8")

        job = Job(cfg, use_member=bool(form.get("useMember")), dry_run=bool(form.get("dryRun")),
                  headless=not form.get("showBrowser"))
        state["job"] = job
        job.thread.start()
        return jsonify({"ok": True})

    @app.get("/api/status")
    def status():
        job = state["job"]
        return jsonify(job.status() if job else {"phase": "idle"})

    @app.get("/api/captcha.png")
    def captcha_image():
        image = current().captcha
        if not image:
            abort(404)
        return Response(image, mimetype="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/captcha")
    def captcha_answer():
        code = str((request.get_json(force=True) or {}).get("code", "")).strip()
        if not code:
            return jsonify({"error": "請輸入驗證碼"}), 400
        current().answer(code)
        return jsonify({"ok": True})

    @app.post("/api/captcha/refresh")
    def captcha_refresh():
        current().answer(REFRESH)
        return jsonify({"ok": True})

    @app.post("/api/stop")
    def stop():
        current().stop()
        return jsonify({"ok": True})

    @app.get("/api/ticket.png")
    def ticket_image():
        job = current()
        if not job.result or not job.result.image:
            abort(404)
        return send_file(job.result.image.resolve(), mimetype="image/png", max_age=0)

    return app
