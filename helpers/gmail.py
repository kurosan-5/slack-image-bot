import logging
from urllib.parse import urlencode

def gmail_compose_url(to: str, subject: str = "", body: str = "", account_index: int | None = None) -> str:
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
