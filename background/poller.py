import asyncio
import httpx
from datetime import datetime

from core.config import POLL_SECONDS, POLL_LIMIT
from core.timeutils import  fmt_in_tz
from db.timers import fetch_due_timers, mark_sent, mark_failed
from db.users import get_user_tz, upsert_dm_result
from services.discord_api import discord_send_dm


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