from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import random
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from psycopg.errors import UndefinedTable

from backend.core.security import hash_password, verify_password
from backend.database.connection import postgres_db, supabase
from backend.database.seed_data import (
    ACHIEVEMENTS,
    BUDDIES,
    COMPANION_MODELS,
    MISSIONS,
    NEW_USER_STATS,
    QUIZZES,
    ROOM_BACKGROUNDS,
)

STREAK_DAILY_COIN_REWARD = 15


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_utc_date() -> date:
    return datetime.now(timezone.utc).date()


def today_scope() -> str:
    return date.today().isoformat()


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "role": row.get("role", "student"),
        "displayName": row.get("display_name") or row.get("email", "").split("@")[0],
        "display_name": row.get("display_name") or row.get("email", "").split("@")[0],
        "name": row.get("display_name") or row.get("email", "").split("@")[0],
        "avatar": initials(row.get("display_name") or row.get("email", "SL")),
        "avatarUrl": row.get("avatar_url") or "",
        "avatar_url": row.get("avatar_url") or "",
    }


def initials(name: str) -> str:
    parts = [part for part in name.replace(".", " ").replace("_", " ").split(" ") if part]
    value = "".join(part[0].upper() for part in parts[:2])
    return value or "SL"


def next_level_xp(level: int) -> int:
    safe_level = max(0, level)
    return 120 + safe_level * 55


def clamp(value: int, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, value))


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed_datetime = parse_iso_datetime(value)
    if parsed_datetime:
        return parsed_datetime.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def iso_date_string(value: Any) -> str | None:
    parsed = parse_iso_date(value)
    return parsed.isoformat() if parsed else None


def weekday_label(value: date) -> str:
    labels = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    return labels[value.weekday()]


def format_topic_label(value: str | None) -> str:
    if not value:
        return "Chung"
    normalized = re.sub(r"[_\-]+", " ", str(value)).strip()
    if not normalized:
        return "Chung"
    return " ".join(part[:1].upper() + part[1:] for part in normalized.split())


def resolve_level_progress(total_xp: int) -> dict[str, int]:
    safe_total_xp = max(0, int(total_xp))
    level = 0
    xp_into_level = safe_total_xp
    while xp_into_level >= next_level_xp(level):
        xp_into_level -= next_level_xp(level)
        level += 1
    return {
        "level": level,
        "next_level_xp": next_level_xp(level),
        "total_xp": safe_total_xp,
        "xp_into_level": xp_into_level,
    }


def resolve_buddy_mood(joy: int, energy: int, focus: int) -> str:
    if joy >= 90 and focus >= 82:
        return "levelUp"
    if joy >= 72:
        return "happy"
    if energy <= 34:
        return "calm"
    if focus >= 74:
        return "focus"
    return "idle"


def default_buddy_state(buddy: dict[str, Any] | None = None) -> dict[str, Any]:
    base_mood = (buddy or {}).get("mood") or (buddy or {}).get("default_mood") or "focus"
    return {
        "joy": 84,
        "energy": 76,
        "focus": 68,
        "mood": base_mood,
    }


def table_missing_error(error: Exception, table_name: str) -> bool:
    message = str(error).lower()
    return isinstance(error, UndefinedTable) or table_name.lower() in message


def calculate_streak(previous_streak: int, previous_last_active_at: Any, next_last_active_at: Any) -> int:
    next_active_at = parse_iso_datetime(next_last_active_at)
    if not next_active_at:
        return max(0, previous_streak)

    previous_active_at = parse_iso_datetime(previous_last_active_at)
    if not previous_active_at:
        return max(1, previous_streak or 0)

    next_day = next_active_at.date()
    previous_day = previous_active_at.date()
    if next_day == previous_day:
        return max(1, previous_streak or 0)
    if next_day == previous_day + timedelta(days=1):
        return max(1, previous_streak or 0) + 1
    return 1


def resolve_streak_at_reference(previous_streak: int, previous_last_active_at: Any, reference_at: Any) -> int:
    reference = parse_iso_datetime(reference_at)
    if not reference:
        return max(0, previous_streak or 0)

    previous_active_at = parse_iso_datetime(previous_last_active_at)
    if not previous_active_at:
        return 0

    day_delta = (reference.date() - previous_active_at.date()).days
    if day_delta <= 1:
        return max(0, previous_streak or 0)
    return 0


