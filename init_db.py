#!/usr/bin/env python3
"""
データベースのテーブルを初期化するスクリプト
本番環境デプロイ前に一度実行してください
"""
import os
from dotenv import load_dotenv
from slack_sdk.oauth.installation_store.sqlalchemy import SQLAlchemyInstallationStore
from slack_sdk.oauth.state_store.sqlalchemy import SQLAlchemyOAuthStateStore
from sqlalchemy import create_engine, MetaData, Table, Column, String, DateTime, Text, Integer, text
from sqlalchemy.sql import func

load_dotenv()

def init_database():
    """データベースのテーブルを作成"""
    database_url = os.environ.get("DATABASE_URL")

    # テスト用にSQLiteを使用（DATABASE_URLが設定されていない場合）
    if not database_url:
        database_url = "sqlite:///./slack_oauth.db"
        print("DATABASE_URL未設定のため、SQLiteを使用します")

    print(f"データベース接続: {database_url}")

    try:
        print("データベースを初期化中...")

        # SQLAlchemy Engine を作成
        engine = create_engine(database_url)

        # メタデータを作成
        metadata = MetaData()

        # Slack installations テーブルを明示的に定義（最新のSlack SDK対応）
        installations_table = Table(
            'slack_installations',
            metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('client_id', String(32), nullable=False),
            Column('app_id', String(32)),
            Column('enterprise_id', String(32)),
            Column('enterprise_name', Text),
            Column('enterprise_url', Text),
            Column('team_id', String(32)),
            Column('team_name', Text),
            Column('bot_token', Text),
            Column('bot_id', String(32)),
            Column('bot_user_id', String(32)),
            Column('bot_scopes', Text),
            Column('bot_refresh_token', Text),
            Column('bot_token_expires_at', DateTime),
            Column('user_id', String(32)),
            Column('user_token', Text),
            Column('user_scopes', Text),
            Column('user_refresh_token', Text),
            Column('user_token_expires_at', DateTime),
            Column('incoming_webhook_url', Text),
            Column('incoming_webhook_channel', Text),
            Column('incoming_webhook_channel_id', String(32)),
            Column('incoming_webhook_configuration_url', Text),
            Column('is_enterprise_install', String(5)),
            Column('token_type', String(32)),
            Column('installed_at', DateTime, default=func.now())
        )

        # Slack bots テーブルを明示的に定義（最新のSlack SDK対応）
        bots_table = Table(
            'slack_bots',
            metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('client_id', String(32), nullable=False),
            Column('app_id', String(32)),
            Column('enterprise_id', String(32)),
            Column('enterprise_name', Text),
            Column('team_id', String(32)),
            Column('team_name', Text),
            Column('bot_token', Text),
            Column('bot_id', String(32)),
            Column('bot_user_id', String(32)),
            Column('bot_scopes', Text),
            Column('bot_refresh_token', Text),
            Column('bot_token_expires_at', DateTime),
            Column('is_enterprise_install', String(5)),
            Column('installed_at', DateTime, default=func.now())
        )

        # OAuth states テーブルを明示的に定義
        oauth_states_table = Table(
            'slack_oauth_states',
            metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('state', String(128), nullable=False, unique=True),
            Column('expire_at', DateTime, nullable=False),
            Column('client_id', String(32)),
            Column('scope', Text),
            Column('team_id', String(32)),
            Column('user_id', String(32))
        )

        # テーブルを実際に作成（既存テーブルを削除してから作成）
        print("既存テーブルを削除して新しいテーブルを作成中...")
        metadata.drop_all(engine)
        metadata.create_all(engine)

        # 作成されたテーブルを確認
        with engine.connect() as conn:
            if database_url.startswith('postgresql'):
                result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                tables = [row[0] for row in result]
            elif database_url.startswith('sqlite'):
                result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
                tables = [row[0] for row in result]
            else:
                tables = ["確認できませんでした"]

            print(f"作成されたテーブル: {', '.join(tables)}")

        # installation_store のインスタンスを作成（接続テスト）
        installation_store = SQLAlchemyInstallationStore(
            client_id=os.environ.get("SLACK_CLIENT_ID", "dummy_client_id"),
            engine=engine
        )

        # state_store のインスタンスを作成（接続テスト）
        state_store = SQLAlchemyOAuthStateStore(
            engine=engine,
            expiration_seconds=600
        )

        print("データベースの初期化が完了しました")
        print("Supabaseコンソールでテーブルを確認してください")
        return True

    except Exception as e:
        print(f"データベース初期化エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    init_database()
