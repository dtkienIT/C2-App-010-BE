from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
from threading import Event, Lock
import time
from typing import Any

from backend.core.config import settings
from backend.notifications.constants import (
    BACKOFF_SECONDS,
    DELIVERY_PERMANENT_FAILURE,
    DELIVERY_SENT,
    DELIVERY_TRANSIENT_FAILURE,
)
from backend.notifications.email_client import StudyReminderEmailClient, client as email_client
from backend.notifications.repository import NotificationRepository, repository
from backend.notifications.scheduler import enqueue_due_reminders
from backend.notifications.web_push_client import WebPushClient, client

logger = logging.getLogger(__name__)
_worker_status_lock = Lock()
_worker_status: dict[str, Any] = {
    "worker_id": None,
    "started_at": None,
    "last_poll_at": None,
    "last_success_at": None,
    "last_error_at": None,
    "last_error_type": None,
    "last_counts": None,
    "is_running": False,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def update_worker_status(**patch: Any) -> None:
    with _worker_status_lock:
        _worker_status.update(patch)


def get_worker_status() -> dict[str, Any]:
    with _worker_status_lock:
        snapshot = dict(_worker_status)
    for key in ("started_at", "last_poll_at", "last_success_at", "last_error_at"):
        snapshot[key] = _iso(snapshot.get(key))
    return snapshot


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_retry_at(attempts: int) -> datetime:
    index = max(0, min(attempts - 1, len(BACKOFF_SECONDS) - 1))
    return utc_now() + timedelta(seconds=BACKOFF_SECONDS[index])


def is_too_late(event: dict[str, Any]) -> bool:
    scheduled_at = parse_datetime(event["scheduled_at"])
    return (utc_now() - scheduled_at).total_seconds() > settings.notification_max_lateness_seconds


def process_email_delivery(
    event: dict[str, Any],
    *,
    repo: NotificationRepository = repository,
    mailer: StudyReminderEmailClient = email_client,
) -> tuple[str, str, str]:
    if not settings.email_notifications_enabled:
        return ("disabled", "", "")

    profile = repo.get_user_notification_profile(event["user_id"])
    email = str((profile or {}).get("email") or "").strip()
    if not profile or not email:
        return ("skipped", "recipient_email_missing", "Learner email is missing")

    delivery = repo.ensure_email_delivery(outbox_id=event["id"], user_id=event["user_id"], email=email)
    if delivery.get("status") == DELIVERY_SENT:
        return ("sent", "", "")

    result = mailer.send(profile, event["payload"])
    if result.is_success:
        repo.record_email_sent(delivery["id"])
        return ("sent", "", "")

    error_code = result.error_code or "email_send_failed"
    error_message = result.error_message or "Email send failed"
    if result.is_skipped:
        repo.record_email_skipped(delivery["id"], error_code=error_code, error_message=error_message)
        return ("skipped", error_code, error_message)

    if result.is_configuration_error:
        repo.record_email_failure(
            delivery["id"],
            status=DELIVERY_PERMANENT_FAILURE,
            error_code=error_code,
            error_message=error_message,
        )
        return ("failed", error_code, error_message)

    repo.record_email_failure(
        delivery["id"],
        status=DELIVERY_TRANSIENT_FAILURE,
        error_code=error_code,
        error_message=error_message,
    )
    return ("retry", error_code, error_message)


def process_event(
    event: dict[str, Any],
    *,
    repo: NotificationRepository = repository,
    push_client: WebPushClient = client,
    mailer: StudyReminderEmailClient = email_client,
) -> str:
    outbox_id = event["id"]
    attempts = int(event.get("attempts") or 1)

    if is_too_late(event):
        repo.mark_outbox_skipped(outbox_id, "notification_too_late", "Notification exceeded max lateness")
        return "skipped"

    email_status, email_error_code, email_error_message = process_email_delivery(event, repo=repo, mailer=mailer)
    subscriptions = repo.active_subscriptions(event["user_id"])
    if not subscriptions and email_status in {"disabled", "skipped"}:
        repo.mark_outbox_skipped(outbox_id, "no_active_subscriptions", "User has no active Web Push subscriptions")
        return "skipped"

    success_count = 0
    permanent_count = 0
    transient_count = 0
    configuration_count = 0
    last_error_code = ""
    last_error_message = ""
    email_success = email_status == "sent"
    email_retry = email_status == "retry"
    email_failed = email_status == "failed"
    if email_error_code:
        last_error_code = email_error_code
        last_error_message = email_error_message

    for subscription in subscriptions:
        delivery = repo.ensure_delivery(outbox_id, subscription["id"])
        if delivery.get("status") == DELIVERY_SENT:
            success_count += 1
            continue

        result = push_client.send(subscription, event["payload"])
        if result.is_success:
            repo.record_delivery_sent(delivery["id"])
            success_count += 1
            continue

        error_code = result.error_code or "web_push_error"
        error_message = result.error_message or "Web Push send failed"
        last_error_code = error_code
        last_error_message = error_message

        if result.is_permanent:
            repo.record_delivery_failure(
                delivery["id"],
                status=DELIVERY_PERMANENT_FAILURE,
                error_code=error_code,
                error_message=error_message,
            )
            repo.deactivate_subscription_by_id(subscription["id"])
            permanent_count += 1
            continue

        repo.record_delivery_failure(
            delivery["id"],
            status=DELIVERY_TRANSIENT_FAILURE,
            error_code=error_code,
            error_message=error_message,
        )
        if result.is_configuration_error:
            configuration_count += 1
        else:
            transient_count += 1

    if email_success:
        success_count += 1
    if email_failed:
        permanent_count += 1
    if email_retry:
        transient_count += 1

    if success_count and (permanent_count or transient_count or configuration_count):
        if transient_count and attempts < settings.notification_max_attempts:
            repo.reschedule_outbox_retry(
                outbox_id,
                next_attempt_at=next_retry_at(attempts),
                error_code=last_error_code or "transient_failure",
                error_message=last_error_message or "Transient notification failure",
            )
            return "retry"
        repo.mark_outbox_partial(outbox_id, last_error_code or "partial_delivery", last_error_message or "Some subscriptions failed")
        return "partial"
    if success_count:
        repo.mark_outbox_sent(outbox_id)
        return "sent"
    if (transient_count or configuration_count) and attempts < settings.notification_max_attempts:
        repo.reschedule_outbox_retry(
            outbox_id,
            next_attempt_at=next_retry_at(attempts),
            error_code=last_error_code or "transient_failure",
            error_message=last_error_message or "Transient notification failure",
        )
        return "retry"

    repo.mark_outbox_failed(
        outbox_id,
        last_error_code or ("permanent_failure" if permanent_count else "delivery_failed"),
        last_error_message or "All deliveries failed",
    )
    return "failed"


def run_once(
    *,
    repo: NotificationRepository = repository,
    push_client: WebPushClient = client,
    mailer: StudyReminderEmailClient = email_client,
    worker_id: str | None = None,
    batch_size: int | None = None,
) -> dict[str, int]:
    worker_id = worker_id or f"notification-worker:{os.getpid()}"
    batch_size = batch_size or settings.notification_worker_batch_size
    scheduled = enqueue_due_reminders(repo=repo, worker_id=worker_id, batch_size=batch_size)
    claimed = repo.claim_due_outbox(limit=batch_size, worker_id=worker_id)
    counts = {"scheduled": len(scheduled), "claimed": len(claimed), "sent": 0, "partial": 0, "failed": 0, "skipped": 0, "retry": 0}
    for event in claimed:
        try:
            status = process_event(event, repo=repo, push_client=push_client, mailer=mailer)
            if status in counts:
                counts[status] += 1
        except Exception as exc:  # pragma: no cover - defensive worker guard.
            logger.exception("notification_worker_event_failed", extra={"outbox_id": event.get("id"), "error_type": type(exc).__name__})
            if int(event.get("attempts") or 1) >= settings.notification_max_attempts:
                repo.mark_outbox_failed(event["id"], "worker_exception", type(exc).__name__)
                counts["failed"] += 1
            else:
                repo.reschedule_outbox_retry(
                    event["id"],
                    next_attempt_at=next_retry_at(int(event.get("attempts") or 1)),
                    error_code="worker_exception",
                    error_message=type(exc).__name__,
                )
                counts["retry"] += 1
    return counts


def run_forever(*, worker_id: str | None = None, stop_event: Event | None = None) -> None:
    worker_id = worker_id or f"notification-worker:{os.getpid()}"
    update_worker_status(
        worker_id=worker_id,
        started_at=utc_now(),
        last_poll_at=None,
        last_success_at=None,
        last_error_at=None,
        last_error_type=None,
        last_counts=None,
        is_running=True,
    )
    logger.info("notification_worker_started", extra={"worker_id": worker_id})
    try:
        while stop_event is None or not stop_event.is_set():
            update_worker_status(last_poll_at=utc_now())
            try:
                counts = run_once(worker_id=worker_id)
                update_worker_status(last_success_at=utc_now(), last_error_type=None, last_counts=counts)
                if counts["scheduled"] or counts["claimed"]:
                    logger.info("notification_worker_batch", extra=counts)
            except Exception as exc:  # pragma: no cover - keeps embedded worker alive after transient DB/network errors.
                update_worker_status(last_error_at=utc_now(), last_error_type=type(exc).__name__)
                logger.exception("notification_worker_poll_failed", extra={"worker_id": worker_id, "error_type": type(exc).__name__})
            sleep_seconds = max(1, settings.notification_worker_poll_seconds)
            if stop_event is None:
                time.sleep(sleep_seconds)
            else:
                stop_event.wait(sleep_seconds)
    finally:
        update_worker_status(is_running=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_forever(worker_id=f"notification-worker:{os.getpid()}")


if __name__ == "__main__":
    main()
