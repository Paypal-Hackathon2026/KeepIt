from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.routes import auth, pages, paypal, challenge_pages
from app.routes.challenges import router as challenges_router
import asyncio
from contextlib import asynccontextmanager
from app.services.loops import check_challenges_ready_for_settlement

@asynccontextmanager
async def lifespan(app: FastAPI):
    async def settle_worker():
        while True:
            asyncio.to_thread(check_challenges_ready_for_settlement)
            await asyncio.sleep(60)

    task = asyncio.create_task(settle_worker())
    yield
    task.cancel()

app = FastAPI(title="KeepIt", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(paypal.router)
app.include_router(challenges_router)
app.include_router(challenge_pages.router)


@app.get("/health")
def health():
    return {"status": "ok"}