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
from backend.progress.router import router as progress_router
from backend.quizzes.router import router as quizzes_router
from backend.rewards.router import router as rewards_router
from backend.users.router import router as users_router


def create_app() -> FastAPI:
    app = FastAPI(title="Buddy Study API", version="0.1.0")

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
        return {"success": True, "data": {"status": "ok"}}

    return app


app = create_app()

