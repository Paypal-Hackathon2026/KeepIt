import logging
from datetime import datetime, timezone
from app.services.settlement_service import settle
from app.db import supabase

logger = logging.getLogger(__name__)

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