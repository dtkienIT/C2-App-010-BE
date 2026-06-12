from backend.database.store import store


def list_missions(user_id: str, mission_type: str | None = None) -> list[dict[str, object]]:
    return store.list_missions(user_id, mission_type)


def complete(user_id: str, mission_id: str) -> dict[str, object]:
    return store.complete_mission(user_id, mission_id)


def claim(user_id: str, mission_id: str) -> dict[str, object]:
    return store.claim_mission(user_id, mission_id)

