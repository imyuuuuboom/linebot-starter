import os
import json
import datetime
import traceback
from zoneinfo import ZoneInfo

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)


# =========================================================
# Render 環境變數
# =========================================================

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")


# 檢查必要環境變數
required_variables = {
    "LINE_CHANNEL_SECRET": LINE_CHANNEL_SECRET,
    "LINE_CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
    "GEMINI_API_KEY": GEMINI_API_KEY,
}

missing_variables = [
    name
    for name, value in required_variables.items()
    if not value
]

if missing_variables:
    raise RuntimeError(
        "缺少 Render 環境變數："
        + ", ".join(missing_variables)
    )


# =========================================================
# 初始化 LINE 與 Gemini
# =========================================================

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

client = genai.Client(api_key=GEMINI_API_KEY)


# =========================================================
# 自建學測數學教材
# =========================================================

TEACHING_DATA = """
【自建學測數學題型資料】

一、函數與圖形

辨識方式：
題目出現函數圖形、交點、最大值、最小值、單調性。

解題順序：
1. 確認定義域。
2. 找出圖形與座標軸交點。
3. 觀察遞增、遞減及轉折位置。

常見錯誤：
忽略定義域、看錯座標、只代入單一數值。


二、排列組合與機率

辨識方式：
題目出現抽取、選擇、排列、至少、至多、機率。

解題順序：
1. 確認是否考慮順序。
2. 列出所有可能情況。
3. 計算符合條件的情況。
4. 用符合條件的情況數除以全部情況數。

常見錯誤：
重複計算、忽略順序、把「至少」和「恰好」混淆。


三、數列與級數

辨識方式：
題目出現第幾項、總和、公差、公比。

解題順序：
1. 判斷是等差數列還是等比數列。
2. 找出首項、公差或公比。
3. 判斷要使用通項公式還是求和公式。

常見錯誤：
把第 n 項與前 n 項總和混淆。


四、平面向量

辨識方式：
題目出現方向、長度、內積、垂直、夾角。

解題順序：
1. 將向量寫成座標形式。
2. 判斷要使用向量長度、加減法或內積。
3. 若兩向量垂直，檢查內積是否為零。

常見錯誤：
方向相反、正負號錯誤、公式代入錯誤。


五、三角比與幾何

辨識方式：
題目出現三角形、角度、邊長、面積。

解題順序：
1. 畫圖並標示已知條件。
2. 判斷能否使用畢氏定理。
3. 再判斷要使用正弦定理、餘弦定理或面積公式。

常見錯誤：
角度與邊的對應錯誤、計算機角度模式設定錯誤。


六、資料分析

辨識方式：
題目出現平均數、中位數、標準差或統計圖表。

解題順序：
1. 確認資料總數。
2. 判斷題目要比較集中程度或離散程度。
3. 從圖表中讀取正確數值。

常見錯誤：
把平均數和中位數混淆、忽略題目單位。
"""


# =========================================================
# 自訂教學 Prompt
# =========================================================

SYSTEM_PROMPT = f"""
你是一位「學測數學考古題解題提示 AI 教學助理」。

你的任務不是一開始就公布答案，而是透過分層提示，
引導學生自己找出解題方法。

請優先參考以下自建教材：

{TEACHING_DATA}

【回答規則】

1. 一律使用繁體中文。
2. 語氣要像耐心、清楚的高中數學老師。
3. 先判斷題目屬於哪一個數學單元。
4. 整理題目提供的已知條件與要求。
5. 第一次回答只提供解題方向與第一層提示。
6. 不要在第一次回答中直接公布最後答案。
7. 提示應使用問題引導學生，例如：
   「題目是否需要考慮順序？」
   「你可以先找出首項和公差嗎？」
8. 學生輸入「再提示」時，根據最近對話提供更明確的第二層提示。
9. 學生輸入「完整解答」時，才提供詳細計算過程與最後答案。
10. 學生傳送自己的答案或計算方式時，要判斷其步驟是否正確。
11. 若學生答錯，指出可能出錯的步驟，不要只回答「錯誤」。
12. 題目資訊不足時，請學生提供完整題目。
13. 不要捏造題目中沒有提供的數字或條件。
14. 不要回答與數學學習完全無關的內容。
15. 每次回答控制在 1000 字以內。

【第一次收到數學題目的回答格式】

【題型判斷】
說明這題屬於哪一個單元。

【已知條件】
整理題目提供的資訊。

【解題方向】
說明可能使用的觀念或公式。

【第一層提示】
只提示學生下一步要做什麼。

【請你試試看】
提出一個讓學生回答的小問題。


【學生要求完整解答時的格式】

【題型分析】

【使用觀念】

【詳細步驟】

【最後答案】

【常見錯誤】
"""


