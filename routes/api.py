from datetime import datetime, timedelta
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from core.timeutils import now_utc, fmt_in_tz
from db.users import is_dm_ready, get_dm_status, upsert_dm_result, upsert_user_tz, get_user_tz
from db.timers import cancel_timer, upsert_timer, get_timers
from services.discord_api import discord_send_dm, discord_bot_invite_url

router = APIRouter()


def require_login(request: Request) -> str:
    uid = request.session.get("discord_user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return uid

def require_dm_ready(user_id: str):
    if not is_dm_ready(user_id):
        raise HTTPException(
            status_code=400,
            detail="DM 알림을 받으려면 먼저 개인 서버에 봇을 초대하고, ‘테스트 DM’으로 활성화를 확인해 주세요."
        )

@router.post("/api/timer/{timer_type}/cancel")
async def cancel_one(request: Request, timer_type: str):
    uid = require_login(request)
    if timer_type not in ("rudolph", "bandage"):
        raise HTTPException(400, "unknown timer_type")

    cancel_timer(uid, timer_type)
    label = "루돌프 코(3시간)" if timer_type == "rudolph" else "반창고(1시간)"
    return HTMLResponse(f"🛑 {label} 타이머를 중지했어요. (삭제됨)")

@router.post("/api/tz")
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

@router.post("/api/timer/{timer_type}")
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

@router.post("/api/test-send")
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

@router.get("/api/dm/health")
async def dm_health(request: Request):
    uid = require_login(request)
    row = get_dm_status(uid)
    if not row:
        row = {"discord_user_id": uid, "dm_status": "unknown", "dm_last_error": None}
    return JSONResponse(row)

@router.get("/api/status.json")
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

@router.post("/api/ack/{kind}")
async def ack(request: Request, kind: str):
    if kind != "invite":
        raise HTTPException(400, "bad kind")
    request.session["invite_clicked"] = True
    return JSONResponse({"ok": True})

@router.get("/api/banner")
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

@router.get("/out/invite")
async def out_invite():
    return RedirectResponse(discord_bot_invite_url(), status_code=302)