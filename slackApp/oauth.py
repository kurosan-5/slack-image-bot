from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk.oauth.installation_store.sqlalchemy import SQLAlchemyInstallationStore
from slack_sdk.oauth.state_store.sqlalchemy import SQLAlchemyOAuthStateStore
from sqlalchemy import create_engine
import os
import logging

def create_oauth_settings():
    database_url = os.environ.get("DATABASE_URL")
    try:
        engine = create_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 30,
                "keepalives_idle": 120,
                "keepalives_interval": 30,
                "keepalives_count": 3,
            }
        )
        with engine.connect():
            logging.info("データベース接続テスト成功")
    except Exception as e:
        logging.exception(f"データベース接続エラー: {e}")
        raise

    installation_store = SQLAlchemyInstallationStore(
        client_id=os.environ["SLACK_CLIENT_ID"],
        engine=engine,
        logger=logging.getLogger(__name__),
    )
    state_store = SQLAlchemyOAuthStateStore(
        engine=engine,
        expiration_seconds=600,
        logger=logging.getLogger(__name__),
    )

    return OAuthSettings(
        client_id=os.environ["SLACK_CLIENT_ID"],
        client_secret=os.environ["SLACK_CLIENT_SECRET"],
        scopes=[
            "chat:write",
            "files:read",
            "im:history",
            "im:read",
        ],
        installation_store=installation_store,
        state_store=state_store,
    )
