from datetime import time

from auto_irs.timeslots import TrainOption, parse_slot, pick_earliest, pick_slot


def test_parse_slot():
    assert parse_slot("1201A") == time(0, 1)
    assert parse_slot("1230A") == time(0, 30)
    assert parse_slot("830A") == time(8, 30)
    assert parse_slot("1200N") == time(12, 0)
    assert parse_slot("1230P") == time(12, 30)
    assert parse_slot("130P") == time(13, 30)
    assert parse_slot("1130P") == time(23, 30)
    assert parse_slot("") is None


def test_pick_slot():
    values = ["", "600A", "630A", "700A", "730A", "800A", "830A", "1200N"]
    assert pick_slot(values, time(8, 15)) == "800A"
    assert pick_slot(values, time(8, 0)) == "800A"
    assert pick_slot(values, time(5, 0)) == "600A"


def test_pick_earliest():
    trains = [
        TrainOption(0, "0603", time(7, 50)),
        TrainOption(1, "0609", time(9, 10)),
        TrainOption(2, "0205", time(8, 20)),
        TrainOption(3, "0613", time(12, 30)),
    ]
    assert pick_earliest(trains, time(8, 0), time(12, 0)).code == "0205"
    assert pick_earliest(trains, time(13, 0), time(14, 0)) is None
