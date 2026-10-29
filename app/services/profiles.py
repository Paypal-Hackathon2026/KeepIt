from app.db import supabase


def get_or_create_profile(paypal_user_id: str, display_name: str, paypal_email: str) -> dict:
    result = (
        supabase.table("profiles")
        .select("*")
        .eq("paypal_user_id", paypal_user_id)
        .execute()
    )
    if result.data:
        return result.data[0]

    result = (
        supabase.table("profiles")
        .insert({
            "paypal_user_id": paypal_user_id,
            "display_name": display_name,
            "paypal_email": paypal_email,
        })
        .execute()
    )
    return result.data[0]

def get_profile(profile_id: str) -> dict | None:
    result = supabase.table("profiles").select("*").eq("id", profile_id).execute()
    if result.data:
        return result.data[0]
    return None