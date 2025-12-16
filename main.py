from dotenv import load_dotenv
load_dotenv()

import os
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from supabase import create_client

# =====================================================
# Time utils
# =====================================================
KST = timezone(timedelta(hours=9))
DEFAULT_TZ = "Asia/Seoul"

def now_utc():
    return datetime.now(timezone.utc)

def fmt_in_tz(dt: datetime, tz_name: str):
    """
    dt(aware) -> tz_name(IANA, e.g. Asia/Seoul) 기준 문자열 포맷
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    return dt.astimezone(tz).strftime("%m/%d %H:%M")

def humanize(sec: int):
    if sec <= 0:
        return "0분"
    m = sec // 60
    h, m = divmod(m, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"

# =====================================================
# ENV
# =====================================================
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SESSION_SECRET = os.environ["SESSION_SECRET"]

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

DISCORD_CLIENT_ID = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
POLL_LIMIT = int(os.getenv("POLL_LIMIT", "50"))

# =====================================================
# Clients / Tables
# =====================================================
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

TIMERS_TABLE = "user_timers"
USERS_TABLE = "discord_users"

# =====================================================
# Discord OAuth / API
# =====================================================
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

# =====================================================
# DB helpers
# =====================================================
def get_dm_status(user_id: str):
    try:
        r = (
            sb.table(USERS_TABLE)
            .select("*")
            .eq("discord_user_id", user_id)
            .maybe_single()
            .execute()
        )
        if r is None:
            return None
        return getattr(r, "data", None)
    except Exception as e:
        print("[get_dm_status ERROR]", user_id, e)
        return None

def is_dm_ready(user_id: str) -> bool:
    row = get_dm_status(user_id) or {}
    return row.get("dm_status") == "ok"

def require_dm_ready(user_id: str):
    if not is_dm_ready(user_id):
        raise HTTPException(
            status_code=400,
            detail="DM 알림을 받으려면 먼저 개인 서버에 봇을 초대하고, ‘테스트 DM’으로 활성화를 확인해 주세요."
        )

def cancel_timer(user_id: str, timer_type: str, reason: str = "user_canceled"):
    sb.table(TIMERS_TABLE).update({
        "status": "canceled",
        "updated_at": now_utc().isoformat(),
        "fail_reason": reason,
    }).eq("discord_user_id", user_id).eq("timer_type", timer_type).execute()

def upsert_timer(user_id: str, timer_type: str, due_at_utc: datetime):
    sb.table(TIMERS_TABLE).upsert({
        "discord_user_id": user_id,
        "timer_type": timer_type,
        "status": "scheduled",
        "last_set_at": now_utc().isoformat(),
        "due_at": due_at_utc.isoformat(),
        "updated_at": now_utc().isoformat(),
        "fail_reason": None,
    }, on_conflict="discord_user_id,timer_type").execute()

def get_timers(user_id: str):
    r = sb.table(TIMERS_TABLE).select("*").eq("discord_user_id", user_id).execute()
    return {x["timer_type"]: x for x in (r.data or [])}

def fetch_due_timers(limit: int):
    r = (
        sb.table(TIMERS_TABLE)
        .select("*")
        .eq("status", "scheduled")
        .lte("due_at", now_utc().isoformat())
        .limit(limit)
        .execute()
    )
    return r.data or []

def mark_sent(user_id: str, timer_type: str):
    sb.table(TIMERS_TABLE).update({
        "status": "sent",
        "updated_at": now_utc().isoformat(),
        "fail_reason": None,
    }).eq("discord_user_id", user_id).eq("timer_type", timer_type).execute()

def mark_failed(user_id: str, timer_type: str, reason: str):
    sb.table(TIMERS_TABLE).update({
        "status": "canceled",
        "updated_at": now_utc().isoformat(),
        "fail_reason": reason[:400],
    }).eq("discord_user_id", user_id).eq("timer_type", timer_type).execute()

def upsert_dm_result(user_id: str, ok: bool, err: str | None = None):
    payload = {
        "discord_user_id": user_id,
        "dm_status": "ok" if ok else "fail",
        "dm_last_error": None if ok else (err or "")[:800],
        "dm_ok_at": now_utc().isoformat() if ok else None,
        "updated_at": now_utc().isoformat(),
    }
    sb.table(USERS_TABLE).upsert(payload, on_conflict="discord_user_id").execute()

def upsert_user_tz(user_id: str, tz_name: str):
    payload = {
        "discord_user_id": user_id,
        "tz": tz_name,
        "updated_at": now_utc().isoformat(),
    }
    sb.table(USERS_TABLE).upsert(payload, on_conflict="discord_user_id").execute()

def get_user_tz(user_id: str) -> str:
    row = get_dm_status(user_id) or {}
    tz = row.get("tz")
    return tz or DEFAULT_TZ

# =====================================================
# FastAPI setup
# =====================================================
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
)

def require_login(request: Request) -> str:
    uid = request.session.get("discord_user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return uid

# =====================================================
# External open routes (새 탭 전용)
# =====================================================
@app.get("/out/invite")
async def out_invite():
    return RedirectResponse(discord_bot_invite_url(), status_code=302)

# =====================================================
# Web UI
# =====================================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    uid = request.session.get("discord_user_id")
    logged_in = bool(uid)

    # ✅ 항상 초기화
    invite_banner = ""

    # ✅ 항상 정의
    if logged_in:
        login_btn = """<a class="btnLogout" href="/logout">로그아웃</a>"""
    else:
        login_btn = """<a class="btnLogin" href="/auth/discord/login">🎮디스코드로 로그인</a>"""

    dm_ready = False
    if logged_in:
        dm_ready = is_dm_ready(uid)
        if not dm_ready:
            invite_banner = """
            <div class="banner2">
              <div class="bannerText">
                <div class="bannerTitle">📩 DM 알림을 받으려면 먼저 2단계만 완료해 주세요</div>
                <div class="bannerSub">
                  1) 개인 서버(관리자)로 봇 초대<br/>
                  2) “테스트 DM”으로 알림 수신 확인
                </div>
                <div class="bannerSub2">
                  개인 서버가 없으면 30초만에 만들 수 있어요:
                  <a class="miniLink" href="https://support.discord.com/hc/ko/articles/204849977" target="_blank" rel="noopener">서버 만들기</a>
                </div>
              </div>

              <div class="bannerBtns">
                <button class="btnPrimary" onclick="openExternal('invite')">봇 초대하기</button>
                <button class="btnGhost" onclick="testSend()">테스트 DM</button>
              </div>
            </div>
            """

    html = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>메이플랜드 크리스마스 이벤트 타이머 (Discord DM)</title>
  <style>
    :root {{
      --bg:#0b0f17;
      --card:#121826;
      --muted:#9aa4b2;
      --text:#e6edf3;
      --accent:#7aa2ff;
      --ok:#2ecc71;
      --line:rgba(255,255,255,.08);

      --xmas-red:#ff5a6b;
      --xmas-green:#2ecc71;
      --xmas-gold:#f1c40f;
    }}

    html {{
      background:
        radial-gradient(900px 500px at 20% 10%, rgba(46,204,113,.10), transparent 55%),
        radial-gradient(900px 500px at 85% 0%, rgba(255,90,107,.10), transparent 55%),
        radial-gradient(600px 400px at 60% 90%, rgba(241,196,15,.06), transparent 60%),
        var(--bg);
      background-attachment: fixed;
    }}

    body {{
      font-size: 16px;
      font-family: system-ui, -apple-system;
      color: var(--text);
      background: transparent;
      min-height: 100vh;
      margin: 0;
    }}

    .wrap {{ max-width:720px; margin:0 auto; padding:24px 14px 60px; }}

    .fabFeedback{{
      position: fixed;
      right: 16px;
      bottom: 16px;
      z-index: 50;

      display: inline-flex;
      align-items: center;
      gap: 8px;

      padding: 10px 12px;
      border-radius: 999px;
      border: 1px solid rgba(241,196,15,.28);
      background: rgba(18,24,38,.92);
      color: var(--text);
      cursor: pointer;

      font-weight: 900;
      font-size: 13px;
      box-shadow:
        0 10px 26px rgba(0,0,0,.35),
        0 0 0 1px rgba(255,255,255,.05) inset;
      backdrop-filter: blur(10px);
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }}

    .fabFeedback:hover{{
      transform: translateY(-1px);
      border-color: rgba(46,204,113,.45);
      box-shadow:
        0 0 0 1px rgba(46,204,113,.12) inset,
        0 16px 34px rgba(46,204,113,.14);
    }}

    .fabFeedback .fabIcon{{
      width: 22px;
      height: 22px;
      border-radius: 999px;
      display:flex;
      align-items:center;
      justify-content:center;
      background: rgba(241,196,15,.12);
      border: 1px solid rgba(241,196,15,.22);
    }}

    @media (max-width:560px){{
      .fabFeedback{{ right: 12px; bottom: 12px; padding: 9px 11px; }}
    }}

    h1 {{
      font-size:26px;
      line-height: 1.35;
      margin:0 0 6px;
      letter-spacing:-0.2px;
      text-shadow: 0 2px 18px rgba(241,196,15,.08);
    }}

    .sub {{ font-size: 16px; color:var(--muted); margin:0 0 18px; }}
    .top {{ display:flex; align-items:center; justify-content:space-between; gap:10px; }}
    .authRow{{ margin-top: -6px; margin-bottom: 8px; display:flex; justify-content: flex-end; }}

    .btn {{
      font-size: 15px;
      padding:10px 14px;
      border-radius:12px;
      border:1px solid var(--line);
      background:#0f172a;
      color:var(--text);
      cursor:pointer;
      font-weight:700;
      transition: box-shadow .18s ease, border-color .18s ease, transform .18s ease;
    }}

    .btnLogin, .btnLogout {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap:10px;

      padding:12px 18px;
      border-radius:18px;
      text-decoration:none;

      font-weight:900;
      font-size:18px;
      letter-spacing:-0.2px;

      background: rgba(18,24,38,.55);
      color: var(--text);

      border:1px solid rgba(46,204,113,.45);
      box-shadow:
        0 10px 26px rgba(0,0,0,.35),
        0 0 0 1px rgba(255,255,255,.05) inset;
      backdrop-filter: blur(10px);

      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }}

    .btnLogin:hover, .btnLogout:hover {{
      transform: translateY(-1px);
      border-color: rgba(46,204,113,.65);
      box-shadow:
        0 0 0 1px rgba(46,204,113,.12) inset,
        0 16px 34px rgba(46,204,113,.14);
    }}

    .btnLogout {{
      border-color: rgba(255, 90, 107, .45);
    }}

    .btnLogout:hover {{
      border-color: rgba(255, 90, 107, .65);
      box-shadow:
        0 0 0 1px rgba(255,90,107,.12) inset,
        0 16px 34px rgba(255,90,107,.14);
    }}

    .btn:hover {{
      border-color: rgba(46,204,113,.45);
      box-shadow:
        0 0 0 1px rgba(46,204,113,.15) inset,
        0 10px 26px rgba(46,204,113,.12);
      transform: translateY(-1px);
    }}

    .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:16px; }}
    @media (max-width: 560px) {{ .grid {{ grid-template-columns:1fr; }} }}

    .card {{
      position: relative;
      background:var(--card);
      border:1px solid var(--line);
      border-radius:18px;
      padding:14px;
      box-shadow:
        0 10px 30px rgba(0,0,0,.25),
        0 0 0 1px rgba(255,255,255,.05) inset,
        0 0 18px rgba(241,196,15,.05);
      overflow:hidden;
    }}

    .card::before {{
      content:"";
      position:absolute;
      inset:-1px;
      border-radius:18px;
      pointer-events:none;
      background:
        radial-gradient(320px 220px at 0% 0%, rgba(241,196,15,.10), transparent 60%),
        radial-gradient(360px 240px at 100% 100%, rgba(46,204,113,.10), transparent 60%);
      opacity:.9;
      mix-blend-mode: screen;
    }}

    .timerBtn {{
      width:100%;
      display:flex;
      align-items:center;
      gap:12px;
      padding:12px;
      border-radius:16px;
      border:1px solid var(--line);
      background:rgba(255,255,255,.02);
      color:var(--text);
      cursor:pointer;
      transition: box-shadow .18s ease, border-color .18s ease, transform .18s ease;
    }}

    .timerBtn:hover {{
      border-color: rgba(46,204,113,.45);
      box-shadow:
        0 0 0 1px rgba(46,204,113,.12) inset,
        0 14px 30px rgba(46,204,113,.10);
      transform: translateY(-1px);
    }}

    .avatar {{ width:56px; height:56px; border-radius:16px; background:#0f172a; display:flex; align-items:center; justify-content:center; overflow:hidden; }}
    .avatar img {{ width:100%; height:100%; object-fit:contain; image-rendering: pixelated; }}

    .title {{ font-weight:800; font-size:18px; }}
    .meta {{ color:var(--muted); font-size:14px; margin-top:2px; line-height:1.35; }}
    .row {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}

    .pill,
    .badge {{
      display: inline-flex;
      align-items: center;

      line-height: 1.15;
      font-size:13px;

      white-space: nowrap;
      flex-shrink: 0;

      color:var(--muted);
      border:1px solid rgba(241,196,15,.25);
      background: rgba(241,196,15,.06);
      padding:4px 8px;
      border-radius:999px;
    }}

    .pill-inline {{
      white-space: nowrap;
      flex-shrink: 0;
      line-height: 1.15;
    }}

    .statusCard {{ margin-top:12px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; color:var(--muted); }}

    .progress {{
      height:10px;
      background:rgba(255,255,255,.06);
      border-radius:999px;
      overflow:hidden;
      border:1px solid var(--line);
    }}

    .bar {{
      height:100%;
      width:0%;
      background: linear-gradient(90deg, rgba(46,204,113,.95), rgba(241,196,15,.95), rgba(255,90,107,.95));
    }}

    .kpi {{ display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top:10px; }}
    .kpi .box {{ background:rgba(255,255,255,.03); border:1px solid var(--line); border-radius:14px; padding:10px; }}
    .kpi .k {{ color:var(--muted); font-size:13px; }}
    .kpi .v {{ font-weight:800; font-size: 24px; margin-top:4px; }}

    .banner2{{
      margin-top:14px;
      padding:12px 12px;
      border:1px solid rgba(241,196,15,.35);
      background:rgba(241,196,15,.08);
      border-radius:14px;
      display:flex;
      gap:12px;
      align-items:center;
      justify-content:space-between;
    }}
    .bannerText{{ display:flex; flex-direction:column; gap:4px; }}
    .bannerTitle{{ font-weight:900; }}
    .bannerSub, .bannerSub2{{ color:var(--muted); font-size:13px; line-height:1.35; }}
    .miniLink{{ color:#9bffd3; text-decoration:none; border-bottom:1px dotted rgba(155,255,211,.45); }}
    .bannerBtns{{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }}

    .btnPrimary{{
      padding:10px 14px;
      border-radius:12px;
      border:1px solid rgba(46,204,113,.45);
      background:rgba(46,204,113,.14);
      color:var(--text);
      text-decoration:none;
      font-weight:900;
      white-space:nowrap;
      transition: box-shadow .18s ease, transform .18s ease, border-color .18s ease;
    }}
    .btnPrimary:hover{{
      border-color: rgba(46,204,113,.65);
      box-shadow:
        0 0 0 1px rgba(46,204,113,.12) inset,
        0 16px 34px rgba(46,204,113,.14);
      transform: translateY(-1px);
    }}

    .btnGhost{{
      padding:10px 14px;
      border-radius:12px;
      border:1px solid var(--line);
      background:transparent;
      color:var(--muted);
      text-decoration:none;
      font-weight:900;
      white-space:nowrap;
      transition: box-shadow .18s ease, transform .18s ease, border-color .18s ease;
    }}
    .btnGhost:hover{{
      color:var(--text);
      border-color: rgba(241,196,15,.35);
      box-shadow: 0 14px 30px rgba(241,196,15,.10);
      transform: translateY(-1px);
    }}

    @media (max-width:560px){{
      .banner2{{ align-items:stretch; flex-direction:column; }}
      .bannerBtns{{ justify-content:flex-start; }}
    }}

    .warnBox {{ margin-top:10px; padding:10px; border-radius:14px; border:1px solid rgba(255,107,107,.35); background:rgba(255,107,107,.08); color:#ffd7d7; display:none; }}

    .modalBg {{ position:fixed; inset:0; background:rgba(0,0,0,.55); display:none; align-items:center; justify-content:center; padding:16px; }}
    .modal {{ width:min(780px, 100%); background:var(--card); border:1px solid var(--line); border-radius:18px; padding:14px; }}
    .modalHeader {{ display:flex; justify-content:space-between; align-items:center; }}
    .close {{ border:1px solid var(--line); background:#0f172a; color:var(--text); border-radius:12px; padding:8px 10px; cursor:pointer; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
    th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); font-size:13px; }}
    th {{ color:var(--muted); font-weight:600; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="topLeft">
        <h1>🎄 메이플랜드 크리스마스 이벤트 타이머 <span class="pill pill-inline">Discord DM 알림</span></h1>
        <p class="sub">퀘스트 완료 후 버튼 클릭 → 시간이 되면 Discord DM으로 알림 전송</p>
      </div>
    </div>

    <div class="authRow">
       {login_btn}
    </div>

    <div id="bannerWrap">
      {invite_banner}
    </div>

    <div class="warnBox" id="dmWarn"></div>

    <div class="grid">
      <div class="card">
        <button class="timerBtn" onclick="startTimer('rudolph')">
          <div class="avatar"><img src="/static/rudolph.png" alt="rudolph"/></div>
          <div style="flex:1">
            <div class="row">
              <div class="title">루돌프 코</div>
              <div class="pill">3시간</div>
            </div>
            <div class="meta">🦌토르의 뿔🦌<br>퀘스트 완료 후 눌러주세요!</div>
          </div>
        </button>
        <div style="margin-top:12px">
          <div class="mono" id="rudolph_line">상태 불러오는 중…</div>
          <div class="progress" style="margin-top:8px"><div class="bar" id="rudolph_bar"></div></div>
        </div>

        <div style="margin-top:10px; display:flex; gap:8px;">
          <button class="btn" onclick="cancelTimer('rudolph')">중지</button>
        </div>
      </div>

      <div class="card">
        <button class="timerBtn" onclick="startTimer('bandage')">
          <div class="avatar"><img src="/static/bandage.png" alt="bandage"/></div>
          <div style="flex:1">
            <div class="row">
              <div class="title">반창고</div>
              <div class="pill">1시간</div>
            </div>
            <div class="meta">🩹산타 고양이 선물상자🩹<br>퀘스트 완료 후 눌러주세요!</div>
          </div>
        </button>
        <div style="margin-top:12px">
          <div class="mono" id="bandage_line">상태 불러오는 중…</div>
          <div class="progress" style="margin-top:8px"><div class="bar" id="bandage_bar"></div></div>

          <div style="margin-top:10px; display:flex; gap:8px;">
            <button class="btn" onclick="cancelTimer('bandage')">중지</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card statusCard">
      <div class="row">
        <div>
          <div class="title">⏱️ 내 타이머</div>
          <div class="meta">남은 시간은 실시간으로 갱신됩니다.</div>
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn" onclick="openDetail()">상세 보기</button>
          <button class="btn" onclick="testSend()">📩 테스트 DM</button>
        </div>
      </div>
      <div class="kpi">
        <div class="box">
          <div class="k">루돌프 코 남은 시간</div>
          <div class="v" id="rudolph_left">-</div>
        </div>
        <div class="box">
          <div class="k">반창고 남은 시간</div>
          <div class="v" id="bandage_left">-</div>
        </div>
      </div>
      <div class="mono" style="margin-top:10px" id="hint">같은 버튼을 다시 누르면 시간 리셋!</div>
    </div>
  </div>

  <div class="modalBg" id="modalBg" onclick="closeDetail(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modalHeader">
        <div>
          <div class="title">📋 타이머 상세</div>
          <div class="meta">다음 알림 시각, 마지막 설정 시각, 진행률을 확인할 수 있어요.</div>
        </div>
        <button class="close" onclick="closeDetail()">닫기</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>타이머</th>
            <th>다음 알림</th>
            <th>남은 시간</th>
            <th>마지막 설정</th>
            <th>진행률</th>
            <th>중지</th>
          </tr>
        </thead>
        <tbody id="detailBody"></tbody>
      </table>
      <div class="mono" style="margin-top:10px">※ 같은 타이머를 다시 누르면 남은 시간이 처음부터 다시 시작돼요.</div>
    </div>
  </div>

<script>
let tzReady = false;

async function ensureTz() {{
  try {{
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone; // e.g. "Asia/Seoul"
    const r = await fetch('/api/tz', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{ tz }})
    }});
    return r.ok;
  }} catch(e) {{
    return false;
  }}
}}

async function ensureTzOnce() {{
  if (tzReady) return;
  const ok = await ensureTz();
  if (ok) tzReady = true;
}}

function openFeedback() {{
  window.open(
    'https://docs.google.com/forms/d/1ht8IpW7Mm4tuScg8JVVQ4cDkU4tcQ1NO5RQ7groAOps',
    '_blank',
    'noopener'
  );
}}

function humanizeSeconds(sec) {{
  if (sec <= 0) return "0분";
  const m = Math.floor(sec / 60);
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h <= 0) return `${{mm}}분`;
  return `${{h}}시간 ${{mm}}분`;
}}

function showWarn(html) {{
  const box = document.getElementById('dmWarn');
  box.innerHTML = html;
  box.style.display = 'block';
}}

function hideWarn() {{
  const box = document.getElementById('dmWarn');
  box.style.display = 'none';
}}

async function openExternal(kind) {{
  try {{
    await fetch('/api/ack/' + kind, {{ method: 'POST' }});
  }} catch(e) {{}}

  window.open('/out/invite', '_blank', 'noopener');

  const started = Date.now();
  const limitMs = 60 * 1000;

  const timer = setInterval(async () => {{
    try {{
      const r = await fetch('/api/banner', {{ cache: 'no-store' }});
      if(!r.ok) return;
      const s = await r.json();

      if(s && s.show_banner === false) {{
        clearInterval(timer);
        const el = document.getElementById('bannerWrap');
        if(el) el.innerHTML = '';
        try {{ await refreshStatus(); }} catch(e) {{}}
      }}
    }} catch(e) {{}}

    if(Date.now() - started > limitMs) {{
      clearInterval(timer);
    }}
  }}, 800);
}}

async function startTimer(type) {{
  const r = await fetch('/api/timer/' + type, {{method:'POST'}});
  if (r.status === 401) {{ showLoginRequired(); return; }}
  const t = await r.text();
  document.getElementById('hint').textContent = t.replaceAll('\\n','  ');
  await refreshStatus();
}}

async function cancelTimer(type) {{
  const r = await fetch('/api/timer/' + type + '/cancel', {{method:'POST'}});
  if (r.status === 401) {{ showLoginRequired(); return; }}
  const t = await r.text();
  document.getElementById('hint').textContent = t.replaceAll('\\n','  ');
  await refreshStatus();
}}

async function testSend(){{
  const r = await fetch('/api/test-send', {{method:'POST'}});
  if (r.status === 401) {{ showLoginRequired(); return; }}
  const t = await r.text();
  document.getElementById('hint').textContent = t.replaceAll('\\n','  ');

  if(!r.ok) {{
    showWarn(`
      <b>DM 전송 실패</b><br/>
      먼저 아래를 확인해 주세요.<br/>
      1) 개인 서버에 봇을 초대했는지<br/>
      2) 디스코드 설정에서 “서버 멤버의 DM 허용”이 꺼져있지 않은지<br/><br/>
      <span class="mono">${{t}}</span>
    `);
  }} else {{
    hideWarn();
  }}
}}

function showLoginRequired() {{
  showWarn(`
    <b>로그인이 필요합니다.</b><br/>
    오른쪽 상단의 디스코드로 로그인 버튼을 눌러주세요.<br/><br/>
  `);
  
  // 상태 UI도 초기화
  document.getElementById('rudolph_left').textContent = '-';
  document.getElementById('bandage_left').textContent = '-';
  document.getElementById('rudolph_line').textContent = '로그인 후 확인 가능';
  document.getElementById('bandage_line').textContent = '로그인 후 확인 가능';
  document.getElementById('rudolph_bar').style.width = "0%";
  document.getElementById('bandage_bar').style.width = "0%";
}}

async function fetchStatus() {{
  const r = await fetch('/api/status.json', {{ cache: 'no-store' }});
  
  // 로그인 필요(401)면: JSON(detail) 찍지 않고 UI 안내로 처리
  if (r.status == 401) {{
    showLoginRequired();
    return null;
  }}
  
  if(!r.ok) {{
    // 그 외 에러는 필요하면 메시지 표시
    const t = await r.text().catch(() => '');
    showWarn(`<b>상태를 불러오지 못했어요.</b><br/><span class="mono">${{t}}</span>`);
    return null;
  }}
  
  hideWarn();
  return await r.json();
}}

async function fetchDmHealth() {{
  const r = await fetch('/api/dm/health', {{ cache: 'no-store' }});
  if (r.status === 401) {{ showLoginRequired(); return null; }}
  if(!r.ok) return null;
  return await r.json();
}}

function calc(timer, serverNowIso, totalSec) {{
  if(!timer || timer.status !== 'scheduled') {{
    return {{ active:false, leftText:"설정 없음", dueLocal:"-", setLocal:"-", pct:0 }};
  }}
  const now = new Date(serverNowIso);
  const due = new Date(timer.due_at);

  const leftSec = Math.floor((due - now) / 1000);
  const elapsed = totalSec - leftSec;
  const pct = Math.max(0, Math.min(100, (elapsed / totalSec) * 100));

  return {{
    active:true,
    leftSec,
    leftText: humanizeSeconds(leftSec),
    dueLocal: timer.due_at_local || "-",
    setLocal: timer.last_set_at_local || "-",
    pct
  }};
}}

let lastData = null;

async function refreshStatus() {{
  const data = await fetchStatus();
  if(!data) return;
  
  const wasTzReady = tzReady;
  await ensureTzOnce(); // 로그인 된 뒤에 tz 저장
  
  // tz가 방금 처음 저장된 경우에만 status를 한번 더 받아서 local time 재계산값 반영
  let finalData = data;
  if (!wasTzReady && tzReady) {{
    const data2 = await fetchStatus();
    if (data2) finalData = data2;
  }}
  
  lastData = finalData;

  const r = calc(finalData.timers.rudolph, finalData.server_now, 3*3600);
  const b = calc(finalData.timers.bandage, finalData.server_now, 1*3600);

  document.getElementById('rudolph_left').textContent = r.leftText;
  document.getElementById('bandage_left').textContent = b.leftText;

  document.getElementById('rudolph_line').textContent =
    r.active ? `다음 알림 ${{r.dueLocal}} (남은 ${{r.leftText}})` : "설정 없음";

  document.getElementById('bandage_line').textContent =
    b.active ? `다음 알림 ${{b.dueLocal}} (남은 ${{b.leftText}})` : "설정 없음";

  document.getElementById('rudolph_bar').style.width = r.pct + "%";
  document.getElementById('bandage_bar').style.width = b.pct + "%";

  if(document.getElementById('modalBg').style.display === 'flex') {{
    renderDetail();
  }}

  const dm = await fetchDmHealth();
  if(dm && dm.dm_status === 'fail') {{
    showWarn(`
      <b>DM이 막혀있는 것 같아요😢</b><br/>
      봇 초대 후 “테스트 DM” 버튼으로 먼저 확인해 주세요.
    `);
  }}
}}

function renderDetail() {{
  const data = lastData;
  if(!data) return;

  const r = calc(data.timers.rudolph, data.server_now, 3*3600);
  const b = calc(data.timers.bandage, data.server_now, 1*3600);

  const rows = [
    {{ type:"rudolph", name: "루돌프 코 (3시간)", due: r.dueLocal, left: r.leftText, set: r.setLocal, pct: r.pct, active: r.active}},
    {{ type:"bandage", name: "반창고 (1시간)", due: b.dueLocal, left: b.leftText, set: b.setLocal, pct: b.pct, active: b.active}}
  ];

  document.getElementById('detailBody').innerHTML = rows.map(x => `
    <tr>
      <td>${{x.name}}</td>
      <td>${{x.due}}</td>
      <td>${{x.left}}</td>
      <td>${{x.set}}</td>
      <td>${{Math.round(x.pct)}}%</td>
      <td>
        ${{ x.active
          ? `<button class="btn" onclick="cancelTimer('${{x.type}}')">중지</button>`
          : `<span class="mono">-</span>`
        }}
      </td>
    </tr>
  `).join('');
}}

async function openDetail() {{
  document.getElementById('modalBg').style.display = 'flex';
  await refreshStatus();
  renderDetail();
}}

function closeDetail(e) {{
  if (e && e.target && e.target.id !== 'modalBg') return;
  document.getElementById('modalBg').style.display = 'none';
}}

refreshStatus();
setInterval(refreshStatus, 30000);
</script>

<button class="fabFeedback" onclick="openFeedback()">
  <span class="fabIcon">💬</span>
  피드백
</button>
</body>
</html>
""".format(
        login_btn=login_btn,
        invite_banner=invite_banner,
    )

    return HTMLResponse(html)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)

