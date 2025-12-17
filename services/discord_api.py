from urllib.parse import urlencode
import httpx
from core.config import (
    BASE_URL,
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_BOT_TOKEN
)


DISCORD_AUTH_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_ME_URL = "https://discord.com/api/users/@me"
DISCORD_API = "https://discord.com/api"

def discord_redirect_uri():
    return f"{BASE_URL}/auth/discord/callback"

def discord_login_url():
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": discord_redirect_uri(),
        "response_type": "code",
        "scope": "identify",
    }
    return f"{DISCORD_AUTH_URL}?{urlencode(params)}"

def discord_bot_invite_url():
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "scope": "bot",
        "permissions": "0",  # DM 최소 권한
    }
    return f"{DISCORD_AUTH_URL}?{urlencode(params)}"

async def discord_exchange_code(code: str):
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": discord_redirect_uri(),
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(DISCORD_TOKEN_URL, data=data)
        r.raise_for_status()
        return r.json()

async def discord_get_me(access_token: str):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(DISCORD_ME_URL, headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return r.json()

async def discord_send_dm(user_id: str, text: str):
    """
    Bot 토큰으로 사용자에게 DM 발송
    1) DM 채널 생성(or 가져오기)
    2) 메시지 발송
    """
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        ch = await c.post(
            f"{DISCORD_API}/users/@me/channels",
            headers=headers,
            json={"recipient_id": user_id},
        )
        ch.raise_for_status()
        channel_id = ch.json()["id"]

        r = await c.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=headers,
            json={"content": text},
        )
        r.raise_for_status()