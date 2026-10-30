from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from app import config
from app.routes import auth,paypal


from app.routes.challenges import router as challenges_router

app = FastAPI(title="KeepIt")


app.include_router(challenges_router)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.include_router(auth.router)
app.include_router(paypal.router)

@app.get("/health")
def health():
    return {"status": "ok"}