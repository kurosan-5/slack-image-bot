import logging
from urllib.parse import urlencode

def gmail_compose_url_PC(to: str, subject: str = "", body: str = "", account_index: int | None = None) -> str:
    try:
        logging.debug(f"Gmail URL作成開始 - to: {to}, subject: {subject[:50]}...")

        if not to or "@" not in to:
            logging.warning(f"無効なメールアドレス: {to}")
            raise ValueError(f"Invalid email address: {to}")

        base = "https://mail.google.com/mail"
        if account_index is not None:
            base += f"/u/{account_index}"
        params = {"fs": "1", "tf": "cm", "to": to}
        if subject:
            params["su"] = subject
        if body:
            params["body"] = body

        url = f"{base}/?{urlencode(params)}"
        logging.debug(f"Gmail URL作成完了: {url[:100]}...")
        return url

    except Exception as e:
        logging.exception(f"Gmail URL作成エラー: {e}")
        raise

from urllib.parse import quote

def gmail_compose_url_mobile(to: str, subject: str = "", body: str = "") -> str:
    if not to or "@" not in to:
        raise ValueError(f"Invalid email address: {to}")

    params = []
    if subject:
        params.append("subject=" + quote(subject))
    if body:
        # 改行は \n でOK（%0A にエンコードされます）
        params.append("body=" + quote(body))
    qs = "&".join(params)
    return f"mailto:{to}?{qs}" if qs else f"mailto:{to}"

