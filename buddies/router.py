from fastapi import APIRouter, Depends

from backend.buddies import service
from backend.buddies.schemas import ActiveBuddyUpdate, EquippedModelUpdate, RoomBackgroundUpdate
from backend.core.errors import ok
from backend.core.security import get_current_user_id

router = APIRouter(tags=["buddies"])


@router.get("/buddies")
def list_buddies(user_id: str = Depends(get_current_user_id)):
    return ok(service.list_buddies(user_id))


@router.get("/buddies/active")
def active(user_id: str = Depends(get_current_user_id)):
    return ok(service.active(user_id))


@router.put("/buddies/active")
def set_active(payload: ActiveBuddyUpdate, user_id: str = Depends(get_current_user_id)):
    return ok(service.set_active(user_id, payload.buddyId or payload.buddy_id))


@router.get("/buddy-3d/models")
def models(_user_id: str = Depends(get_current_user_id)):
    return ok(service.models())


@router.get("/buddy-3d/backgrounds")
def backgrounds(_user_id: str = Depends(get_current_user_id)):
    return ok(service.backgrounds())


@router.get("/buddy-3d/settings")
def settings(user_id: str = Depends(get_current_user_id)):
    return ok(service.settings(user_id))


@router.put("/buddy-3d/equipped-model")
def equip_model(payload: EquippedModelUpdate, user_id: str = Depends(get_current_user_id)):
    return ok(service.equip_model(user_id, payload.modelId or payload.model_id))


@router.put("/buddy-3d/room-background")
def select_background(payload: RoomBackgroundUpdate, user_id: str = Depends(get_current_user_id)):
    return ok(service.select_background(user_id, payload.backgroundId or payload.background_id))

