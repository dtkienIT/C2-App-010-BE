from backend.core.config import settings
from backend.database.connection import psycopg


EXPECTED_TABLES = [
    "profiles",
    "user_stats",
    "buddies",
    "user_buddies",
    "companion_models",
    "room_backgrounds",
    "user_companion_settings",
    "missions",
    "user_missions",
    "quizzes",
    "quiz_questions",
    "quiz_options",
    "quiz_attempts",
    "quiz_attempt_answers",
    "achievements",
    "user_achievements",
    "web_push_subscriptions",
    "study_reminders",
    "notification_outbox",
    "notification_deliveries",
    "notification_email_deliveries",
]


def main() -> None:
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL is required")

    with psycopg.connect(settings.supabase_db_url) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = %s
                  and table_name = any(%s)
                order by table_name
                """,
                ("public", EXPECTED_TABLES),
            ).fetchall()
        ]
        profile_columns = [
            row[0]
            for row in conn.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = %s
                  and table_name = %s
                order by ordinal_position
                """,
                ("public", "profiles"),
            ).fetchall()
        ]

    missing_tables = sorted(set(EXPECTED_TABLES) - set(tables))
    print("tables:", tables)
    print("missing_tables:", missing_tables)
    print("profiles_columns:", profile_columns)


if __name__ == "__main__":
    main()
