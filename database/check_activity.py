import argparse

from backend.database.connection import postgres_db


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminate", action="store_true")
    args = parser.parse_args()

    with postgres_db.connect() as conn:
        rows = conn.execute(
            """
            select pid, state, wait_event_type, wait_event, now() - query_start as age, query
            from pg_stat_activity
            where datname = current_database()
              and pid <> pg_backend_pid()
              and state <> 'idle'
            order by query_start nulls last
            """
        ).fetchall()
        print(f"active_sessions={len(rows)}")
        for row in rows:
            print(dict(row))
        if args.terminate:
            for row in rows:
                pid = row["pid"]
                result = conn.execute("select pg_terminate_backend(%s) as terminated", (pid,)).fetchone()
                print(f"terminate pid={pid}: {result['terminated']}")
            conn.commit()


if __name__ == "__main__":
    main()
