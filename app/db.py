import httpx
from supabase import create_client, ClientOptions

from app import config

_http_client = httpx.Client(http2=False, timeout=30.0)
_options = ClientOptions(httpx_client=_http_client)

supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SECRET_KEY, options=_options)
