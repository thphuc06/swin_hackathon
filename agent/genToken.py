import base64
import hashlib
import hmac
import os

import boto3
from dotenv import load_dotenv
from pathlib import Path

env_file = os.getenv("ENV_FILE")
if env_file:
    load_dotenv(env_file)
else:
    load_dotenv(Path(__file__).with_name(".env"))

REGION = os.getenv("AWS_REGION", "us-east-1")
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET", "")
USERNAME = os.getenv("COGNITO_USERNAME", "")
PASSWORD = os.getenv("COGNITO_PASSWORD", "")

if not CLIENT_ID or not USERNAME or not PASSWORD:
    raise SystemExit(
        "Missing COGNITO_CLIENT_ID / COGNITO_USERNAME / COGNITO_PASSWORD env vars. "
        "Run from agent/ or set ENV_FILE to your .env path."
    )


def secret_hash(username: str, client_id: str, client_secret: str) -> str:
    msg = (username + client_id).encode("utf-8")
    key = client_secret.encode("utf-8")
    dig = hmac.new(key, msg, hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


client = boto3.client("cognito-idp", region_name=REGION)

auth_params = {"USERNAME": USERNAME, "PASSWORD": PASSWORD}
if CLIENT_SECRET:
    auth_params["SECRET_HASH"] = secret_hash(USERNAME, CLIENT_ID, CLIENT_SECRET)

resp = client.initiate_auth(
    ClientId=CLIENT_ID,
    AuthFlow="USER_PASSWORD_AUTH",
    AuthParameters=auth_params,
)

print("AccessToken:", resp["AuthenticationResult"]["AccessToken"])
print("IdToken:", resp["AuthenticationResult"]["IdToken"])
