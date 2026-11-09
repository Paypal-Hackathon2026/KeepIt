import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from app.db import supabase
from app.services.payouts import compute_payouts
from app.services.paypal import create_paypal_batch
import httpx
from uuid import UUID


logger = logging.getLogger(__name__)
def _parse_ts(ts:str)->datetime:
    return datetime.fromisoformat(ts.replace("Z","+00:00"))

def settle(challenge_id:UUID)->dict:
    ch_id=str(challenge_id)
    challenge=(supabase.table("challenges")
               .select("id,creator_id,status,entry_fee_minor,proof_deadline")
               .eq("id", ch_id).maybe_single().execute())
    ch=challenge.data
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")
    ALLOWED_STATUS=["active","closed","voting"]
    if ch["status"] not in ALLOWED_STATUS:
        raise HTTPException(status_code=409, detail=f"Challenge status does not allow settlement.")
    participants=(supabase.table("participants")
                 .select("user_id,outcome,profiles(paypal_email)")
                 .eq("challenge_id", ch_id)
                 .eq("paid", True)
                 .execute())
    p=participants.data or []
    if not p:
        supabase.table("challenges").update({"status":"settled"}).eq("id", ch_id).execute()
        return {"settled": True, "payouts": 0}
    deadline_passed=(True if ch["status"]=="closed" else False)
    all_resolved=all(participant["outcome"]!="pending" for participant in p)
    if not (deadline_passed or all_resolved):
        raise HTTPException(status_code=409, detail="Challenge is not ready for settlement.")
    lock_resp=(supabase.table("challenges")
                .update({"status":"settling"})
                .eq("id", ch_id)
                .eq("status", ch["status"])
                .execute())
    if not lock_resp.data:
        raise HTTPException(status_code=409, detail="Challenge is already being settled.")
    unresolved_ev=(
        supabase.table("evidence")
        .select("id")
        .eq("challenge_id", ch_id)
        .eq("status", "needs_vote")
        .execute()
    )
    has_unresolved_evidence=bool(unresolved_ev.data)
    if has_unresolved_evidence:
        logger.info(f"Challenge {ch_id} has unresolved evidence, refunding entry fees to all participants.")
        supabase.table("participants").update({"outcome":"forfeited"}).eq("challenge_id", ch_id).execute()
        for participant in p:
            participant["outcome"]="forfeited"
    elif deadline_passed:
        supabase.table("participants").update({"outcome":"forfeited"}).eq("challenge_id", ch_id).eq("outcome", "pending").execute()
        for participant in p:
            if participant["outcome"]=="pending":
                participant["outcome"]="forfeited"
    payouts_mapping=compute_payouts(participants=p, entry_fee_minor=ch["entry_fee_minor"])
    to_pay = {uid: amt for uid, amt in payouts_mapping.items() if amt > 0}
    if not to_pay:
        supabase.table("challenges").update({"status":"settled"}).eq("id", ch_id).execute()
        return {"settled": True, "payouts": 0}
    payout_rows=[{
        "challenge_id": ch_id,
        "user_id": uid,
        "amount_minor": amt,
        "status": "pending"}
        for uid,amt in to_pay.items()
    ]
    supabase.table("payouts").upsert(payout_rows, on_conflict="challenge_id,user_id").execute()
    saved_payouts=(supabase.table("payouts")
                     .select("id,user_id,amount_minor")
                     .eq("challenge_id", ch_id)
                     .execute()).data or []
    emails={participant["user_id"]: participant["profiles"]["paypal_email"] for participant in p if participant.get("profiles")}
    items_to_send=[{
        "payout_id": str(sp["id"]),
        "email":emails[sp["user_id"]],
        "amount_minor": sp["amount_minor"],}
        for sp in saved_payouts]
    try:
        paypal_reult=create_paypal_batch(ch_id, items_to_send)
        batch_id=paypal_reult["batch_header"]["payout_batch_id"]
    except Exception as exc:
        logger.exception("Paypal Payouts error for challenge %s: %s", ch_id, str(exc))
        supabase.table("challenges").update({"status":ch["status"]}).eq("id", ch_id).execute()
        raise HTTPException(status_code=502, detail="Paypal Payouts failed") from exc
    supabase.table("challenges").update({"paypal_batch_id": batch_id}).eq("id", ch_id).execute()
    return {"status": "settling", "paypal_batch_id": batch_id, "payouts": len(items_to_send)}

