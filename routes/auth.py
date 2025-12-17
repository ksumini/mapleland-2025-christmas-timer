from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from services.discord_api import discord_login_url, discord_exchange_code, discord_get_me


router = APIRouter()

@router.get("/auth/discord/login")
async def discord_login():
    return RedirectResponse(discord_login_url(), status_code=302)

@router.get("/auth/discord/callback")
async def discord_callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(f"디스코드 로그인 실패: {error}", status_code=400)
    if not code:
        return HTMLResponse("인가 코드 없음", status_code=400)

    token = await discord_exchange_code(code)
    me = await discord_get_me(token["access_token"])
    request.session["discord_user_id"] = str(me["id"])
    return RedirectResponse("/", status_code=302)