def json_value(value: Any) -> Any:
    if hasattr(value, "as_string"):
        return value.as_string()
    return value


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class AppStore:
    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self._users_by_email: dict[str, str] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        self._user_buddies: dict[str, list[dict[str, Any]]] = {}
        self._buddy_states: dict[str, dict[str, dict[str, Any]]] = {}
        self._unlocked_models: dict[str, set[str]] = {}
        self._unlocked_backgrounds: dict[str, set[str]] = {}
        self._settings: dict[str, dict[str, Any]] = {}
        self._user_missions: dict[str, list[dict[str, Any]]] = {}
        self._attempts: dict[str, dict[str, Any]] = {}
        self._attempt_answers: dict[str, list[dict[str, Any]]] = {}
        self._user_achievements: dict[str, list[dict[str, Any]]] = {}
        self._buddies_cache: list[dict[str, Any]] | None = None
        self._email_verification_otps: list[dict[str, Any]] = []
        self._postgres_table_exists_cache: dict[str, bool] = {}
        self._postgres_column_exists_cache: dict[tuple[str, str], bool] = {}

    @property
    def use_postgres(self) -> bool:
        return postgres_db is not None

    @property
    def use_supabase(self) -> bool:
        return supabase is not None and not self.use_postgres

    def postgres_table_exists(self, table_name: str) -> bool:
        if not self.use_postgres:
            return False
        if table_name in self._postgres_table_exists_cache:
            return self._postgres_table_exists_cache[table_name]

        row = postgres_db.fetch_one(
            """
            select exists (
              select 1
              from information_schema.tables
              where table_schema = 'public' and table_name = %s
            ) as exists
            """,
            (table_name,),
        )
        exists = bool(row["exists"]) if row else False
        self._postgres_table_exists_cache[table_name] = exists
        return exists

    def postgres_column_exists(self, table_name: str, column_name: str) -> bool:
        if not self.use_postgres:
            return False
        cache_key = (table_name, column_name)
        if cache_key in self._postgres_column_exists_cache:
            return self._postgres_column_exists_cache[cache_key]

        row = postgres_db.fetch_one(
            """
            select exists (
              select 1
              from information_schema.columns
              where table_schema = 'public'
                and table_name = %s
                and column_name = %s
            ) as exists
            """,
            (table_name, column_name),
        )
        exists = bool(row["exists"]) if row else False
        self._postgres_column_exists_cache[cache_key] = exists
        return exists

    def _table(self, table: str):
        if not supabase:
            raise RuntimeError("Supabase is not configured")
        return supabase.table(table)

    def register_user(self, email: str, password: str, display_name: str | None = None) -> dict[str, Any]:
        email = email.strip().lower()
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select * from profiles where email = %s", (email,))
                    existing = cursor.fetchone()
                    if existing:
                        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
                    cursor.execute(
                        """
                        insert into profiles (id, email, display_name, avatar_url, role, password_hash, is_email_verified, email_verified_at, status, created_at, updated_at)
                        values (%s::uuid, %s, %s, %s, %s, %s, false, null, 'pending_verification', now(), now())
                        returning *
                        """,
                        (str(uuid4()), email, display_name or email.split("@")[0], "", "student", hash_password(password)),
                    )
                    row = cursor.fetchone()
                    self._ensure_user_defaults_postgres(str(row["id"]), cursor)
                connection.commit()
            row = dict(row)
            row["id"] = str(row["id"])
            return row

        if self.use_supabase:
            existing = self._table("profiles").select("*").eq("email", email).execute().data
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
            row = {
                "id": str(uuid4()),
                "email": email,
                "display_name": display_name or email.split("@")[0],
                "avatar_url": "",
                "role": "student",
                "password_hash": hash_password(password),
                "is_email_verified": False,
                "email_verified_at": None,
                "status": "pending_verification",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
            self._table("profiles").insert(row).execute()
            self._table("user_stats").insert({"user_id": row["id"], **NEW_USER_STATS, "last_active_at": utc_now(), "updated_at": utc_now()}).execute()
            self.ensure_user_defaults(row["id"])
            return row

        if email in self._users_by_email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        row = {
            "id": str(uuid4()),
            "email": email,
            "display_name": display_name or email.split("@")[0],
            "avatar_url": "",
            "role": "student",
            "password_hash": hash_password(password),
            "is_email_verified": False,
            "email_verified_at": None,
            "status": "pending_verification",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._users[row["id"]] = row
        self._users_by_email[email] = row["id"]
        self._stats[row["id"]] = {"user_id": row["id"], **deepcopy(NEW_USER_STATS), "last_active_at": utc_now(), "updated_at": utc_now()}
        self.ensure_user_defaults(row["id"])
        return row

    def authenticate_user(self, email: str, password: str) -> dict[str, Any]:
        if self.use_postgres:
            email = email.strip().lower()
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select * from profiles where email = %s", (email,))
                    user = cursor.fetchone()
                    if not user or not verify_password(password, user.get("password_hash", "")):
                        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
                    user = dict(user)
                    user["id"] = str(user["id"])
                connection.commit()
            return user

        user = self.get_user_by_email(email)
        if not user or not verify_password(password, user.get("password_hash", "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        self.ensure_user_defaults(user["id"])
        return user

    def mark_email_verified(self, user_id: str) -> dict[str, Any]:
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                update profiles
                set is_email_verified = true,
                    email_verified_at = now(),
                    status = 'active',
                    updated_at = now()
                where id = %s::uuid
                returning *
                """,
                (user_id,),
            )
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            row = dict(row)
            row["id"] = str(row["id"])
            return row
        if self.use_supabase:
            fields = {"is_email_verified": True, "email_verified_at": utc_now(), "status": "active", "updated_at": utc_now()}
            self._table("profiles").update(fields).eq("id", user_id).execute()
            return self.get_user(user_id)
        user = self._users[user_id]
        user.update({"is_email_verified": True, "email_verified_at": utc_now(), "status": "active", "updated_at": utc_now()})
        return user

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        email = email.strip().lower()
        if self.use_postgres:
            row = postgres_db.fetch_one("select * from profiles where email = %s", (email,))
            if not row:
                return None
            row = dict(row)
            row["id"] = str(row["id"])
            return row
        if self.use_supabase:
            rows = self._table("profiles").select("*").eq("email", email).execute().data
            return rows[0] if rows else None
        user_id = self._users_by_email.get(email)
        return self._users.get(user_id) if user_id else None

    def get_user_by_verification_session(self, verification_session_id: str) -> dict[str, Any] | None:
        otp = self.get_email_verification_otp(verification_session_id)
        if not otp:
            return None
        return self.get_user(str(otp["user_id"]))

    def invalidate_pending_email_otps(self, user_id: str) -> None:
        if self.use_postgres:
            postgres_db.execute(
                """
                update email_verification_otps
                set used_at = coalesce(used_at, now()), updated_at = now()
                where user_id = %s::uuid and used_at is null
                """,
                (user_id,),
            )
            return
        if self.use_supabase:
            self._table("email_verification_otps").update({"used_at": utc_now(), "updated_at": utc_now()}).eq("user_id", user_id).is_("used_at", "null").execute()
            return
        now = utc_now()
        for otp in self._email_verification_otps:
            if str(otp["user_id"]) == str(user_id) and not otp.get("used_at"):
                otp["used_at"] = now
                otp["updated_at"] = now

    def create_email_verification_otp(self, user_id: str, verification_session_id: str, otp_hash: str, expires_at: datetime) -> dict[str, Any]:
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                insert into email_verification_otps (id, user_id, verification_session_id, otp_hash, expires_at, attempt_count, last_sent_at, created_at, updated_at)
                values (%s::uuid, %s::uuid, %s::uuid, %s, %s, 0, now(), now(), now())
                returning *
                """,
                (str(uuid4()), user_id, verification_session_id, otp_hash, expires_at),
            )
            return dict(row)
        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "verification_session_id": verification_session_id,
            "otp_hash": otp_hash,
            "expires_at": expires_at,
            "attempt_count": 0,
            "used_at": None,
            "locked_at": None,
            "last_sent_at": utc_now(),
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        if self.use_supabase:
            self._table("email_verification_otps").insert(row).execute()
        else:
            self._email_verification_otps.append(row)
        return row

    def get_email_verification_otp(self, verification_session_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            row = postgres_db.fetch_one("select * from email_verification_otps where verification_session_id = %s::uuid", (verification_session_id,))
            return dict(row) if row else None
        if self.use_supabase:
            rows = self._table("email_verification_otps").select("*").eq("verification_session_id", verification_session_id).execute().data
            return rows[0] if rows else None
        return next((otp for otp in self._email_verification_otps if str(otp["verification_session_id"]) == str(verification_session_id)), None)

    def get_latest_email_otp_for_user(self, user_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            row = postgres_db.fetch_one(
                "select * from email_verification_otps where user_id = %s::uuid order by created_at desc limit 1",
                (user_id,),
            )
            return dict(row) if row else None
        if self.use_supabase:
            rows = self._table("email_verification_otps").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute().data
            return rows[0] if rows else None
        rows = [otp for otp in self._email_verification_otps if str(otp["user_id"]) == str(user_id)]
        return max(rows, key=lambda item: parse_datetime(item["created_at"])) if rows else None

    def update_email_verification_otp(self, verification_session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        patch = {**patch, "updated_at": utc_now()}
        if self.use_postgres:
            allowed = ["attempt_count", "used_at", "locked_at", "otp_hash", "expires_at", "last_sent_at"]
            assignments = [f"{key} = %s" for key in allowed if key in patch]
            params = [patch[key] for key in allowed if key in patch]
            if not assignments:
                return self.get_email_verification_otp(verification_session_id)
            row = postgres_db.execute_returning(
                f"""
                update email_verification_otps
                set {', '.join(assignments)}, updated_at = now()
                where verification_session_id = %s::uuid
                returning *
                """,
                (*params, verification_session_id),
            )
            return dict(row) if row else None
        if self.use_supabase:
            self._table("email_verification_otps").update(patch).eq("verification_session_id", verification_session_id).execute()
            return self.get_email_verification_otp(verification_session_id)
        otp = self.get_email_verification_otp(verification_session_id)
        if otp:
            otp.update(patch)
        return otp

    def count_recent_email_otps_for_user(self, user_id: str, since: datetime) -> int:
        if self.use_postgres:
            row = postgres_db.fetch_one("select count(*) as count from email_verification_otps where user_id = %s::uuid and created_at >= %s", (user_id, since))
            return int(row["count"]) if row else 0
        if self.use_supabase:
            rows = self._table("email_verification_otps").select("id").eq("user_id", user_id).gte("created_at", since.isoformat()).execute().data
            return len(rows)
        return sum(1 for otp in self._email_verification_otps if str(otp["user_id"]) == str(user_id) and parse_datetime(otp["created_at"]) >= since)

    def get_user(self, user_id: str) -> dict[str, Any]:
        if self.use_postgres:
            row = postgres_db.fetch_one("select * from profiles where id = %s::uuid", (user_id,))
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            row = dict(row)
            row["id"] = str(row["id"])
            return row
        if self.use_supabase:
            rows = self._table("profiles").select("*").eq("id", user_id).execute().data
            if not rows:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            self.ensure_user_defaults(user_id)
            return rows[0]
        if user_id not in self._users:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        self.ensure_user_defaults(user_id)
        return self._users[user_id]

    def update_profile(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        fields = {
            "display_name": patch.get("displayName") or patch.get("display_name"),
            "avatar_url": patch.get("avatarUrl") or patch.get("avatar_url"),
            "updated_at": utc_now(),
        }
        fields = {key: value for key, value in fields.items() if value is not None}
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                update profiles
                set display_name = coalesce(%s, display_name),
                    avatar_url = coalesce(%s, avatar_url),
                    updated_at = now()
                where id = %s::uuid
                returning *
                """,
                (fields.get("display_name"), fields.get("avatar_url"), user_id),
            )
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            row = dict(row)
            row["id"] = str(row["id"])
            return row
        if self.use_supabase:
            self._table("profiles").update(fields).eq("id", user_id).execute()
            return self.get_user(user_id)
        self._users[user_id].update(fields)
        return self._users[user_id]

    def get_stats(self, user_id: str) -> dict[str, Any]:
        if self.use_postgres:
            self._ensure_user_defaults_postgres(user_id)
            row = postgres_db.fetch_one("select * from user_stats where user_id = %s::uuid", (user_id,))
            if not row:
                raise HTTPException(status_code=404, detail="User stats not found")
            return self.normalize_stats_row(dict(row))
        if self.use_supabase:
            self.ensure_user_defaults(user_id)
            rows = self._table("user_stats").select("*").eq("user_id", user_id).execute().data
            if not rows:
                raise HTTPException(status_code=404, detail="User stats not found")
            return self.normalize_stats_row(rows[0])
        self.ensure_user_defaults(user_id)
        return self.normalize_stats_row(self._stats[user_id])

    def get_stats_with_daily_check_in(self, user_id: str, reference_at: Any | None = None) -> dict[str, Any]:
        daily_result = self.apply_daily_check_in(user_id, reference_at=reference_at)
        return {
            "dailyCheckIn": daily_result["dailyCheckIn"],
            "stats": self.normalize_stats_row(daily_result["stats"]),
        }

    def apply_daily_check_in(self, user_id: str, reference_at: Any | None = None) -> dict[str, Any]:
        reference_dt = parse_iso_datetime(reference_at) or datetime.now(timezone.utc)
        if self.use_postgres:
            has_daily_columns = self.postgres_column_exists("user_stats", "streak_count")
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    self._ensure_user_defaults_postgres(user_id, cursor)
                    cursor.execute("select * from user_stats where user_id = %s::uuid for update", (user_id,))
                    row = cursor.fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail="User stats not found")
                    current = self.normalize_stats_row(dict(row))
                    if not has_daily_columns:
                        result = self._resolve_legacy_daily_check_in(current, reference_dt)
                        cursor.execute(
                            """
                            update user_stats
                            set coins = %s,
                                streak = %s,
                                last_active_at = %s,
                                updated_at = now()
                            where user_id = %s::uuid
                            """,
                            (
                                result["stats"]["coins"],
                                result["stats"]["streak"],
                                result["stats"].get("last_active_at"),
                                user_id,
                            ),
                        )
                        connection.commit()
                        return result
                    result = self._resolve_daily_check_in(current, reference_dt)
                    next_stats = self.normalize_stats_row(result["stats"])
                    cursor.execute(
                        """
                        update user_stats
                        set coins = %s,
                            streak = %s,
                            streak_count = %s,
                            last_streak_date = %s,
                            last_login_reward_date = %s,
                            last_active_at = %s,
                            updated_at = now()
                        where user_id = %s::uuid
                        """,
                        (
                            next_stats["coins"],
                            next_stats["streak"],
                            next_stats["streak_count"],
                            next_stats.get("last_streak_date"),
                            next_stats.get("last_login_reward_date"),
                            next_stats.get("last_active_at"),
                            user_id,
                        ),
                    )
                connection.commit()
            return result
        if self.use_supabase:
            self.ensure_user_defaults(user_id)
            rows = self._table("user_stats").select("*").eq("user_id", user_id).execute().data
            current = self.normalize_stats_row(rows[0]) if rows else self.normalize_stats_row({"user_id": user_id, **deepcopy(NEW_USER_STATS), "last_active_at": utc_now()})
            result = self._resolve_daily_check_in(current, reference_dt)
            self._table("user_stats").update(result["stats"]).eq("user_id", user_id).execute()
            return result
        self.ensure_user_defaults(user_id)
        current = self.normalize_stats_row(self._stats[user_id])
        result = self._resolve_daily_check_in(current, reference_dt)
        self._stats[user_id] = result["stats"]
        return result

    def _resolve_daily_check_in(self, stats: dict[str, Any], reference_dt: datetime) -> dict[str, Any]:
        normalized_stats = self.normalize_stats_row(stats)
        today = reference_dt.date()
        today_iso = today.isoformat()
        last_streak_date = parse_iso_date(normalized_stats.get("last_streak_date"))
        last_reward_date = parse_iso_date(normalized_stats.get("last_login_reward_date"))
        current_streak = max(0, int(normalized_stats.get("streak_count", normalized_stats.get("streak", 0)) or 0))
        already_checked_in_today = last_streak_date == today
        awarded = False
        reward = 0
        next_streak = current_streak

        if already_checked_in_today:
            next_streak = current_streak if current_streak > 0 else 1
        else:
            if last_streak_date == today - timedelta(days=1):
                next_streak = max(1, current_streak) + 1
            else:
                next_streak = 1
            if last_reward_date != today:
                awarded = True
                reward = STREAK_DAILY_COIN_REWARD

        next_stats = self.normalize_stats_row(
            {
                **normalized_stats,
                "coins": int(normalized_stats.get("coins", 0) or 0) + reward,
                "streak": next_streak,
                "streak_count": next_streak,
                "last_streak_date": today_iso if not already_checked_in_today else iso_date_string(normalized_stats.get("last_streak_date")) or today_iso,
                "last_login_reward_date": today_iso if awarded else iso_date_string(normalized_stats.get("last_login_reward_date")),
                "last_active_at": reference_dt.isoformat(),
            },
        )

        return {
            "dailyCheckIn": {
                "alreadyCheckedInToday": already_checked_in_today,
                "awarded": awarded,
                "checkedInDate": today_iso,
                "reward": reward,
                "streakCount": next_streak,
            },
            "stats": next_stats,
        }

    def _resolve_legacy_daily_check_in(self, stats: dict[str, Any], reference_dt: datetime) -> dict[str, Any]:
        normalized_stats = self.normalize_stats_row(stats)
        today = reference_dt.date()
        previous_active_at = parse_iso_datetime(normalized_stats.get("last_active_at"))
        previous_day = previous_active_at.date() if previous_active_at else None
        already_checked_in_today = previous_day == today
        current_streak = max(0, int(normalized_stats.get("streak", 0) or 0))
        reward = 0
        awarded = False

        if already_checked_in_today:
          next_streak = current_streak if current_streak > 0 else 1
        elif previous_day == today - timedelta(days=1):
          next_streak = max(1, current_streak) + 1
          reward = STREAK_DAILY_COIN_REWARD
          awarded = True
        else:
          next_streak = 1
          reward = STREAK_DAILY_COIN_REWARD
          awarded = True

        next_stats = self.normalize_stats_row(
            {
                **normalized_stats,
                "coins": int(normalized_stats.get("coins", 0) or 0) + reward,
                "streak": next_streak,
                "last_active_at": reference_dt.isoformat(),
            },
        )
        return {
            "dailyCheckIn": {
                "alreadyCheckedInToday": already_checked_in_today,
                "awarded": awarded,
                "checkedInDate": today.isoformat(),
                "reward": reward,
                "streakCount": next_streak,
            },
            "stats": next_stats,
        }

    def update_stats(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_stats(user_id)
        next_row = self.normalize_stats_row({**current, **patch, "updated_at": utc_now()})
        if self.use_postgres:
            allowed = {
                "level",
                "xp",
                "coins",
                "streak",
                "total_quizzes",
                "total_correct_answers",
                "total_study_minutes",
                "last_active_at",
            }
            if self.postgres_column_exists("user_stats", "streak_count"):
                allowed.update({"streak_count", "last_streak_date", "last_login_reward_date"})
            assignments = [f"{key} = %s" for key in next_row if key in allowed]
            params = [next_row[key] for key in next_row if key in allowed]
            if assignments:
                postgres_db.execute(
                    f"update user_stats set {', '.join(assignments)}, updated_at = now() where user_id = %s::uuid",
                    (*params, user_id),
                )
            return self.get_stats(user_id)
        if self.use_supabase:
            self._table("user_stats").update(next_row).eq("user_id", user_id).execute()
        else:
            self._stats[user_id] = next_row
        return next_row

    def normalize_stats_row(self, row: dict[str, Any]) -> dict[str, Any]:
        next_row = dict(row)
        next_row["xp"] = max(0, int(next_row.get("xp", 0) or 0))
        next_row["coins"] = max(0, int(next_row.get("coins", 0) or 0))
        streak_count = max(0, int(next_row.get("streak_count", next_row.get("streak", 0)) or 0))
        next_row["streak_count"] = streak_count
        next_row["streak"] = streak_count
        next_row["last_streak_date"] = iso_date_string(next_row.get("last_streak_date"))
        next_row["last_login_reward_date"] = iso_date_string(next_row.get("last_login_reward_date"))
        progress = resolve_level_progress(next_row["xp"])
        next_row["level"] = progress["level"]
        return next_row

    def sync_streak_for_reference(self, user_id: str, stats: dict[str, Any], reference_at: Any | None = None) -> dict[str, Any]:
        resolved_streak = resolve_streak_at_reference(stats.get("streak", 0), stats.get("last_active_at"), reference_at or utc_now())
        if resolved_streak == stats.get("streak", 0):
            return stats

        patch = {"streak": resolved_streak}
        if self.use_postgres:
            postgres_db.execute(
                "update user_stats set streak = %s, updated_at = now() where user_id = %s::uuid",
                (resolved_streak, user_id),
            )
            refreshed = postgres_db.fetch_one("select * from user_stats where user_id = %s::uuid", (user_id,))
            return self.normalize_stats_row(dict(refreshed)) if refreshed else self.normalize_stats_row({**stats, **patch})
        if self.use_supabase:
            self._table("user_stats").update(patch).eq("user_id", user_id).execute()
            return self.normalize_stats_row({**stats, **patch})

        self._stats[user_id] = {**self._stats[user_id], **patch, "updated_at": utc_now()}
        return self.normalize_stats_row(self._stats[user_id])

    def _ensure_user_defaults_postgres(self, user_id: str, cursor: Any) -> None:
        cursor.execute(
            """
            insert into user_stats (user_id, level, xp, coins, streak, total_quizzes, total_correct_answers, total_study_minutes, last_active_at, updated_at)
            values (%s::uuid, %s, %s, %s, %s, %s, %s, %s, now(), now())
            on conflict (user_id) do nothing
            """,
            (
                user_id,
                NEW_USER_STATS["level"],
                NEW_USER_STATS["xp"],
                NEW_USER_STATS["coins"],
                NEW_USER_STATS["streak"],
                NEW_USER_STATS["total_quizzes"],
                NEW_USER_STATS["total_correct_answers"],
                NEW_USER_STATS["total_study_minutes"],
            ),
        )
        cursor.execute(
            """
            insert into user_companion_settings (user_id, active_buddy_id, equipped_model_id, room_background_id, buddy_3d_enabled, updated_at)
            values (%s::uuid, %s, null, %s, false, now())
            on conflict (user_id) do nothing
            """,
            (user_id, "miu", "cozy-night"),
        )
        buddy_rows = [(user_id, buddy["id"], buddy["id"] == "miu", 0, 0) for buddy in BUDDIES]
        if buddy_rows:
            values_sql = ", ".join(["(%s::uuid, %s, %s, %s, %s, now(), now())"] * len(buddy_rows))
            params = tuple(value for row in buddy_rows for value in row)
            cursor.execute(
                f"""
                insert into user_buddies (user_id, buddy_id, is_selected, level, xp, created_at, updated_at)
                values {values_sql}
                on conflict (user_id, buddy_id) do nothing
                """,
                params,
            )
            if self.postgres_table_exists("user_buddy_states"):
                buddy_state_rows = []
                for buddy in BUDDIES:
                    state = default_buddy_state(buddy)
                    buddy_state_rows.append((user_id, buddy["id"], state["joy"], state["energy"], state["focus"], state["mood"]))
                values_sql = ", ".join(["(%s::uuid, %s, %s, %s, %s, %s, now())"] * len(buddy_state_rows))
                params = tuple(value for row in buddy_state_rows for value in row)
                cursor.execute(
                    f"""
                    insert into user_buddy_states (user_id, buddy_id, joy, energy, focus, mood, updated_at)
                    values {values_sql}
                    on conflict (user_id, buddy_id) do nothing
                    """,
                    params,
                )
        if self.postgres_table_exists("user_unlocked_room_backgrounds"):
            cursor.execute(
                """
                insert into user_unlocked_room_backgrounds (user_id, background_id, unlocked_at)
                values (%s::uuid, %s, now())
                on conflict (user_id, background_id) do nothing
                """,
                (user_id, "cozy-night"),
            )

        scope = today_scope()
        cursor.execute("select mission_id, date_scope from user_missions where user_id = %s::uuid", (user_id,))
        existing_keys = {(row["mission_id"], row.get("date_scope")) for row in cursor.fetchall()}
        rows_to_insert = []
        for mission in MISSIONS:
            date_scope = scope if mission["type"] == "daily" else "global"
            if (mission["id"], date_scope) not in existing_keys:
                rows_to_insert.append((str(uuid4()), user_id, mission["id"], date_scope))
        if rows_to_insert:
            values_sql = ", ".join(["(%s::uuid, %s::uuid, %s, 0, false, false, %s, now(), now())"] * len(rows_to_insert))
            params = tuple(value for row in rows_to_insert for value in row)
            cursor.execute(
                f"""
                insert into user_missions (id, user_id, mission_id, progress, is_completed, is_claimed, date_scope, created_at, updated_at)
                values {values_sql}
                on conflict (user_id, mission_id, date_scope) do nothing
                """,
                params,
            )

    def ensure_user_defaults(self, user_id: str) -> None:
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    self._ensure_user_defaults_postgres(user_id, cursor)
                connection.commit()
            return

        if self.use_supabase:
            stats = self._table("user_stats").select("user_id").eq("user_id", user_id).execute().data
            if not stats:
                self._table("user_stats").insert({"user_id": user_id, **NEW_USER_STATS, "last_active_at": utc_now(), "updated_at": utc_now()}).execute()
            settings = self._table("user_companion_settings").select("user_id").eq("user_id", user_id).execute().data
            if not settings:
                self._table("user_companion_settings").insert({
                    "user_id": user_id,
                    "active_buddy_id": "miu",
                    "equipped_model_id": None,
                    "room_background_id": "cozy-night",
                    "buddy_3d_enabled": False,
                    "updated_at": utc_now(),
                }).execute()
            return

        self._stats.setdefault(user_id, {"user_id": user_id, **deepcopy(NEW_USER_STATS), "last_active_at": utc_now(), "updated_at": utc_now()})
        self._settings.setdefault(
            user_id,
            {
                "user_id": user_id,
                "active_buddy_id": "miu",
                "equipped_model_id": None,
                "room_background_id": "cozy-night",
                "buddy_3d_enabled": False,
                "updated_at": utc_now(),
            },
        )
        if user_id not in self._user_buddies:
            self._user_buddies[user_id] = [
                {"id": str(uuid4()), "user_id": user_id, "buddy_id": buddy["id"], "is_selected": buddy["id"] == "miu", "level": 0, "xp": 0, "created_at": utc_now(), "updated_at": utc_now()}
                for buddy in BUDDIES
            ]
        self._buddy_states.setdefault(
            user_id,
            {
                buddy["id"]: {**default_buddy_state(buddy), "user_id": user_id, "buddy_id": buddy["id"], "updated_at": utc_now()}
                for buddy in BUDDIES
            },
        )
        self._unlocked_models.setdefault(user_id, set())
        self._unlocked_backgrounds.setdefault(user_id, set())
        self._user_missions.setdefault(user_id, [])
        self._user_achievements.setdefault(user_id, [])
        self.ensure_mission_rows(user_id)

    def list_buddies(self) -> list[dict[str, Any]]:
        if self.use_postgres:
            if self._buddies_cache is not None:
                return deepcopy(self._buddies_cache)
            rows = postgres_db.fetch_all("select * from buddies where is_active = true order by created_at, id")
            self._buddies_cache = [dict(row) for row in rows] or deepcopy(BUDDIES)
            return deepcopy(self._buddies_cache)
        if self.use_supabase:
            rows = self._table("buddies").select("*").eq("is_active", True).execute().data
            return rows or BUDDIES
        return deepcopy(BUDDIES)

    def get_settings(self, user_id: str) -> dict[str, Any]:
        if self.use_postgres:
            row = postgres_db.fetch_one("select * from user_companion_settings where user_id = %s::uuid", (user_id,))
            if not row:
                self.ensure_user_defaults(user_id)
                row = postgres_db.fetch_one("select * from user_companion_settings where user_id = %s::uuid", (user_id,))
            if not row:
                raise HTTPException(status_code=404, detail="Companion settings not found")
            return dict(row)
        if self.use_supabase:
            rows = self._table("user_companion_settings").select("*").eq("user_id", user_id).execute().data
            return rows[0]
        return self._settings[user_id]

    def update_settings(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if self.use_postgres:
            allowed = {"active_buddy_id", "equipped_model_id", "room_background_id", "buddy_3d_enabled"}
            assignments = [f"{key} = %s" for key in patch if key in allowed]
            params = [patch[key] for key in patch if key in allowed]
            if assignments:
                row = postgres_db.execute_returning(
                    f"update user_companion_settings set {', '.join(assignments)}, updated_at = now() where user_id = %s::uuid returning *",
                    (*params, user_id),
                )
                if row:
                    return dict(row)
            return self.get_settings(user_id)
        current = self.get_settings(user_id)
        next_row = {**current, **patch, "updated_at": utc_now()}
        if self.use_supabase:
            self._table("user_companion_settings").update(next_row).eq("user_id", user_id).execute()
        else:
            self._settings[user_id] = next_row
        return next_row

    def set_active_buddy(self, user_id: str, buddy_id: str) -> dict[str, Any]:
        if not any(buddy["id"] == buddy_id for buddy in self.list_buddies()):
            raise HTTPException(status_code=404, detail="Buddy not found")
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        update user_companion_settings
                        set active_buddy_id = %s,
                            buddy_3d_enabled = false,
                            updated_at = now()
                        where user_id = %s::uuid
                        returning *
                        """,
                        (buddy_id, user_id),
                    )
                    settings = cursor.fetchone()
                    cursor.execute(
                        "update user_buddies set is_selected = (buddy_id = %s), updated_at = now() where user_id = %s::uuid",
                        (buddy_id, user_id),
                    )
                connection.commit()
            return dict(settings)
        settings = self.update_settings(user_id, {"active_buddy_id": buddy_id, "buddy_3d_enabled": False})
        if not self.use_supabase:
            for row in self._user_buddies[user_id]:
                row["is_selected"] = row["buddy_id"] == buddy_id
        return settings

    def active_buddy(self, user_id: str) -> dict[str, Any]:
        settings = self.get_settings(user_id)
        return self.active_buddy_from_settings(user_id, settings)

    def active_buddy_from_settings(self, user_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        buddies = self.list_buddies()
        buddy = next((item for item in buddies if item["id"] == settings.get("active_buddy_id")), buddies[0])
        return self.enrich_buddy(user_id, buddy)

    def get_buddy_state(self, user_id: str, buddy_id: str) -> dict[str, Any]:
        buddy = next((item for item in self.list_buddies() if item["id"] == buddy_id), None)
        fallback = {
            **default_buddy_state(buddy),
            "user_id": user_id,
            "buddy_id": buddy_id,
            "updated_at": utc_now(),
        }
        if self.use_postgres:
            if not self.postgres_table_exists("user_buddy_states"):
                return fallback
            try:
                row = postgres_db.fetch_one(
                    "select * from user_buddy_states where user_id = %s::uuid and buddy_id = %s",
                    (user_id, buddy_id),
                )
            except UndefinedTable:
                self._postgres_table_exists_cache["user_buddy_states"] = False
                return fallback
            return {**fallback, **(dict(row) if row else {})}
        if self.use_supabase:
            rows = self._table("user_buddy_states").select("*").eq("user_id", user_id).eq("buddy_id", buddy_id).execute().data
            return {**fallback, **(rows[0] if rows else {})}
        self.ensure_user_defaults(user_id)
        return {**fallback, **self._buddy_states[user_id].get(buddy_id, {})}

    def update_buddy_state(self, user_id: str, buddy_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_buddy_state(user_id, buddy_id)
        next_row = {
            **current,
            **patch,
            "joy": clamp(int(patch.get("joy", current.get("joy", 84)))),
            "energy": clamp(int(patch.get("energy", current.get("energy", 76)))),
            "focus": clamp(int(patch.get("focus", current.get("focus", 68)))),
            "updated_at": utc_now(),
        }
        next_row["mood"] = patch.get("mood") or resolve_buddy_mood(next_row["joy"], next_row["energy"], next_row["focus"])
        if self.use_postgres:
            if not self.postgres_table_exists("user_buddy_states"):
                return next_row
            try:
                postgres_db.execute(
                    """
                    insert into user_buddy_states (user_id, buddy_id, joy, energy, focus, mood, updated_at)
                    values (%s::uuid, %s, %s, %s, %s, %s, now())
                    on conflict (user_id, buddy_id)
                    do update set
                        joy = excluded.joy,
                        energy = excluded.energy,
                        focus = excluded.focus,
                        mood = excluded.mood,
                        updated_at = now()
                    """,
                    (user_id, buddy_id, next_row["joy"], next_row["energy"], next_row["focus"], next_row["mood"]),
                )
            except UndefinedTable:
                self._postgres_table_exists_cache["user_buddy_states"] = False
                return next_row
            return self.get_buddy_state(user_id, buddy_id)
        if self.use_supabase:
            self._table("user_buddy_states").upsert(next_row).execute()
            return next_row
        self.ensure_user_defaults(user_id)
        self._buddy_states[user_id][buddy_id] = next_row
        return next_row

    def update_buddy_progress(self, user_id: str, buddy_id: str, xp_delta: int) -> dict[str, Any]:
        safe_delta = max(0, int(xp_delta))
        if self.use_postgres:
            postgres_db.execute(
                "update user_buddies set xp = xp + %s, updated_at = now() where user_id = %s::uuid and buddy_id = %s",
                (safe_delta, user_id, buddy_id),
            )
            row = postgres_db.fetch_one(
                "select * from user_buddies where user_id = %s::uuid and buddy_id = %s",
                (user_id, buddy_id),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Buddy progress not found")
            progress = resolve_level_progress(dict(row).get("xp", 0))
            postgres_db.execute(
                "update user_buddies set level = %s, updated_at = now() where user_id = %s::uuid and buddy_id = %s",
                (progress["level"], user_id, buddy_id),
            )
            row = postgres_db.fetch_one(
                "select * from user_buddies where user_id = %s::uuid and buddy_id = %s",
                (user_id, buddy_id),
            )
            return dict(row)
        self.ensure_user_defaults(user_id)
        row = next((item for item in self._user_buddies[user_id] if item["buddy_id"] == buddy_id), None)
        if not row:
            raise HTTPException(status_code=404, detail="Buddy progress not found")
        row["xp"] = max(0, int(row.get("xp", 0) or 0) + safe_delta)
        row["level"] = resolve_level_progress(row["xp"])["level"]
        row["updated_at"] = utc_now()
        return row

    def gamification_rules(self) -> dict[str, Any]:
        return {
            "levels": {
                "baseXp": 120,
                "perLevelStep": 55,
                "formula": "next_level_xp = 120 + (level - 1) * 55",
            },
            "streaks": {
                "sameDay": "Giữ nguyên streak",
                "nextDay": "Tăng streak thêm 1",
                "missedDay": "Reset về 0, đăng nhập lại sẽ bắt đầu từ 1",
            },
            "miniQuizRewards": {
                "beginner": {"joy": 3, "energy": 2, "focus": 1},
                "intermediate": {"joy": 5, "energy": 3, "focus": 3},
                "advanced": {"joy": 8, "energy": 4, "focus": 6},
            },
        }

    def calculate_buddy_reward(
        self,
        *,
        activity_type: str,
        difficulty: str = "beginner",
        total_questions: int = 1,
        correct_answers: int = 0,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        difficulty_key = difficulty if difficulty in {"beginner", "intermediate", "advanced"} else "beginner"
        bases = {
            "beginner": {"joy": 3, "energy": 2, "focus": 1, "buddy_xp": 14},
            "intermediate": {"joy": 5, "energy": 3, "focus": 3, "buddy_xp": 24},
            "advanced": {"joy": 8, "energy": 4, "focus": 6, "buddy_xp": 36},
        }
        if activity_type == "break_return":
            return {
                "joy": 2,
                "energy": 4,
                "focus": 2,
                "buddyXp": 8,
                "message": "Bạn quay lại đúng nhịp nên Buddy hồi năng lượng và vui lên rõ rệt.",
                "source": "break_return",
            }
        base = dict(bases[difficulty_key])
        accuracy = 0 if total_questions <= 0 else correct_answers / total_questions
        question_bonus = max(0, min(total_questions, 3) - 1)
        base["joy"] += question_bonus
        base["focus"] += question_bonus
        base["buddy_xp"] += question_bonus * 6
        if accuracy >= 1:
            base["joy"] += 3
            base["focus"] += 2
            base["buddy_xp"] += 10
        elif accuracy >= 0.67:
            base["joy"] += 2
            base["focus"] += 1
            base["buddy_xp"] += 6
        elif accuracy > 0:
            base["joy"] += 1
            base["buddy_xp"] += 3
        if duration_seconds is not None and duration_seconds <= 90 and accuracy >= 0.67:
            base["joy"] += 1
            base["focus"] += 2
            base["buddy_xp"] += 4
        return {
            "joy": base["joy"],
            "energy": base["energy"],
            "focus": base["focus"],
            "buddyXp": base["buddy_xp"],
            "message": "Buddy vừa nhận được một reward thật từ mini quiz của bạn.",
            "source": "mini_quiz",
        }

    def apply_buddy_reward(
        self,
        user_id: str,
        *,
        activity_type: str,
        difficulty: str = "beginner",
        total_questions: int = 1,
        correct_answers: int = 0,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        settings = self.get_settings(user_id)
        buddy_id = settings.get("active_buddy_id") or "miu"
        current_state = self.get_buddy_state(user_id, buddy_id)
        reward = self.calculate_buddy_reward(
            activity_type=activity_type,
            difficulty=difficulty,
            total_questions=total_questions,
            correct_answers=correct_answers,
            duration_seconds=duration_seconds,
        )
        next_state = self.update_buddy_state(
            user_id,
            buddy_id,
            {
                "joy": current_state["joy"] + reward["joy"],
                "energy": current_state["energy"] + reward["energy"],
                "focus": current_state["focus"] + reward["focus"],
            },
        )
        buddy_progress = self.update_buddy_progress(user_id, buddy_id, reward["buddyXp"])
        updated_stats = self.update_stats(user_id, {"last_active_at": utc_now()})
        active_buddy = self.active_buddy(user_id)
        return {
            "activeBuddy": active_buddy,
            "buddyProgress": {
                "level": buddy_progress.get("level", active_buddy.get("level")),
                "totalXp": buddy_progress.get("xp", active_buddy.get("totalXp", 0)),
            },
            "buddyStats": next_state,
            "gamification": self.gamification_rules(),
            "reward": reward,
            "userStats": self.format_stats_for_ui(updated_stats),
        }

    def list_buddies_for_user(self, user_id: str) -> list[dict[str, Any]]:
        buddies = self.list_buddies()
        if self.use_postgres:
            rows = postgres_db.fetch_all("select * from user_buddies where user_id = %s::uuid", (user_id,))
            by_buddy_id = {row["buddy_id"]: dict(row) for row in rows}
            return [self.enrich_buddy(user_id, buddy, by_buddy_id.get(buddy["id"])) for buddy in buddies]
        return [self.enrich_buddy(user_id, buddy) for buddy in buddies]

    def enrich_buddy(self, user_id: str, buddy: dict[str, Any], user_buddy: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.use_postgres:
            if user_buddy is None:
                user_buddy = postgres_db.fetch_one(
                    "select * from user_buddies where user_id = %s::uuid and buddy_id = %s",
                    (user_id, buddy["id"]),
                )
        elif not self.use_supabase:
            user_buddy = next((row for row in self._user_buddies.get(user_id, []) if row["buddy_id"] == buddy["id"]), None)
        buddy_state = self.get_buddy_state(user_id, buddy["id"])
        buddy_progress = resolve_level_progress((user_buddy or {}).get("xp", 0))
        return {
            **buddy,
            "fallbackImage": buddy.get("fallbackImage") or buddy.get("avatar_url"),
            "mood": buddy_state.get("mood") or buddy.get("mood") or buddy.get("default_mood", "idle"),
            "level": buddy_progress["level"],
            "xp": buddy_progress["xp_into_level"],
            "totalXp": buddy_progress["total_xp"],
            "nextLevelXp": buddy_progress["next_level_xp"],
            "energy": buddy_state.get("energy", 76),
            "focus": buddy_state.get("focus", 68),
            "motivation": buddy_state.get("joy", 84),
            "quote": "Bạn đang tiến bộ tốt, làm thêm một quiz nữa nhé!",
        }
    def list_missions(self, user_id: str, mission_type: str | None = None) -> list[dict[str, Any]]:
        self.ensure_mission_rows(user_id)
        definitions = [mission for mission in MISSIONS if not mission_type or mission["type"] == mission_type]
        user_rows = self._mission_rows(user_id)
        return [self.format_mission(mission, next((row for row in user_rows if row["mission_id"] == mission["id"]), None)) for mission in definitions]

    def _mission_rows(self, user_id: str) -> list[dict[str, Any]]:
        if self.use_postgres:
            return [dict(row) for row in postgres_db.fetch_all("select * from user_missions where user_id = %s::uuid", (user_id,))]
        if self.use_supabase:
            return self._table("user_missions").select("*").eq("user_id", user_id).execute().data
        return self._user_missions[user_id]

    def ensure_mission_rows(self, user_id: str) -> None:
        scope = today_scope()
        if self.use_postgres:
            existing = postgres_db.fetch_all("select mission_id, date_scope from user_missions where user_id = %s::uuid", (user_id,))
            existing_keys = {(row["mission_id"], row.get("date_scope")) for row in existing}
            rows_to_insert = []
            for mission in MISSIONS:
                date_scope = scope if mission["type"] == "daily" else "global"
                if (mission["id"], date_scope) in existing_keys:
                    continue
                rows_to_insert.append((str(uuid4()), user_id, mission["id"], date_scope))
            if rows_to_insert:
                values_sql = ", ".join(["(%s::uuid, %s::uuid, %s, 0, false, false, %s, now(), now())"] * len(rows_to_insert))
                params = tuple(value for row in rows_to_insert for value in row)
                postgres_db.execute(
                    f"""
                    insert into user_missions (id, user_id, mission_id, progress, is_completed, is_claimed, date_scope, created_at, updated_at)
                    values {values_sql}
                    on conflict (user_id, mission_id, date_scope) do nothing
                    """,
                    params,
                )
            return

        if self.use_supabase:
            existing = self._table("user_missions").select("*").eq("user_id", user_id).execute().data
            existing_keys = {(row["mission_id"], row.get("date_scope")) for row in existing}
            rows = []
            for mission in MISSIONS:
                date_scope = scope if mission["type"] == "daily" else "global"
                if (mission["id"], date_scope) not in existing_keys:
                    rows.append({"id": str(uuid4()), "user_id": user_id, "mission_id": mission["id"], "progress": 0, "is_completed": False, "is_claimed": False, "date_scope": date_scope, "created_at": utc_now(), "updated_at": utc_now()})
            if rows:
                self._table("user_missions").insert(rows).execute()
            return

        rows = self._user_missions.setdefault(user_id, [])
        existing_keys = {(row["mission_id"], row.get("date_scope")) for row in rows}
        for mission in MISSIONS:
            date_scope = scope if mission["type"] == "daily" else "global"
            if (mission["id"], date_scope) not in existing_keys:
                rows.append({"id": str(uuid4()), "user_id": user_id, "mission_id": mission["id"], "progress": 0, "is_completed": False, "is_claimed": False, "date_scope": date_scope, "created_at": utc_now(), "updated_at": utc_now()})

    def format_mission(self, mission: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
        progress = row.get("progress", 0) if row else 0
        completed = bool(row.get("is_completed")) if row else False
        return {
            "id": mission["id"],
            "type": mission["type"],
            "title": mission["title"],
            "description": mission["description"],
            "progress": progress,
            "target": mission["target_value"],
            "targetValue": mission["target_value"],
            "rewardXp": mission["reward_xp"],
            "rewardCoins": mission["reward_coins"],
            "reward": f"+{mission['reward_xp']} XP" + (f" · +{mission['reward_coins']} coin" if mission["reward_coins"] else ""),
            "completed": completed,
            "isCompleted": completed,
            "isClaimed": bool(row.get("is_claimed")) if row else False,
        }

    def complete_mission(self, user_id: str, mission_id: str) -> dict[str, Any]:
        mission = self.get_mission_definition(mission_id)
        rows = self._mission_rows(user_id)
        row = next((item for item in rows if item["mission_id"] == mission_id and (mission["type"] != "daily" or item.get("date_scope") == today_scope())), None)
        if not row:
            self.ensure_mission_rows(user_id)
            return self.complete_mission(user_id, mission_id)
        row["progress"] = mission["target_value"]
        row["is_completed"] = True
        row["completed_at"] = utc_now()
        row["updated_at"] = utc_now()
        if self.use_postgres:
            postgres_db.execute(
                "update user_missions set progress = %s, is_completed = true, completed_at = now(), updated_at = now() where id = %s::uuid",
                (row["progress"], row["id"]),
            )
        if self.use_supabase:
            self._table("user_missions").update(row).eq("id", row["id"]).execute()
        return self.format_mission(mission, row)

    def claim_mission(self, user_id: str, mission_id: str) -> dict[str, Any]:
        mission = self.get_mission_definition(mission_id)
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select *
                        from user_missions
                        where user_id = %s::uuid
                          and mission_id = %s
                        order by created_at desc
                        limit 1
                        """,
                        (user_id, mission_id),
                    )
                    row = cursor.fetchone()
                    if not row or not row.get("is_completed"):
                        raise HTTPException(status_code=400, detail="Mission is not completed")
                    if row.get("is_claimed"):
                        raise HTTPException(status_code=409, detail="Mission reward already claimed")
                    cursor.execute(
                        "update user_missions set is_claimed = true, claimed_at = now(), updated_at = now() where id = %s::uuid",
                        (row["id"],),
                    )
                    cursor.execute(
                        """
                        update user_stats
                        set xp = xp + %s,
                            coins = coins + %s,
                            updated_at = now()
                        where user_id = %s::uuid
                        """,
                        (mission["reward_xp"], mission["reward_coins"], user_id),
                    )
                connection.commit()
            row = dict(row)
            row["is_claimed"] = True
            row["claimed_at"] = utc_now()
            row["updated_at"] = utc_now()
            return self.format_mission(mission, row)

        row = next((item for item in self._mission_rows(user_id) if item["mission_id"] == mission_id), None)
        if not row or not row.get("is_completed"):
            raise HTTPException(status_code=400, detail="Mission is not completed")
        if row.get("is_claimed"):
            raise HTTPException(status_code=409, detail="Mission reward already claimed")
        row["is_claimed"] = True
        row["claimed_at"] = utc_now()
        row["updated_at"] = utc_now()
        stats = self.get_stats(user_id)
        self.update_stats(user_id, {"xp": stats["xp"] + mission["reward_xp"], "coins": stats["coins"] + mission["reward_coins"]})
        if self.use_postgres:
            postgres_db.execute(
                "update user_missions set is_claimed = true, claimed_at = now(), updated_at = now() where id = %s::uuid",
                (row["id"],),
            )
        if self.use_supabase:
            self._table("user_missions").update(row).eq("id", row["id"]).execute()
        return self.format_mission(mission, row)

    def get_mission_definition(self, mission_id: str) -> dict[str, Any]:
        mission = next((mission for mission in MISSIONS if mission["id"] == mission_id), None)
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")
        return mission

    def list_quizzes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "generated-vocabulary",
                "title": "Vocabulary Quiz",
                "description": "Practice English vocabulary from dictionary",
                "level": 1,
                "topic": "Vocabulary",
                "rewardXp": 20,
                "rewardCoin": 5,
                "rewardCoins": 5,
            }
        ]

    def get_quiz(self, quiz_id: str) -> dict[str, Any]:
        if not self.use_postgres:
            quiz = next((quiz for quiz in QUIZZES if quiz["id"] == quiz_id), None)
            if not quiz:
                raise HTTPException(status_code=404, detail="Quiz not found")
            return self.format_quiz_detail(quiz)
        raise HTTPException(status_code=400, detail="Use /quizzes/generate to create a dictionary quiz")

    def format_quiz_summary(self, quiz: dict[str, Any]) -> dict[str, Any]:
        return {"id": quiz["id"], "title": quiz["title"], "description": quiz["description"], "level": quiz["level"], "topic": quiz["topic"], "rewardXp": quiz["reward_xp"], "rewardCoin": quiz["reward_coins"], "rewardCoins": quiz["reward_coins"]}

    def format_quiz_detail(self, quiz: dict[str, Any]) -> dict[str, Any]:
        return {
            **self.format_quiz_summary(quiz),
            "questions": [
                {
                    "id": question["id"],
                    "question": question["question_text"],
                    "questionText": question["question_text"],
                    "explanation": question["explanation"],
                    "options": [{"id": option_id, "text": text, "optionText": text} for option_id, text, _is_correct in question["options"]],
                }
                for question in quiz["questions"]
            ],
        }

    def submit_attempt(self, user_id: str, quiz_id: str, answers: list[dict[str, str]]) -> dict[str, Any]:
        if self.use_postgres:
            return self.submit_generated_attempt(user_id, quiz_id, answers)

        quiz = next((quiz for quiz in QUIZZES if quiz["id"] == quiz_id), None)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")
        answer_map = {answer["questionId"]: answer["selectedOptionId"] for answer in answers}
        if len(answer_map) != len(quiz["questions"]):
            raise HTTPException(status_code=400, detail="Please answer all questions before submitting")

        details = []
        correct = 0
        for question in quiz["questions"]:
            selected_id = answer_map.get(question["id"])
            selected = next((option for option in question["options"] if option[0] == selected_id), None)
            if not selected:
                raise HTTPException(status_code=400, detail=f"Invalid option for question {question['id']}")
            correct_option = next(option for option in question["options"] if option[2])
            is_correct = bool(selected[2])
            correct += 1 if is_correct else 0
            details.append({
                "questionId": question["id"],
                "questionText": question["question_text"],
                "selectedOptionId": selected_id,
                "selectedOptionText": selected[1],
                "correctOptionId": correct_option[0],
                "correctOptionText": correct_option[1],
                "isCorrect": is_correct,
                "explanation": question["explanation"],
            })

        total = len(quiz["questions"])
        percentage = round((correct / total) * 100) if total else 0
        earned_xp = quiz["reward_xp"] if percentage >= 70 else max(5, quiz["reward_xp"] // 2)
        earned_coins = quiz["reward_coins"] if percentage >= 70 else 0
        attempt_id = str(uuid4())
        attempt = {
            "id": attempt_id,
            "user_id": user_id,
            "quiz_id": quiz_id,
            "score": correct,
            "total_questions": total,
            "correct_answers": correct,
            "earned_xp": earned_xp,
            "earned_coins": earned_coins,
            "percentage": percentage,
            "created_at": utc_now(),
        }
        self._attempts[attempt_id] = attempt
        self._attempt_answers[attempt_id] = details

        stats = self.get_stats(user_id)
        self.update_stats(user_id, {
            "xp": stats["xp"] + earned_xp,
            "coins": stats["coins"] + earned_coins,
            "total_quizzes": stats.get("total_quizzes", 0) + 1,
            "total_correct_answers": stats.get("total_correct_answers", 0) + correct,
            "last_active_at": utc_now(),
        })
        self.increment_missions(user_id, "quiz_completed", 1)
        self.unlock_achievements(user_id)
        return self.format_attempt(attempt_id)

    def generate_quiz(self, user_id: str, count: int = 10, difficulty: str = "beginner", question_types: list[str] | None = None) -> dict[str, Any]:
        if not self.use_postgres:
            quiz = self.format_quiz_detail(QUIZZES[0])
            quiz["quizId"] = quiz["id"]
            quiz["difficulty"] = difficulty
            quiz["totalQuestions"] = len(quiz.get("questions", []))
            return quiz

        allowed_types = {"meaning", "reverse", "pronunciation", "type", "fill_blank"}
        requested_types = [item for item in (question_types or []) if item in allowed_types] or ["meaning", "reverse"]
        safe_count = max(1, min(count, 50))
        safe_difficulty = difficulty if difficulty in {"beginner", "elementary", "intermediate", "advanced", "mixed"} else "mixed"

        params: list[Any] = []
        where = ["is_active = true"]
        if safe_difficulty != "mixed":
            where.append("difficulty_level = %s")
            params.append(safe_difficulty)
        words = postgres_db.fetch_all(
            f"""
            select *
            from dictionary_words
            where {' and '.join(where)}
            order by random()
            limit %s
            """,
            (*params, safe_count * 4),
        )
        if not words:
            raise HTTPException(status_code=400, detail="Dictionary is empty. Please import dictionary data first.")

        all_words = postgres_db.fetch_all("select * from dictionary_words where is_active = true order by random() limit 500")
        questions: list[dict[str, Any]] = []
        used_word_ids: set[str] = set()
        for word in words:
            if str(word["id"]) in used_word_ids:
                continue
            available_types = self.available_question_types(word, requested_types)
            random.shuffle(available_types)
            for question_type in available_types:
                question = self.build_dictionary_question(word, question_type, all_words)
                if question:
                    used_word_ids.add(str(word["id"]))
                    questions.append(question)
                    break
            if len(questions) >= safe_count:
                break

        if not questions:
            raise HTTPException(status_code=400, detail="Dictionary is empty. Please import dictionary data first.")

        session_id = str(uuid4())
        with postgres_db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into quiz_sessions (id, user_id, title, difficulty, question_types, total_questions, created_at, expires_at)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s, now(), now() + interval '2 hours')
                    """,
                    (session_id, user_id, "Vocabulary Quiz", safe_difficulty, requested_types, len(questions)),
                )
                question_values = []
                question_params: list[Any] = []
                option_values = []
                option_params: list[Any] = []
                for index, question in enumerate(questions, start=1):
                    question_values.append("(%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, now())")
                    question_params.extend(
                        [
                            question["id"],
                            session_id,
                            question["dictionaryWordId"],
                            question["type"],
                            question["questionText"],
                            question["correctAnswerText"],
                            question["explanation"],
                            index,
                        ]
                    )
                    for option_index, option in enumerate(question["options"], start=1):
                        option_values.append("(%s::uuid, %s::uuid, %s, %s, %s, now())")
                        option_params.extend([option["id"], question["id"], option["text"], option["isCorrect"], option_index])
                if question_values:
                    cursor.execute(
                        f"""
                        insert into quiz_session_questions (id, session_id, dictionary_word_id, question_type, question_text, correct_answer_text, explanation, order_index, created_at)
                        values {", ".join(question_values)}
                        """,
                        tuple(question_params),
                    )
                if option_values:
                    cursor.execute(
                        f"""
                        insert into quiz_session_options (id, session_question_id, option_text, is_correct, order_index, created_at)
                        values {", ".join(option_values)}
                        """,
                        tuple(option_params),
                    )
            connection.commit()

        return {
            "id": session_id,
            "quizId": session_id,
            "title": "Vocabulary Quiz",
            "description": "Practice English vocabulary from dictionary",
            "difficulty": safe_difficulty,
            "topic": "Vocabulary",
            "rewardXp": None,
            "rewardCoin": None,
            "rewardCoins": None,
            "totalQuestions": len(questions),
            "questions": [
                {
                    "id": question["id"],
                    "dictionaryWordId": question["dictionaryWordId"],
                    "type": question["type"],
                    "question": question["questionText"],
                    "questionText": question["questionText"],
                    "options": [{"id": option["id"], "text": option["text"], "optionText": option["text"]} for option in question["options"]],
                }
                for question in questions
            ],
        }

    def available_question_types(self, word: dict[str, Any], requested_types: list[str]) -> list[str]:
        available = []
        for question_type in requested_types:
            if question_type == "pronunciation" and not word.get("pronunciation"):
                continue
            if question_type == "type" and not word.get("type"):
                continue
            if question_type == "fill_blank" and not self.example_contains_word(word):
                continue
            available.append(question_type)
        return available

    def example_contains_word(self, word: dict[str, Any]) -> bool:
        example = str(word.get("example") or "")
        value = str(word.get("word") or "")
        if not example or not value:
            return False
        return re.search(rf"\b{re.escape(value)}\b", example, flags=re.IGNORECASE) is not None

    def build_dictionary_question(self, word: dict[str, Any], question_type: str, all_words: list[dict[str, Any]]) -> dict[str, Any] | None:
        correct = self.correct_answer_for(word, question_type)
        if not correct:
            return None
        distractors = self.dictionary_distractors(word, question_type, correct, all_words)
        if len(distractors) < 3:
            return None
        options = [{"id": str(uuid4()), "text": correct, "isCorrect": True}]
        options.extend({"id": str(uuid4()), "text": item, "isCorrect": False} for item in distractors[:3])
        random.shuffle(options)
        return {
            "id": str(uuid4()),
            "dictionaryWordId": str(word["id"]),
            "type": question_type,
            "questionText": self.question_text_for(word, question_type),
            "correctAnswerText": correct,
            "explanation": self.explanation_for(word, question_type),
            "options": options,
        }

    def correct_answer_for(self, word: dict[str, Any], question_type: str) -> str:
        if question_type == "meaning":
            return str(word.get("meaning") or "").strip()
        if question_type in {"reverse", "fill_blank"}:
            return str(word.get("word") or "").strip()
        if question_type == "pronunciation":
            return str(word.get("pronunciation") or "").strip()
        if question_type == "type":
            return str(word.get("type") or "").strip()
        return ""

    def question_text_for(self, word: dict[str, Any], question_type: str) -> str:
        if question_type == "meaning":
            return f'What does "{word["word"]}" mean?'
        if question_type == "reverse":
            return f'Which word means "{word["meaning"]}"?'
        if question_type == "pronunciation":
            return f'What is the pronunciation of "{word["word"]}"?'
        if question_type == "type":
            return f'What type of word is "{word["word"]}"?'
        if question_type == "fill_blank":
            blanked = re.sub(rf"\b{re.escape(str(word['word']))}\b", "_____", str(word.get("example") or ""), count=1, flags=re.IGNORECASE)
            return f"Complete the sentence: {blanked}"
        return str(word["word"])

    def explanation_for(self, word: dict[str, Any], question_type: str) -> str:
        if question_type == "meaning":
            return f'{word["word"]} means {word["meaning"]}.'
        if question_type == "reverse":
            return f'{word["meaning"]} means {word["word"]}.'
        if question_type == "pronunciation":
            return f'The pronunciation of {word["word"]} is {word["pronunciation"]}.'
        if question_type == "type":
            return f'{word["word"]} is marked as {word["type"]}.'
        if question_type == "fill_blank":
            return f'The missing word is {word["word"]}.'
        return ""

    def dictionary_distractors(self, word: dict[str, Any], question_type: str, correct: str, all_words: list[dict[str, Any]]) -> list[str]:
        preferred = [
            item
            for item in all_words
            if str(item["id"]) != str(word["id"])
            and (item.get("type") == word.get("type") or item.get("difficulty_level") == word.get("difficulty_level"))
        ]
        fallback = [item for item in all_words if str(item["id"]) != str(word["id"])]
        choices: list[str] = []
        for pool in (preferred, fallback):
            random.shuffle(pool)
            for item in pool:
                value = self.correct_answer_for(item, question_type)
                if value and value != correct and value not in choices:
                    choices.append(value)
                if len(choices) >= 3:
                    return choices
        return choices

    def submit_generated_attempt(self, user_id: str, quiz_id: str, answers: list[dict[str, str]]) -> dict[str, Any]:
        answer_map = {answer["questionId"]: answer["selectedOptionId"] for answer in answers}
        details = []
        correct_count = 0

        with postgres_db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select * from quiz_sessions where id = %s::uuid and user_id = %s::uuid", (quiz_id, user_id))
                session = cursor.fetchone()
                if not session:
                    raise HTTPException(status_code=404, detail="Quiz session not found")
                cursor.execute(
                    """
                    select
                      q.id as question_id,
                      q.question_text,
                      q.explanation,
                      q.order_index,
                      o.id as option_id,
                      o.option_text,
                      o.is_correct,
                      o.order_index as option_order_index
                    from quiz_session_questions q
                    join quiz_session_options o on o.session_question_id = q.id
                    where q.session_id = %s::uuid
                    order by q.order_index, o.order_index
                    """,
                    (quiz_id,),
                )
                option_rows = [dict(row) for row in cursor.fetchall()]
                questions: dict[str, dict[str, Any]] = {}
                for row in option_rows:
                    question_id = str(row["question_id"])
                    questions.setdefault(
                        question_id,
                        {
                            "id": question_id,
                            "question_text": row["question_text"],
                            "explanation": row.get("explanation") or "",
                            "order_index": row["order_index"],
                            "options": [],
                        },
                    )["options"].append(row)
                if len(answer_map) != len(questions):
                    raise HTTPException(status_code=400, detail="Please answer all questions before submitting")

                for question in questions:
                    question_row = questions[question]
                    selected_id = answer_map.get(question)
                    options = question_row["options"]
                    selected = next((option for option in options if str(option["option_id"]) == selected_id), None)
                    correct_option = next((option for option in options if option["is_correct"]), None)
                    if not selected or not correct_option:
                        raise HTTPException(status_code=400, detail=f"Invalid answer for question {question}")
                    is_correct = bool(selected["is_correct"])
                    correct_count += 1 if is_correct else 0
                    details.append(
                        {
                            "questionId": question,
                            "questionText": question_row["question_text"],
                            "selectedOptionId": str(selected["option_id"]),
                            "selectedOptionText": selected["option_text"],
                            "selectedAnswer": selected["option_text"],
                            "correctOptionId": str(correct_option["option_id"]),
                            "correctOptionText": correct_option["option_text"],
                            "correctAnswer": correct_option["option_text"],
                            "isCorrect": is_correct,
                            "explanation": question_row.get("explanation") or "",
                        }
                    )

                total = len(questions)
                percentage = round((correct_count / total) * 100) if total else 0
                earned_xp = correct_count * 2 + (5 if percentage == 100 else 0)
                earned_coins = correct_count // 2 + (2 if percentage == 100 else 0)
                attempt_id = str(uuid4())
                cursor.execute(
                    """
                    insert into quiz_attempts (id, user_id, quiz_id, score, total_questions, correct_answers, earned_xp, earned_coins, percentage, created_at)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (attempt_id, user_id, quiz_id, correct_count, total, correct_count, earned_xp, earned_coins, percentage),
                )
                if details:
                    values_sql = ", ".join(["(%s::uuid, %s, %s, %s, now())"] * len(details))
                    params = tuple(
                        value
                        for detail in details
                        for value in (attempt_id, detail["questionId"], detail["selectedOptionId"], detail["isCorrect"])
                    )
                    cursor.execute(
                        f"""
                        insert into quiz_attempt_answers (attempt_id, question_id, selected_option_id, is_correct, created_at)
                        values {values_sql}
                        """,
                        params,
                    )
                cursor.execute(
                    """
                    update user_stats
                    set xp = xp + %s,
                        coins = coins + %s,
                        total_quizzes = total_quizzes + 1,
                        total_correct_answers = total_correct_answers + %s,
                        last_active_at = now(),
                        updated_at = now()
                    where user_id = %s::uuid
                    """,
                    (earned_xp, earned_coins, correct_count, user_id),
                )
                cursor.execute(
                    """
                    update user_missions row
                    set progress = least(mission.target_value, row.progress + 1),
                        is_completed = least(mission.target_value, row.progress + 1) >= mission.target_value,
                        completed_at = case
                            when least(mission.target_value, row.progress + 1) >= mission.target_value and row.completed_at is null
                            then now()
                            else row.completed_at
                        end,
                        updated_at = now()
                    from missions mission
                    where row.mission_id = mission.id
                      and row.user_id = %s::uuid
                      and mission.target_type = %s
                      and row.is_completed = false
                    """,
                    (user_id, "quiz_completed"),
                )
            connection.commit()

        self.update_stats(user_id, {"last_active_at": utc_now()})
        return {
            "id": attempt_id,
            "attemptId": attempt_id,
            "quizId": quiz_id,
            "score": correct_count,
            "totalQuestions": total,
            "correctAnswers": correct_count,
            "earnedXp": earned_xp,
            "earnedCoins": earned_coins,
            "percentage": percentage,
            "answers": details,
            "createdAt": utc_now(),
        }

    def format_attempt(self, attempt_id: str) -> dict[str, Any]:
        if self.use_postgres:
            attempt = postgres_db.fetch_one("select * from quiz_attempts where id = %s::uuid", (attempt_id,))
            if not attempt:
                raise HTTPException(status_code=404, detail="Quiz attempt not found")
            rows = postgres_db.fetch_all(
                """
                select
                  q.id as question_id,
                  q.question_text,
                  q.explanation,
                  selected.id as selected_option_id,
                  selected.option_text as selected_option_text,
                  correct.id as correct_option_id,
                  correct.option_text as correct_option_text,
                  a.is_correct
                from quiz_attempt_answers a
                join quiz_session_questions q on q.id = a.question_id::uuid
                join quiz_session_options selected on selected.id = a.selected_option_id::uuid
                join quiz_session_options correct on correct.session_question_id = q.id and correct.is_correct = true
                where a.attempt_id = %s::uuid
                order by q.order_index
                """,
                (attempt_id,),
            )
            return {
                "id": str(attempt["id"]),
                "attemptId": str(attempt["id"]),
                "quizId": attempt["quiz_id"],
                "score": attempt["score"],
                "totalQuestions": attempt["total_questions"],
                "correctAnswers": attempt["correct_answers"],
                "earnedXp": attempt["earned_xp"],
                "earnedCoins": attempt["earned_coins"],
                "percentage": attempt["percentage"],
                "answers": [
                    {
                        "questionId": str(row["question_id"]),
                        "questionText": row["question_text"],
                        "selectedOptionId": str(row["selected_option_id"]),
                        "selectedOptionText": row["selected_option_text"],
                        "selectedAnswer": row["selected_option_text"],
                        "correctOptionId": str(row["correct_option_id"]),
                        "correctOptionText": row["correct_option_text"],
                        "correctAnswer": row["correct_option_text"],
                        "isCorrect": row["is_correct"],
                        "explanation": row.get("explanation") or "",
                    }
                    for row in rows
                ],
                "createdAt": attempt["created_at"],
            }

        attempt = self._attempts.get(attempt_id)
        if not attempt:
            raise HTTPException(status_code=404, detail="Quiz attempt not found")
        return {
            "id": attempt["id"],
            "attemptId": attempt["id"],
            "quizId": attempt["quiz_id"],
            "score": attempt["score"],
            "totalQuestions": attempt["total_questions"],
            "correctAnswers": attempt["correct_answers"],
            "earnedXp": attempt["earned_xp"],
            "earnedCoins": attempt["earned_coins"],
            "percentage": attempt["percentage"],
            "answers": self._attempt_answers.get(attempt_id, []),
            "createdAt": attempt["created_at"],
        }

    def increment_missions(self, user_id: str, target_type: str, amount: int) -> None:
        self.ensure_mission_rows(user_id)
        rows = self._mission_rows(user_id)
        for mission in MISSIONS:
            if mission["target_type"] != target_type:
                continue
            row = next((item for item in rows if item["mission_id"] == mission["id"]), None)
            if not row or row.get("is_completed"):
                continue
            row["progress"] = min(mission["target_value"], row.get("progress", 0) + amount)
            row["is_completed"] = row["progress"] >= mission["target_value"]
            row["completed_at"] = utc_now() if row["is_completed"] else None
            row["updated_at"] = utc_now()

    def unlock_achievements(self, user_id: str) -> None:
        stats = self.get_stats(user_id)
        unlocked = self._user_achievements.setdefault(user_id, [])
        unlocked_ids = {row["achievement_id"] for row in unlocked}
        for achievement in ACHIEVEMENTS:
            if achievement["id"] in unlocked_ids:
                continue
            condition_type = achievement["condition_type"]
            value = stats.get("total_quizzes" if condition_type == "quiz_completed" else "streak", 0)
            if value >= achievement["condition_value"]:
                unlocked.append({"id": str(uuid4()), "user_id": user_id, "achievement_id": achievement["id"], "unlocked_at": utc_now(), "is_claimed": False, "claimed_at": None})

    def list_achievements(self, user_id: str) -> list[dict[str, Any]]:
        self.unlock_achievements(user_id)
        user_rows = self._user_achievements.setdefault(user_id, [])
        return [self.format_achievement(item, next((row for row in user_rows if row["achievement_id"] == item["id"]), None)) for item in ACHIEVEMENTS]

    def format_achievement(self, achievement: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "id": achievement["id"],
            "name": achievement["title"],
            "title": achievement["title"],
            "description": achievement["description"],
            "icon": achievement["icon"],
            "type": "badge",
            "rewardXp": achievement["reward_xp"],
            "rewardCoins": achievement["reward_coins"],
            "unlocked": bool(row),
            "isClaimed": bool(row and row.get("is_claimed")),
            "unlockedAt": row.get("unlocked_at") if row else None,
        }

    def claim_achievement(self, user_id: str, achievement_id: str) -> dict[str, Any]:
        achievement = next((item for item in ACHIEVEMENTS if item["id"] == achievement_id), None)
        if not achievement:
            raise HTTPException(status_code=404, detail="Achievement not found")
        self.unlock_achievements(user_id)
        row = next((item for item in self._user_achievements[user_id] if item["achievement_id"] == achievement_id), None)
        if not row:
            raise HTTPException(status_code=400, detail="Achievement is locked")
        if row.get("is_claimed"):
            raise HTTPException(status_code=409, detail="Achievement already claimed")
        row["is_claimed"] = True
        row["claimed_at"] = utc_now()
        stats = self.get_stats(user_id)
        self.update_stats(user_id, {"xp": stats["xp"] + achievement["reward_xp"], "coins": stats["coins"] + achievement["reward_coins"]})
        return self.format_achievement(achievement, row)

    def get_unlocked_model_ids(self, user_id: str) -> set[str]:
        self.ensure_user_defaults(user_id)
        if self.use_postgres:
            if not self.postgres_table_exists("user_unlocked_companion_models"):
                return set()
            try:
                rows = postgres_db.fetch_all(
                    "select model_id from user_unlocked_companion_models where user_id = %s::uuid",
                    (user_id,),
                )
                return {row["model_id"] for row in rows}
            except Exception as error:
                if table_missing_error(error, "user_unlocked_companion_models"):
                    self._postgres_table_exists_cache["user_unlocked_companion_models"] = False
                    return set()
                raise
        if self.use_supabase:
            rows = self._table("user_unlocked_companion_models").select("model_id").eq("user_id", user_id).execute().data
            return {row["model_id"] for row in rows}
        return set(self._unlocked_models.get(user_id, set()))

    def get_unlocked_background_ids(self, user_id: str) -> set[str]:
        self.ensure_user_defaults(user_id)
        if self.use_postgres:
            if not self.postgres_table_exists("user_unlocked_room_backgrounds"):
                return {"cozy-night"}
            try:
                rows = postgres_db.fetch_all(
                    "select background_id from user_unlocked_room_backgrounds where user_id = %s::uuid",
                    (user_id,),
                )
                unlocked_ids = {row["background_id"] for row in rows}
                unlocked_ids.add("cozy-night")
                return unlocked_ids
            except Exception as error:
                if table_missing_error(error, "user_unlocked_room_backgrounds"):
                    self._postgres_table_exists_cache["user_unlocked_room_backgrounds"] = False
                    return {"cozy-night"}
                raise
        if self.use_supabase:
            rows = self._table("user_unlocked_room_backgrounds").select("background_id").eq("user_id", user_id).execute().data
            return {row["background_id"] for row in rows}
        return set(self._unlocked_backgrounds.get(user_id, set()))

    def list_models(self, user_id: str) -> list[dict[str, Any]]:
        unlocked_ids = self.get_unlocked_model_ids(user_id)
        return [self.format_model(row, unlocked=row["id"] in unlocked_ids) for row in COMPANION_MODELS if row.get("source") == "shop"]

    def list_backgrounds(self, user_id: str) -> list[dict[str, Any]]:
        unlocked_ids = self.get_unlocked_background_ids(user_id)
        return [self.format_background(row, unlocked=row["id"] in unlocked_ids) for row in ROOM_BACKGROUNDS]

    def format_model(self, row: dict[str, Any], *, unlocked: bool = True) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "shopName": row["name"],
            "achievementName": row["name"],
            "description": row["description"],
            "rewardLabel": "Mở khóa từ cửa hàng",
            "type": "vrm",
            "price": row["price"],
            "source": row.get("source", "shop"),
            "unlocked": unlocked,
            "vrmUrl": row["model_url"],
            "modelUrl": row["model_url"],
            "actions": row.get("actions", []),
            "accent": row.get("accent", "cyan"),
        }

    def format_background(self, row: dict[str, Any], *, unlocked: bool = True) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row.get("description", ""),
            "imageUrl": row["image_url"],
            "thumbnailUrl": row["thumbnail_url"],
            "price": row["price"],
            "accent": row.get("accent", "cyan"),
            "unlocked": unlocked,
        }

    def equip_model(self, user_id: str, model_id: str) -> dict[str, Any]:
        model = next((item for item in COMPANION_MODELS if item["id"] == model_id), None)
        if not model:
            raise HTTPException(status_code=404, detail="3D model not found")
        if model_id not in self.get_unlocked_model_ids(user_id):
            raise HTTPException(status_code=403, detail="3D model is locked")
        return self.update_settings(user_id, {"equipped_model_id": model_id, "buddy_3d_enabled": True})

    def select_background(self, user_id: str, background_id: str) -> dict[str, Any]:
        background = next((item for item in ROOM_BACKGROUNDS if item["id"] == background_id), None)
        if not background:
            raise HTTPException(status_code=404, detail="Room background not found")
        if background_id not in self.get_unlocked_background_ids(user_id):
            raise HTTPException(status_code=403, detail="Room background is locked")
        return self.update_settings(user_id, {"room_background_id": background_id})

    def purchase_model(self, user_id: str, model_id: str) -> dict[str, Any]:
        model = next((item for item in COMPANION_MODELS if item["id"] == model_id and item.get("source") == "shop"), None)
        if not model:
            raise HTTPException(status_code=404, detail="3D model not found")
        unlocked_ids = self.get_unlocked_model_ids(user_id)
        if model_id in unlocked_ids:
            return self.get_settings(user_id)

        stats = self.get_stats(user_id)
        cost = int(model.get("price", 0) or 0)
        if stats["coins"] < cost:
            raise HTTPException(status_code=400, detail="Not enough coins")

        if self.use_postgres:
            if not self.postgres_table_exists("user_unlocked_companion_models"):
                raise HTTPException(status_code=503, detail="3D model unlocks are unavailable until the shop schema is installed")
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into user_unlocked_companion_models (user_id, model_id, unlocked_at)
                        values (%s::uuid, %s, now())
                        on conflict (user_id, model_id) do nothing
                        """,
                        (user_id, model_id),
                    )
                    cursor.execute(
                        """
                        update user_stats
                        set coins = greatest(0, coins - %s),
                            updated_at = now()
                        where user_id = %s::uuid
                        """,
                        (cost, user_id),
                    )
                connection.commit()
            from backend.notifications.service import create_unlock_notification

            create_unlock_notification(
                user_id,
                item_name=str(model.get("name") or model_id),
                item_kind="model",
                cost=cost,
                target_url="/buddy-3d",
                image_url=model.get("thumbnail_url"),
            )
            return self.get_settings(user_id)

        if self.use_supabase:
            self._table("user_unlocked_companion_models").insert({"user_id": user_id, "model_id": model_id, "unlocked_at": utc_now()}).execute()
        else:
            self._unlocked_models.setdefault(user_id, set()).add(model_id)
        self.update_stats(user_id, {"coins": stats["coins"] - cost})
        from backend.notifications.service import create_unlock_notification

        create_unlock_notification(
            user_id,
            item_name=str(model.get("name") or model_id),
            item_kind="model",
            cost=cost,
            target_url="/buddy-3d",
            image_url=model.get("thumbnail_url"),
        )
        return self.get_settings(user_id)

    def purchase_background(self, user_id: str, background_id: str) -> dict[str, Any]:
        background = next((item for item in ROOM_BACKGROUNDS if item["id"] == background_id), None)
        if not background:
            raise HTTPException(status_code=404, detail="Room background not found")
        unlocked_ids = self.get_unlocked_background_ids(user_id)
        if background_id in unlocked_ids:
            return self.get_settings(user_id)

        stats = self.get_stats(user_id)
        cost = int(background.get("price", 0) or 0)
        if stats["coins"] < cost:
            raise HTTPException(status_code=400, detail="Not enough coins")

        if self.use_postgres:
            if not self.postgres_table_exists("user_unlocked_room_backgrounds"):
                raise HTTPException(status_code=503, detail="Room background unlocks are unavailable until the shop schema is installed")
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into user_unlocked_room_backgrounds (user_id, background_id, unlocked_at)
                        values (%s::uuid, %s, now())
                        on conflict (user_id, background_id) do nothing
                        """,
                        (user_id, background_id),
                    )
                    cursor.execute(
                        """
                        update user_stats
                        set coins = greatest(0, coins - %s),
                            updated_at = now()
                        where user_id = %s::uuid
                        """,
                        (cost, user_id),
                    )
                connection.commit()
            from backend.notifications.service import create_unlock_notification

            create_unlock_notification(
                user_id,
                item_name=str(background.get("name") or background_id),
                item_kind="background",
                cost=cost,
                target_url="/buddy-room",
                image_url=background.get("thumbnail_url") or background.get("image_url"),
            )
            return self.get_settings(user_id)

        if self.use_supabase:
            self._table("user_unlocked_room_backgrounds").insert({"user_id": user_id, "background_id": background_id, "unlocked_at": utc_now()}).execute()
        else:
            self._unlocked_backgrounds.setdefault(user_id, set()).add(background_id)
        self.update_stats(user_id, {"coins": stats["coins"] - cost})
        from backend.notifications.service import create_unlock_notification

        create_unlock_notification(
            user_id,
            item_name=str(background.get("name") or background_id),
            item_kind="background",
            cost=cost,
            target_url="/buddy-room",
            image_url=background.get("thumbnail_url") or background.get("image_url"),
        )
        return self.get_settings(user_id)

    def progress_summary(self, user_id: str) -> dict[str, Any]:
        stats = self.get_stats(user_id)
        return self.progress_summary_from_stats(stats, user_id)

    def build_weekly_xp_activity(self, user_id: str) -> tuple[list[int], list[str]]:
        today = date.today()
        days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        day_index = {day.isoformat(): index for index, day in enumerate(days)}
        xp7days = [0] * len(days)

        if self.use_postgres:
            rows = postgres_db.fetch_all(
                """
                select earned_xp, created_at
                from quiz_attempts
                where user_id = %s::uuid
                  and created_at >= %s
                order by created_at asc
                """,
                (user_id, datetime.combine(days[0], datetime.min.time(), tzinfo=timezone.utc)),
            )
            attempts = [dict(row) for row in rows]
        else:
            attempts = [
                attempt
                for attempt in self._attempts.values()
                if str(attempt.get("user_id")) == str(user_id)
            ]

        for attempt in attempts:
            created_at = parse_iso_datetime(attempt.get("created_at"))
            if not created_at:
                continue
            day_key = created_at.date().isoformat()
            if day_key not in day_index:
                continue
            xp7days[day_index[day_key]] += max(0, int(attempt.get("earned_xp", 0) or 0))

        return xp7days, [weekday_label(day) for day in days]

    def build_topic_progress(self, user_id: str) -> list[dict[str, Any]]:
        if self.use_postgres:
            rows = postgres_db.fetch_all(
                """
                select
                  coalesce(nullif(dw.type, ''), nullif(q.question_type, ''), 'general') as raw_topic,
                  count(*) as total_answers,
                  sum(case when a.is_correct then 1 else 0 end) as correct_answers
                from quiz_attempt_answers a
                join quiz_attempts attempt on attempt.id = a.attempt_id::uuid
                join quiz_session_questions q on q.id = a.question_id::uuid
                left join dictionary_words dw on dw.id = q.dictionary_word_id
                where attempt.user_id = %s::uuid
                group by raw_topic
                order by total_answers desc, raw_topic asc
                """,
                (user_id,),
            )
            topic_rows = [dict(row) for row in rows]
        else:
            question_topic_map: dict[str, str] = {}
            for quiz in QUIZZES:
                for question in quiz.get("questions", []):
                    question_topic_map[str(question.get("id"))] = str(quiz.get("topic") or "general")

            totals: dict[str, dict[str, int]] = {}
            for attempt_id, answers in self._attempt_answers.items():
                attempt = self._attempts.get(attempt_id)
                if not attempt or str(attempt.get("user_id")) != str(user_id):
                    continue
                for answer in answers:
                    raw_topic = question_topic_map.get(str(answer.get("questionId")), "general")
                    bucket = totals.setdefault(raw_topic, {"correct_answers": 0, "total_answers": 0})
                    bucket["total_answers"] += 1
                    bucket["correct_answers"] += 1 if answer.get("isCorrect") else 0

            topic_rows = [
                {"raw_topic": topic, **values}
                for topic, values in sorted(totals.items(), key=lambda item: (-item[1]["total_answers"], item[0]))
            ]

        topic_progress: list[dict[str, Any]] = []
        for row in topic_rows:
            total_answers = int(row.get("total_answers", 0) or 0)
            if total_answers <= 0:
                continue
            correct_answers = int(row.get("correct_answers", 0) or 0)
            topic_progress.append(
                {
                    "topic": format_topic_label(str(row.get("raw_topic") or "general")),
                    "score": round((correct_answers / total_answers) * 100),
                    "correctAnswers": correct_answers,
                    "totalAnswers": total_answers,
                }
            )

        return topic_progress

    def build_ai_roadmap(
        self,
        stats: dict[str, Any],
        xp7days: list[int],
        topic_progress: list[dict[str, Any]],
        weak_topics: list[str],
    ) -> list[str]:
        accuracy = round((stats.get("total_correct_answers", 0) / max(1, stats.get("total_quizzes", 0) * 3)) * 100)
        total_study_minutes = int(stats.get("total_study_minutes", 0) or 0)
        current_streak = int(stats.get("streak", 0) or 0)
        roadmap: list[str] = []

        if stats.get("total_quizzes", 0) <= 0:
            roadmap.append("Làm 1 quiz đầu tiên để hệ thống bắt đầu phân tích tiến độ học của bạn.")
        if weak_topics:
            roadmap.append(f"Ôn lại chủ đề {weak_topics[0]} trước khi làm thêm quiz mới để tăng độ chính xác.")
        if accuracy < 70:
            roadmap.append("Chọn một quiz ngắn và tập trung làm chậm, chắc để cải thiện độ chính xác tổng thể.")
        if sum(xp7days) <= 0:
            roadmap.append("Hôm nay nên hoàn thành ít nhất 1 quiz để biểu đồ XP 7 ngày bắt đầu ghi nhận tiến độ thật.")
        if total_study_minutes < 90:
            roadmap.append("Tăng thêm 15-20 phút học trong ngày để xây nền đều hơn cho tuần này.")
        if current_streak > 0:
            roadmap.append(f"Giữ streak thêm 1 ngày nữa để không làm gián đoạn nhịp học hiện tại của bạn.")
        else:
            roadmap.append("Bắt đầu streak mới bằng một phiên học ngắn hôm nay, chỉ cần 10-15 phút cũng đủ.")
        if topic_progress:
            strongest_topic = max(topic_progress, key=lambda item: item["score"])
            roadmap.append(f"Tiếp tục phát huy ở {strongest_topic['topic']} vì đây đang là mảng bạn làm tốt nhất.")

        deduped: list[str] = []
        seen: set[str] = set()
        for item in roadmap:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
            if len(deduped) >= 3:
                break

        return deduped

    def progress_summary_from_stats(self, stats: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        stats = self.normalize_stats_row(stats)
        total_quizzes = stats.get("total_quizzes", 0)
        total_questions = max(1, total_quizzes * 3)
        xp7days, xp7day_labels = self.build_weekly_xp_activity(user_id) if user_id else ([0] * 7, ["T2", "T3", "T4", "T5", "T6", "T7", "CN"])
        topic_progress = self.build_topic_progress(user_id) if user_id else []
        strong_topics = [item["topic"] for item in sorted(topic_progress, key=lambda topic: (-topic["score"], -topic["totalAnswers"], topic["topic"]))[:3]]
        weak_topics = [item["topic"] for item in sorted(topic_progress, key=lambda topic: (topic["score"], -topic["totalAnswers"], topic["topic"]))[:3]]
        ai_roadmap = self.build_ai_roadmap(stats, xp7days, topic_progress, weak_topics)
        return {
            "level": stats["level"],
            "xp": resolve_level_progress(stats["xp"])["xp_into_level"],
            "coins": stats["coins"],
            "streak": stats["streak"],
            "totalQuizzes": total_quizzes,
            "quizCompleted": total_quizzes,
            "accuracy": round((stats.get("total_correct_answers", 0) / total_questions) * 100),
            "studyTime": f"{stats.get('total_study_minutes', 0) // 60}h {stats.get('total_study_minutes', 0) % 60}m",
            "weeklyActivity": xp7days,
            "xp7Days": xp7days,
            "xp7DayLabels": xp7day_labels,
            "topicProgress": topic_progress,
            "strongTopics": strong_topics,
            "weakTopics": weak_topics,
            "aiRoadmap": ai_roadmap,
        }

    def dashboard(self, user_id: str) -> dict[str, Any]:
        if self.use_postgres:
            row = postgres_db.fetch_one(
                """
                select
                  p.id as profile_id,
                  p.email,
                  p.role,
                  p.display_name,
                  p.avatar_url,
                  s.user_id as stats_user_id,
                  s.level,
                  s.xp,
                  s.coins,
                  s.streak,
                  s.total_quizzes,
                  s.total_correct_answers,
                  s.total_study_minutes,
                  s.last_active_at,
                  s.updated_at as stats_updated_at,
                  settings.active_buddy_id,
                  settings.equipped_model_id,
                  settings.room_background_id,
                  settings.buddy_3d_enabled,
                  ub.id as user_buddy_id,
                  ub.buddy_id as user_buddy_buddy_id,
                  ub.is_selected as user_buddy_is_selected,
                  ub.level as user_buddy_level,
                  ub.xp as user_buddy_xp
                from profiles p
                left join user_stats s on s.user_id = p.id
                left join user_companion_settings settings on settings.user_id = p.id
                left join user_buddies ub on ub.user_id = p.id and ub.buddy_id = settings.active_buddy_id
                where p.id = %s::uuid
                """,
                (user_id,),
            )
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            if row.get("stats_user_id") is None or row.get("active_buddy_id") is None:
                self.ensure_user_defaults(user_id)
                return self.dashboard(user_id)

            user = public_user(
                {
                    "id": row["profile_id"],
                    "email": row["email"],
                    "role": row.get("role", "student"),
                    "display_name": row.get("display_name"),
                    "avatar_url": row.get("avatar_url") or "",
                }
            )
            stats = {
                "user_id": row["stats_user_id"],
                "level": row["level"],
                "xp": row["xp"],
                "coins": row["coins"],
                "streak": row["streak"],
                "total_quizzes": row["total_quizzes"],
                "total_correct_answers": row["total_correct_answers"],
                "total_study_minutes": row["total_study_minutes"],
                "last_active_at": row.get("last_active_at"),
                "updated_at": row.get("stats_updated_at"),
            }
            progress_summary = self.progress_summary_from_stats(stats, user_id)
            mission_rows = [
                dict(item)
                for item in postgres_db.fetch_all("select * from user_missions where user_id = %s::uuid", (user_id,))
            ]
            daily_quests = [
                self.format_mission(mission, next((item for item in mission_rows if item["mission_id"] == mission["id"] and item.get("date_scope") == today_scope()), None))
                for mission in MISSIONS
                if mission["type"] == "daily"
            ]
            settings = {
                "active_buddy_id": row["active_buddy_id"],
                "equipped_model_id": row.get("equipped_model_id"),
                "room_background_id": row.get("room_background_id"),
                "buddy_3d_enabled": row.get("buddy_3d_enabled"),
            }
            buddies = self.list_buddies()
            buddy = next((item for item in buddies if item["id"] == settings.get("active_buddy_id")), buddies[0])
            user_buddy = None
            if row.get("user_buddy_buddy_id"):
                user_buddy = {
                    "id": row.get("user_buddy_id"),
                    "buddy_id": row.get("user_buddy_buddy_id"),
                    "is_selected": row.get("user_buddy_is_selected"),
                    "level": row.get("user_buddy_level"),
                    "xp": row.get("user_buddy_xp"),
                }
            return {
                "user": {**user, **self.format_stats_for_ui(stats, progress_summary)},
                "statsCards": [
                    {"label": "Level hiá»‡n táº¡i", "value": f"Lv. {stats['level']}", "tone": "violet", "icon": "Zap"},
                    {"label": "Tá»•ng XP", "value": f"{stats['xp']:,}", "tone": "blue", "icon": "Sparkles"},
                    {"label": "Streak", "value": f"{stats['streak']} ngÃ y", "tone": "orange", "icon": "Flame"},
                ],
                "dailyQuests": daily_quests,
                "progressSummary": progress_summary,
                "currentBuddy": self.enrich_buddy(user_id, buddy, user_buddy),
                "aiSuggestion": {
                    "title": "Gá»£i Ã½ tá»« AI",
                    "text": "Báº¡n Ä‘ang lÃ m tá»‘t Vocabulary. HÃ´m nay nÃªn dÃ nh 20 phÃºt cho Present Perfect vÃ  lÃ m 1 quiz Grammar má»©c trung bÃ¬nh.",
                },
            }

        user = public_user(self.get_user(user_id))
        stats = self.get_stats(user_id)
        progress_summary = self.progress_summary_from_stats(stats, user_id)
        return {
            "user": {**user, **self.format_stats_for_ui(stats, progress_summary)},
            "statsCards": [
                {"label": "Level hiện tại", "value": f"Lv. {stats['level']}", "tone": "violet", "icon": "Zap"},
                {"label": "Tổng XP", "value": f"{stats['xp']:,}", "tone": "blue", "icon": "Sparkles"},
                {"label": "Streak", "value": f"{stats['streak']} ngày", "tone": "orange", "icon": "Flame"},
            ],
            "dailyQuests": self.list_missions(user_id, "daily"),
            "progressSummary": progress_summary,
            "currentBuddy": self.active_buddy(user_id),
            "aiSuggestion": {
                "title": "Gợi ý từ AI",
                "text": "Bạn đang làm tốt Vocabulary. Hôm nay nên dành 20 phút cho Present Perfect và làm 1 quiz Grammar mức trung bình.",
            },
        }

    def format_stats_for_ui(self, stats: dict[str, Any], progress_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        stats = self.normalize_stats_row(stats)
        level_progress = resolve_level_progress(stats["xp"])
        progress_summary = progress_summary or self.progress_summary_from_stats(stats)
        return {
            "level": stats["level"],
            "xp": level_progress["xp_into_level"],
            "nextLevelXp": level_progress["next_level_xp"],
            "totalXp": stats["xp"],
            "streak": stats["streak"],
            "coins": stats["coins"],
            "quizCompleted": stats.get("total_quizzes", 0),
            "accuracy": progress_summary["accuracy"],
            "studyTime": progress_summary["studyTime"],
        }

    def ensure_catalog_seeded(self, skip_missions: bool = False) -> None:
        if not self.use_postgres:
            return
        for buddy in BUDDIES:
            postgres_db.execute(
                """
                insert into buddies (id, name, role, type, emoji, gradient, description, personality, avatar_url, tags, skills, accent, rarity, default_mood, is_active)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, true)
                on conflict (id) do nothing
                """,
                (
                    buddy["id"],
                    buddy["name"],
                    buddy["role"],
                    buddy["type"],
                    buddy["emoji"],
                    buddy["gradient"],
                    buddy["description"],
                    buddy["personality"],
                    buddy["avatar_url"],
                    json.dumps(buddy["tags"], ensure_ascii=False),
                    json.dumps(buddy["skills"], ensure_ascii=False),
                    buddy["accent"],
                    buddy["rarity"],
                    buddy["default_mood"],
                ),
            )
        for model in COMPANION_MODELS:
            postgres_db.execute(
                """
                insert into companion_models (id, name, description, model_url, thumbnail_url, rarity, price, tags, actions, accent, source, is_active)
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, true)
                on conflict (id) do nothing
                """,
                (
                    model["id"],
                    model["name"],
                    model["description"],
                    model["model_url"],
                    model["thumbnail_url"],
                    model["rarity"],
                    model["price"],
                    json.dumps(model["tags"], ensure_ascii=False),
                    json.dumps(model["actions"], ensure_ascii=False),
                    model["accent"],
                    model["source"],
                ),
            )
        for background in ROOM_BACKGROUNDS:
            postgres_db.execute(
                """
                insert into room_backgrounds (id, name, description, image_url, thumbnail_url, price, accent, is_active)
                values (%s, %s, %s, %s, %s, %s, %s, true)
                on conflict (id) do nothing
                """,
                (
                    background["id"],
                    background["name"],
                    background["description"],
                    background["image_url"],
                    background["thumbnail_url"],
                    background["price"],
                    background["accent"],
                ),
            )
        if skip_missions:
            return
        for mission in MISSIONS:
            postgres_db.execute(
                """
                insert into missions (id, title, description, type, target_type, target_value, reward_xp, reward_coins, is_active)
                values (%s, %s, %s, %s, %s, %s, %s, %s, true)
                on conflict (id) do nothing
                """,
                (
                    mission["id"],
                    mission["title"],
                    mission["description"],
                    mission["type"],
                    mission["target_type"],
                    mission["target_value"],
                    mission["reward_xp"],
                    mission["reward_coins"],
                ),
            )


store = AppStore()
