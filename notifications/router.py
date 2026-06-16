from fastapi import APIRouter, Depends, Request

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.notifications import service
from backend.notifications.schemas import (
    PushSubscriptionRequest,
    StudyReminderCreateRequest,
    StudyReminderUpdateRequest,
    SubscriptionDeactivateRequest,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/subscriptions")
def register_subscription(payload: PushSubscriptionRequest, request: Request, user_id: str = Depends(get_current_user_id)):
    return ok(
        service.register_subscription(
            user_id=user_id,
            installation_id=payload.installation_id,
            endpoint=payload.endpoint,
            p256dh_key=payload.keys.p256dh,
            auth_key=payload.keys.auth,
            content_encoding=payload.content_encoding,
            platform=payload.platform,
            user_agent=request.headers.get("user-agent"),
        )
    )


@router.get("/subscriptions")
def list_subscriptions(user_id: str = Depends(get_current_user_id)):
    return ok(service.list_subscriptions(user_id))


@router.delete("/subscriptions/current")
def deactivate_current_subscription(payload: SubscriptionDeactivateRequest, user_id: str = Depends(get_current_user_id)):
    return ok(service.deactivate_current_subscription(user_id, payload.installation_id))


@router.get("/reminders")
def list_reminders(user_id: str = Depends(get_current_user_id)):
    return ok(service.list_reminders(user_id))


@router.get("/recent")
def list_recent_notifications(user_id: str = Depends(get_current_user_id)):
    return ok(service.list_recent_notifications(user_id))


@router.post("/reminders")
def create_reminder(payload: StudyReminderCreateRequest, user_id: str = Depends(get_current_user_id)):
    return ok(service.create_reminder(user_id, payload))


@router.patch("/reminders/{reminder_id}")
def update_reminder(reminder_id: str, payload: StudyReminderUpdateRequest, user_id: str = Depends(get_current_user_id)):
    return ok(service.update_reminder(user_id, reminder_id, payload))


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: str, user_id: str = Depends(get_current_user_id)):
    return ok(service.delete_reminder(user_id, reminder_id))


@router.post("/test")
def enqueue_test_notification(user_id: str = Depends(get_current_user_id)):
    return ok(service.enqueue_test_notification(user_id))
