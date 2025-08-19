# Flaskサーバーのエントリーポイント

from config.logging import setup_logging
import os
import logging
from dotenv import load_dotenv
load_dotenv()

log_level = logging.DEBUG if os.environ.get('ENVIRONMENT') == 'development' else logging.INFO
logger, log_print, safe_log_info = setup_logging(log_level)

if __name__ == "__main__":
    from slackApp.app import flask_app
    port = int(os.environ.get("PORT", 3000))
    safe_log_info(f"Starting Flask app on port {port}")
    debug_mode = os.environ.get('ENVIRONMENT') == 'development'
    flask_app.run(host="0.0.0.0", port=port, debug=debug_mode)
