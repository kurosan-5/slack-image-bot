from slackApp.app import app
from slackApp.utils import fetch_slack_private_file, is_probably_image, send_mail_link
from AIParcer.parser import extract_from_bytes
import logging
import os
from collections import deque
from google.sheets import append_record_to_sheet

# scanData のテンプレートと、チャンネル(DM)ごとの保存先
SCAN_DATA_TEMPLATE = {
    "name_jp": "",
    "name_en": "",
    "company": "",
    "postal_code": "",
    "address": "",
    "email": "",
    "website": "",
    "phone": "",
}

# チャンネルごとに画像処理を直列化するための簡易キューと状態
channel_queues = {}        # channel_id -> deque([file_obj, ...])
channel_processing = {}    # channel_id -> bool (処理中か)
channel_tokens = {}        # channel_id -> bot_token（ファイル取得に使用）
channel_progress = {}      # channel_id -> {"processed": int, "total": int}
channel_scan_data = {}     # channel_id -> dict(scanData)


def _get_scan_data(channel_id: str) -> dict:
    data = channel_scan_data.get(channel_id)
    if data is None:
        data = dict(SCAN_DATA_TEMPLATE)
        channel_scan_data[channel_id] = data
    return data

def _clear_scan_data(channel_id: str):
    data = channel_scan_data.get(channel_id)
    if data is None:
        channel_scan_data[channel_id] = dict(SCAN_DATA_TEMPLATE)
        return
    for k in list(data.keys()):
        data[k] = ""


def _get_channel_id_from_event_body(body: dict) -> str:
    event = body.get("event", {})
    return event.get("channel") or event.get("channel_id") or ""


def _get_channel_id_from_action_body(body: dict) -> str:
    # actions の payload から頑健に channel_id を抜き出す
    ch = body.get("channel", {}).get("id")
    if ch:
        return ch
    container = body.get("container", {})
    if container.get("channel_id"):
        return container.get("channel_id")
    # fallback（まれ）
    return body.get("team", {}).get("id", "")


def _process_next_file_for_channel(channel_id: str, say):
    """チャンネルの待ち行列から次の1件だけ処理。失敗・成功に関わらず、
    ボタン押下の完了、または失敗通知後に次を進める設計のため、ここでは1件だけ解析し、
    アクションハンドラ側で次を起動する。"""
    try:
        q = channel_queues.get(channel_id)
        if not q or len(q) == 0:
            channel_processing[channel_id] = False
            # 進捗リセット
            if channel_id in channel_progress:
                channel_progress[channel_id]["processed"] = 0
                channel_progress[channel_id]["total"] = 0
            return

        # 処理中フラグを立てる
        channel_processing[channel_id] = True
        bot_token = channel_tokens.get(channel_id) or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            say("内部設定エラー（Bot token 未設定）。インストール設定を確認してください。")
            channel_processing[channel_id] = False
            return

        # 進捗の案内（現在のファイルが何件目か）
        prog = channel_progress.setdefault(channel_id, {"processed": 0, "total": 0})
        idx = prog.get("processed", 0) + 1
        total = prog.get("total", 0) or (prog.get("processed", 0) + len(q) + 1)
        try:
            say(f"読み込んでいます...({idx}/{total})")
        except Exception:
            pass

        f = q.popleft()
        if not is_probably_image(f, bot_token):
            logging.info(f"画像以外（に見える）のでスキップ: {f.get('name')} ({f.get('mimetype')}/{f.get('filetype')})")
            say("画像ファイル以外の形式で入力されたため、スキップします。")
            # 次のファイルへ（スキップも1件として進捗を進める）
            channel_progress[channel_id]["processed"] = channel_progress[channel_id].get("processed", 0) + 1
            _process_next_file_for_channel(channel_id, say)
            return

        url_private = f.get("url_private_download") or f.get("url_private")
        try:
            image_bytes = fetch_slack_private_file(url_private, bot_token)
        except Exception:
            logging.exception("画像ダウンロードに失敗しました")
            say("画像のダウンロードに失敗しました。もう一度お試しください。")
            # 次のファイルへ（失敗も1件として進捗を進める）
            channel_progress[channel_id]["processed"] = channel_progress[channel_id].get("processed", 0) + 1
            _process_next_file_for_channel(channel_id, say)
            return

        try:
            parsed = extract_from_bytes(image_bytes)
            logging.info(f"Gemini解析結果: {parsed}")
            ch_data = _get_scan_data(channel_id)
            ch_data.update({
                "name_jp":     parsed.get("name_jp", "")     or ch_data.get("name_jp", ""),
                "name_en":     parsed.get("name_en", "")     or ch_data.get("name_en", ""),
                "company":     parsed.get("company", "")     or ch_data.get("company", ""),
                "postal_code": parsed.get("postal_code", "") or ch_data.get("postal_code", ""),
                "address":     parsed.get("address", "")     or ch_data.get("address", ""),
                "email":       parsed.get("email", "")       or ch_data.get("email", ""),
                "website":     parsed.get("website", "")     or ch_data.get("website", ""),
                "phone":       parsed.get("phone", "")       or ch_data.get("phone", ""),
            })
            say("読み取り完了。\n")
            say(f"名前: {ch_data['name_jp']}")
            say(f"会社名: {ch_data['company']}")
            say(f"会社住所: {ch_data['address']}")
            say(f"Email: {ch_data['email']}")
            say(f"ウェブサイト: {ch_data['website']}")
            say(f"電話番号: {ch_data['phone']}")
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
            # ここでは待機。ボタン押下ハンドラの finally で次へ進む
        except Exception:
            logging.exception("Gemini 解析に失敗")
            say("画像の解析に失敗しました。もう一度お試しください。")
            # 次のファイルへ（失敗も1件として進捗を進める）
            channel_progress[channel_id]["processed"] = channel_progress[channel_id].get("processed", 0) + 1
            _process_next_file_for_channel(channel_id, say)
            return
    except Exception as e:
        logging.exception(f"キュー処理でエラー: {e}")
        # 失敗しても次に進める（進捗を進める）
        channel_progress.setdefault(channel_id, {"processed": 0, "total": 0})
        channel_progress[channel_id]["processed"] += 1
        _process_next_file_for_channel(channel_id, say)


