import os
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()
load_dotenv(".env1", override=True)


def _build_database_url(user: str, password: str, host: str, port: int, db_name: str) -> str:
    return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(db_name)}"


_raw_database_url = os.getenv("DATABASE_URL")
_db_host = os.getenv("DB_HOST", "localhost")
_db_port = int(os.getenv("DB_PORT", "5432"))
_db_name = os.getenv("DB_NAME", "granit_ural_ais")
_db_user = os.getenv("DB_USER", "postgres")
_db_password = os.getenv("DB_PASSWORD", "123123")
_has_explicit_db_parts = any(
    os.getenv(name) is not None for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
)
_resolved_database_url = (
    _build_database_url(_db_user, _db_password, _db_host, _db_port, _db_name)
    if _has_explicit_db_parts
    else (_raw_database_url or _build_database_url(_db_user, _db_password, _db_host, _db_port, _db_name))
)


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "development-secret-key")
    DB_HOST = _db_host
    DB_PORT = _db_port
    DB_NAME = _db_name
    DB_USER = _db_user
    DB_PASSWORD = _db_password
    DATABASE_URL = _resolved_database_url
    APP_PORT = int(os.getenv("APP_PORT", "5005"))
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Yandex Market API
    YANDEX_MARKET_API_KEY = os.getenv("YANDEX_MARKET_API_KEY")
    YANDEX_MARKET_CAMPAIGN_ID = os.getenv("YANDEX_MARKET_CAMPAIGN_ID")
    YANDEX_MARKET_BUSINESS_ID = os.getenv("YANDEX_MARKET_BUSINESS_ID")
    YANDEX_MARKET_WAREHOUSE_ID = int(os.getenv("YANDEX_MARKET_WAREHOUSE_ID", "1"))
