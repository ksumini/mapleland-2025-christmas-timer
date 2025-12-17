from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db.users import is_dm_ready

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/")
async def home(request: Request):
    uid = request.session.get("discord_user_id")
    logged_in = bool(uid)
    dm_ready = False
    if logged_in:
        dm_ready = is_dm_ready(uid)

    return templates.TemplateResponse(
        "home.html",
        {"request": request, "logged_in": logged_in, "dm_ready": dm_ready},
    )

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)