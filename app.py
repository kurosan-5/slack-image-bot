import os
import logging
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
from dotenv import load_dotenv
import requests

# ログ設定（ここが重要！）
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# Slackのイベント受信用エンドポイント
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

@app.event("app_mention")
def handle_mentions(body, say):
    user = body["event"]["user"]
    say(f"<@{user}> メンションありがとう！")

@app.event("message")
def handle_message_events(body, say):
    event = body.get("event", {})
    headers = {
        "Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"
    }

    if "files" in event:
        for f in event["files"]:
            url = f['url_private']
            filename = f['name']
            logger.info(f"📷 ファイル名: {filename}")
            logger.info(f"🔗 URL: {url}")

            # ダウンロード＆保存
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                with open(filename, 'wb') as img_file:
                    img_file.write(response.content)
                logger.info(f"✅ 保存完了: {filename}")
            else:
                logger.error(f"❌ ダウンロード失敗: {response.status_code}")
    else:
        logger.info("📝 通常メッセージ: " + event.get("text", "（テキストなし）"))

if __name__ == "__main__":
    flask_app.run(port=3000)
