from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
from .oauth import create_oauth_settings
import os
import logging
from dotenv import load_dotenv
load_dotenv()

app = App(
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    oauth_settings=create_oauth_settings(),
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# ハンドラ登録
import slackApp.handlers

# Flask エラーハンドラー
@flask_app.errorhandler(404)
def handle_404_error(e):
    logging.warning(f"404 Not Found: {request.method} {request.path} - {e}")
    return {"error": "Not Found", "message": f"Path {request.path} not found"}, 404

@flask_app.errorhandler(400)
def handle_400_error(e):
    logging.error(f"400 Bad Request: {e}")
    return {"error": "Bad Request", "message": str(e)}, 400

@flask_app.errorhandler(500)
def handle_500_error(e):
    logging.exception(f"500 Internal Server Error: {e}")
    return {"error": "Internal Server Error", "message": str(e)}, 500

@flask_app.errorhandler(Exception)
def handle_generic_error(e):
    logging.exception(f"Unhandled exception: {e}")
    return {"error": "Internal Server Error", "message": str(e)}, 500

@flask_app.route("/")
def root():
    return '''<html><head><title>Slack Image Bot</title></head><body><h1>🤖 Slack Image Bot</h1><div>✅ サーバーは正常に動作中です</div></body></html>'''

@flask_app.route("/robots.txt", methods=["GET"])
def robots_txt():
    return "User-agent: *\nDisallow: /\n", 200, {'Content-Type': 'text/plain'}

@flask_app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204

@flask_app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    blocked_patterns = [
        'wp-', 'admin', 'login', 'config', '.env', 'api/v1',
        'graphql', 'xmlrpc', 'phpmyadmin', '.git', 'swagger'
    ]
    if any(pattern in path.lower() for pattern in blocked_patterns):
        logging.warning(f"ブロックされたパス: {request.method} /{path}")
        return {"error": "Forbidden"}, 403
    logging.warning(f"未定義のパス: {request.method} /{path}")
    return {"error": "Not Found", "message": f"Path /{path} not found"}, 404

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    try:
        result = handler.handle(request)
        return result
    except Exception as e:
        logging.exception(f"Slack events エンドポイントでエラー: {e}")
        return {"error": "Internal Server Error"}, 500

@flask_app.route("/slack/install", methods=["GET"])
def install():
    try:
        result = handler.handle(request)
        return result
    except Exception as e:
        logging.exception(f"Slack install エンドポイントでエラー: {e}")
        raise

@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def oauth_redirect():
    try:
        result = handler.handle(request)
        return result
    except Exception as e:
        logging.exception(f"Slack oauth_redirect エンドポイントでエラー: {e}")
        raise

@flask_app.route("/health", methods=["GET"])
def health_check():
    return {"status": "ok", "message": "Application is running"}
