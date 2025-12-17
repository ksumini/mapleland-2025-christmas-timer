import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SESSION_SECRET = os.environ["SESSION_SECRET"]

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

DISCORD_CLIENT_ID = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
POLL_LIMIT = int(os.getenv("POLL_LIMIT", "50"))

TIMERS_TABLE = "user_timers"
USERS_TABLE = "discord_users"
DEFAULT_TZ = "Asia/Seoul"