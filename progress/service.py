from backend.database.store import store


def summary(user_id: str) -> dict[str, object]:
    return store.progress_summary(user_id)


def activity(user_id: str) -> dict[str, object]:
    progress = store.progress_summary(user_id)
    return {"weeklyActivity": progress["weeklyActivity"], "topicProgress": progress["topicProgress"]}

