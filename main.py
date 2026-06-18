from contextlib import asynccontextmanager
import logging
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.achievements.router import router as achievements_router
from backend.auth.router import router as auth_router
from backend.buddies.router import router as buddies_router
from backend.core.config import settings
from backend.core.errors import install_error_handlers
from backend.dashboard.router import router as dashboard_router
from backend.missions.router import router as missions_router
from backend.newsfeed.router import router as newsfeed_router
from backend.notifications.router import router as notifications_router
from backend.notifications.service import notification_test_endpoint_enabled
from backend.notifications.worker import get_worker_status, run_forever as run_notification_worker
from backend.progress.router import router as progress_router
from backend.quizzes.router import router as quizzes_router
from backend.rewards.router import router as rewards_router
from backend.users.router import router as users_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event: Event | None = None
    worker_thread: Thread | None = None
    if settings.notification_worker_embedded_enabled:
        stop_event = Event()
        worker_thread = Thread(
            target=run_notification_worker,
            kwargs={"worker_id": "embedded-notification-worker", "stop_event": stop_event},
            name="embedded-notification-worker",
            daemon=True,
        )
        worker_thread.start()
        logger.info("embedded_notification_worker_started")
    try:
        yield
    finally:
        if stop_event is not None:
            stop_event.set()
        if worker_thread is not None:
            worker_thread.join(timeout=max(2, settings.notification_worker_poll_seconds + 1))
            logger.info("embedded_notification_worker_stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Buddy Study API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    routers = [
        auth_router,
        users_router,
        dashboard_router,
        missions_router,
        newsfeed_router,
        notifications_router,
        quizzes_router,
        progress_router,
        buddies_router,
        achievements_router,
        rewards_router,
    ]

    for router in routers:
        app.include_router(router)
        app.include_router(router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, object]:
        worker_status = get_worker_status()
        return {
            "success": True,
            "data": {
                "status": "ok",
                "webPushEnabled": settings.web_push_enabled,
                "webPushConfigured": bool(settings.web_push_vapid_public_key and settings.web_push_vapid_private_key),
                "notificationTestEndpointEnabled": notification_test_endpoint_enabled(),
                "embeddedNotificationWorkerEnabled": settings.notification_worker_embedded_enabled,
                "embeddedNotificationWorkerAlive": bool(worker_status.get("is_running")),
                "notificationWorker": worker_status,
            },
        }

    return app


app = create_app()

