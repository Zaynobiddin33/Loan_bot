from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "db.sqlite3"


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_ids: list[int]


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is missing. Add it to the .env file before starting the bot.")

    raw_admin_ids = os.getenv("ADMIN_IDS", "")
    admin_ids = [int(item.strip()) for item in raw_admin_ids.split(",") if item.strip()]

    return Settings(bot_token=bot_token, admin_ids=admin_ids)
