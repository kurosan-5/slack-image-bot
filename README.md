# Slack Image Bot 仕様書・構成ドキュメント

## 概要
Slack Image Botは、Slack上で画像（名刺等）を受け取り、Gemini APIでテキスト解析し、Gmail作成やGoogle Sheets連携などを行う業務支援ボットです。

---

## フォルダ構成

```
slack-image-bot/
│
├── main.py                # アプリ起動・Flaskサーバーのエントリーポイント
├── slack/                 # Slack関連処理置き場
│   ├── app.py             # Slack Boltアプリ本体・Flaskルーティング
│   ├── handlers.py        # Slackイベント/アクションハンドラ
│   ├── utils.py           # Slack用ユーティリティ（画像判定・ファイル取得）
│   └── oauth.py           # OAuth設定
├── gemini/                # Gemini解析置き場
│   └── parser.py          # 画像解析ロジック（Gemini API）
├── google/                # Google API置き場
│   └── sheets.py          # Google Sheets連携
├── helpers/               # 汎用ヘルパー置き場
│   └── gmail.py           # Gmail作成URL生成
├── config/                # 設定・初期化置き場
│   └── logging.py         # ログ設定
├── requirements.txt       # Python依存パッケージ
├── Procfile               # サーバー起動用（Heroku/Render等）
└── .env                   # 環境変数管理
```

---

## 処理フロー

1. **Slackイベント受信**
    - `main.py` → `slack/app.py` → `slack/handlers.py`
    - 画像ファイルが投稿されると、`handle_message_events`で受信
2. **画像判定・取得**
    - `slack/utils.py`の`is_probably_image`で画像判定
    - `fetch_slack_private_file`で画像バイト取得
3. **Gemini解析**
    - `gemini/parser.py`の`extract_from_bytes`で画像解析
    - 名刺情報（氏名・会社・メール等）を抽出
4. **Slackへの結果表示・アクション**
    - 解析結果をSlackに表示
    - 「保存」「変更」ボタンでアクション
5. **Gmail作成リンク生成**
    - `helpers/gmail.py`の`gmail_compose_url`でGmail新規作成URL生成
    - Slack上でボタン表示
6. **Google Sheets連携**
    - `google/sheets.py`の`export_to_existing_sheet`でデータをGoogle Sheetsへ出力
7. **ログ・エラーハンドリング**
    - `config/logging.py`でログ出力・Render/Heroku対応
    - Flask/Slackのエラーは`slack/app.py`で一元管理

---

## 拡張・運用ポイント
- 各用途ごとに分割されているため、機能追加・修正が容易
- APIキーやDB接続情報は`.env`で管理
- Flaskルーティングは`slack/app.py`で一元化
- Gemini解析ロジックは`gemini/parser.py`で独立管理
- Google SheetsやGmail連携も個別ファイルで拡張可能

---

## 依存パッケージ例
- slack_bolt
- flask
- pillow, pillow_heif
- google-generativeai
- gspread, oauth2client
- python-dotenv
- sqlalchemy

---

## 環境変数例（.env）
```
SLACK_SIGNING_SECRET=xxxx
SLACK_CLIENT_ID=xxxx
SLACK_CLIENT_SECRET=xxxx
SLACK_BOT_TOKEN=xxxx
DATABASE_URL=postgresql://...
GEMINI_API_KEY=xxxx
GOOGLE_CREDENTIALS={...}
SPREADSHEET_ID=xxxx
ENVIRONMENT=development
PORT=3000
```

---

## 備考
- 主要な処理は各ファイルに分離済み
- 追加機能やAPI連携も容易に拡張可能
