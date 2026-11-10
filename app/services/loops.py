import logging
from datetime import datetime, timezone
from app.services.settlement_service import settle
from app.db import supabase
from app.services.challenge_service import sync_challenge_status

logger = logging.getLogger(__name__)
def sync_challenge_statuses(challenge_id: str | None = None):
    now=datetime.now(timezone.utc).isoformat()
    try:
        challenges=(
            supabase.table("challenges").select("id, status,join_deadline,proof_deadline,voting_deadline").in_("status",["open","active","voting"])
            .execute()
        )
        for ch in challenges.data or []:
            sync_challenge_status(ch)

    except Exception as e:
        logger.error("Error syncing challenge statuses: %s", e)
def check_challenges_ready_for_settlement():
    now=datetime.now(timezone.utc).isoformat()
    try:
        due=(supabase.table("challenges")
             .select("id")
             .in_("status", ["closed"])
             .execute())
        for row in due.data or []:
            ch_id=row["id"]
            failed_payouts=(supabase.table("payouts")
                            .select("id")
                            .eq("challenge_id", ch_id)
                            .eq("status", "failed")
                            .limit(1)
                            .execute())
            if failed_payouts.data:
                continue
            try:
                logger.info(f"Auto-settling challenge {row['id']}")
                settle(row["id"])
            except Exception as e:
                logger.error(f"Error Auto-settling challenge {row['id']}: {e}")
    except Exception as e:
        logger.error(f"Error checking challenges for settlement: {e}")