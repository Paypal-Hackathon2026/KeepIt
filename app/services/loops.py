import logging
from datetime import datetime, timezone
from app.services.settlement_service import settle
from app.db import supabase

logger = logging.getLogger(__name__)
def sync_challenge_statuses():
    now=datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("challenges").update({"status": "active"}).eq("status","open").lte("join_deadline", now).execute()
        supabase.table("challenges").update({"status": "voting"}).eq("status","active").lte("proof_deadline", now).gt("voting_deadline", now).execute()
        supabase.table("challenges").update({"status": "closed"}).eq.in_("status",["active","voting"]).lte("voting_deadline", now).execute()
    except Exception as e:
        logger.error("Error syncing challenge statuses: ", e)
def check_challenges_ready_for_settlement():
    now=datetime.now(timezone.utc).isoformat()
    try:
        due=(supabase.table("challenges")
             .select("id")
             .in_("status", ["closed"])
             .execute())
        for row in due.data or []:
            try:
                logger.info(f"Auto-settling challenge {row['id']}")
                settle(row["id"])
            except Exception as e:
                logger.error(f"Error Auto-settling challenge {row['id']}: {e}")
    except Exception as e:
        logger.error(f"Error checking challenges for settlement: {e}")