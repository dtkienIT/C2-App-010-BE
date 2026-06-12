from fastapi import APIRouter, Depends

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.progress import service

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("/summary")
def summary(user_id: str = Depends(get_current_user_id)):
    return ok(service.summary(user_id))


@router.get("/activity")
def activity(user_id: str = Depends(get_current_user_id)):
    return ok(service.activity(user_id))

