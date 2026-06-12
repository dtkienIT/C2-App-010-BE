from backend.achievements.service import list_achievements


def list_rewards(user_id: str) -> list[dict[str, object]]:
    return list_achievements(user_id)

