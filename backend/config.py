import os
from pathlib import Path


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
STATIC_DIR = BACKEND_DIR / "static"
DATA_DIR = BACKEND_DIR / "data"
DATABASE_PATH = DATA_DIR / "taskbuddy.db"

APP_NAME = "TaskBuddy"
API_PREFIX = "/api/v1"
MAX_CHARACTERS = 250
MAX_PLAN_STEPS = 2
THREAD_TITLE_LIMIT = 48
MAX_THREADS_PER_USER = 5
MAX_TASK_FLOWS_PER_THREAD = 3
SESSION_COOKIE_NAME = "taskbuddy_session"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 12
JWT_SECRET = os.getenv("TASKBUDDY_JWT_SECRET", "taskbuddy-dev-secret")
PBKDF2_ITERATIONS = 120_000
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
SUPPORTED_ROLES = {ROLE_ADMIN, ROLE_USER}
MAX_ADMIN_USERS = 1
MAX_STANDARD_USERS = 2
DEMO_PACING_ENABLED = _env_flag("TASKBUDDY_DEMO_PACING", True)
STREAM_STEP_DELAY_MS = _env_int("TASKBUDDY_STREAM_STEP_DELAY_MS", 250)
RETRY_BACKOFF_MS = _env_int("TASKBUDDY_RETRY_BACKOFF_MS", 400)
DEFAULT_DEMO_USERS = (
    {"username": DEFAULT_ADMIN_USERNAME, "password": DEFAULT_ADMIN_PASSWORD, "role": ROLE_ADMIN},
)

SUPPORTED_WEATHER_CITIES = {
    "toronto": {"city": "Toronto", "condition": "Cloudy", "temperature_c": 8, "humidity_pct": 71},
    "vancouver": {"city": "Vancouver", "condition": "Rainy", "temperature_c": 11, "humidity_pct": 84},
    "new york": {"city": "New York", "condition": "Sunny", "temperature_c": 14, "humidity_pct": 49},
    "chicago": {"city": "Chicago", "condition": "Windy", "temperature_c": 6, "humidity_pct": 58},
    "london": {"city": "London", "condition": "Foggy", "temperature_c": 9, "humidity_pct": 76},
    "sydney": {"city": "Sydney", "condition": "Clear", "temperature_c": 24, "humidity_pct": 42},
}

SUPPORTED_CURRENCY_RATES = {
    "USD": 1.00,
    "CAD": 1.35,
    "GBP": 0.79,
    "AUD": 1.52,
}

TRANSACTION_KEYWORDS = {
    "groceries": ["grocery", "costco", "whole foods", "superstore", "walmart"],
    "transport": ["uber", "lyft", "shell", "esso", "metro", "transit"],
    "bills": ["hydro", "electric", "internet", "insurance", "bill", "phone"],
    "dining": ["starbucks", "restaurant", "coffee", "mcdonald", "pizza"],
    "shopping": ["amazon", "target", "best buy", "mall", "shop"],
    "travel": ["airbnb", "hotel", "delta", "flight", "marriott"],
    "entertainment": ["netflix", "cinema", "spotify", "concert", "game"],
}
