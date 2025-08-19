from slackApp.app import app
from helpers.gmail import gmail_compose_url
from slackApp.utils import fetch_slack_private_file, is_probably_image
from AIParcer.parser import extract_from_bytes
import logging
import os

scanData = {
    "name_jp": "",
    "name_en": "",
    "company": "",
    "postal_code": "",
    "address": "",
    "email": "",
    "website": "",
    "phone": "",
}

@app.action("save_text")
def handle_save_text(ack, body, say):
    try:
        ack()
        if not scanData.get('email'):
            say("メールアドレスが読み取れなかったため、Gmail作成リンクを生成できません。")
            return
        say("保存しました。")
        body_template = (
            f"こんにちは、{scanData['name_jp']}さん。\n"
            f"会社名: {scanData['company']}\n"
            f"会社住所: {scanData['address']}\n"
            f"Email: {scanData['email']}\n"
            f"ウェブサイト: {scanData['website']}\n"
            f"電話番号: {scanData['phone']}"
        )
        url = gmail_compose_url(
            to=scanData["email"],
            subject=f"{scanData['name_jp']}さんの名刺情報",
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
    except Exception as e:
        logging.exception(f"save_text ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logging.exception(f"エラーメッセージの送信にも失敗: {say_error}")

@app.action("edit_text")
def handle_edit_text(ack, body, say):
    try:
        ack()
        say("該当項目を変更してください。")
        editBlocks = [
            {
                "type": "input",
                "block_id": "edit_name",
                "label": {"type": "plain_text", "text": "名前"},
                "element": {"type": "plain_text_input", "action_id": "name", "initial_value": f"{scanData['name_jp']}"},
            },
            {
                "type": "input",
                "block_id": "edit_company",
                "label": {"type": "plain_text", "text": "会社名"},
                "element": {"type": "plain_text_input", "action_id": "company", "initial_value": f"{scanData['company']}"},
            },
            {
                "type": "input",
                "block_id": "edit_address",
                "label": {"type": "plain_text", "text": "会社住所"},
                "element": {"type": "plain_text_input", "action_id": "address", "initial_value": f"{scanData['address']}"},
            },
            {
                "type": "input",
                "block_id": "edit_email",
                "label": {"type": "plain_text", "text": "Email"},
                "element": {"type": "plain_text_input", "action_id": "email", "initial_value": f"{scanData['email']}"},
            },
            {
                "type": "input",
                "block_id": "edit_phone",
                "label": {"type": "plain_text", "text": "電話番号"},
                "element": {"type": "plain_text_input", "action_id": "phone", "initial_value": f"{scanData['phone']}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "変更を保存"},
                        "style": "primary",
                        "action_id": "save_changes"
                    }
                ],
            },
        ]
        say(blocks=editBlocks, text="変更したい項目を選んでください")
    except Exception as e:
        logging.exception(f"edit_text ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logging.exception(f"エラーメッセージの送信にも失敗: {say_error}")

@app.action("save_changes")
def handle_save_changes(ack, body, say):
    try:
        ack()
        changes = []
        state_values = body.get("state", {}).get("values", {})
        if not state_values:
            logging.warning("state.values が空です")
            say("❌ フォームデータが取得できませんでした。もう一度お試しください。")
            return
        for block in state_values:
            block_data = state_values[block]
            for key, value in block_data.items():
                display_key = ""
                new_value = value.get("value", "")
                if key == "name":
                    display_key = "名前"
                    scanData["name_jp"] = new_value
                elif key == "company":
                    display_key = "会社名"
                    scanData["company"] = new_value
                elif key == "address":
                    display_key = "会社住所"
                    scanData["address"] = new_value
                elif key == "email":
                    display_key = "Email"
                    scanData["email"] = new_value
                elif key == "phone":
                    display_key = "電話番号"
                    scanData["phone"] = new_value
                if display_key:
                    changes.append(f"{display_key}: {new_value}")
                    logging.info(f"{display_key} を {new_value} に更新")
        say("変更内容を保存しました:\n" + "\n".join(changes))
        body_template = (
            f"こんにちは、{scanData['name_jp']}さん。\n"
            f"会社名: {scanData['company']}\n"
            f"会社住所: {scanData['address']}\n"
            f"Email: {scanData['email']}\n"
            f"ウェブサイト: {scanData['website']}\n"
            f"電話番号: {scanData['phone']}"
        )
        if not scanData.get('email'):
            say("メールアドレスが読み取れなかったため、Gmail作成リンクを生成できません。")
            return
        url = gmail_compose_url(
            to=scanData["email"],
            subject=f"{scanData['name_jp']}さんの名刺情報",
            body=body_template,
        )
        logging.info(f"生成されたGmail URL: {url}")
        say(
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": "保存した内容をもとにGmailを送信:"}},
                {"type": "actions", "elements": [
                    {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Gmailで新規作成"}, "url": url}
                ]},
            ],
            text=f"Gmail作成リンク: {url}",
        )
        logging.info("Gmail作成リンク送信完了")
    except Exception as e:
        logging.exception(f"save_changes ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logging.exception(f"エラーメッセージの送信にも失敗: {say_error}")

@app.event("message")
def handle_message_events(body, say, context):
    say('読み込んでいます...')
    event = body.get("event", {})
    if "files" in event:
        bot_token = context.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            say("内部設定エラー（Bot token 未設定）。インストール設定を確認してください。")
            return
        for f in event["files"]:
            if not is_probably_image(f, bot_token):
                logging.info(f"画像以外（に見える）のでスキップ: {f.get('name')} ({f.get('mimetype')}/{f.get('filetype')})")
                continue
            url_private = f.get("url_private_download") or f.get("url_private")
            filename = f.get("name", "unknown")
            try:
                image_bytes = fetch_slack_private_file(url_private, bot_token)
            except Exception:
                logging.exception("画像ダウンロードに失敗しました")
                say("画像のダウンロードに失敗しました。もう一度お試しください。")
                continue
            try:
                data = extract_from_bytes(image_bytes)
                logging.info(f"Gemini解析結果: {data}")
                scanData.update({
                    "name_jp":     data.get("name_jp", "")     or scanData.get("name_jp", ""),
                    "name_en":     data.get("name_en", "")     or scanData.get("name_en", ""),
                    "company":     data.get("company", "")     or scanData.get("company", ""),
                    "postal_code": data.get("postal_code", "") or scanData.get("postal_code", ""),
                    "address":     data.get("address", "")     or scanData.get("address", ""),
                    "email":       data.get("email", "")       or scanData.get("email", ""),
                    "website":     data.get("website", "")     or scanData.get("website", ""),
                    "phone":       data.get("phone", "")       or scanData.get("phone", ""),
                })
                say("読み取り完了。\n")
                say(f"名前: {scanData['name_jp']}")
                say(f"会社名: {scanData['company']}")
                say(f"会社住所: {scanData['address']}")
                say(f"Email: {scanData['email']}")
                say(f"ウェブサイト: {scanData['website']}")
                say(f"電話番号: {scanData['phone']}")
                blocks = [
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "保存する"},
                                "style": "primary",
                                "action_id": "save_text"
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "変更する"},
                                "action_id": "edit_text"
                            },
                        ],
                    }
                ]
                say(blocks=blocks, text="読み取り結果に対してアクションを選んでください")
            except Exception:
                logging.exception("Gemini 解析に失敗")
                say("画像の解析に失敗しました。もう一度お試しください。")
    else:
        logging.info("通常メッセージ: " + event.get("text", "（テキストなし）"))
