from datetime import datetime
from decimal import Decimal

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
    result = supabase.table("profiles").select("*").eq("id", str(profile_id)).execute()
    if result.data:
        return result.data[0]
    return None


def format_member_since(value: str | datetime | None) -> str:
    """
    Format member since date nicely (e.g. 'November 7, 2026').
    """
    if not value:
        return ""
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
        except (ValueError, TypeError):
            return value[:10]
    elif isinstance(value, datetime):
        return f"{value.strftime('%B')} {value.day}, {value.year}"
    return str(value)


def get_profile_stats(user_id: str) -> dict:
    """
    Compute statistics for the user's profile:
    - challenges_joined: total challenges the user joined
    - challenges_completed: number of challenges completed (outcome == 'verified')
    - net_result_minor: successful payouts minus captured payments in minor units
    - net_result_pln: net result in PLN (Decimal)
    - net_result_fmt: formatted net result string (e.g. '+25.00 PLN', '-10.00 PLN', '0.00 PLN')
    - active_challenges_amount_minor: entry fees paid into active challenges (not settled yet)
    - active_challenges_amount_pln: active challenges amount in PLN (Decimal)
    - active_challenges_amount_fmt: formatted active challenges amount string (e.g. '20.00 PLN')
    """
    user_id_str = str(user_id)

    participants_res = (
        supabase.table("participants")
        .select("challenge_id, paid, outcome")
        .eq("user_id", user_id_str)
        .execute()
    )
    participants = participants_res.data or []

    challenges_joined = len(participants)
    challenges_completed = sum(1 for p in participants if p.get("outcome") == "verified")

    active_challenges_amount_minor = 0
    challenge_ids = [p["challenge_id"] for p in participants if p.get("challenge_id")]
    if challenge_ids:
        challenges_res = (
            supabase.table("challenges")
            .select("id, status, entry_fee_minor")
            .in_("id", challenge_ids)
            .execute()
        )
        challenges_by_id = {str(c["id"]): c for c in (challenges_res.data or [])}
        for p in participants:
            if p.get("paid"):
                c = challenges_by_id.get(str(p["challenge_id"]))
                if c and c.get("status") in ("open", "active", "voting", "closed", "settling"):
                    active_challenges_amount_minor += c.get("entry_fee_minor", 0)

    payouts_res = (
        supabase.table("payouts")
        .select("amount_minor, status")
        .eq("user_id", user_id_str)
        .execute()
    )
    total_payouts_minor = sum(
        row.get("amount_minor", 0)
        for row in (payouts_res.data or [])
        if row.get("status") == "success"
    )

    payments_res = (
        supabase.table("payments")
        .select("amount_minor, status")
        .eq("user_id", user_id_str)
        .execute()
    )
    total_payments_minor = sum(
        row.get("amount_minor", 0)
        for row in (payments_res.data or [])
        if row.get("status") == "captured"
    )

    net_result_minor = total_payouts_minor - total_payments_minor
    net_result_pln = Decimal(net_result_minor) / Decimal(100)

    if net_result_minor > 0:
        net_result_fmt = f"+{net_result_pln:.2f} PLN"
    elif net_result_minor < 0:
        net_result_fmt = f"{net_result_pln:.2f} PLN"
    else:
        net_result_fmt = "0.00 PLN"

    active_challenges_amount_pln = Decimal(active_challenges_amount_minor) / Decimal(100)
    active_challenges_amount_fmt = f"{active_challenges_amount_pln:.2f} PLN"

    return {
        "challenges_joined": challenges_joined,
        "challenges_completed": challenges_completed,
        "net_result_minor": net_result_minor,
        "net_result_pln": net_result_pln,
        "net_result_fmt": net_result_fmt,
        "active_challenges_amount_minor": active_challenges_amount_minor,
        "active_challenges_amount_pln": active_challenges_amount_pln,
        "active_challenges_amount_fmt": active_challenges_amount_fmt,
    }
