from datetime import date, datetime, time, timezone

from tortoise.timezone import get_default_timezone, get_use_tz

from config import settings


def billing_day_start(day: date) -> datetime:
    # SQLite compares timestamp text, so use the same zone as ORM-created rows.
    storage_zone = timezone.utc if get_use_tz() else get_default_timezone()
    return datetime.combine(day, time.min, settings.tz).astimezone(storage_zone)
