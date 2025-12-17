import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core.config import SESSION_SECRET
from routes.web import router as web_router
from routes.auth import router as auth_router
from routes.api import router as api_router
from background.poller import poller


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
)

app.include_router(web_router)
app.include_router(auth_router)
app.include_router(api_router)

@app.on_event("startup")
async def startup():
    asyncio.create_task(poller())