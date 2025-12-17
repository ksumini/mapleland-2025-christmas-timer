from datetime import datetime
from core.supabase import sb
from core.config import TIMERS_TABLE
from core.timeutils import now_utc


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
