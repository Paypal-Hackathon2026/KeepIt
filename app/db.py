from supabase import create_client

from app import config

supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SECRET_KEY)