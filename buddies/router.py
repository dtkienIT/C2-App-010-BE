from fastapi import APIRouter, Depends

from backend.buddies import service
from backend.buddies.schemas import (
    ActiveBuddyUpdate,
    BuddyRewardApplyPayload,
    EquippedModelUpdate,
    PurchaseBackgroundPayload,
    PurchaseModelPayload,
    RoomBackgroundUpdate,
)
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
def models(user_id: str = Depends(get_current_user_id)):
    return ok(service.models(user_id))


@router.get("/buddy-3d/backgrounds")
def backgrounds(user_id: str = Depends(get_current_user_id)):
    return ok(service.backgrounds(user_id))


@router.get("/buddy-3d/settings")
def settings(user_id: str = Depends(get_current_user_id)):
    return ok(service.settings(user_id))


@router.put("/buddy-3d/equipped-model")
def equip_model(payload: EquippedModelUpdate, user_id: str = Depends(get_current_user_id)):
    return ok(service.equip_model(user_id, payload.modelId or payload.model_id))


@router.put("/buddy-3d/room-background")
def select_background(payload: RoomBackgroundUpdate, user_id: str = Depends(get_current_user_id)):
    return ok(service.select_background(user_id, payload.backgroundId or payload.background_id))


@router.post("/buddy-3d/purchase-model")
def purchase_model(payload: PurchaseModelPayload, user_id: str = Depends(get_current_user_id)):
    return ok(service.purchase_model(user_id, payload.modelId or payload.model_id))


@router.post("/buddy-3d/purchase-background")
def purchase_background(payload: PurchaseBackgroundPayload, user_id: str = Depends(get_current_user_id)):
    return ok(service.purchase_background(user_id, payload.backgroundId or payload.background_id))


@router.get("/buddy/stats")
def buddy_stats(user_id: str = Depends(get_current_user_id)):
    return ok(service.buddy_stats(user_id))


@router.post("/buddy/stats/reward")
def apply_buddy_reward(payload: BuddyRewardApplyPayload, user_id: str = Depends(get_current_user_id)):
    return ok(
        service.apply_buddy_reward(
            user_id,
            activity_type=payload.activityType,
            difficulty=payload.difficulty,
            total_questions=payload.totalQuestions,
            correct_answers=payload.correctAnswers,
            duration_seconds=payload.durationSeconds,
        )
    )