# =====================================================
# Discord OAuth routes
# =====================================================
@app.get("/auth/discord/login")
async def discord_login():
    return RedirectResponse(discord_login_url(), status_code=302)

@app.get("/auth/discord/callback")
async def discord_callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(f"디스코드 로그인 실패: {error}", status_code=400)
    if not code:
        return HTMLResponse("인가 코드 없음", status_code=400)

    token = await discord_exchange_code(code)
    me = await discord_get_me(token["access_token"])
    request.session["discord_user_id"] = str(me["id"])
    return RedirectResponse("/", status_code=302)

# =====================================================
# API
# =====================================================
@app.post("/api/timer/{timer_type}/cancel")
async def cancel_one(request: Request, timer_type: str):
    uid = require_login(request)
    if timer_type not in ("rudolph", "bandage"):
        raise HTTPException(400, "unknown timer_type")

    cancel_timer(uid, timer_type)
    label = "루돌프 코(3시간)" if timer_type == "rudolph" else "반창고(1시간)"
    return HTMLResponse(f"🛑 {label} 타이머를 중지했어요. (삭제됨)")

@app.post("/api/tz")
async def set_tz(request: Request):
    """
    브라우저의 IANA time zone을 받아서
    - session에 저장 (UI)
    - discord_users.tz에 저장 (poller DM)
    """
    uid = require_login(request)
    data = await request.json()
    tz = (data.get("tz") or "").strip()

    if not tz or len(tz) > 64 or "/" not in tz:
        raise HTTPException(400, "bad tz")

    prev = request.session.get("tz") or get_user_tz(uid)
    request.session["tz"] = tz
    if tz != prev:
        upsert_user_tz(uid, tz)

    return JSONResponse({"ok": True, "tz": tz})

