from fastapi import APIRouter, Request

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