# =========================================================
# 簡易對話紀錄
# 讓學生可以接著輸入「再提示」或「完整解答」
# Render 重新部署或休眠後，暫存紀錄會消失
# =========================================================

conversation_history = {}

MAX_HISTORY_ITEMS = 6


def build_conversation_content(user_id, user_msg):
    """
    將最近幾次對話一起傳給 Gemini，
    讓 Gemini 看得懂「再提示」和「完整解答」。
    """

    history = conversation_history.get(user_id, [])

    history_text = ""

    for item in history[-MAX_HISTORY_ITEMS:]:
        role_name = "學生" if item["role"] == "user" else "教學助理"
        history_text += f"{role_name}：{item['text']}\n\n"

    if history_text:
        return f"""
以下是最近的數學教學對話：

{history_text}

學生這次輸入：
{user_msg}

請根據最近對話和學生這次輸入繼續引導。
"""

    return f"""
學生輸入的數學題目或問題：

{user_msg}
"""


def save_conversation(user_id, user_msg, bot_reply):
    """
    儲存最近幾筆對話，避免內容無限增加。
    """

    history = conversation_history.get(user_id, [])

    history.append({
        "role": "user",
        "text": user_msg
    })

    history.append({
        "role": "assistant",
        "text": bot_reply
    })

    conversation_history[user_id] = history[-MAX_HISTORY_ITEMS:]


# =========================================================
# Google Sheets
# =========================================================

sheets_service = None


def get_sheets_service():
    """
    建立並回傳 Google Sheets API 服務。
    若沒有設定試算表環境變數，則略過記錄功能。
    """

    global sheets_service

    if sheets_service is not None:
        return sheets_service

    if not GOOGLE_CREDENTIALS or not SPREADSHEET_ID:
        print("尚未設定 GOOGLE_CREDENTIALS 或 SPREADSHEET_ID，略過試算表記錄。")
        return None

    try:
        credentials_info = json.loads(GOOGLE_CREDENTIALS)

        credentials = Credentials.from_service_account_info(
            credentials_info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets"
            ]
        )

        sheets_service = build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False
        )

        return sheets_service

    except Exception as error:
        print(f"Sheets 連線錯誤：{error}")
        traceback.print_exc()
        return None


def log_to_sheets(user_msg, bot_reply):
    """
    將時間、學生訊息與 AI 回覆寫入 Google 試算表。
    """

    try:
        service = get_sheets_service()

        if service is None:
            return

        taiwan_time = datetime.datetime.now(
            ZoneInfo("Asia/Taipei")
        ).strftime("%Y-%m-%d %H:%M:%S")

        values = [[
            taiwan_time,
            user_msg,
            bot_reply
        ]]

        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="'工作表1'!A:C",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={
                "values": values
            }
        ).execute()

        print(f"試算表記錄成功：{taiwan_time}")

    except Exception as error:
        print(f"試算表記錄失敗：{error}")
        traceback.print_exc()


# =========================================================
# Render 首頁健康檢查
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "LINE 數學解題提示 AI 正常運作中", 200


# =========================================================
# LINE Webhook
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature")

    if not signature:
        abort(400)

    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)

    except InvalidSignatureError:
        print("LINE 簽章驗證失敗")
        abort(400)

    except Exception as error:
        print(f"Webhook 處理錯誤：{error}")
        traceback.print_exc()

    return "OK", 200


# =========================================================
# 接收 LINE 文字訊息
# =========================================================

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()

    user_id = getattr(
        event.source,
        "user_id",
        "unknown_user"
    )

    try:
        conversation_content = build_conversation_content(
            user_id,
            user_msg
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=conversation_content,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=1200
            )
        )

        reply = response.text

        if not reply:
            reply = "目前無法產生解題提示，請重新輸入一次完整題目。"

    except Exception as error:
        print(f"Gemini 錯誤：{error}")
        traceback.print_exc()

        reply = (
            "目前無法取得數學解題提示，請稍後再試。\n"
            "若持續發生，請檢查 Gemini API Key 與 Render Logs。"
        )

    # 儲存簡易對話紀錄
    save_conversation(
        user_id,
        user_msg,
        reply
    )

    # 寫入 Google 試算表
    log_to_sheets(
        user_msg,
        reply
    )

    # 回覆 LINE 訊息
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )

    except Exception as error:
        print(f"LINE 回覆失敗：{error}")
        traceback.print_exc()


# =========================================================
# 本機執行
# Render 使用 gunicorn app:app 時不會執行這一段
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )

