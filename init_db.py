#!/usr/bin/env python3
"""
データベースのテーブルを初期化するスクリプト
本番環境デプロイ前に一度実行してください
"""
import os
from dotenv import load_dotenv
from slack_sdk.oauth.installation_store.sqlalchemy import SQLAlchemyInstallationStore
from slack_sdk.oauth.state_store.sqlalchemy import SQLAlchemyOAuthStateStore

load_dotenv()

def init_database():
    """データベースのテーブルを作成"""
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        print("❌ DATABASE_URL環境変数が設定されていません")
        return False

    try:
        print("📊 データベースを初期化中...")

        # installation_store のテーブル作成
        installation_store = SQLAlchemyInstallationStore(
            database_url=database_url
        )

        # state_store のテーブル作成
        state_store = SQLAlchemyOAuthStateStore(
            database_url=database_url,
            expiration_seconds=600
        )

        print("✅ データベースの初期化が完了しました")
        print(f"🔗 接続先: {database_url.split('@')[1] if '@' in database_url else 'ローカル'}")
        return True

    except Exception as e:
        print(f"❌ データベース初期化エラー: {e}")
        return False

if __name__ == "__main__":
    init_database()
