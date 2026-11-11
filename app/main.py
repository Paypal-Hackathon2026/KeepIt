from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.routes import auth, pages, paypal, challenges, challenge_pages, payment_pages, evidence_pages, voting_pages
import asyncio
from contextlib import asynccontextmanager
from app.services.loops import check_challenges_ready_for_settlement,sync_challenge_statuses

@asynccontextmanager
async def lifespan(app: FastAPI):
    async def sync_settle_worker():
        while True:
            try:
                await asyncio.to_thread(sync_challenge_statuses)
                await asyncio.to_thread(check_challenges_ready_for_settlement)
            except Exception as exc:
                print(f"Error in sync_settle_worker: {exc}")
            await asyncio.sleep(60)

    task = asyncio.create_task(sync_settle_worker())
    yield
    task.cancel()

app = FastAPI(title="KeepIt", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(paypal.router)
app.include_router(challenges.router)
app.include_router(challenge_pages.router)
app.include_router(payment_pages.router)
app.include_router(evidence_pages.router)
app.include_router(voting_pages.router)


@app.get("/health")
def health():
    return {"status": "ok"}