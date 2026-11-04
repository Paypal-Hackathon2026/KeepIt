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


def save_evidence(challenge_id: str, user_id: str, photo: bytes) -> dict:
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
    return result.data[0]


    