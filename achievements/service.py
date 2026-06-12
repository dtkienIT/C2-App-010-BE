from backend.database.store import store


def list_achievements(user_id: str) -> list[dict[str, object]]:
    return store.list_achievements(user_id)


def claim(user_id: str, achievement_id: str) -> dict[str, object]:
    return store.claim_achievement(user_id, achievement_id)

