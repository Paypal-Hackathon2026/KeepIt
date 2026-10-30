"""
Quick local test for POST /api/challenges.

Simulates a logged-in session without going through PayPal OAuth.
Run:  .venv/bin/python tests/test_create_challenge.py
"""

import httpx
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

# ── boot the app ──────────────────────────────────────────────
from app.main import app
from app.db import supabase

client = TestClient(app)

# ── Step 1: make sure we have a test profile ──────────────────
PAYPAL_USER_ID = "TEST-LOCAL-001"

existing = (
    supabase.table("profiles")
    .select("*")
    .eq("paypal_user_id", PAYPAL_USER_ID)
    .execute()
)

if existing.data:
    profile = existing.data[0]
    print(f"Using existing test profile: {profile['id']}")
else:
    result = (
        supabase.table("profiles")
        .insert({
            "paypal_user_id": PAYPAL_USER_ID,
            "display_name": "Local Tester",
            "paypal_email": "local-test@example.com",
        })
        .execute()
    )
    profile = result.data[0]
    print(f"Created test profile: {profile['id']}")

PROFILE_ID = profile["id"]

# ── Step 2: simulate login by injecting session ──────────────
# TestClient handles cookies, so we manually hit a tiny helper
# endpoint that sets session["profile_id"] for us.

from fastapi import Request
from fastapi.responses import JSONResponse

@app.get("/_test/fake-login")
def _fake_login(request: Request):
    """Test-only: simulate PayPal login by writing session directly."""
    request.session["profile_id"] = PROFILE_ID
    return JSONResponse({"logged_in_as": PROFILE_ID})

# Call it to set the session cookie
resp = client.get("/_test/fake-login")
print(f"Fake login: {resp.json()}")

# ── Step 3: test POST /api/challenges ─────────────────────────
print("\n" + "=" * 60)
print("TEST 1: Valid challenge creation")
print("=" * 60)

resp = client.post("/api/challenges", json={
    "title": "Run 5km",
    "criteria": "Run 5km and take photo with proof_code",
    "entry_fee_pln": 10.50,
    "join_deadline": "2026-12-01T12:00:00Z",
    "proof_deadline": "2026-12-15T23:59:00Z",
})

print(f"Status: {resp.status_code}")
if resp.status_code == 201:
    data = resp.json()
    print(f" Challenge created")
    print(f"   id:              {data['id']}")
    print(f"   title:           {data['title']}")
    print(f"   entry_fee_minor: {data['entry_fee_minor']} (should be 1050)")
    print(f"   proof_code:      {data['proof_code']}")
    print(f"   status:          {data['status']}")
    challenge_id = data["id"]

    # Verify participant was created
    part = (
        supabase.table("participants")
        .select("*")
        .eq("challenge_id", challenge_id)
        .eq("user_id", PROFILE_ID)
        .execute()
    )
    if part.data:
        print(f"Creator auto-registered as participant")
    else:
        print(f"Participant NOT found!")
else:
    print(f"Error: {resp.json()}")

# ── Step 4: test validation errors ────────────────────────────
print("\n" + "=" * 60)
print("TEST 2: Deadline in the past → should be 422")
print("=" * 60)

resp = client.post("/api/challenges", json={
    "title": "Bad deadline",
    "criteria": "This should fail validation",
    "entry_fee_pln": 5.00,
    "join_deadline": "2020-01-01T00:00:00Z",
    "proof_deadline": "2026-12-01T00:00:00Z",
})
print(f"Status: {resp.status_code} {'ok' if resp.status_code == 422 else 'err'}")

print("\n" + "=" * 60)
print("TEST 3: proof_deadline before join_deadline → should be 422")
print("=" * 60)

resp = client.post("/api/challenges", json={
    "title": "Bad order",
    "criteria": "This should also fail validation",
    "entry_fee_pln": 5.00,
    "join_deadline": "2026-12-15T00:00:00Z",
    "proof_deadline": "2026-12-01T00:00:00Z",
})
print(f"Status: {resp.status_code} {'ok' if resp.status_code == 422 else 'err'}")

# ── Step 5: test without session → 303 ───────────────────────
print("\n" + "=" * 60)
print("TEST 4: No auth → should redirect (303)")
print("=" * 60)

no_auth_client = TestClient(app, cookies={})
resp = no_auth_client.post("/api/challenges", json={
    "title": "No auth test",
    "criteria": "Should get 303 redirect",
    "entry_fee_pln": 5.00,
    "join_deadline": "2026-12-01T00:00:00Z",
    "proof_deadline": "2026-12-15T00:00:00Z",
}, follow_redirects=False)
print(f"Status: {resp.status_code} {'ok' if resp.status_code == 303 else 'err'}")

# ── Cleanup: remove the test route ────────────────────────────
app.routes[:] = [r for r in app.routes if getattr(r, 'path', '') != '/_test/fake-login']

print("\n" + "=" * 60)
print("ALL TESTS DONE")
print("=" * 60)

