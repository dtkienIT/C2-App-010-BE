from backend.database.connection import postgres_db, supabase
from backend.database.seed_data import ACHIEVEMENTS, BUDDIES, COMPANION_MODELS, MISSIONS, QUIZZES, ROOM_BACKGROUNDS
from backend.database.store import store


def upsert(table: str, rows: list[dict], key: str = "id") -> None:
    if not rows:
        return
    if supabase is None:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required to seed Supabase")
    supabase.table(table).upsert(rows, on_conflict=key).execute()


def run() -> None:
    if postgres_db is not None:
        store.ensure_catalog_seeded()
        print("Seed completed through SUPABASE_DB_URL")
        return

    upsert(
        "buddies",
        [
            {
                "id": buddy["id"],
                "name": buddy["name"],
                "role": buddy["role"],
                "type": buddy["type"],
                "emoji": buddy["emoji"],
                "gradient": buddy["gradient"],
                "description": buddy["description"],
                "personality": buddy["personality"],
                "avatar_url": buddy["avatar_url"],
                "tags": buddy["tags"],
                "skills": buddy["skills"],
                "accent": buddy["accent"],
                "rarity": buddy["rarity"],
                "default_mood": buddy["default_mood"],
                "is_active": True,
            }
            for buddy in BUDDIES
        ],
    )
    upsert("missions", [{**mission, "is_active": True} for mission in MISSIONS])
    upsert(
        "quizzes",
        [
            {
                "id": quiz["id"],
                "title": quiz["title"],
                "description": quiz["description"],
                "level": quiz["level"],
                "topic": quiz["topic"],
                "reward_xp": quiz["reward_xp"],
                "reward_coins": quiz["reward_coins"],
                "is_active": True,
            }
            for quiz in QUIZZES
        ],
    )
    questions = []
    options = []
    for quiz in QUIZZES:
        for question in quiz["questions"]:
            questions.append(
                {
                    "id": question["id"],
                    "quiz_id": quiz["id"],
                    "question_text": question["question_text"],
                    "explanation": question["explanation"],
                    "order_index": question["order_index"],
                }
            )
            for index, (option_id, option_text, is_correct) in enumerate(question["options"], start=1):
                options.append(
                    {
                        "id": option_id,
                        "question_id": question["id"],
                        "option_text": option_text,
                        "is_correct": is_correct,
                        "order_index": index,
                    }
                )
    upsert("quiz_questions", questions)
    upsert("quiz_options", options)
    upsert("achievements", ACHIEVEMENTS)
    upsert("companion_models", [{**model, "is_active": True} for model in COMPANION_MODELS])
    upsert("room_backgrounds", [{**background, "is_active": True} for background in ROOM_BACKGROUNDS])


if __name__ == "__main__":
    run()
    print("Seed completed")
