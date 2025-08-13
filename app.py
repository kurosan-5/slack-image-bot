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
import boto3
import csv
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

oauth_settings = OAuthSettings(
    client_id=os.environ["SLACK_CLIENT_ID"],
    client_secret=os.environ["SLACK_CLIENT_SECRET"],
    scopes=[  # GUIで付けているスコープと一致させる
        "canvases:write",
        "app_mentions:read",
        "chat:write",
        "channels:history",
        "app_mentions:read",
        "im:history",
        "files:read",
        "channels:history"     # 公開CHのmessage取得が要るなら
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

# Slackのイベント受信用エンドポイント
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

# インストール開始URL（ブラウザで開く）
@flask_app.route("/slack/install", methods=["GET"])
def install():
    return handler.handle(request)

# OAuthリダイレクト受け取り（Slackの Redirect URL に登録する）
@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def oauth_redirect():
    return handler.handle(request)


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

def gmail_compose_url(to: str, subject: str = "", body: str = "", account_index: int | None = None) -> str:
    base = "https://mail.google.com/mail"
    if account_index is not None:
        base += f"/u/{account_index}"
    params = {"fs": "1", "tf": "cm", "to": to}
    if subject:
        params["su"] = subject
    if body:
        params["body"] = body
    # UTF-8でURLエンコード（日本語OK）
    return f"{base}/?{urlencode(params)}"

@app.event("app_mention")
def handle_mention(event, say):
    # 応答
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
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "保存する"
                    },
                    "style": "primary",
                    "value": "save_text",
                    "action_id": "save_text"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "変更する"
                    },
                    "value": "edit_text",
                    "action_id": "edit_text"
                }
            ]
        }
    ]
    say(blocks=blocks, text="読み取り結果に対してアクションを選んでください")

@app.action("save_text")
def handle_save_text(ack, body, say):
    ack()
    file_path = "output.csv"

    # 今回のデータ取得
    keys = ["phone","name","address","email","company"]
    values = [dammyData["phone"], dammyData["name_jp"], dammyData["address"], dammyData["email"], dammyData["company"]]
    # ファイルが存在しない → ヘッダーあり
    file_exists = os.path.isfile(file_path)

    with open(file_path, "a", encoding="utf-8", newline="") as f:
        # 最初の1回だけヘッダーを書き込む
        if not file_exists:
            f.write(",".join(keys) + "\n")

        # データ行を書き込む
        f.write(",".join(values) + "\n")
    say("保存しました。")

    body_template = f"""こんにちは、{dammyData['name_jp']}さん。
会社名: {dammyData['company']}
会社住所: {dammyData['address']}
Email: {dammyData['email']}
ウェブサイト: {dammyData['website']}
電話番号: {dammyData['phone']}"""

    url = gmail_compose_url(
        to=dammyData['email'],
        subject=f"{dammyData['name_jp']}さんの名刺情報",
        body=body_template,
    )

    say(
    blocks=[
        {"type":"section","text":{"type":"mrkdwn","text":"保存した内容をもとにGmailを送信:"}},
        {"type":"actions","elements":[
            {"type":"button","style":"primary","text":{"type":"plain_text","text":"Gmailで新規作成"},"url": url}
        ]}
    ],
    text=f"Gmail作成リンク: {url}"
    )
    


@app.action("edit_text")
def handle_edit_text(ack, body, say):
    ack()
    say("該当項目を変更してください。")
    editBlocks = [
        {
            "type": "input",
            "block_id": "edit_name",
            "label": {
                "type": "plain_text",
                "text": "名前"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "name",
                "initial_value": f"{dammyData['name_jp']}"
            }
        },
        {
            "type": "input",
            "block_id": "edit_company",
            "label": {
                "type": "plain_text",
                "text": "会社名"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "company",
                "initial_value": f"{dammyData['company']}"
            }
        },
        {
            "type": "input",
            "block_id": "edit_address",
            "label": {
                "type": "plain_text",
                "text": "会社住所"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "address",
                "initial_value": f"{dammyData['address']}"
            }
        },
        {
            "type": "input",
            "block_id": "edit_email",
            "label": {
                "type": "plain_text",
                "text": "Email"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "email",
                "initial_value": f"{dammyData['email']}"
            }
        },
        {
            "type": "input",
            "block_id": "edit_phone",
            "label": {
                "type": "plain_text",
                "text": "電話番号"
            },
            "element": {
                "type": "plain_text_input",
                "action_id": "phone",
                "initial_value": f"{dammyData['phone']}"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "変更を保存"
                    },
                    "style": "primary",
                    "value": "save_changes",
                    "action_id": "save_changes"
                }
            ]
        }
    ]
    say(blocks=editBlocks, text="変更したい項目を選んでください")

@app.action("save_changes")
def handle_save_changes(ack, body, say):
    ack()
    changes = []
    for block in body['state']['values']:
        block_data = body['state']['values'][block]
        for key, value in block_data.items():
            display_key = ""
            if key == "name":
                display_key = "名前"
                dammyData['name_jp'] = value['value']
            elif key == "company":
                display_key = "会社名"
                dammyData['company'] = value['value']
            elif key == "address":
                display_key = "会社住所"
                dammyData['address'] = value['value']
            elif key == "email":
                display_key = "Email"
                dammyData['email'] = value['value']
            elif key == "phone":
                display_key = "電話番号"
                dammyData['phone'] = value['value']
            changes.append(f"{display_key}: {value['value']}")

    say("変更内容を保存しました:\n" + "\n".join(changes))

    file_path = "output.csv"

    # 今回のデータ取得
    keys = []
    values = []

    for block in body['state']['values']:
        block_data = body['state']['values'][block]
        for key, value in block_data.items():
            keys.append(key)
            values.append(value['value'])

    # ファイルが存在しない → ヘッダーあり
    file_exists = os.path.isfile(file_path)

    with open(file_path, "a", encoding="utf-8", newline="") as f:

        # 最初の1回だけヘッダーを書き込む
        if not file_exists:
            f.write(",".join(keys) + "\n")

        # データ行を書き込む
        f.write(",".join(values) + "\n")

@app.event("message")
def handle_message_events(body, say):

    event = body.get("event", {})
    # if event.get("subtype") is not None:
    #     return
    if event.get("channel_type") == "im":
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
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "保存する"
                        },
                        "style": "primary",
                        "value": "save_text",
                        "action_id": "save_text"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "変更する"
                        },
                        "value": "edit_text",
                        "action_id": "edit_text"
                    }
                ]
            }
        ]
        say(blocks=blocks, text="読み取り結果に対してアクションを選んでください")

    headers = {
        "Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"
    }

    if "files" in event:
        for f in event["files"]:
            url = f['url_private']
            filename = f['name']
            logger.info(f"ファイル名: {filename}")
            logger.info(f"URL: {url}")


    else:
        logger.info("通常メッセージ: " + event.get("text", "（テキストなし）"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)


