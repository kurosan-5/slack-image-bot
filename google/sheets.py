import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SCOPES = [
	"https://www.googleapis.com/auth/spreadsheets",
]

def get_gsheet_client():
	creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
	creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
	return gspread.authorize(creds)

def export_to_existing_sheet(data):
	gc = get_gsheet_client()
	spreadsheet_id = os.environ["SPREADSHEET_ID"]
	sh = gc.open_by_key(spreadsheet_id)
	ws = sh.get_worksheet(0) or sh.add_worksheet(title="Sheet1", rows="100", cols="26")
	ws.clear()
	ws.update("A1", data)
	return sh.url
