import requests
from helpers.gmail import gmail_compose_url_PC, gmail_compose_url_mobile
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff")

def fetch_slack_private_file(url_private: str, bot_token: str) -> bytes:
    headers = {"Authorization": f"Bearer {bot_token}"}
    resp = requests.get(url_private, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content

def is_probably_image(slack_file: dict, bot_token: str) -> bool:
    mt = (slack_file.get("mimetype") or "").lower()
    if mt.startswith("image/"):
        return True

    name = (slack_file.get("name") or "").lower()
    if any(name.endswith(ext) for ext in IMAGE_EXTS):
        return True

    ft = (slack_file.get("filetype") or "").lower()
    if ft in [ext.lstrip(".") for ext in IMAGE_EXTS]:
        return True

    try:
        url = slack_file.get("url_private") or slack_file.get("url_private_download")
        if url:
            headers = {"Authorization": f"Bearer {bot_token}"}
            r = requests.head(url, headers=headers, timeout=10)
            ct = (r.headers.get("Content-Type") or "").lower()
            if ct.startswith("image/"):
                return True
    except Exception:
        pass
    return False

def send_mail_link(scanData, say):
    display_name = scanData.get('name', '')
    body_template = (
            f"こんにちは、{display_name}さん。\n"
            f"会社名: {scanData['company']}\n"
            f"郵便番号: {scanData['postal_code']}\n"
            f"会社住所: {scanData['address']}\n"
            f"Email: {scanData['email']}\n"
            f"ウェブサイト: {scanData['website']}\n"
            f"電話番号: {scanData['phone']}"
    )
    url_mobile = gmail_compose_url_mobile(
        to=scanData["email"],
        subject=f"{display_name}さんの名刺情報",
        body=body_template,
    )
    url_PC = gmail_compose_url_PC(
        to=scanData["email"],
        subject=f"{display_name}さんの名刺情報",
        body=body_template,
    )
    say(
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": "保存した内容をもとにGmailを送信:"}},
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "メールを作成(モバイル)"}, "url": url_mobile}
            ]},
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "メールを作成(PC)"}, "url": url_PC}
            ]},
        ],
        text=f"Gmail作成リンク: {url_mobile}",
    )