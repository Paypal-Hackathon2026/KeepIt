from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from PIL import Image, UnidentifiedImageError

from app.deps import current_user
from app.services.challenge_service import get_challenge_by_id
from app.services.evidence import get_my_evidence
from app.services.proof_service import process_proof
from app.routes.helpers import MAX_UPLOAD_BYTES, _find_participant

router = APIRouter()


@router.post("/challenges/{challenge_id}/evidence")
def upload_evidence(
    challenge_id: UUID,
    user: Annotated[dict, Depends(current_user)],
    photo: UploadFile = File(...),
):
    back = f"/challenges/{challenge_id}"

    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    participant = _find_participant(challenge, user["id"])
    if not participant or not participant.get("paid"):
        raise HTTPException(status_code=403, detail="Only paid participants can upload proof")

    if participant.get("outcome") != "pending":
        return RedirectResponse(f"{back}?proof_error=closed", status_code=303)
    user_attempts = get_my_evidence(str(challenge_id), str(user["id"]))
    if any(attempt.get("status") == "needs_vote" for attempt in user_attempts):
        return RedirectResponse(f"{back}?proof_error=needs_vote", status_code=303)

    now = datetime.now(timezone.utc)
    proof_dl = challenge.get("proof_deadline")
    if isinstance(proof_dl, str):
        proof_dl = datetime.fromisoformat(proof_dl.replace("Z", "+00:00"))
    if proof_dl and proof_dl.tzinfo is None:
        proof_dl = proof_dl.replace(tzinfo=timezone.utc)

    if (proof_dl and now >= proof_dl) or challenge.get("status") not in ("open", "active"):
        return RedirectResponse(f"{back}?proof_error=closed", status_code=303)

    data = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return RedirectResponse(f"{back}?proof_error=too_big", status_code=303)

    try:
        result = process_proof(challenge, str(user["id"]), data)
    except ValueError:
        return RedirectResponse(f"{back}?proof_error=no_attempts", status_code=303)
    except (UnidentifiedImageError, Image.DecompressionBombError):
        return RedirectResponse(f"{back}?proof_error=not_image", status_code=303)

    return RedirectResponse(f"{back}?proof={result}", status_code=303)
