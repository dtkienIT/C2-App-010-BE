from backend.database.store import public_user, store


def stats(user_id: str) -> dict[str, object]:
    user = public_user(store.get_user(user_id))
    user_stats = store.get_stats(user_id)
    return {**user, **store.format_stats_for_ui(user_stats)}


def update_profile(user_id: str, patch: dict[str, object]) -> dict[str, object]:
    return public_user(store.update_profile(user_id, patch))

