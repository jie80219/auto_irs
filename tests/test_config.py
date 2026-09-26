from datetime import date, time

import pytest

from auto_irs.config import ConfigError, mask_id, parse_config, parse_identity

BASE = {
    "THSR_ID": "a123456789",
    "THSR_MEMBER_ID": "A123456789",
    "FROM_STATION": "臺北",
    "TO_STATION": "左營",
    "TRAVEL_DATE": "2026-10-10",
    "DEPART_AFTER": "08:00",
    "DEPART_BEFORE": "12:00",
}


def test_parses_defaults():
    cfg = parse_config(BASE)
    assert cfg.id_number == "A123456789"
    assert cfg.from_station == "台北"
    assert cfg.travel_date == date(2026, 10, 10)
    assert cfg.depart_after == time(8, 0)
    assert cfg.tickets["adult"] == 1 and cfg.total_tickets == 1
    assert cfg.car_class == "standard" and cfg.seat_pref == "none"


def test_member_optional():
    assert parse_config({**BASE, "THSR_MEMBER_ID": ""}).member_id is None


@pytest.mark.parametrize(
    "override",
    [
        {"THSR_ID": "123"},
        {"TO_STATION": "台北"},
        {"FROM_STATION": "高鐵站"},
        {"DEPART_AFTER": "13:00"},
        {"TICKET_ADULT": "0"},
        {"TICKET_ADULT": "6", "TICKET_ELDER": "5"},
        {"CAR_CLASS": "first"},
        {"RETRY_INTERVAL_SEC": "1"},
    ],
)
def test_rejects_invalid(override):
    with pytest.raises(ConfigError):
        parse_config({**BASE, **override})


def test_mixed_tickets_require_passenger_ids():
    with pytest.raises(ConfigError):
        parse_config({**BASE, "TICKET_ADULT": "2", "TICKET_COLLEGE": "1"})
    cfg = parse_config({**BASE, "TICKET_ADULT": "2", "TICKET_COLLEGE": "1", "PASSENGER_IDS": "b223456789"})
    assert cfg.total_tickets == 3
    assert cfg.passenger_ids == ["B223456789"]


def test_start_at_from_datetime_local():
    cfg = parse_config({**BASE, "START_AT": "2026-10-01T00:00"})
    assert cfg.start_at.hour == 0 and cfg.start_at.day == 1


def test_identity_only_needs_ids():
    identity = parse_identity({"THSR_ID": "A123456789", "THSR_MEMBER_ID": ""})
    assert identity.member_id is None
    assert mask_id(identity.id_number) == "A12*****89"
