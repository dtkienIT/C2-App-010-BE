from backend.database.store import public_user, store


def stats(user_id: str) -> dict[str, object]:
    user = public_user(store.get_user(user_id))
    daily_result = store.get_stats_with_daily_check_in(user_id)
    return {**user, **store.format_stats_for_ui(daily_result["stats"]), "dailyCheckIn": daily_result["dailyCheckIn"]}


def update_profile(user_id: str, patch: dict[str, object]) -> dict[str, object]:
    return public_user(store.update_profile(user_id, patch))