@app.post("/api/ack/{kind}")
async def ack(request: Request, kind: str):
    if kind != "invite":
        raise HTTPException(400, "bad kind")
    request.session["invite_clicked"] = True
    return JSONResponse({"ok": True})

@app.post("/api/timer/{timer_type}")
async def set_timer(request: Request, timer_type: str):
    uid = require_login(request)

    require_dm_ready(uid)

    tz_name = request.session.get("tz") or get_user_tz(uid)
    request.session["tz"] = tz_name

    if timer_type not in ("rudolph", "bandage"):
        raise HTTPException(400, "unknown timer_type")

    hours = 3 if timer_type == "rudolph" else 1
    due_u = now_utc() + timedelta(hours=hours)
    upsert_timer(uid, timer_type, due_u)

    label = "루돌프 코(3시간)" if timer_type == "rudolph" else "반창고(1시간)"
    return HTMLResponse(f"✅ {label} 타이머 갱신!\n- 다음 알림: {fmt_in_tz(due_u, tz_name)} ({tz_name})")

@app.post("/api/test-send")
async def test_send(request: Request):
    uid = require_login(request)
    tz_name = request.session.get("tz") or get_user_tz(uid)
    request.session["tz"] = tz_name

    try:
        await discord_send_dm(uid, "✅ 테스트 DM: 테스트 메시지가 정상적으로 도착했어요!")
        upsert_dm_result(uid, ok=True)
        return HTMLResponse("✅ 테스트 DM을 보냈어요! (Discord DM 확인)")

    except httpx.HTTPStatusError as e:
        err_txt = f"{e.response.status_code} {e.response.text}"
        upsert_dm_result(uid, ok=False, err=err_txt)
        return HTMLResponse(
            # f"❌ DM 전송 실패: {err_txt}\n"
            f"→ 개인 서버에 봇을 초대했는지 확인하고, 디스코드에서 서버/DM 설정을 확인해 주세요.",
            status_code=400
        )

    except Exception as e:
        upsert_dm_result(uid, ok=False, err=str(e))
        return HTMLResponse(f"❌ DM 전송 실패: {e}", status_code=400)

