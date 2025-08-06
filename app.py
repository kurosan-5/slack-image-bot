import os
import logging
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
from dotenv import load_dotenv
import requests
import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# boto3 S3クライアント作成
s3 = boto3.client(
    service_name='s3',
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    endpoint_url=os.getenv("R2_ENDPOINT")
)

def upload_file_to_r2(local_path, file_name):
    bucket_name = os.getenv("R2_BUCKET_NAME")
    with open(local_path, "rb") as f:
        s3.upload_fileobj(f, bucket_name, file_name)
    logger.info(f"R2にアップロード成功: {file_name}")

# Slackのイベント受信用エンドポイント
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


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
            logger.info(f"ファイル名: {filename}")
            logger.info(f"URL: {url}")

            # ダウンロード＆保存
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                # 一時保存
                with open(filename, 'wb') as img_file:
                    img_file.write(response.content)
                logger.info(f"保存完了: {filename}")

                # R2にアップロード
                r2_key = f"uploads/{filename}"
                upload_file_to_r2(filename, r2_key)

                # 一時ファイル削除（任意）
                os.remove(filename)
            else:
                logger.error(f"ダウンロード失敗: {response.status_code}")
    else:
        logger.info("通常メッセージ: " + event.get("text", "（テキストなし）"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)