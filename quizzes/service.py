from backend.database.store import store


def list_quizzes() -> list[dict[str, object]]:
    return store.list_quizzes()


def get_quiz(quiz_id: str) -> dict[str, object]:
    return store.get_quiz(quiz_id)


def submit_attempt(user_id: str, quiz_id: str, answers: list[dict[str, str]]) -> dict[str, object]:
    return store.submit_attempt(user_id, quiz_id, answers)


def generate_quiz(user_id: str, count: int, difficulty: str, question_types: list[str]) -> dict[str, object]:
    return store.generate_quiz(user_id, count=count, difficulty=difficulty, question_types=question_types)


def submit_generated_attempt(user_id: str, quiz_id: str, answers: list[dict[str, str]]) -> dict[str, object]:
    return store.submit_generated_attempt(user_id, quiz_id, answers)


def get_attempt(attempt_id: str) -> dict[str, object]:
    return store.format_attempt(attempt_id)
