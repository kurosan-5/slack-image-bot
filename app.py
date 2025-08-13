# app.py
import os
import logging
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.oauth.installation_store.file import FileInstallationStore
from slack_sdk.oauth.state_store.file import FileOAuthStateStore
from slack_bolt.oauth.oauth_settings import OAuthSettings
from flask import Flask, request
from dotenv import load_dotenv
import requests
import csv
from urllib.parse import urlencode

# Gemini 解析（gemini.py に extract_from_bytes を実装してください）
from gemini import extract_from_bytes

# ----------------- 基本設定 -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# ----------------- OAuth 設定 -----------------
oauth_settings = OAuthSettings(
    client_id=os.environ["SLACK_CLIENT_ID"],
    client_secret=os.environ["SLACK_CLIENT_SECRET"],
    scopes=[
        "app_mentions:read",
        "chat:write",
        "im:history",
        "files:read",
        "channels:history",
        "canvases:write",
    ],
    installation_store=FileInstallationStore(base_dir="./.slack_install"),
    state_store=FileOAuthStateStore(base_dir="./.slack_state", expiration_seconds=600),
)

app = App(
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    oauth_settings=oauth_settings,
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# ----------------- 便利ヘルパー -----------------
def gmail_compose_url(to: str, subject: str = "", body: str = "", account_index: int | None = None) -> str:
    base = "https://mail.google.com/mail"
    if account_index is not None:
        base += f"/u/{account_index}"
    params = {"fs": "1", "tf": "cm", "to": to}
    if subject:
        params["su"] = subject
    if body:
        params["body"] = body
    return f"{base}/?{urlencode(params)}"

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

# ----------------- 表示用データ（Gemini結果が入る） -----------------
dammyData = {
    "name_jp": "山本一翔",
    "name_en": "Kazuhiro Yamamoto",
    "company": "株式会社ユニークビジョン",
    "postal_code": "100-0001",
    "address": "東京都千代田区1-1",
    "email": "yamamoto@example.com",
    "website": "https://example.com",
    "phone": "03-1234-5678",
}

# ----------------- ハンドラ -----------------
@app.event("app_mention")
def handle_mention(event, say):
    say("読み取り完了。\n")
    say(f"名前: {dammyData['name_jp']}")
    say(f"会社名: {dammyData['company']}")
    say(f"会社住所: {dammyData['address']}")
    say(f"Email: {dammyData['email']}")
    say(f"ウェブサイト: {dammyData['website']}")
    say(f"電話番号: {dammyData['phone']}")

    blocks = [
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "保存する"}, "style": "primary", "value": "save_text", "action_id": "save_text"},
                {"type": "button", "text": {"type": "plain_text", "text": "変更する"}, "value": "edit_text", "action_id": "edit_text"},
            ],
        }
    ]
    say(blocks=blocks, text="読み取り結果に対してアクションを選んでください")

@app.action("save_text")
def handle_save_text(ack, body, say):
    ack()
    file_path = "output.csv"
    keys = ["phone", "name", "address", "email", "company"]
    values = [
        dammyData.get("phone", ""),
        dammyData.get("name_jp", ""),
        dammyData.get("address", ""),
        dammyData.get("email", ""),
        dammyData.get("company", ""),
    ]
    file_exists = os.path.isfile(file_path)
    with open(file_path, "a", encoding="utf-8", newline="") as f:
        if not file_exists:
            f.write(",".join(keys) + "\n")
        f.write(",".join(values) + "\n")
    say("保存しました。")

    body_template = (
        f"こんにちは、{dammyData['name_jp']}さん。\n"
        f"会社名: {dammyData['company']}\n"
        f"会社住所: {dammyData['address']}\n"
        f"Email: {dammyData['email']}\n"
        f"ウェブサイト: {dammyData['website']}\n"
        f"電話番号: {dammyData['phone']}"
    )
    url = gmail_compose_url(
        to=dammyData["email"],
        subject=f"{dammyData['name_jp']}さんの名刺情報",
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

@app.action("edit_text")
def handle_edit_text(ack, body, say):
    ack()
    say("該当項目を変更してください。")
    editBlocks = [
        {
            "type": "input",
            "block_id": "edit_name",
            "label": {"type": "plain_text", "text": "名前"},
            "element": {"type": "plain_text_input", "action_id": "name", "initial_value": f"{dammyData['name_jp']}"},
        },
        {
            "type": "input",
            "block_id": "edit_company",
            "label": {"type": "plain_text", "text": "会社名"},
            "element": {"type": "plain_text_input", "action_id": "company", "initial_value": f"{dammyData['company']}"},
        },
        {
            "type": "input",
            "block_id": "edit_address",
            "label": {"type": "plain_text", "text": "会社住所"},
            "element": {"type": "plain_text_input", "action_id": "address", "initial_value": f"{dammyData['address']}"},
        },
        {
            "type": "input",
            "block_id": "edit_email",
            "label": {"type": "plain_text", "text": "Email"},
            "element": {"type": "plain_text_input", "action_id": "email", "initial_value": f"{dammyData['email']}"},
        },
        {
            "type": "input",
            "block_id": "edit_phone",
            "label": {"type": "plain_text", "text": "電話番号"},
            "element": {"type": "plain_text_input", "action_id": "phone", "initial_value": f"{dammyData['phone']}"},
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "変更を保存"}, "style": "primary", "value": "save_changes", "action_id": "save_changes"}
            ],
        },
    ]
    say(blocks=editBlocks, text="変更したい項目を選んでください")

