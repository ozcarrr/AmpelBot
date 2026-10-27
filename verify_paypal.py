#!/usr/bin/env python3
"""
AmpelBot: PayPal Sandbox OAuth2 Verification Script
Validates sandbox credentials and confirms retrieval of a valid Bearer access token.
"""

import os
import sys
import base64
import json
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
TOKEN_ENDPOINT = f"{PAYPAL_BASE_URL}/v1/oauth2/token"


def check_prerequisites():
    """Validates presence of required environment variables."""
    missing = []
    if not PAYPAL_CLIENT_ID or "your_paypal_sandbox_client_id_here" in PAYPAL_CLIENT_ID:
        missing.append("PAYPAL_CLIENT_ID")
    if not PAYPAL_CLIENT_SECRET or "your_paypal_sandbox_client_secret_here" in PAYPAL_CLIENT_SECRET:
        missing.append("PAYPAL_CLIENT_SECRET")

    if missing:
        print("[ERROR] Missing or default credentials in .env:")
        for var in missing:
            print(f"  - {var}")
        print(f"Path: {os.path.abspath('.env')}")
        sys.exit(1)


def get_oauth2_token() -> bool:
    """Executes OAuth2 client_credentials token request against PayPal endpoint."""
    masked_id = (
        PAYPAL_CLIENT_ID[:6] + "..." + PAYPAL_CLIENT_ID[-4:]
        if len(PAYPAL_CLIENT_ID) > 10
        else "***"
    )
    print(f"[INFO] Target Base URL : {PAYPAL_BASE_URL}")
    print(f"[INFO] Token Endpoint  : {TOKEN_ENDPOINT}")
    print(f"[INFO] Client ID       : {masked_id}")

    try:
        import requests
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }
        data = {"grant_type": "client_credentials"}
        response = requests.post(
            TOKEN_ENDPOINT,
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            headers=headers,
            data=data,
            timeout=15,
        )
        status_code = response.status_code
        try:
            payload = response.json()
        except Exception:
            payload = {"raw_text": response.text}

    except ImportError:
        import urllib.request
        import urllib.parse
        import urllib.error

        credentials = f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode("utf-8")
        basic_auth_header = f"Basic {base64.b64encode(credentials).decode('utf-8')}"
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")

        req = urllib.request.Request(
            TOKEN_ENDPOINT,
            data=data,
            headers={
                "Authorization": basic_auth_header,
                "Accept": "application/json",
                "Accept-Language": "en_US",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.status
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status_code = e.code
            try:
                payload = json.loads(e.read().decode("utf-8"))
            except Exception:
                payload = {"error": str(e)}

    if status_code != 200:
        print(f"[ERROR] OAuth2 handshake failed with HTTP {status_code}.")
        print(f"[ERROR] Response: {json.dumps(payload, indent=2)}")
        return False

    access_token = payload.get("access_token", "")
    token_type = payload.get("token_type", "Bearer")
    expires_in = payload.get("expires_in", 0)
    app_id = payload.get("app_id", "N/A")
    scope = payload.get("scope", "N/A")
    expiry_time = datetime.now() + timedelta(seconds=expires_in)
    masked_token = (
        access_token[:12] + "..." + access_token[-8:]
        if len(access_token) > 20
        else access_token
    )

    print("[SUCCESS] OAuth2 token acquired.")
    print(f"  Status        : HTTP {status_code} OK")
    print(f"  Token Type    : {token_type}")
    print(f"  Token         : {masked_token}")
    print(f"  App ID        : {app_id}")
    print(f"  Valid (sec)   : {expires_in} (~{round(expires_in / 3600, 1)}h)")
    print(f"  Expires       : {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Scope         : {scope[:80]}...")
    return True


if __name__ == "__main__":
    check_prerequisites()
    success = get_oauth2_token()
    sys.exit(0 if success else 1)
