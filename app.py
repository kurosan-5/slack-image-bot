import os
import logging
import time
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.oauth.installation_store.sqlalchemy import SQLAlchemyInstallationStore
from slack_sdk.oauth.state_store.sqlalchemy import SQLAlchemyOAuthStateStore
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DisconnectionError
from slack_bolt.oauth.oauth_settings import OAuthSettings
from flask import Flask, request
from dotenv import load_dotenv
import requests
from urllib.parse import urlencode
import json
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from datetime import datetime, timezone, timedelta

# Gemini 解析
from gemini import extract_from_bytes

# ----------------- 基本設定 -----------------
# Render等の本番環境では標準出力への明示的な出力が重要
# 本番環境ではINFO、開発環境ではDEBUGレベルを使用
log_level = logging.DEBUG if os.environ.get('ENVIRONMENT') == 'development' else logging.INFO

# 標準出力への強制出力設定（Render対応）
import sys
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,  # 標準出力を明示的に指定
    force=True  # 既存のloggingハンドラーを強制的にリセット
)
logger = logging.getLogger(__name__)

# 追加のprint関数でのログ出力（確実にRenderログに表示される）
def log_print(message, level="INFO"):
    """Renderサーバー用の確実なログ出力"""
    timestamp = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}", flush=True)

# logger.infoの代替として使用
def safe_log_info(message):
    """logger.infoとprintの両方でログ出力"""
    logger.info(message)
    log_print(message, "INFO")

# Slack Boltの特定の警告を抑制
slack_bolt_logger = logging.getLogger("slack_bolt.App")
slack_bolt_logger.setLevel(logging.ERROR)

load_dotenv()


# ----------------- OAuth 設定 -----------------
def create_oauth_settings():
    database_url = os.environ.get("DATABASE_URL")
    engine = create_engine(database_url)

    installation_store = SQLAlchemyInstallationStore(
        client_id=os.environ["SLACK_CLIENT_ID"],
        engine=engine,
        logger=logger,
    )
    state_store = SQLAlchemyOAuthStateStore(
        engine=engine,
        expiration_seconds=600,
        logger=logger,
    )

    installation_store.create_tables()
    state_store.create_tables()

    return OAuthSettings(
        client_id=os.environ["SLACK_CLIENT_ID"],
        client_secret=os.environ["SLACK_CLIENT_SECRET"],
        scopes=[
            "app_mentions:read","channels:read","chat:write",
            "files:read","im:history","im:read","im:write",
        ],
        installation_store=installation_store,
        state_store=state_store,
    )

    return OAuthSettings(
        client_id=os.environ["SLACK_CLIENT_ID"],
        client_secret=os.environ["SLACK_CLIENT_SECRET"],
        scopes=[
            "app_mentions:read",
            "channels:read",
            "chat:write",
            "files:read",
            "im:history",
            "im:read",
            "im:write",
        ],
        installation_store=installation_store,
        state_store=state_store,
    )

oauth_settings = create_oauth_settings()

app = App(
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    oauth_settings=oauth_settings,
)

# Slack Bolt 全体のログレベルを調整してイベント処理を監視
logging.getLogger("slack_bolt").setLevel(logging.INFO)

