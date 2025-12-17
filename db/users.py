from core.supabase import sb
from core.config import USERS_TABLE, DEFAULT_TZ
from core.timeutils import now_utc


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