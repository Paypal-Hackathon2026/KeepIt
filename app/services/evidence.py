from app.db import supabase
from app.services.images import to_jpeg

BUCKET = "evidence"
MAX_ATTEMPTS = 3

def count_attempts(challenge_id: str, user_id: str) -> int:
    result = (
        supabase.table("evidence")
        .select("id")
        .eq("challenge_id", challenge_id)
        .eq("user_id", user_id)
        .execute()
    )
    return len(result.data)


def save_evidence(challenge_id: str, user_id: str, photo: bytes) -> tuple[dict, bytes]:
    attempt = count_attempts(challenge_id, user_id) + 1
    if attempt > MAX_ATTEMPTS:
        raise ValueError("You have already used all 3 attempts.")

    jpeg = to_jpeg(photo)
    path = f"{challenge_id}/{user_id}/{attempt}.jpg"
    
    supabase.storage.from_(BUCKET).upload(
    path, jpeg, {"content-type": "image/jpeg", "upsert": "true"}
    )

    result = (
        supabase.table("evidence")
        .insert({
            "challenge_id": challenge_id,
            "user_id": user_id,
            "attempt": attempt,
            "storage_path": path,
        })
        .execute()
    )
    return result.data[0], jpeg


def send_to_vote(evidence_id: str) -> None:
    supabase.table("evidence").update({"status": "needs_vote"}).eq("id", evidence_id).execute()

def get_my_evidence(challenge_id: str, user_id: str) -> list[dict]:
    result = (
        supabase.table("evidence")
        .select("attempt, storage_path, verdicts(verified, confidence, reasoning, fraud_flags)")
        .eq("challenge_id", challenge_id)
        .eq("user_id", user_id)
        .order("attempt", desc=True)
        .execute()
    )

    attempts = result.data or []
    for row in attempts:
        try:
            signed_url = supabase.storage.from_(BUCKET).create_signed_url(
                row["storage_path"], 3600
            )
            row["photo_url"] = signed_url.get("signedURL") or signed_url.get("signedUrl")
        except Exception:
            row["photo_url"] = None
        row["verdict"] = row["verdicts"][0] if row["verdicts"] else None

    return attempts