from __future__ import annotations

from backend.core.config import settings
from backend.notifications.repository import NotificationRepository, repository


def enqueue_due_reminders(
    *,
    repo: NotificationRepository = repository,
    worker_id: str,
    batch_size: int | None = None,
) -> list[dict[str, object]]:
    return repo.claim_due_reminders(
        limit=batch_size or settings.notification_worker_batch_size,
        worker_id=worker_id,
    )
