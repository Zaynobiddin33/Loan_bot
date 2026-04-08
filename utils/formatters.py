from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import pytz


UZ_TZ = pytz.timezone("Asia/Tashkent")
UTC = pytz.UTC


def format_amount(value: float | int | Decimal) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == amount.to_integral():
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


def parse_amount(text: str) -> float | None:
    cleaned = text.strip().replace(" ", "").replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None

    if value <= 0:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def format_timestamp(timestamp: str | datetime | None) -> str:
    if timestamp is None:
        return "Noma'lum vaqt"

    if isinstance(timestamp, datetime):
        dt = timestamp
    else:
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        dt = UTC.localize(dt)

    if dt.tzinfo is None:
        dt = UTC.localize(dt)
    return dt.astimezone(UZ_TZ).strftime("%Y-%m-%d %H:%M")


def now_local() -> datetime:
    return datetime.now(UZ_TZ)


def get_period_bounds(period: str) -> tuple[str, datetime | None, datetime | None]:
    current = now_local()

    if period == "today":
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return "Bugun", start, current

    if period == "week":
        start = (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return "Shu hafta", start, current

    if period == "month":
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return "Shu oy", start, current

    return "Barcha vaqt", None, None


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = UZ_TZ.localize(dt)
    return dt.astimezone(UTC)


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower() or "guruh"


def display_name(full_name: str | None, username: str | None, telegram_id: int) -> str:
    if full_name and full_name.strip():
        return full_name.strip()
    if username and username.strip():
        return f"@{username.strip()}"
    return f"Noma'lum foydalanuvchi (#{telegram_id})"


def telegram_user_name(user: Any) -> str:
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name
    username = getattr(user, "username", None)
    if username:
        return f"@{username}"
    user_id = getattr(user, "id", "unknown")
    return f"Noma'lum foydalanuvchi (#{user_id})"
