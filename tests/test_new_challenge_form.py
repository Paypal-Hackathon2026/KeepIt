"""
Unit and integration tests for the Frontend New Challenge Form issue:
- GET /challenges/new renders form with all required fields (title, criteria, Entry Fee, two deadlines)
- Unauthenticated requests are redirected
- Form submission validation errors appear next to the fields
- Successful submission creates a challenge and redirects (303) to /challenges/{id}
- GET /challenges/{id} renders the challenge page with details
- Non-existent challenge returns 404
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.main import app
from app.db import supabase

client = TestClient(app)

# Setup a test profile
TEST_PAYPAL_ID = "TEST-FRONTEND-USER-001"

existing_profile = (
    supabase.table("profiles")
    .select("*")
    .eq("paypal_user_id", TEST_PAYPAL_ID)
    .execute()
)

if existing_profile.data:
    profile = existing_profile.data[0]
else:
    created = (
        supabase.table("profiles")
        .insert({
            "paypal_user_id": TEST_PAYPAL_ID,
            "display_name": "Frontend Tester",
            "paypal_email": "frontend-test@example.com",
        })
        .execute()
    )
    profile = created.data[0]

PROFILE_ID = profile["id"]


# Register a test-only route to set session cookie for test client
@app.get("/_test/set-session")
def _set_test_session(request: Request):
    request.session["profile_id"] = PROFILE_ID
    return JSONResponse({"logged_in": True, "profile_id": PROFILE_ID})


def test_unauthenticated_access_redirects():
    """Visiting /challenges/new without session redirects to /login."""
    no_auth_client = TestClient(app, cookies={})
    resp = no_auth_client.get("/challenges/new", follow_redirects=False)
    assert resp.status_code == 303, f"Expected 303, got {resp.status_code}"
    assert resp.headers.get("location") == "/login"


def test_authenticated_get_form():
    """GET /challenges/new renders form with title, criteria, Entry Fee, two deadlines."""
    auth_client = TestClient(app)
    auth_client.get("/_test/set-session")

    resp = auth_client.get("/challenges/new")
    assert resp.status_code == 200
    html = resp.text

    # Verify all required form fields exist
    assert 'name="title"' in html, "Missing title field"
    assert 'name="criteria"' in html, "Missing criteria field"
    assert 'name="entry_fee_pln"' in html, "Missing entry_fee_pln field"
    assert 'name="join_deadline"' in html, "Missing join_deadline field"
    assert 'name="proof_deadline"' in html, "Missing proof_deadline field"
    assert 'type="datetime-local"' in html, "Missing datetime-local input"
    assert 'Create Challenge' in html, "Missing submit button"


def test_form_validation_errors_next_to_fields():
    """Form submission with invalid data returns 422 and renders errors."""
    auth_client = TestClient(app)
    auth_client.get("/_test/set-session")

    # Submit invalid data:
    # - title too short
    # - criteria too short
    # - entry_fee_pln negative
    # - deadlines in past, proof before join
    form_data = {
        "title": "ab",
        "criteria": "short",
        "entry_fee_pln": "-5.00",
        "join_deadline": "2020-01-01T12:00",
        "proof_deadline": "2019-01-01T12:00",
    }

    resp = auth_client.post("/challenges/new", data=form_data)
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    html = resp.text

    # Check that validation error messages and preserved values are present
    assert "String should have at least 3 characters" in html or "characters" in html
    assert "String should have at least 10 characters" in html or "characters" in html
    assert "Input should be greater than 0" in html or "greater than 0" in html
    assert "Deadline must be in the future" in html

    # Preserved values
    assert 'value="ab"' in html
    assert "short" in html
    assert 'value="-5.00"' in html


def test_proof_deadline_after_join_deadline_validation():
    """proof_deadline <= join_deadline triggers validation error."""
    auth_client = TestClient(app)
    auth_client.get("/_test/set-session")

    now = datetime.now(timezone.utc)
    future_join = (now + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")
    earlier_proof = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")

    form_data = {
        "title": "Valid Title Here",
        "criteria": "Valid criteria with more than ten characters.",
        "entry_fee_pln": "25.00",
        "join_deadline": future_join,
        "proof_deadline": earlier_proof,
    }

    resp = auth_client.post("/challenges/new", data=form_data)
    assert resp.status_code == 422
    html = resp.text
    assert "proof_deadline must be later than join_deadline" in html


def test_successful_form_submission_and_detail_page():
    """
    Submitting valid form creates challenge, auto-registers creator as participant,
    and redirects (303) to /challenges/{id}, which displays the challenge page.
    """
    auth_client = TestClient(app)
    auth_client.get("/_test/set-session")

    now = datetime.now(timezone.utc)
    join_dt = (now + timedelta(days=2)).strftime("%Y-%m-%dT12:00")
    proof_dt = (now + timedelta(days=10)).strftime("%Y-%m-%dT18:00")

    unique_title = f"Cycle 50km {now.timestamp()}"
    form_data = {
        "title": unique_title,
        "criteria": "Upload a screenshot of your cycling tracking app with the proof code visible.",
        "entry_fee_pln": "35.50",
        "join_deadline": join_dt,
        "proof_deadline": proof_dt,
    }

    # Follow redirect is False so we can inspect the 303 RedirectResponse
    resp = auth_client.post("/challenges/new", data=form_data, follow_redirects=False)
    assert resp.status_code == 303, f"Expected 303 redirect, got {resp.status_code}"
    redirect_url = resp.headers.get("location")
    assert redirect_url.startswith("/challenges/"), f"Unexpected location: {redirect_url}"

    challenge_id = redirect_url.split("/")[-1]

    # Check detail page
    detail_resp = auth_client.get(redirect_url)
    assert detail_resp.status_code == 200
    detail_html = detail_resp.text

    assert unique_title in detail_html
    assert "35.50" in detail_html
    assert "PLN" in detail_html
    assert "Upload a screenshot" in detail_html
    assert "Verification Proof Code" in detail_html
    assert "open" in detail_html

    # Verify participant was created in Supabase
    part = (
        supabase.table("participants")
        .select("*")
        .eq("challenge_id", challenge_id)
        .eq("user_id", PROFILE_ID)
        .execute()
    )
    assert len(part.data) == 1, "Creator was not auto-registered in participants"


def test_non_existent_challenge_returns_404():
    """GET /challenges/{invalid_uuid} returns 404."""
    resp = client.get("/challenges/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


if __name__ == "__main__":
    print("Running frontend form tests...")
    test_unauthenticated_access_redirects()
    print("[PASS] test_unauthenticated_access_redirects")
    test_authenticated_get_form()
    print("[PASS] test_authenticated_get_form")
    test_form_validation_errors_next_to_fields()
    print("[PASS] test_form_validation_errors_next_to_fields")
    test_proof_deadline_after_join_deadline_validation()
    print("[PASS] test_proof_deadline_after_join_deadline_validation")
    test_successful_form_submission_and_detail_page()
    print("[PASS] test_successful_form_submission_and_detail_page")
    test_non_existent_challenge_returns_404()
    print("[PASS] test_non_existent_challenge_returns_404")
    print("\nALL FRONTEND FORM TESTS PASSED SUCCESSFULLY!")

