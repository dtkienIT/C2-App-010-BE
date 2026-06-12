from fastapi import APIRouter, Depends

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.users import service
from backend.users.schemas import ProfilePatch

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/stats")
def stats(user_id: str = Depends(get_current_user_id)):
    return ok(service.stats(user_id))


@router.patch("/me/profile")
def update_profile(payload: ProfilePatch, user_id: str = Depends(get_current_user_id)):
    return ok(service.update_profile(user_id, payload.model_dump(exclude_none=True)))

