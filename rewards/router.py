from fastapi import APIRouter, Depends

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.rewards import service

router = APIRouter(prefix="/rewards", tags=["rewards"])


@router.get("")
def rewards(user_id: str = Depends(get_current_user_id)):
    return ok(service.list_rewards(user_id))