@app.get("/api/dm/health")
async def dm_health(request: Request):
    uid = require_login(request)
    row = get_dm_status(uid)
    if not row:
        row = {"discord_user_id": uid, "dm_status": "unknown", "dm_last_error": None}
    return JSONResponse(row)

@app.get("/api/banner")
async def banner_state(request: Request):
    uid = request.session.get("discord_user_id")
    if not uid:
        return JSONResponse({"logged_in": False, "show_banner": False})

    dm_ready = is_dm_ready(uid)
    return JSONResponse({
        "logged_in": True,
        "dm_ready": dm_ready,
        "show_banner": (not dm_ready),
    })

@app.get("/api/status.json")
async def status_json(request: Request):
    uid = require_login(request)
    timers = get_timers(uid)

    tz_name = request.session.get("tz") or get_user_tz(uid)
    request.session["tz"] = tz_name

    def local_str_from_iso(iso: str | None):
        if not iso:
            return None
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return fmt_in_tz(dt, tz_name)

    def norm(row):
        if not row:
            return None

        due_iso = row.get("due_at")
        set_iso = row.get("last_set_at")

        return {
            "timer_type": row.get("timer_type"),
            "status": row.get("status"),
            "last_set_at": set_iso,
            "due_at": due_iso,
            "last_set_at_local": local_str_from_iso(set_iso),
            "due_at_local": local_str_from_iso(due_iso),
        }

    return JSONResponse({
        "server_now": now_utc().isoformat(),
        "server_now_local": fmt_in_tz(now_utc(), tz_name),
        "tz": tz_name,
        "timers": {
            "rudolph": norm(timers.get("rudolph")),
            "bandage": norm(timers.get("bandage")),
        }
    })

