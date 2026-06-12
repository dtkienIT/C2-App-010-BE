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


def models() -> list[dict[str, object]]:
    return store.list_models()


def backgrounds() -> list[dict[str, object]]:
    return store.list_backgrounds()


def format_settings(user_id: str, row: dict[str, object]) -> dict[str, object]:
    active_model = next((model for model in COMPANION_MODELS if model["id"] == row.get("equipped_model_id")), None)
    active_background = next((background for background in ROOM_BACKGROUNDS if background["id"] == row.get("room_background_id")), None)
    return {
        **row,
        "activeBuddy": store.active_buddy_from_settings(user_id, row),
        "equippedModel": store.format_model(active_model) if active_model else None,
        "selectedBackground": store.format_background(active_background) if active_background else None,
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
