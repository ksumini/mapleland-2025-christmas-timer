from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from core.config import DEFAULT_TZ


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