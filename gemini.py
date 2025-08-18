# gemini.py
import io, os, json
from typing import Dict, Any
from PIL import Image
from pillow_heif import register_heif_opener
import google.generativeai as genai

# HEICファイルサポートを有効にする
register_heif_opener()

MODEL = "gemini-2.5-flash-lite"

SCHEMA = {
  "type": "object",
  "properties": {
    "name_jp": {"type": "string"},
    "name_en": {"type": "string"},
    "company": {"type": "string"},
    "postal_code": {"type": "string"},
    "address": {"type": "string"},
    "email": {"type": "string"},
    "website": {"type": "string"},
    "phone": {"type": "string"}
  }
}

SYSTEM_PROMPT = (
  "You are a precise business card parser for Japanese and English cards. "
  "Return strict JSON per the schema. Missing fields should be empty strings."
)

def _bytes_to_pil(b: bytes) -> Image.Image:
  try:
    img = Image.open(io.BytesIO(b))
    # 形式を確認してログ出力
    print(f"Image format detected: {img.format}")
    return img.convert("RGB")
  except Exception as e:
    print(f"Error opening image: {type(e).__name__}: {e}")
    # より詳細なエラー情報を提供
    print(f"Image bytes length: {len(b)}")
    print(f"First 20 bytes: {b[:20]}")
    raise

def extract_from_bytes(image_bytes: bytes) -> Dict[str, Any]:
  genai.configure(api_key=os.environ["GEMINI_API_KEY"])
  img = _bytes_to_pil(image_bytes)

  model = genai.GenerativeModel(
    model_name=MODEL,
    generation_config={
      "response_mime_type": "application/json",
      "response_schema": SCHEMA
    },
    system_instruction=SYSTEM_PROMPT
  )

  resp = model.generate_content([img])

  text = getattr(resp, "text", None)
  if text is None:
    # 互換: 古いレスポンス形式
    text = resp.candidates[0].content.parts[0].text

  try:
    data = json.loads(text)
  except Exception:
    # まれに説明文が混ざるので {} 部分を抽出してパース
    left, right = text.find("{"), text.rfind("}")
    data = json.loads(text[left:right+1])

  # 欠けているキーを空文字で補完
  for k in SCHEMA["properties"].keys():
    data.setdefault(k, "")

  return data
