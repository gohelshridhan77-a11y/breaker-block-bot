import os
import json
import requests
import hashlib

FYERS_CLIENT_ID  = os.environ.get("FYERS_CLIENT_ID")
FYERS_SECRET_KEY = os.environ.get("FYERS_SECRET_KEY")
FYERS_AUTH_CODE  = os.environ.get("FYERS_AUTH_CODE")

def get_app_hash():
    app_id = FYERS_CLIENT_ID.split("-")[0]
    secret = FYERS_SECRET_KEY
    combined = f"{app_id}:{secret}"
    return hashlib.sha256(combined.encode()).hexdigest()

def get_access_token():
    url = "https://api-t1.fyers.in/api/v3/token"
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": get_app_hash(),
        "code": FYERS_AUTH_CODE,
    }
    headers = {
        "Content-Type": "application/json"
    }
    r = requests.post(url, json=payload, headers=headers)
    data = r.json()
    if data.get("s") == "ok":
        return data["access_token"]
    raise Exception(f"Token error: {data}")
