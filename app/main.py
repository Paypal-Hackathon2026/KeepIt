from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from app import config
from app.routes import auth

app = FastAPI(title="KeepIt")

app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.include_router(auth.router)

@app.get("/health")
def health():
    return {"status": "ok"}