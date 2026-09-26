# auto_irs — 高鐵半自動訂票

程式會幫你填好訂票表單，你只要輸入驗證碼，後面的選車次、填身分資料、確認訂位都由程式完成。

## 流程

1. 程式開啟高鐵訂票網站（Playwright + Chromium，看得到的瀏覽器視窗）
2. 自動填入起訖站、日期、時段、車廂、座位偏好、各票種張數
3. **跳出 macOS 通知，由你在瀏覽器輸入驗證碼後按 Enter**
4. 程式在第二頁選出時間區間內**最早出發**的車次並送出
5. 填入取票人身分證、會員身分證（TGo），勾選同意條款，完成訂位
6. 抓到訂位代號後發通知、存截圖，並寫入 `bookings.log`

如果驗證碼錯誤、時間區間內沒有車次或頁面逾時，程式會等 `RETRY_INTERVAL_SEC` 秒後重來一輪，最多跑 `MAX_ATTEMPTS` 輪。

> 驗證碼一定要由本人輸入。依《鐵路法》第 65 條第 2 項，以不正指令輸入電腦取得訂票最高可處 5 年有期徒刑，所以本專案不會加入自動辨識驗證碼的功能。

## 安裝

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env   # 編輯 .env 填入你的資料
```

## 使用

```bash
.venv/bin/python -m auto_irs --check   # 只檢查設定
.venv/bin/python -m auto_irs           # 開始訂票
```

搶開賣時可以設定 `START_AT`（高鐵通常在乘車日前 28 天的 00:00 開放訂票），程式會等到那個時間才打開網頁。

## `.env` 設定

| 變數 | 說明 |
|---|---|
| `THSR_ID` | 取票人身分證字號（必填） |
| `THSR_MEMBER_ID` | TGo 會員身分證字號，留空表示非會員 |
| `THSR_PHONE` / `THSR_EMAIL` | 選填 |
| `FROM_STATION` / `TO_STATION` | 南港、台北、板橋、桃園、新竹、苗栗、台中、彰化、雲林、嘉義、台南、左營 |
| `TRAVEL_DATE` | `YYYY/MM/DD` |
| `DEPART_AFTER` / `DEPART_BEFORE` | 出發時間區間 `HH:MM` |
| `CAR_CLASS` | `standard` 標準、`business` 商務 |
| `SEAT_PREF` | `none`、`window`、`aisle` |
| `TICKET_ADULT` / `CHILD` / `DISABLED` / `ELDER` / `COLLEGE` | 各票種張數，總和 1–10 張 |
| `START_AT` | 選填，`YYYY-MM-DD HH:MM:SS` |
| `MAX_ATTEMPTS` / `RETRY_INTERVAL_SEC` / `CAPTCHA_TIMEOUT_SEC` | 重試次數、間隔（最少 10 秒）、等驗證碼的秒數 |

敬老、愛心、大學生票在確認頁需要填每位乘客的身分證字號，遇到這種情況程式會通知你在瀏覽器填寫並按「完成訂位」，接著繼續抓訂位代號。

## 網站改版時

所有頁面選擇器都集中在 `auto_irs/page_selectors.py`。任何一步找不到欄位時，程式會存截圖到 `screenshots/`、發通知，並保留瀏覽器讓你手動完成，再依截圖修改選擇器即可。

## 測試

```bash
.venv/bin/python -m pytest
```
