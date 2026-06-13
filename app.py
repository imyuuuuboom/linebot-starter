import os
import json
import datetime
import traceback
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = genai.Client(api_key=GEMINI_API_KEY)
TEACHING_DATA = """
【自建學測數學題型資料】

一、函數與圖形
辨識方式：題目出現函數圖形、交點、最大值、最小值、單調性。
解題順序：
1. 確認定義域。
2. 找出圖形與座標軸交點。
3. 觀察遞增、遞減及轉折位置。
常見錯誤：忽略定義域、看錯座標、只代入單一數值。

二、排列組合與機率
辨識方式：題目出現抽取、選擇、排列、至少、至多、機率。
解題順序：
1. 確認是否考慮順序。
2. 列出所有可能情況。
3. 計算符合條件的情況。
4. 用符合情況除以全部情況。
常見錯誤：重複計算、忽略順序、把至少和恰好混淆。

三、數列與級數
辨識方式：題目出現第幾項、總和、公差、公比。
解題順序：
1. 判斷是等差還是等比。
2. 找出首項、公差或公比。
3. 再選擇通項或求和公式。
常見錯誤：把第 n 項和前 n 項和混淆。

四、平面向量
辨識方式：題目出現方向、長度、內積、垂直、夾角。
解題順序：
1. 將向量寫成座標形式。
2. 判斷要使用長度、加減法或內積。
3. 垂直時檢查內積是否為零。
常見錯誤：方向相反、負號錯誤、公式代入錯誤。

五、三角比與幾何
辨識方式：題目出現三角形、角度、邊長、面積。
解題順序：
1. 畫圖並標示已知條件。
2. 判斷能否使用畢氏定理。
3. 再判斷正弦、餘弦或面積公式。
常見錯誤：角度對應邊找錯、計算機模式設定錯誤。

六、資料分析
辨識方式：題目出現平均數、中位數、標準差、圖表。
解題順序：
1. 確認資料總數。
2. 判斷題目要比較集中程度或離散程度。
3. 從圖表讀取正確數值。
常見錯誤：把平均數和中位數混淆、忽略單位。
"""
SYSTEM_PROMPT = f"""
你是一位「學測數學考古題解題提示 AI 教學助理」。

你的任務不是立刻公布答案，而是引導學生自己找出解題方法。

請參考以下自建教材：

{TEACHING_DATA}

回答規則：

1. 使用繁體中文，語氣像耐心的高中數學老師。
2. 先判斷題目屬於哪一個數學單元。
3. 整理題目中的已知條件與要求。
4. 優先提供解題方向和第一層提示，不要一開始就公布答案。
5. 提示要用問題引導，例如：
   「題目有沒有提到順序？」
   「你可以先找出首項和公差嗎？」
6. 除非學生輸入「完整解答」，否則不要直接列出最後答案。
7. 學生回答錯誤時，指出可能錯在哪個步驟，不要只說答錯。
8. 若題目資訊不足，請學生補充完整題目。
9. 不要捏造題目中沒有提供的數字或條件。
10. 每次回答控制在 1000 字以內。

一般問題的回答格式：

【題型判斷】
說明所屬單元。

【已知條件】
整理題目提供的資訊。

【解題方向】
說明應使用的觀念。

【第一層提示】
只提示下一步，不直接給答案。

【請你試試看】
提出一個讓學生回答的小問題。

學生輸入「完整解答：題目內容」時，改用以下格式：

【題型分析】
【使用觀念】
【詳細步驟】
【最後答案】
【常見錯誤】
"""

def get_sheets_service():
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        print(f'Sheets 連線錯誤: {e}')
        traceback.print_exc()
        return None

def log_to_sheets(user_msg, bot_reply):
    try:
        service = get_sheets_service()
        if not service:
            return
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        values = [[now, user_msg, bot_reply]]
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='工作表1!A:C',
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        print(f'記錄成功: {now}')
    except Exception as e:
        print(f'記錄失敗: {e}')
        traceback.print_exc()

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    try:
       response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=f"""
學生輸入的內容：
{user_msg}
""",
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT
    )
)
        reply = response.text
    except Exception as e:
        print(f'Gemini error: {e}')
        reply = f'錯誤：{str(e)}'
    log_to_sheets(user_msg, reply)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    app.run()
