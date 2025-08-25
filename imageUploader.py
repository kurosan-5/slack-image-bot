import boto3
import os
from dotenv import load_dotenv

load_dotenv()

session = boto3.session.Session()

s3 = session.client(
    service_name='s3',
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    endpoint_url=os.getenv("ENDPOINT_URL"),
)


def upload_file_to_r2(local_path, file_name):
    bucket_name = os.getenv("R2_BUCKET_NAME")
    with open(local_path, "rb") as f:
        s3.upload_fileobj(f, bucket_name, file_name)
    print(f"✅ アップロード成功: {file_name}")

# 使用例
upload_file_to_r2("image.jpg", "image.jpg")
