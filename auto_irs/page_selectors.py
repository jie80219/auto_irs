"""高鐵訂票網站 (irs.thsrc.com.tw) 的頁面選擇器。

高鐵改版導致欄位抓不到時，只需要修改這個檔案。
"""

BOOKING_URL = "https://irs.thsrc.com.tw/IMINT/"

# ---- 第一頁：查詢條件 ----
START_STATION = 'select[name="selectStartStation"]'
DEST_STATION = 'select[name="selectDestinationStation"]'
DATE_INPUT = 'input[name="toTimeInputField"]'
TIME_SELECT = 'select[name="toTimeTable"]'
CAR_CLASS_LABEL = {"standard": "標準車廂", "business": "商務車廂"}
SEAT_PREF_LABEL = {"none": "無座位偏好", "window": "靠窗優先", "aisle": "走道優先"}
TICKET_AMOUNT = 'select[name="ticketPanel:rows:{row}:ticketAmount"]'
CAPTCHA_INPUT = 'input[name="homeCaptcha:securityCode"]'
CAPTCHA_IMAGE = "#BookingS1Form_homeCaptcha_passCode"
CAPTCHA_REFRESH = "#BookingS1Form_homeCaptcha_reCodeLink"
COOKIE_ACCEPT = "#cookieAccpetBtn"

# ---- 第二頁：選擇車次 ----
TRAIN_RADIO = 'input[name="TrainQueryDataViewPanel:TrainGroup"]'
TRAIN_SUBMIT = 'input[name="SubmitButton"]'

# ---- 第三頁：取票人資料 ----
ID_INPUT = "#idNumber"
MEMBER_TGO_LABEL = "高鐵會員 TGo 帳號"
MEMBER_NUMBER_INPUT = "#msNumber"
MEMBER_SAME_AS_TAKER = "#memberSystemCheckBox"
PASSENGER_ID_INPUT = 'input[name*="passengerDataIdNumber"]'
AGREE_CHECKBOX = 'input[name="agree"]'
CONFIRM_SUBMIT = "#isSubmit"

# ---- 第四頁：訂位結果 ----
PNR_TEXT_PATTERN = r"訂位代號\s*[:：]?\s*(\d{8})"

# ---- 錯誤訊息 ----
ERROR_MESSAGE = ".feedbackPanelERROR, #divErrMSG"

# ---- 訂位明細截圖：從標題往上找到同時包含這些文字的最小區塊 ----
TICKET_SECTION_TITLE = "訂位明細"
TICKET_SECTION_MUST_CONTAIN = ("訂位代號", "總票價")
