from fastapi import APIRouter, Depends

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.dashboard import service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(user_id: str = Depends(get_current_user_id)):
    return ok(service.get_dashboard(user_id))

