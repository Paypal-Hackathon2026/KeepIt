import re
from pathlib import Path
from datetime import datetime, timezone

from app.services.challenge_filters import (
    CHALLENGE_STATUSES,
    CHALLENGE_STATUS_LABELS,
    filter_and_sort_challenges,
    relevant_deadline,
)


NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def challenge(
    challenge_id,
    status="open",
    mode="ai",
    join_deadline="2026-11-12T12:00:00+00:00",
    proof_deadline="2026-11-20T12:00:00+00:00",
    voting_deadline="2026-11-21T12:00:00+00:00",
    created_at="2026-11-01T12:00:00+00:00",
    pool_minor=1000,
):
    return {
        "id": challenge_id,
        "status": status,
        "verification_mode": mode,
        "join_deadline": join_deadline,
        "proof_deadline": proof_deadline,
        "voting_deadline": voting_deadline,
        "created_at": created_at,
        "pool_minor": pool_minor,
    }


def test_challenge_statuses_match_database_constraint_and_have_labels():
    schema = (Path(__file__).resolve().parents[1] / "supabase" / "schema.sql").read_text()
    challenge_table = re.search(
        r"create\s+table\s+if\s+not\s+exists\s+challenges\s*\((.*?)\n\);",
        schema,
        re.IGNORECASE | re.DOTALL,
    )
    assert challenge_table is not None
    status_constraint = re.search(
        r"\bstatus\s+text\b.*?\bcheck\s*\(\s*status\s+in\s*\(([^)]*)\)\s*\)",
        challenge_table.group(1),
        re.IGNORECASE | re.DOTALL,
    )
    assert status_constraint is not None
    database_statuses = tuple(re.findall(r"'([^']+)'", status_constraint.group(1)))

    assert CHALLENGE_STATUSES == database_statuses
    assert set(CHALLENGE_STATUS_LABELS) == set(database_statuses)
    assert all(CHALLENGE_STATUS_LABELS[status] for status in database_statuses)


def test_filter_and_sort_by_status():
    challenges = [challenge("open"), challenge("active", status="active")]

    result = filter_and_sort_challenges(challenges, "active", "all", "deadline", NOW)

    assert [item["id"] for item in result] == ["active"]


def test_filter_by_voting_and_closed_statuses():
    challenges = [
        challenge("voting", status="voting"),
        challenge("closed", status="closed"),
        challenge("open", status="open"),
    ]

    voting = filter_and_sort_challenges(challenges, "voting", "all", "deadline", NOW)
    closed = filter_and_sort_challenges(challenges, "closed", "all", "deadline", NOW)

    assert [item["id"] for item in voting] == ["voting"]
    assert [item["id"] for item in closed] == ["closed"]


def test_filter_and_sort_by_mode_defaults_missing_mode_to_ai():
    challenges = [
        challenge("ai"),
        {**challenge("missing-mode"), "verification_mode": None},
        challenge("vote", mode="vote"),
    ]
    del challenges[1]["verification_mode"]

    result = filter_and_sort_challenges(challenges, "all", "vote", "deadline", NOW)

    assert [item["id"] for item in result] == ["vote"]


def test_sort_by_newest_descending():
    challenges = [
        challenge("older", created_at="2026-11-01T12:00:00+00:00"),
        challenge("newer", created_at="2026-11-10T12:00:00+00:00"),
    ]

    result = filter_and_sort_challenges(challenges, "all", "all", "newest", NOW)

    assert [item["id"] for item in result] == ["newer", "older"]


def test_sort_by_pool_descending():
    challenges = [
        challenge("small", pool_minor=1000),
        challenge("large", pool_minor=5000),
    ]

    result = filter_and_sort_challenges(challenges, "all", "all", "pool", NOW)

    assert [item["id"] for item in result] == ["large", "small"]


