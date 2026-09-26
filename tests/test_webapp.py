import time

import pytest

from auto_irs import webapp
from auto_irs.booking import BookingResult
from auto_irs.config import Identity

TRIP = {"FROM_STATION": "台北", "TO_STATION": "左營", "TRAVEL_DATE": "2026-10-10",
        "DEPART_AFTER": "08:00", "DEPART_BEFORE": "12:00", "TICKET_ADULT": "1"}


def wait_for(client, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/status").get_json()
        if predicate(status):
            return status
        time.sleep(0.02)
    raise AssertionError(f"狀態未達成：{status}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(webapp, "notify", lambda *a, **k: None)
    app = webapp.create_app(Identity("A123456789", "A123456789"))
    return app.test_client()


def test_captcha_round_trip(client, monkeypatch):
    received = {}

    def fake_run(cfg, ui, **kwargs):
        received["kwargs"] = kwargs
        received["code"] = ui.ask_captcha(b"PNG", timeout=5)
        return BookingResult(None, None, "訂位代號 12345678")

    monkeypatch.setattr(webapp, "run", fake_run)

    setup = client.get("/api/setup").get_json()
    assert setup["idMasked"] == "A12*****89" and "台北" in setup["stations"]

    res = client.post("/api/start", json={"trip": TRIP, "useMember": True})
    assert res.status_code == 200

    status = wait_for(client, lambda s: s["phase"] == "captcha")
    assert client.get("/api/captcha.png").data == b"PNG"
    assert status["captchaSeq"] == 1

    client.post("/api/captcha", json={"code": "ab12"})
    status = wait_for(client, lambda s: s["phase"] == "done")
    assert received["code"] == "ab12"
    assert received["kwargs"] == {"use_member": True, "dry_run": False, "headless": True}
    assert status["result"]["summary"] == "訂位代號 12345678"


def test_invalid_trip_rejected(client):
    res = client.post("/api/start", json={"trip": {**TRIP, "TO_STATION": "台北"}})
    assert res.status_code == 400 and "不可相同" in res.get_json()["error"]


def test_stop_while_waiting_for_captcha(client, monkeypatch):
    from auto_irs.booking import Cancelled

    def fake_run(cfg, ui, **kwargs):
        ui.ask_captcha(b"PNG", timeout=5)
        if ui.cancelled():
            raise Cancelled()

    monkeypatch.setattr(webapp, "run", fake_run)
    client.post("/api/start", json={"trip": TRIP})
    wait_for(client, lambda s: s["phase"] == "captcha")
    client.post("/api/stop")
    wait_for(client, lambda s: s["phase"] == "stopped")
