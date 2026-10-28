from fastapi import FastAPI

from app.routes.challenges import router as challenges_router

app = FastAPI(title="KeepIt")

app.include_router(challenges_router)


@app.get("/health")
def health():
    return {"status": "ok"}