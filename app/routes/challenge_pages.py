from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse

from app.templating import templates
from app.deps import current_user

from app.services.challenge_service import create_challenge
from app.models.challenge import ChallengeCreate
from pydantic import ValidationError
router = APIRouter()

@router.get("/challenges/new")
def new_challenge_page(request: Request, user: dict = Depends(current_user)):
    return templates.TemplateResponse(request, "new_challenge.html",
                                       {"user": user, "errors": {}, "values": {}})
@router.post("/challenges/new")
def created_challenge(request: Request,
                      title: str = Form(""),
                      criteria: str = Form(""),
                      entry_fee_pln: str = Form(""),
                      join_deadline: str = Form(""),
                      proof_deadline: str = Form(""),
                      user: dict = Depends(current_user)):
    values = {
        "title": title,
        "criteria": criteria,
        "entry_fee_pln": entry_fee_pln,
        "join_deadline": join_deadline,
        "proof_deadline": proof_deadline
    }

    try:
        challenge_data = ChallengeCreate(title=title, criteria=criteria, entry_fee_pln=entry_fee_pln, join_deadline=join_deadline, proof_deadline=proof_deadline)
    except ValidationError as e:
        errors={}
        for error in e.errors():
            loc=error["loc"]
            msg=error["msg"]
            if msg.startswith("Value error, "):
                msg=msg.replace("Value error, ", "")
            if loc:
                field_name=str(loc[0])
                errors[field_name]=msg
            else:
                errors["proof_deadline"]=msg
        return templates.TemplateResponse(request, "new_challenge.html",
                                             {"user": user, "errors": errors, "values": values},
                                             status_code=422,)
    new_challenge = create_challenge(challenge_data,creator_id=user["id"])
    return RedirectResponse(url=f"/challenges/{new_challenge['id']}", status_code=303)
    

        
