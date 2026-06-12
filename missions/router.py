from fastapi import APIRouter, Depends, Query

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.missions import service

router = APIRouter(prefix="/missions", tags=["missions"])


@router.get("")
def list_missions(type: str | None = Query(default=None), user_id: str = Depends(get_current_user_id)):
    return ok(service.list_missions(user_id, type))


@router.post("/{mission_id}/complete")
def complete(mission_id: str, user_id: str = Depends(get_current_user_id)):
    return ok(service.complete(user_id, mission_id))


@router.post("/{mission_id}/claim")
def claim(mission_id: str, user_id: str = Depends(get_current_user_id)):
    return ok(service.claim(user_id, mission_id))

