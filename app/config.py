import os
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "development-secret-key")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME", "granit_ural_ais")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "123123")
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"postgresql://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{quote_plus(DB_NAME)}",
    )
    APP_PORT = int(os.getenv("APP_PORT", "5005"))
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Yandex Market API
    YANDEX_MARKET_TOKEN = os.getenv("YANDEX_MARKET_TOKEN")
    YANDEX_MARKET_CAMPAIGN_ID = os.getenv("YANDEX_MARKET_CAMPAIGN_ID")
    YANDEX_MARKET_BUSINESS_ID = os.getenv("YANDEX_MARKET_BUSINESS_ID")
    YANDEX_MARKET_WAREHOUSE_ID = int(os.getenv("YANDEX_MARKET_WAREHOUSE_ID", "1"))
