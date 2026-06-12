from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.core.config import settings
from backend.database.connection import postgres_db


DIFFICULTY_BY_SOURCE_ID = [
    (500, "beginner"),
    (2000, "elementary"),
    (5000, "intermediate"),
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def difficulty_for(source_id: int | None) -> str:
    if source_id is None:
        return "beginner"
    for limit, level in DIFFICULTY_BY_SOURCE_ID:
        if source_id <= limit:
            return level
    return "advanced"


def parse_source_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_dictionary_file(raw_path: str | None) -> Path:
    if raw_path:
        path = Path(raw_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Dictionary file not found: {raw_path}")

    root = Path.cwd()
    candidates = [
        root / "dictionary.json",
        root / "dictionary(1).json",
        root / "backend" / "database" / "data" / "dictionary.json",
        root / "backend" / "database" / "data" / "dictionary(1).json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Dictionary file not found. Pass --file path/to/dictionary.json")


def normalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    source_id = parse_source_id(record.get("id"))
    word = clean(record.get("word"))
    meaning = clean(record.get("meaning"))
    if not word or not meaning:
        return None
    return {
        "source_id": source_id,
        "word": word,
        "type": clean(record.get("type")),
        "meaning": meaning,
        "example": clean(record.get("example")),
        "pronunciation": clean(record.get("pronunciation")),
        "difficulty_level": clean(record.get("difficulty_level")) or difficulty_for(source_id),
    }


def import_dictionary(path: Path) -> dict[str, Any]:
    if not settings.supabase_db_url or postgres_db is None:
        raise RuntimeError("SUPABASE_DB_URL is required to import dictionary data")

    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Dictionary JSON must be an array")

    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0, "errors": []}
    seen_pairs: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            stats["skipped"] += 1
            stats["errors"].append(f"Row {index}: not an object")
            continue

        normalized = normalize_record(record)
        if normalized is None:
            stats["skipped"] += 1
            stats["errors"].append(f"Row {index}: missing word or meaning")
            continue

        pair = (normalized["word"].lower(), normalized["meaning"].lower())
        if pair in seen_pairs:
            stats["skipped"] += 1
            continue
        seen_pairs.add(pair)
        rows.append(normalized)

    if len(rows) <= 500:
        with postgres_db.connect() as connection:
            with connection.cursor() as cursor:
                for row in rows:
                    existing_by_source = None
                    if row["source_id"] is not None:
                        cursor.execute("select id from dictionary_words where source_id = %s", (row["source_id"],))
                        existing_by_source = cursor.fetchone()
                    if existing_by_source:
                        cursor.execute(
                            """
                            update dictionary_words
                            set word = %s,
                                type = %s,
                                meaning = %s,
                                example = %s,
                                pronunciation = %s,
                                difficulty_level = %s,
                                is_active = true,
                                updated_at = now()
                            where source_id = %s
                            """,
                            (row["word"], row["type"], row["meaning"], row["example"], row["pronunciation"], row["difficulty_level"], row["source_id"]),
                        )
                        stats["updated"] += 1
                        continue
                    cursor.execute(
                        """
                        insert into dictionary_words (source_id, word, type, meaning, example, pronunciation, difficulty_level, is_active, created_at, updated_at)
                        values (%s, %s, %s, %s, %s, %s, %s, true, now(), now())
                        on conflict do nothing
                        """,
                        (row["source_id"], row["word"], row["type"], row["meaning"], row["example"], row["pronunciation"], row["difficulty_level"]),
                    )
                    if cursor.rowcount:
                        stats["inserted"] += 1
                    else:
                        stats["skipped"] += 1
            connection.commit()
        return stats

    with postgres_db.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                create temp table tmp_dictionary_words (
                  source_id integer,
                  word text,
                  type text,
                  meaning text,
                  example text,
                  pronunciation text,
                  difficulty_level text
                ) on commit drop
                """
            )
            with cursor.copy(
                """
                copy tmp_dictionary_words (source_id, word, type, meaning, example, pronunciation, difficulty_level)
                from stdin
                """
            ) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            row["source_id"],
                            row["word"],
                            row["type"],
                            row["meaning"],
                            row["example"],
                            row["pronunciation"],
                            row["difficulty_level"],
                        )
                    )

            cursor.execute(
                """
                update dictionary_words target
                set word = source.word,
                    type = source.type,
                    meaning = source.meaning,
                    example = source.example,
                    pronunciation = source.pronunciation,
                    difficulty_level = source.difficulty_level,
                    is_active = true,
                    updated_at = now()
                from tmp_dictionary_words source
                where source.source_id is not null
                  and target.source_id = source.source_id
                """
            )
            stats["updated"] = cursor.rowcount

            cursor.execute(
                """
                insert into dictionary_words (source_id, word, type, meaning, example, pronunciation, difficulty_level, is_active, created_at, updated_at)
                select source.source_id, source.word, source.type, source.meaning, source.example, source.pronunciation, source.difficulty_level, true, now(), now()
                from tmp_dictionary_words source
                left join dictionary_words by_source
                  on source.source_id is not null
                 and by_source.source_id = source.source_id
                where by_source.id is null
                on conflict do nothing
                """
            )
            stats["inserted"] = cursor.rowcount
        connection.commit()

    stats["skipped"] += max(0, len(rows) - stats["updated"] - stats["inserted"])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import dictionary JSON into Supabase Postgres")
    parser.add_argument("--file", dest="file_path", help="Path to dictionary JSON file")
    args = parser.parse_args()

    path = find_dictionary_file(args.file_path)
    stats = import_dictionary(path)
    print(f"Dictionary file: {path}")
    print(f"total={stats['total']}")
    print(f"inserted={stats['inserted']}")
    print(f"updated={stats['updated']}")
    print(f"skipped={stats['skipped']}")
    if stats["errors"]:
        print("errors:")
        for error in stats["errors"][:50]:
            print(f"- {error}")


if __name__ == "__main__":
    main()
