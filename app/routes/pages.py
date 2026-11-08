from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.deps import current_user
from app.services.profiles import format_member_since, get_profile_stats
from app.templating import templates

router = APIRouter()

LOGIN_ERRORS = {
    "cancelled": "Login was cancelled. Please try again.",
    "failed": "Something went wrong. Please try again.",
}


@router.get("/login")
def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": LOGIN_ERRORS.get(error)},
    )


@router.get("/")
def home_page(request: Request):
    logged_in = bool(request.session.get("profile_id"))
    return templates.TemplateResponse(request, "home.html", {"logged_in": logged_in})


@router.get("/profile")
def profile_page(
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    stats = get_profile_stats(user["id"])
    user_view = dict(user)
    user_view["member_since"] = format_member_since(user.get("created_at"))
    return templates.TemplateResponse(request, "profile.html", {"user": user_view, "stats": stats})
