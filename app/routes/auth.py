import secrets

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse

from app.db import supabase
from app.services import paypal_auth, profiles
from app.deps import current_user

router = APIRouter()

@router.get("/auth/paypal/login")
def paypal_login(request: Request):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    return RedirectResponse(paypal_auth.build_login_url(state))


@router.get("/auth/callback")
def paypal_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error or not code:
        return {"error": "Login was cancelled or failed"}

    expected_state = request.session.pop("oauth_state", None)
    if not state or state != expected_state:
        return {"error": "Invalid state"}

    access_token = paypal_auth.exchange_code(code)
    user_info = paypal_auth.get_user_info(access_token)

    primary_email = next(
        email["value"] for email in user_info["emails"] if email["primary"]
    )

    profile = profiles.get_or_create_profile(
        paypal_user_id=user_info["payer_id"],
        display_name=user_info["name"],
        paypal_email=primary_email,
    )

    request.session["profile_id"] = profile["id"]

    # TODO: change to "/" once the home page exists
    return RedirectResponse("/api/me", status_code=303)

@router.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user

@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"logged_out": True}