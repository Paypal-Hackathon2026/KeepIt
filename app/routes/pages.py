from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

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