import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


APP_URL = _require("APP_URL")
SESSION_SECRET = _require("SESSION_SECRET")
PAYPAL_CLIENT_ID = _require("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = _require("PAYPAL_SECRET")
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_SECRET_KEY = _require("SUPABASE_SECRET_KEY")

PAYPAL_API_BASE = os.getenv("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
PAYPAL_WEB_BASE = os.getenv("PAYPAL_WEB_BASE", "https://www.sandbox.paypal.com")