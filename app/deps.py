from fastapi import HTTPException, Request

from app.services import profiles

def current_user(request: Request) -> dict:
    profile_id = request.session.get("profile_id")
    if not profile_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    profile = profiles.get_profile(profile_id)
    if profile is None:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    return profile