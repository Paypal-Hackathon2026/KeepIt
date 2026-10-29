from urllib.parse import urlencode

import httpx

from app import config

REDIRECT_URI = f"{config.APP_URL}/auth/callback"


def build_login_url(state: str) -> str:
    params = {
        "flowEntry": "static",
        "client_id": config.PAYPAL_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    return f"{config.PAYPAL_WEB_BASE}/connect/?{urlencode(params)}"


def exchange_code(code: str) -> str:
    response = httpx.post(
        f"{config.PAYPAL_API_BASE}/v1/oauth2/token",
        auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_SECRET),
        data={"grant_type": "authorization_code", "code": code},
    )
    response.raise_for_status()
    return response.json()["access_token"]

def get_user_info(access_token: str) -> dict:
    response = httpx.get(
        f"{config.PAYPAL_API_BASE}/v1/identity/oauth2/userinfo",
        params={"schema": "paypalv1.1"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    response.raise_for_status()
    return response.json()