@app.action("save_changes")
def handle_save_changes(ack, body, say):
    ack()
    changes = []
    for block in body["state"]["values"]:
        block_data = body["state"]["values"][block]
        for key, value in block_data.items():
            display_key = ""
            if key == "name":
                display_key = "名前"
                dammyData["name_jp"] = value["value"]
            elif key == "company":
                display_key = "会社名"
                dammyData["company"] = value["value"]
            elif key == "address":
                display_key = "会社住所"
                dammyData["address"] = value["value"]
            elif key == "email":
                display_key = "Email"
                dammyData["email"] = value["value"]
            elif key == "phone":
                display_key = "電話番号"
                dammyData["phone"] = value["value"]
            changes.append(f"{display_key}: {value['value']}")
    say("変更内容を保存しました:\n" + "\n".join(changes))

    # 任意：編集結果をCSVに追記（フォームの key 名が列名になる）
    file_path = "output.csv"
    keys, values = [], []
    for block in body["state"]["values"]:
        block_data = body["state"]["values"][block]
        for key, value in block_data.items():
            keys.append(key)
            values.append(value["value"])
    file_exists = os.path.isfile(file_path)
    with open(file_path, "a", encoding="utf-8", newline="") as f:
        if not file_exists:
            f.write(",".join(keys) + "\n")
        f.write(",".join(values) + "\n")

@app.event("message")
def handle_message_events(body, say, context):
    event = body.get("event", {})

    # DM の通常メッセージ（ファイルなし）に既存情報を表示（任意）
    if event.get("channel_type") == "im" and "files" not in event:
        say("読み取り完了。\n")
        say(f"名前: {dammyData['name_jp']}")
        say(f"会社名: {dammyData['company']}")
        say(f"会社住所: {dammyData['address']}")
        say(f"Email: {dammyData['email']}")
        say(f"ウェブサイト: {dammyData['website']}")
        say(f"電話番号: {dammyData['phone']}")
        blocks = [
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "保存する"}, "style": "primary", "value": "save_text", "action_id": "save_text"},
                    {"type": "button", "text": {"type": "plain_text", "text": "変更する"}, "value": "edit_text", "action_id": "edit_text"},
                ],
            }
        ]
        say(blocks=blocks, text="読み取り結果に対してアクションを選んでください")

    # 添付ファイル（画像）を処理
    if "files" in event:
        bot_token = context.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            logger.error("Bot token が見つかりません（OAuth未完了 or 環境変数未設定）")
            say("内部設定エラー（Bot token 未設定）。インストール設定を確認してください。")
            return

        for f in event["files"]:
            if not is_probably_image(f, bot_token):
                logger.info(f"画像以外（に見える）のでスキップ: {f.get('name')} ({f.get('mimetype')}/{f.get('filetype')})")
                continue

            url_private = f.get("url_private_download") or f.get("url_private")
            filename = f.get("name", "unknown")
            logger.info(f"受信ファイル: {filename} ({f.get('mimetype')}/{f.get('filetype')}) URL: {url_private}")

            try:
                image_bytes = fetch_slack_private_file(url_private, bot_token)
            except Exception:
                logger.exception("画像ダウンロードに失敗しました")
                say("画像のダウンロードに失敗しました。もう一度お試しください。")
                continue

            # --- Gemini 解析 → dammyData へ反映 → Slack 表示 ---
            try:
                data = extract_from_bytes(image_bytes)
                logger.info(f"Gemini解析結果: {data}")

                dammyData.update({
                    "name_jp":     data.get("name_jp", "")     or dammyData.get("name_jp", ""),
                    "name_en":     data.get("name_en", "")     or dammyData.get("name_en", ""),
                    "company":     data.get("company", "")     or dammyData.get("company", ""),
                    "postal_code": data.get("postal_code", "") or dammyData.get("postal_code", ""),
                    "address":     data.get("address", "")     or dammyData.get("address", ""),
                    "email":       data.get("email", "")       or dammyData.get("email", ""),
                    "website":     data.get("website", "")     or dammyData.get("website", ""),
                    "phone":       data.get("phone", "")       or dammyData.get("phone", ""),
                })

                say("読み取り完了。\n")
                say(f"名前: {dammyData['name_jp']}")
                say(f"会社名: {dammyData['company']}")
                say(f"会社住所: {dammyData['address']}")
                say(f"Email: {dammyData['email']}")
                say(f"ウェブサイト: {dammyData['website']}")
                say(f"電話番号: {dammyData['phone']}")

                blocks = [
                    {
                        "type": "actions",
                        "elements": [
                            {"type": "button", "text": {"type": "plain_text", "text": "保存する"}, "style": "primary", "value": "save_text", "action_id": "save_text"},
                            {"type": "button", "text": {"type": "plain_text", "text": "変更する"}, "value": "edit_text", "action_id": "edit_text"},
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
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)
