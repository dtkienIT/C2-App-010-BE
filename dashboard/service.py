from backend.database.store import store


def get_dashboard(user_id: str) -> dict[str, object]:
    return store.dashboard(user_id)

