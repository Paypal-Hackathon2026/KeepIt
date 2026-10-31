from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from app import config
from app.routes import auth, pages

from app.routes.challenges import router as challenges_router

from fastapi.staticfiles import StaticFiles
   
app = FastAPI(title="KeepIt")


app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)

app.include_router(challenges_router)
app.include_router(auth.router)
app.include_router(pages.router)


@app.get("/health")
def health():
    return {"status": "ok"}