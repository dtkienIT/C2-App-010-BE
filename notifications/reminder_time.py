from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_days_of_week(days_of_week: list[int]) -> list[int]:
    unique_days = sorted(set(days_of_week))
    if not unique_days:
        raise ValueError("days_of_week must not be empty")
    invalid = [day for day in unique_days if day < 1 or day > 7]
    if invalid:
        raise ValueError("days_of_week values must be between 1 and 7")
    return unique_days


def parse_reminder_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("reminder_time must use HH:MM format") from exc
    return parsed.replace(second=0, microsecond=0)


def validate_timezone(timezone_name: str) -> str:
    timezone_name = timezone_name.strip()
    if not timezone_name:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return timezone_name


def calculate_next_run(
    reminder_time: time,
    days_of_week: list[int],
    timezone_name: str,
    now_utc: datetime,
) -> datetime:
    days = validate_days_of_week(days_of_week)
    timezone_name = validate_timezone(timezone_name)
    tz = ZoneInfo(timezone_name)

    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")

    now_local = now_utc.astimezone(tz)
    today_local = now_local.date()
    for offset in range(0, 8):
        candidate_date = today_local + timedelta(days=offset)
        candidate_weekday = candidate_date.isoweekday()
        if candidate_weekday not in days:
            continue
        candidate_local = datetime.combine(candidate_date, reminder_time, tzinfo=tz)
        if candidate_local > now_local:
            return candidate_local.astimezone(timezone.utc)

    raise ValueError("Unable to calculate next reminder run")
