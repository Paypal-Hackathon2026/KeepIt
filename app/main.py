from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.routes import auth, pages, paypal
from app.routes.challenges import router as challenges_router

app = FastAPI(title="KeepIt")

app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(paypal.router)
app.include_router(challenges_router)


@app.get("/health")
def health():
    return {"status": "ok"}