from auto_irs.ticket import parse_ticket

RESULT_TEXT = """訂位明細
訂位代號\t03801248
未付款（付款期限：09/29）
取票識別碼\tA12*****89
去程 10/08 1305
08:01 台北 1:59 10:00 左營
座位
3車9A
車廂 標準車廂
票數 全票 1 張
總票價
TWD 1,490
"""


def test_parse_ticket():
    info = parse_ticket("03801248", RESULT_TEXT)
    assert info.seats == ["3車9A"]
    assert info.pay_deadline == "09/29"
    assert info.total == "1,490"
    assert info.summary() == "訂位代號 03801248｜座位 3車9A｜TWD 1,490｜付款期限 09/29"


def test_parse_ticket_missing_fields():
    info = parse_ticket("12345678", "訂位代號 12345678")
    assert info.seats == [] and info.total is None and info.pay_deadline is None
