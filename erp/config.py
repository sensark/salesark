import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///data/sales_erp.db")
    if url.startswith("mysql://"):
        url = url.replace("mysql://", "mysql+pymysql://", 1)
    # Resolve relative SQLite paths against the project root so the app works from any cwd.
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        rel = url.removeprefix("sqlite:///")
        if not Path(rel).is_absolute():
            path = BASE_DIR / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path.as_posix()}"
    return url


DATABASE_URL = _database_url()
COMPANY_NAME = os.getenv("COMPANY_NAME", "Krypton Industries Limited")
COMPANY_STATE = os.getenv("COMPANY_STATE", "West Bengal")
COMPANY_CURRENCY = "INR"

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = _bool("SMTP_USE_SSL", False)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
EMAIL_ENABLED = _bool("EMAIL_ENABLED", True)
ADMIN_NOTIFY_EMAIL = [e.strip() for e in os.getenv("ADMIN_NOTIFY_EMAIL", "").split(",") if e.strip()]

AUTH_COOKIE_KEY = os.getenv("AUTH_COOKIE_KEY", "dev-only-insecure-key")
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "sales_erp_auth")
AUTH_COOKIE_EXPIRY_DAYS = float(os.getenv("AUTH_COOKIE_EXPIRY_DAYS", "1"))

DEFAULT_REORDER_LEVEL = 10

MODEL_DIR = BASE_DIR / os.getenv("MODEL_DIR", "data/models")
REPLENISHMENT_LEAD_DAYS = int(os.getenv("REPLENISHMENT_LEAD_DAYS", "14"))
SERVICE_LEVEL_Z = float(os.getenv("SERVICE_LEVEL_Z", "1.65"))