def test_default_sort_uses_status_then_relevant_and_terminal_deadlines():
    challenges = [
        challenge(
            "settled-old",
            status="settled",
            proof_deadline="2026-10-01T12:00:00+00:00",
        ),
        challenge(
            "active-late",
            status="active",
            proof_deadline="2026-11-15T12:00:00+00:00",
        ),
        challenge("cancelled-new", status="cancelled", proof_deadline="2026-11-10T12:00:00+00:00"),
        challenge(
            "settling",
            status="settling",
            proof_deadline="2026-10-15T12:00:00+00:00",
        ),
        challenge("open-late", join_deadline="2026-11-14T12:00:00+00:00"),
        challenge("active-soon", status="active", proof_deadline="2026-11-12T13:00:00+00:00"),
        challenge(
            "active-voting",
            status="active",
            proof_deadline="2026-11-10T12:00:00+00:00",
            voting_deadline="2026-11-12T14:00:00+00:00",
        ),
        challenge("open-soon", join_deadline="2026-11-12T13:00:00+00:00"),
        challenge(
            "settled-new",
            status="settled",
            proof_deadline="2026-11-01T12:00:00+00:00",
        ),
    ]

    result = filter_and_sort_challenges(challenges, "all", "all", "deadline", NOW)

    assert [item["id"] for item in result] == [
        "open-soon",
        "open-late",
        "active-soon",
        "active-voting",
        "active-late",
        "settling",
        "settled-new",
        "settled-old",
        "cancelled-new",
    ]


def test_default_sort_orders_active_voting_closed_then_settling():
    challenges = [
        challenge(
            "settling",
            status="settling",
            proof_deadline="2026-11-15T12:00:00+00:00",
        ),
        challenge(
            "closed",
            status="closed",
            proof_deadline="2026-11-10T12:00:00+00:00",
            voting_deadline="2026-11-11T13:00:00+00:00",
        ),
        challenge(
            "voting-later",
            status="voting",
            voting_deadline="2026-11-11T14:00:00+00:00",
        ),
        challenge(
            "active",
            status="active",
            proof_deadline="2026-11-11T13:00:00+00:00",
        ),
        challenge(
            "voting-sooner",
            status="voting",
            voting_deadline="2026-11-11T12:30:00+00:00",
        ),
    ]

    result = filter_and_sort_challenges(challenges, "all", "all", "deadline", NOW)

    assert [item["id"] for item in result] == [
        "active",
        "voting-sooner",
        "voting-later",
        "closed",
        "settling",
    ]


def test_unknown_filter_and_sort_values_fall_back_to_defaults():
    challenges = [
        challenge("later", join_deadline="2026-11-14T12:00:00+00:00"),
        challenge("sooner", join_deadline="2026-11-12T13:00:00+00:00"),
    ]

    result = filter_and_sort_challenges(
        challenges, "unknown", "unknown", "unknown", NOW
    )

    assert [item["id"] for item in result] == ["sooner", "later"]


def test_relevant_deadline_for_open_challenge():
    assert relevant_deadline(challenge("open"), NOW) == (
        "Join by",
        "2026-11-12T12:00:00+00:00",
    )


def test_relevant_deadline_for_active_challenge():
    active = challenge("active", status="active")

    assert relevant_deadline(active, NOW) == (
        "Proof due",
        "2026-11-20T12:00:00+00:00",
    )


def test_relevant_deadline_for_active_after_proof_deadline():
    active = challenge(
        "active",
        status="active",
        proof_deadline="2026-11-10T12:00:00+00:00",
    )

    assert relevant_deadline(active, NOW) == (
        "Voting ends",
        "2026-11-21T12:00:00+00:00",
    )


def test_relevant_deadline_for_voting_challenge():
    assert relevant_deadline(challenge("voting", status="voting"), NOW) == (
        "Voting ends",
        "2026-11-21T12:00:00+00:00",
    )


def test_relevant_deadline_for_closed_challenge():
    assert relevant_deadline(challenge("closed", status="closed"), NOW) == (
        "Ended",
        "2026-11-21T12:00:00+00:00",
    )


def test_relevant_deadline_for_terminal_statuses():
    for status in ("settling", "settled", "cancelled"):
        assert relevant_deadline(challenge(status, status=status), NOW) == (
            "Ended",
            "2026-11-20T12:00:00+00:00",
        )
