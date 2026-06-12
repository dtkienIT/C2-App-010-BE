from fastapi import APIRouter, Depends

from backend.achievements import service
from backend.core.errors import ok
from backend.core.security import get_current_user_id

router = APIRouter(prefix="/achievements", tags=["achievements"])


@router.get("")
def list_achievements(user_id: str = Depends(get_current_user_id)):
    return ok(service.list_achievements(user_id))


@router.post("/{achievement_id}/claim")
def claim(achievement_id: str, user_id: str = Depends(get_current_user_id)):
    return ok(service.claim(user_id, achievement_id))

