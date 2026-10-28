import os
from fastapi import HTTPException, Request
from itsdangerous import URLSafeSerializer
from app.supabase_client import supabase

serializer = URLSafeSerializer(os.environ["SESSION_SECRET"])


def get_current_user(request: Request) -> dict:
    """Extract the authenticated user profile from a signed session cookie."""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = serializer.loads(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session")

    resp = (
        supabase.table("profiles")
        .select("*")
        .eq("id", data["user_id"])
        .single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=401, detail="User not found")
    return resp.data

