import os
import logging
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.oauth.installation_store.file import FileInstallationStore
from slack_sdk.oauth.state_store.file import FileOAuthStateStore
from slack_sdk.oauth.installation_store.sqlalchemy import SQLAlchemyInstallationStore
from slack_sdk.oauth.state_store.sqlalchemy import SQLAlchemyOAuthStateStore
from sqlalchemy import create_engine
from slack_bolt.oauth.oauth_settings import OAuthSettings
from flask import Flask, request
from dotenv import load_dotenv
import requests
import csv
from urllib.parse import urlencode
import json
from oauth2client.service_account import ServiceAccountCredentials
import gspread
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

    # SQLAlchemy Engine を作成
    try:
        engine = create_engine(database_url)
        # 接続テスト
        with engine.connect():
            safe_log_info("データベース接続テスト成功")
    except Exception as e:
        logger.exception(f"データベース接続エラー: {e}")
        raise

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

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    # createしないなら drive.file は不要。残してもOK
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

# data = [
#     ["Name", "Email", "Message"],
#     ["Alice", "alice@example.com", "Hello!"],
#     ["Bob", "bob@example.com", "Hi there!"]
# ]

# sheet_url = export_to_existing_sheet(data)
# print(f"Google Sheets URL: {sheet_url}")

# ----------------- ルーティング（OAuth / Events） -----------------
@flask_app.route("/")
def root():
    safe_log_info("ルートパス（/）にアクセスされました")
    return '''
    <html>
        <head>
            <title>Slack Image Bot</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }
                .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                h1 { color: #4A154B; margin-bottom: 20px; }
                p { line-height: 1.6; color: #333; }
                .status { padding: 10px; background-color: #28a745; color: white; border-radius: 4px; margin: 20px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 Slack Image Bot</h1>
                <div class="status">✅ サーバーは正常に動作中です</div>
                <p>このボットは画像をアップロードしてテキスト解析を行うSlackアプリです。</p>
                <p><strong>機能:</strong></p>
                <ul>
                    <li>画像からのテキスト抽出</li>
                    <li>Gmail作成支援</li>
                    <li>データ管理</li>
                </ul>
            </div>
        </body>
    </html>
    '''

@flask_app.route("/robots.txt", methods=["GET"])
def robots_txt():
    safe_log_info("robots.txt にアクセスされました")
    return "User-agent: *\nDisallow: /\n", 200, {'Content-Type': 'text/plain'}

@flask_app.route("/favicon.ico", methods=["GET"])
def favicon():
    safe_log_info("favicon.ico にアクセスされました")
    return "", 204  # No Content

# 一般的なボット攻撃パスを処理
@flask_app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    # WordPress、admin、API攻撃などをブロック
    blocked_patterns = [
        'wp-', 'admin', 'login', 'config', '.env', 'api/v1',
        'graphql', 'xmlrpc', 'phpmyadmin', '.git', 'swagger'
    ]

    if any(pattern in path.lower() for pattern in blocked_patterns):
        logger.warning(f"ブロックされたパス: {request.method} /{path} from {request.remote_addr}")
        return {"error": "Forbidden"}, 403

    logger.warning(f"未定義のパス: {request.method} /{path} from {request.remote_addr}")
    return {"error": "Not Found", "message": f"Path /{path} not found"}, 404

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    try:
        result = handler.handle(request)
        return result
    except Exception as e:
        logger.exception(f"Slack events エンドポイントでエラー: {e}")
        # エラーでも適切なレスポンスを返す
        return {"error": "Internal Server Error"}, 500

@flask_app.route("/slack/install", methods=["GET"])
def install():
    try:
        result = handler.handle(request)
        return result
    except Exception as e:
        logger.exception(f"Slack install エンドポイントでエラー: {e}")
        raise

@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def oauth_redirect():
    try:
        result = handler.handle(request)
        return result
    except Exception as e:
        logger.exception(f"Slack oauth_redirect エンドポイントでエラー: {e}")
        raise

@flask_app.route("/health", methods=["GET"])
def health_check():
    return {"status": "ok", "message": "Application is running"}

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

# ----------------- ハンドラ -----------------
@app.action("save_text")
def handle_save_text(ack, body, say):
    try:
        safe_log_info("🔥🔥🔥 SAVE_TEXT アクションが呼び出されました！ 🔥🔥🔥")
        ack()
        # データの検証
        if not scanData.get('email'):
            say("メールアドレスが読み取れなかったため、Gmail作成リンクを生成できません。")
            return

        say("保存しました。")

        body_template = (
            f"こんにちは、{scanData['name_jp']}さん。\n"
            f"会社名: {scanData['company']}\n"
            f"会社住所: {scanData['address']}\n"
            f"Email: {scanData['email']}\n"
            f"ウェブサイト: {scanData['website']}\n"
            f"電話番号: {scanData['phone']}"
        )

        safe_log_info(f"Gmail作成用のメールアドレス: {scanData['email']}")

        url = gmail_compose_url(
            to=scanData["email"],
            subject=f"{scanData['name_jp']}さんの名刺情報",
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
        safe_log_info("🔥🔥🔥 EDIT_TEXT アクションが呼び出されました！ 🔥🔥🔥")

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
def handle_save_changes(ack, body, say):
    try:
        safe_log_info("🔥🔥🔥 SAVE_CHANGES アクションが呼び出されました！ 🔥🔥🔥")

        ack()
        changes = []
        state_values = body.get("state", {}).get("values", {})

        if not state_values:
            logger.warning("state.values が空です")
            say("❌ フォームデータが取得できませんでした。もう一度お試しください。")
            return

        for block in state_values:
            block_data = state_values[block]
            for key, value in block_data.items():
                display_key = ""
                new_value = value.get("value", "")

                if key == "name":
                    display_key = "名前"
                    scanData["name_jp"] = new_value
                elif key == "company":
                    display_key = "会社名"
                    scanData["company"] = new_value
                elif key == "address":
                    display_key = "会社住所"
                    scanData["address"] = new_value
                elif key == "email":
                    display_key = "Email"
                    scanData["email"] = new_value
                elif key == "phone":
                    display_key = "電話番号"
                    scanData["phone"] = new_value

                if display_key:
                    changes.append(f"{display_key}: {new_value}")
                    safe_log_info(f"{display_key} を {new_value} に更新")

        say("変更内容を保存しました:\n" + "\n".join(changes))

        body_template = (
            f"こんにちは、{scanData['name_jp']}さん。\n"
            f"会社名: {scanData['company']}\n"
            f"会社住所: {scanData['address']}\n"
            f"Email: {scanData['email']}\n"
            f"ウェブサイト: {scanData['website']}\n"
            f"電話番号: {scanData['phone']}"
        )

        if not scanData.get('email'):
            say("メールアドレスが読み取れなかったため、Gmail作成リンクを生成できません。")
            return

        url = gmail_compose_url(
            to=scanData["email"],
            subject=f"{scanData['name_jp']}さんの名刺情報",
            body=body_template,
        )

        safe_log_info(f"生成されたGmail URL: {url}")

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
            filename = f.get("name", "unknown")

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
                logger.info("Gemini解析後ボタンブロック送信中...")
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
