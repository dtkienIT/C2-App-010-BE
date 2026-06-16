from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from backend.core.config import settings
from backend.notifications.repository import NotificationRepository, build_payload, repository, utc_now
from backend.notifications.schemas import StudyReminderCreateRequest, StudyReminderUpdateRequest

_test_cooldowns: dict[str, datetime] = {}


def notification_test_endpoint_enabled() -> bool:
    is_production = settings.environment.strip().lower() == "production"
    if is_production:
        return settings.enable_notification_test_endpoint
    return settings.enable_notification_test_endpoint or settings.vite_enable_notification_test


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def format_time(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


def mask_endpoint(endpoint: str | None) -> str:
    if not endpoint:
        return ""
    if endpoint.startswith("revoked:"):
        return "revoked"
    if len(endpoint) <= 36:
        return "https://.../"
    return f"{endpoint[:24]}...{endpoint[-8:]}"


def format_subscription(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "installationId": row["installation_id"],
        "endpointPreview": mask_endpoint(row.get("endpoint")),
        "platform": row.get("platform") or "web",
        "isActive": bool(row.get("is_active")),
        "lastSeenAt": iso(row.get("last_seen_at")),
        "createdAt": iso(row.get("created_at")),
        "updatedAt": iso(row.get("updated_at")),
        "revokedAt": iso(row.get("revoked_at")),
    }


def format_reminder(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "reminderTime": format_time(row["reminder_time"]),
        "daysOfWeek": list(row["days_of_week"]),
        "timezone": row["timezone"],
        "isEnabled": bool(row["is_enabled"]),
        "nextRunAt": iso(row["next_run_at"]),
        "lastSentAt": iso(row.get("last_sent_at")),
        "createdAt": iso(row.get("created_at")),
        "updatedAt": iso(row.get("updated_at")),
    }


def format_outbox(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "reminderId": row.get("reminder_id") or row.get("payload", {}).get("reminderId"),
        "eventType": row["event_type"],
        "scheduledAt": iso(row["scheduled_at"]),
        "status": row["status"],
        "attempts": row.get("attempts", 0),
        "createdAt": iso(row.get("created_at")),
    }


def format_recent_notification(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    return {
        "id": row["id"],
        "eventType": row["event_type"],
        "status": row["status"],
        "processedAt": iso(row.get("processed_at")),
        "payload": payload,
    }


def register_subscription(
    *,
    user_id: str,
    installation_id: str,
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
    content_encoding: str | None,
    platform: str,
    user_agent: str | None,
    repo: NotificationRepository = repository,
) -> dict[str, Any]:
    row = repo.upsert_subscription(
        user_id=user_id,
        installation_id=installation_id,
        endpoint=endpoint,
        p256dh_key=p256dh_key,
        auth_key=auth_key,
        content_encoding=content_encoding,
        platform=platform,
        user_agent=user_agent,
    )
    return format_subscription(row)


def list_subscriptions(user_id: str, repo: NotificationRepository = repository) -> list[dict[str, Any]]:
    return [format_subscription(row) for row in repo.list_subscriptions(user_id)]


def deactivate_current_subscription(user_id: str, installation_id: str, repo: NotificationRepository = repository) -> dict[str, Any]:
    row = repo.deactivate_subscription(user_id, installation_id)
    if not row:
        return {"installationId": installation_id, "isActive": False}
    return format_subscription(row)


def list_reminders(user_id: str, repo: NotificationRepository = repository) -> list[dict[str, Any]]:
    return [format_reminder(row) for row in repo.list_reminders(user_id)]


def list_recent_notifications(user_id: str, repo: NotificationRepository = repository) -> list[dict[str, Any]]:
    since = utc_now() - timedelta(minutes=15)
    rows = repo.list_recent_delivered_outbox(user_id=user_id, limit=10, since=since)
    return [format_recent_notification(row) for row in rows]


def create_reminder(user_id: str, payload: StudyReminderCreateRequest, repo: NotificationRepository = repository) -> dict[str, Any]:
    if repo.count_reminders(user_id) >= settings.max_study_reminders_per_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many study reminders")
    row = repo.create_reminder(
        user_id=user_id,
        reminder_time=payload.parsed_time,
        days_of_week=payload.days_of_week,
        timezone_name=payload.timezone,
        is_enabled=payload.is_enabled,
    )
    return format_reminder(row)


def update_reminder(
    user_id: str,
    reminder_id: str,
    payload: StudyReminderUpdateRequest,
    repo: NotificationRepository = repository,
) -> dict[str, Any]:
    patch = payload.model_dump(exclude_unset=True)
    row = repo.update_reminder(user_id=user_id, reminder_id=reminder_id, patch=patch)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study reminder not found")
    return format_reminder(row)


def delete_reminder(user_id: str, reminder_id: str, repo: NotificationRepository = repository) -> dict[str, Any]:
    row = repo.delete_reminder(user_id, reminder_id)
    if not row:
        return {"id": reminder_id, "deleted": True, "idempotent": True}
    return {**format_reminder(row), "deleted": True}


def enqueue_test_notification(user_id: str, repo: NotificationRepository = repository, push_client: Any | None = None) -> dict[str, Any]:
    if not notification_test_endpoint_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification test endpoint is disabled")

    now = utc_now()
    last_sent = _test_cooldowns.get(user_id)
    if last_sent and (now - last_sent).total_seconds() < settings.notification_test_cooldown_seconds:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Notification test cooldown is active")
    if not repo.active_subscriptions(user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active Web Push subscription")

    reminder_id = f"test-{uuid4()}"
    row = repo.enqueue_outbox(user_id=user_id, reminder_id=None, scheduled_at=now, payload=build_payload(reminder_id, now))
    from backend.notifications.worker import process_event

    delivery_status = process_event(row, repo=repo, push_client=push_client) if push_client else process_event(row, repo=repo)
    fresh_row = repo.get_outbox(row["id"]) or row
    formatted = format_outbox(fresh_row)
    formatted["deliveryStatus"] = delivery_status
    if delivery_status not in {"sent", "partial"}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Immediate test notification failed: {delivery_status}",
        )
    _test_cooldowns[user_id] = now
    return formatted
