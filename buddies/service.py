from fastapi import HTTPException

from backend.database.seed_data import COMPANION_MODELS, ROOM_BACKGROUNDS
from backend.database.store import store


def list_buddies(user_id: str) -> list[dict[str, object]]:
    return store.list_buddies_for_user(user_id)


def active(user_id: str) -> dict[str, object]:
    return store.active_buddy(user_id)


def set_active(user_id: str, buddy_id: str | None) -> dict[str, object]:
    if not buddy_id:
        raise HTTPException(status_code=422, detail="buddyId is required")
    settings = store.set_active_buddy(user_id, buddy_id)
    return store.active_buddy_from_settings(user_id, settings)


def models(user_id: str) -> list[dict[str, object]]:
    return store.list_models(user_id)


def backgrounds(user_id: str) -> list[dict[str, object]]:
    return store.list_backgrounds(user_id)


def format_settings(user_id: str, row: dict[str, object]) -> dict[str, object]:
    active_model = next((model for model in COMPANION_MODELS if model["id"] == row.get("equipped_model_id")), None)
    active_background = next((background for background in ROOM_BACKGROUNDS if background["id"] == row.get("room_background_id")), None)
    unlocked_model_ids = store.get_unlocked_model_ids(user_id)
    unlocked_background_ids = store.get_unlocked_background_ids(user_id)
    return {
        **row,
        "activeBuddy": store.active_buddy_from_settings(user_id, row),
        "equippedModel": store.format_model(active_model, unlocked=active_model["id"] in unlocked_model_ids) if active_model else None,
        "selectedBackground": store.format_background(active_background, unlocked=active_background["id"] in unlocked_background_ids) if active_background else None,
        "userStats": store.format_stats_for_ui(store.get_stats(user_id)),
    }


def settings(user_id: str) -> dict[str, object]:
    return format_settings(user_id, store.get_settings(user_id))


def equip_model(user_id: str, model_id: str | None) -> dict[str, object]:
    if not model_id:
        raise HTTPException(status_code=422, detail="modelId is required")
    return format_settings(user_id, store.equip_model(user_id, model_id))


def select_background(user_id: str, background_id: str | None) -> dict[str, object]:
    if not background_id:
        raise HTTPException(status_code=422, detail="backgroundId is required")
    return format_settings(user_id, store.select_background(user_id, background_id))


def purchase_model(user_id: str, model_id: str | None) -> dict[str, object]:
    if not model_id:
        raise HTTPException(status_code=422, detail="modelId is required")
    return format_settings(user_id, store.purchase_model(user_id, model_id))


def purchase_background(user_id: str, background_id: str | None) -> dict[str, object]:
    if not background_id:
        raise HTTPException(status_code=422, detail="backgroundId is required")
    return format_settings(user_id, store.purchase_background(user_id, background_id))


def buddy_stats(user_id: str) -> dict[str, object]:
    return {
        "activeBuddy": store.active_buddy(user_id),
        "gamification": store.gamification_rules(),
        "userStats": store.format_stats_for_ui(store.get_stats(user_id)),
    }


def apply_buddy_reward(
    user_id: str,
    *,
    activity_type: str,
    difficulty: str | None = None,
    total_questions: int | None = None,
    correct_answers: int | None = None,
    duration_seconds: int | None = None,
) -> dict[str, object]:
    return store.apply_buddy_reward(
        user_id,
        activity_type=activity_type,
        difficulty=difficulty or "beginner",
        total_questions=total_questions or 1,
        correct_answers=correct_answers or 0,
        duration_seconds=duration_seconds,
    )
