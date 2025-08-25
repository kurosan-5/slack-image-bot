import requests
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