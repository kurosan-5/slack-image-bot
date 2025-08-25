import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone, timedelta

SCOPES = [
	"https://www.googleapis.com/auth/spreadsheets",
]

def get_gsheet_client():
	creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
	creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
	return gspread.authorize(creds)

def get_worksheet():
    """SPREADSHEET_ID と SHEET_NAME からワークシートを取得（無ければ作成）。"""
    gc = get_gsheet_client()
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    sheet_name = os.environ.get("SHEET_NAME", "Sheet1")

    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows="1000", cols="20")
    return ws

HEADER = [
    "timestamp_jst",
    "source",        # "slack"
    "slack_user",    # 表示名（可能なら）/ ユーザID
    "name_jp",
    "name_en",
    "company",
    "postal_code",
    "address",
    "email",
    "website",
    "phone",
]

def ensure_header(ws):
    """先頭行にヘッダを整備。既存ヘッダが空または不一致なら置き換える。"""
    existing = ws.row_values(1)
    if len(existing) < len(HEADER) or existing[:len(HEADER)] != HEADER:
        ws.update("A1", [HEADER])

def append_record_to_sheet(record: dict, slack_user_label: str = ""):
    """名刺情報1件を1行追記。"""
    ws = get_worksheet()
    ensure_header(ws)

    # JST タイムスタンプ
    jst = timezone(timedelta(hours=9))
    ts = datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S")

    row = [
        ts,
        "slack",
        slack_user_label,
        record.get("name_jp", ""),
        record.get("name_en", ""),
        record.get("company", ""),
        record.get("postal_code", ""),
        record.get("address", ""),
        record.get("email", ""),
        record.get("website", ""),
        record.get("phone", ""),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")