# =====================================================
# Background poller
# =====================================================
async def poller():
    while True:
        try:
            due_rows = fetch_due_timers(POLL_LIMIT)
            for row in due_rows:
                uid = row["discord_user_id"]
                t = row["timer_type"]

                due = datetime.fromisoformat(row["due_at"].replace("Z", "+00:00"))
                tz_name = get_user_tz(uid)
                due_local = fmt_in_tz(due, tz_name)

                if t == "rudolph":
                    msg = f"🦌 루돌프 코 쿨타임 끝! ({due_local})"
                else:
                    msg = f"🩹 반창고 쿨타임 끝! ({due_local})"

                try:
                    await discord_send_dm(uid, msg)
                    mark_sent(uid, t)
                    upsert_dm_result(uid, ok=True)
                except httpx.HTTPStatusError as e:
                    err_txt = f"{e.response.status_code} {e.response.text}"
                    mark_failed(uid, t, err_txt)
                    upsert_dm_result(uid, ok=False, err=err_txt)
                    print("[SEND FAIL]", uid, t, err_txt)
                except Exception as e:
                    mark_failed(uid, t, str(e))
                    upsert_dm_result(uid, ok=False, err=str(e))
                    print("[SEND FAIL]", uid, t, e)

        except Exception as e:
            print("[POLL LOOP FAIL]", e)

        await asyncio.sleep(POLL_SECONDS)

@app.on_event("startup")
async def startup():
    asyncio.create_task(poller())