@app.action("save_text")
def handle_save_text(ack, body, say):
    try:
        ack()
        channel_id = _get_channel_id_from_action_body(body)
        ch_data = _get_scan_data(channel_id)
        # Slackユーザ表記（display_name があれば優先）
        user_id = body.get("user", {}).get("id") or body.get("user", "")
        user_label = user_id
        try:
            if user_id:
                prof = app.client.users_info(user=user_id).get("user", {}).get("profile", {})
                display = prof.get("display_name") or prof.get("real_name")
                if display:
                    user_label = f"{display} ({user_id})"
        except Exception:
            pass

        try:
            append_record_to_sheet(ch_data, slack_user_label=user_label)
            say("スプレッドシートに保存しました。")
        except Exception as e:
            logging.exception("Sheets への保存に失敗しました")
            say(f"保存に失敗しました: {e}")

        if not ch_data.get('email'):
            say("メールアドレスが読み取れなかったため、Gmail作成リンクを生成できません。")
            # 次のファイルへ
            return

        send_mail_link(ch_data, say)

    except Exception as e:
        logging.exception(f"save_text ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logging.exception(f"エラーメッセージの送信にも失敗: {say_error}")
    finally:
        # 5) 必ず初期化（return ルートでも確実に実行）
        _clear_scan_data(channel_id)
            # 次のファイルへ
        channel_id = _get_channel_id_from_action_body(body)
        # processed を進める
        channel_progress.setdefault(channel_id, {"processed": 0, "total": 0})
        channel_progress[channel_id]["processed"] += 1
        _process_next_file_for_channel(channel_id, say)


@app.action("edit_text")
def handle_edit_text(ack, body, say):
    try:
        ack()
        channel_id = _get_channel_id_from_action_body(body)
        ch_data = _get_scan_data(channel_id)
        say("該当項目を変更してください。")
        editBlocks = [
            {
                "type": "input",
                "block_id": "edit_name",
                "label": {"type": "plain_text", "text": "名前"},
        "element": {"type": "plain_text_input", "action_id": "name", "initial_value": f"{ch_data['name_jp']}"},
            },
            {
                "type": "input",
                "block_id": "edit_company",
                "label": {"type": "plain_text", "text": "会社名"},
        "element": {"type": "plain_text_input", "action_id": "company", "initial_value": f"{ch_data['company']}"},
            },
            {
                "type": "input",
                "block_id": "edit_address",
                "label": {"type": "plain_text", "text": "会社住所"},
        "element": {"type": "plain_text_input", "action_id": "address", "initial_value": f"{ch_data['address']}"},
            },
            {
                "type": "input",
                "block_id": "edit_email",
                "label": {"type": "plain_text", "text": "Email"},
        "element": {"type": "plain_text_input", "action_id": "email", "initial_value": f"{ch_data['email']}"},
            },
            {
                "type": "input",
                "block_id": "edit_phone",
                "label": {"type": "plain_text", "text": "電話番号"},
        "element": {"type": "plain_text_input", "action_id": "phone", "initial_value": f"{ch_data['phone']}"},
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
        channel_id = _get_channel_id_from_action_body(body)
        ch_data = _get_scan_data(channel_id)
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
                    ch_data["name_jp"] = new_value
                elif key == "company":
                    display_key = "会社名"
                    ch_data["company"] = new_value
                elif key == "address":
                    display_key = "会社住所"
                    ch_data["address"] = new_value
                elif key == "email":
                    display_key = "Email"
                    ch_data["email"] = new_value
                elif key == "phone":
                    display_key = "電話番号"
                    ch_data["phone"] = new_value
                if display_key:
                    changes.append(f"{display_key}: {new_value}")
                    logging.info(f"{display_key} を {new_value} に更新")
        # 変更後の内容でシートへ追記（編集のたびに履歴が残る運用）
        user_id = body.get("user", {}).get("id") or body.get("user", "")
        user_label = user_id
        try:
            if user_id:
                prof = app.client.users_info(user=user_id).get("user", {}).get("profile", {})
                display = prof.get("display_name") or prof.get("real_name")
                if display:
                    user_label = f"{display} ({user_id})"
        except Exception:
            pass
        try:
            append_record_to_sheet(ch_data, slack_user_label=user_label)
            say("スプレッドシートにも追記しました。")
        except Exception as e:
            logging.exception("Sheets への保存に失敗しました")
            say(f"保存に失敗しました: {e}")

        if not ch_data.get('email'):
                say("メールアドレスが読み取れなかったため、Gmail作成リンクを生成できません。")
                # 次のファイルへ
                return

        send_mail_link(ch_data, say)

    except Exception as e:
        logging.exception(f"save_changes ハンドラーでエラーが発生: {e}")
        try:
            say(f"❌ エラーが発生しました: {str(e)}")
        except Exception as say_error:
            logging.exception(f"エラーメッセージの送信にも失敗: {say_error}")

    finally:
        # 5) 必ず初期化（return ルートでも確実に実行）
        _clear_scan_data(channel_id)
            # 次のファイルへ
        channel_id = _get_channel_id_from_action_body(body)
        # processed を進める
        channel_progress.setdefault(channel_id, {"processed": 0, "total": 0})
        channel_progress[channel_id]["processed"] += 1
        _process_next_file_for_channel(channel_id, say)



@app.event("message")
def handle_message_events(body, say, context):
    event = body.get("event", {})
    if "files" in event:
        channel_id = _get_channel_id_from_event_body(body)
        bot_token = context.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            say("内部設定エラー（Bot token 未設定）。インストール設定を確認してください。")
            return

        # キューへ投入
        q = channel_queues.get(channel_id)
        if q is None:
            q = deque()
            channel_queues[channel_id] = q
    # 進捗 total を加算
    channel_progress.setdefault(channel_id, {"processed": 0, "total": 0})
    channel_progress[channel_id]["total"] += len(event["files"])

    for f in event["files"]:
        q.append(f)
        # token を保持
        channel_tokens[channel_id] = bot_token
        # 進行中でなければ最初の1件だけ処理開始
        if not channel_processing.get(channel_id):
            _process_next_file_for_channel(channel_id, say)
        else:
            logging.info("通常メッセージ: " + event.get("text", "（テキストなし）"))