# Slack Bolt アプリケーションのグローバルエラーハンドラー
@app.error
def global_error_handler(error, body, logger):
    """Slack Boltアプリの全体的なエラーハンドラー"""
    logger.exception(f"Slack Bolt エラー: {error}")
    # エラーをre-raiseして、デフォルトのエラーハンドリングも動作させる
    raise error

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# Flask エラーハンドラー
@flask_app.errorhandler(404)
def handle_404_error(e):
    logger.warning(f"404 Not Found: {request.method} {request.path} - {e}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    return {"error": "Not Found", "message": f"Path {request.path} not found", "available_paths": ["/health", "/slack/events", "/slack/install", "/slack/oauth_redirect"]}, 404

@flask_app.errorhandler(400)
def handle_400_error(e):
    logger.error(f"400 Bad Request: {e}")
    return {"error": "Bad Request", "message": str(e)}, 400

@flask_app.errorhandler(500)
def handle_500_error(e):
    logger.exception(f"500 Internal Server Error: {e}")
    return {"error": "Internal Server Error", "message": str(e)}, 500

@flask_app.errorhandler(Exception)
def handle_generic_error(e):
    logger.exception(f"Unhandled exception: {e}")
    return {"error": "Internal Server Error", "message": str(e)}, 500

# ----------------- 便利ヘルパー -----------------
def gmail_compose_url(to: str, subject: str = "", body: str = "", account_index: int | None = None) -> str:
    try:
        logger.debug(f"Gmail URL作成開始 - to: {to}, subject: {subject[:50]}...")

        if not to or "@" not in to:
            logger.warning(f"無効なメールアドレス: {to}")
            raise ValueError(f"Invalid email address: {to}")

        base = "https://mail.google.com/mail"
        if account_index is not None:
            base += f"/u/{account_index}"
        params = {"fs": "1", "tf": "cm", "to": to}
        if subject:
            params["su"] = subject
        if body:
            params["body"] = body

        url = f"{base}/?{urlencode(params)}"
        logger.debug(f"Gmail URL作成完了: {url[:100]}...")
        return url

    except Exception as e:
        logger.exception(f"Gmail URL作成エラー: {e}")
        raise

def fetch_slack_private_file(url_private: str, bot_token: str) -> bytes:
    headers = {"Authorization": f"Bearer {bot_token}"}
    resp = requests.get(url_private, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content

# 画像判定（mimetype が application/octet-stream の場合でも拾う）
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff")
def is_probably_image(slack_file: dict, bot_token: str) -> bool:
    mt = (slack_file.get("mimetype") or "").lower()
    if mt.startswith("image/"):
        return True

    name = (slack_file.get("name") or "").lower()
    if any(name.endswith(ext) for ext in IMAGE_EXTS):
        return True

    ft = (slack_file.get("filetype") or "").lower()
    if ft in [ext.lstrip(".") for ext in IMAGE_EXTS]:
        return True

    # 最終手段：HEAD で Content-Type を確認
    try:
        url = slack_file.get("url_private") or slack_file.get("url_private_download")
        if url:
            headers = {"Authorization": f"Bearer {bot_token}"}
            r = requests.head(url, headers=headers, timeout=10)
            ct = (r.headers.get("Content-Type") or "").lower()
            if ct.startswith("image/"):
                return True
    except Exception as e:
        logger.debug(f"HEAD content-type check failed: {e}")

    return False

# ----------------- Google Sheets ヘルパー -----------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_gsheet_client():
    creds_env = os.environ.get("GOOGLE_CREDENTIALS")          # JSON文字列（1行）
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE")    # JSONファイルのパス
    if creds_env:
        try:
            creds_dict = json.loads(creds_env)
        except Exception as e:
            raise RuntimeError(f"GOOGLE_CREDENTIALS がJSONとして読み込めません: {e}")
    elif creds_file:
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                creds_dict = json.load(f)
        except Exception as e:
            raise RuntimeError(f"GOOGLE_CREDENTIALS_FILE の読込に失敗: {e}")
    else:
        raise RuntimeError("GOOGLE_CREDENTIALS か GOOGLE_CREDENTIALS_FILE を設定してください。")

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

# ----------------- 表示用データ（Gemini結果が入る） -----------------
scanData = {
    "name_jp": "",
    "name_en": "",
    "company": "",
    "postal_code": "",
    "address": "",
    "email": "",
    "website": "",
    "phone": "",
}

# ----------------- ルーティング（OAuth / Events） -----------------
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

@flask_app.route("/slack/install", methods=["GET"])
def install():
    return handler.handle(request)

@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def oauth_redirect():
    return handler.handle(request)

# ----------------- ハンドラ -----------------
@app.action("save_text")
def handle_save_text(ack, body, say, client, context):
    ack()

    # Slackユーザ表記（display_name があれば優先）
    user_id = body.get("user", {}).get("id") or body.get("user", "")
    user_label = user_id
    try:
        if user_id:
            prof = client.users_info(user=user_id).get("user", {}).get("profile", {})
            display = prof.get("display_name") or prof.get("real_name")
            if display:
                user_label = f"{display} ({user_id})"
    except Exception:
        pass

    try:
        append_record_to_sheet(scanData, slack_user_label=user_label)
        say("スプレッドシートに保存しました。")
    except Exception as e:
        logger.exception("Sheets への保存に失敗しました")
        say(f"保存に失敗しました: {e}")

    body_template = (
        f"こんにちは、{scanData['name_jp']}さん。\n"
        f"会社名: {scanData['company']}\n"
        f"会社住所: {scanData['address']}\n"
        f"Email: {scanData['email']}\n"
        f"ウェブサイト: {scanData['website']}\n"
        f"電話番号: {scanData['phone']}"
    )
    url = gmail_compose_url(
        to=scanData.get("email", ""),
        subject=f"{scanData.get('name_jp','')}さんの名刺情報",
        body=body_template,
    )

        say(
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": "保存した内容をもとにGmailを送信:"}},
                {"type": "actions", "elements": [
                    {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Gmailで新規作成"}, "url": url}
                ]},
            ],
            text=f"Gmail作成リンク: {url}",
        )

    except Exception as e:
        logger.exception(f"save_text ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logger.exception(f"エラーメッセージの送信にも失敗: {say_error}")

@app.action("edit_text")
def handle_edit_text(ack, body, say):
    try:
        ack()

        say("該当項目を変更してください。")

        editBlocks = [
            {
                "type": "input",
                "block_id": "edit_name",
                "label": {"type": "plain_text", "text": "名前"},
                "element": {"type": "plain_text_input", "action_id": "name", "initial_value": f"{scanData['name_jp']}"},
            },
            {
                "type": "input",
                "block_id": "edit_company",
                "label": {"type": "plain_text", "text": "会社名"},
                "element": {"type": "plain_text_input", "action_id": "company", "initial_value": f"{scanData['company']}"},
            },
            {
                "type": "input",
                "block_id": "edit_address",
                "label": {"type": "plain_text", "text": "会社住所"},
                "element": {"type": "plain_text_input", "action_id": "address", "initial_value": f"{scanData['address']}"},
            },
            {
                "type": "input",
                "block_id": "edit_email",
                "label": {"type": "plain_text", "text": "Email"},
                "element": {"type": "plain_text_input", "action_id": "email", "initial_value": f"{scanData['email']}"},
            },
            {
                "type": "input",
                "block_id": "edit_phone",
                "label": {"type": "plain_text", "text": "電話番号"},
                "element": {"type": "plain_text_input", "action_id": "phone", "initial_value": f"{scanData['phone']}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "変更を保存"},
                        "style": "primary",
                        "action_id": "save_changes"
                    }
                ],
            },
        ]

        say(blocks=editBlocks, text="変更したい項目を選んでください")

    except Exception as e:
        logger.exception(f"edit_text ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logger.exception(f"エラーメッセージの送信にも失敗: {say_error}")

@app.action("save_changes")
def handle_save_changes(ack, body, say, client):
    ack()
    changes = []
    for block in body["state"]["values"]:
        block_data = body["state"]["values"][block]
        for key, value in block_data.items():
            display_key = ""
            if key == "name":
                display_key = "名前"
                scanData["name_jp"] = value["value"]
            elif key == "company":
                display_key = "会社名"
                scanData["company"] = value["value"]
            elif key == "address":
                display_key = "会社住所"
                scanData["address"] = value["value"]
            elif key == "email":
                display_key = "Email"
                scanData["email"] = value["value"]
            elif key == "phone":
                display_key = "電話番号"
                scanData["phone"] = value["value"]
            changes.append(f"{display_key}: {value['value']}")
    say("変更内容を保存しました:\n" + "\n".join(changes))

    # 変更後の内容でシートへ追記（編集のたびに履歴が残る運用）
    user_id = body.get("user", {}).get("id") or body.get("user", "")
    user_label = user_id
    try:
        if user_id:
            prof = client.users_info(user=user_id).get("user", {}).get("profile", {})
            display = prof.get("display_name") or prof.get("real_name")
            if display:
                user_label = f"{display} ({user_id})"
    except Exception:
        pass
    try:
        append_record_to_sheet(scanData, slack_user_label=user_label)
        say("スプレッドシートにも追記しました。")
    except Exception as e:
        logger.exception("Sheets への保存に失敗しました")
        say(f"保存に失敗しました: {e}")

    body_template = (
        f"こんにちは、{scanData['name_jp']}さん。\n"
        f"会社名: {scanData['company']}\n"
        f"会社住所: {scanData['address']}\n"
        f"Email: {scanData['email']}\n"
        f"ウェブサイト: {scanData['website']}\n"
        f"電話番号: {scanData['phone']}"
    )
    url = gmail_compose_url(
        to=scanData.get("email",""),
        subject=f"{scanData.get('name_jp','')}さんの名刺情報",
        body=body_template,
    )

        say(
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": "保存した内容をもとにGmailを送信:"}},
                {"type": "actions", "elements": [
                    {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Gmailで新規作成"}, "url": url}
                ]},
            ],
            text=f"Gmail作成リンク: {url}",
        )

        safe_log_info("Gmail作成リンク送信完了")

    except Exception as e:
        logger.exception(f"save_changes ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logger.exception(f"エラーメッセージの送信にも失敗: {say_error}")

@app.event("message")
def handle_message_events(body, say, context):
    say('読み込んでいます...')
    event = body.get("event", {})

    # 添付ファイル（画像）を処理
    if "files" in event:
        bot_token = context.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            say("内部設定エラー（Bot token 未設定）。インストール設定を確認してください。")
            return

        for f in event["files"]:
            if not is_probably_image(f, bot_token):
                logger.info(f"画像以外（に見える）のでスキップ: {f.get('name')} ({f.get('mimetype')}/{f.get('filetype')})")
                continue

            url_private = f.get("url_private_download") or f.get("url_private")
            try:
                image_bytes = fetch_slack_private_file(url_private, bot_token)
            except Exception:
                logger.exception("画像ダウンロードに失敗しました")
                say("画像のダウンロードに失敗しました。もう一度お試しください。")
                continue

            # --- Gemini 解析 → scanData へ反映 → Slack 表示 ---
            try:
                data = extract_from_bytes(image_bytes)
                logger.info(f"Gemini解析結果: {data}")

                scanData.update({
                    "name_jp":     data.get("name_jp", "")     or scanData.get("name_jp", ""),
                    "name_en":     data.get("name_en", "")     or scanData.get("name_en", ""),
                    "company":     data.get("company", "")     or scanData.get("company", ""),
                    "postal_code": data.get("postal_code", "") or scanData.get("postal_code", ""),
                    "address":     data.get("address", "")     or scanData.get("address", ""),
                    "email":       data.get("email", "")       or scanData.get("email", ""),
                    "website":     data.get("website", "")     or scanData.get("website", ""),
                    "phone":       data.get("phone", "")       or scanData.get("phone", ""),
                })

                say("読み取り完了。\n")
                say(f"名前: {scanData['name_jp']}")
                say(f"会社名: {scanData['company']}")
                say(f"会社住所: {scanData['address']}")
                say(f"Email: {scanData['email']}")
                say(f"ウェブサイト: {scanData['website']}")
                say(f"電話番号: {scanData['phone']}")

                blocks = [
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "保存する"},
                                "style": "primary",
                                "action_id": "save_text"
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "変更する"},
                                "action_id": "edit_text"
                            },
                        ],
                    }
                ]
                say(blocks=blocks, text="読み取り結果に対してアクションを選んでください")

            except Exception:
                logger.exception("Gemini 解析に失敗")
                say("画像の解析に失敗しました。もう一度お試しください。")

    else:
        logger.info("通常メッセージ: " + event.get("text", "（テキストなし）"))

# ----------------- 起動 -----------------
if __name__ == "__main__":
    try:
        # 起動時の環境情報をログ出力
        logger.info("=== アプリケーション起動開始 ===")
        logger.info(f"Python version: {os.sys.version}")
        logger.info(f"Current working directory: {os.getcwd()}")
        safe_log_info(f"Environment: {os.environ.get('ENVIRONMENT', 'production')}")

        port = int(os.environ.get("PORT", 3000))
        safe_log_info(f"Starting Flask app on port {port}")

        # 本番環境の場合はデバッグモードを無効にする
        debug_mode = os.environ.get('ENVIRONMENT') == 'development'

        flask_app.run(
            host="0.0.0.0",
            port=port,
            debug=debug_mode
        )

    except Exception as e:
        logger.exception(f"アプリケーション起動エラー: {e}")
        raise
