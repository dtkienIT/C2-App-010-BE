from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import random
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from backend.core.security import hash_password, verify_password
from backend.database.connection import postgres_db, supabase
from backend.database.seed_data import (
    ACHIEVEMENTS,
    BUDDIES,
    COMPANION_MODELS,
    DEFAULT_STATS,
    MISSIONS,
    QUIZZES,
    ROOM_BACKGROUNDS,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return max(1000, level * 100)


def json_value(value: Any) -> Any:
    if hasattr(value, "as_string"):
        return value.as_string()
    return value


class AppStore:
    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self._users_by_email: dict[str, str] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        self._user_buddies: dict[str, list[dict[str, Any]]] = {}
        self._settings: dict[str, dict[str, Any]] = {}
        self._user_missions: dict[str, list[dict[str, Any]]] = {}
        self._attempts: dict[str, dict[str, Any]] = {}
        self._attempt_answers: dict[str, list[dict[str, Any]]] = {}
        self._user_achievements: dict[str, list[dict[str, Any]]] = {}
        self._buddies_cache: list[dict[str, Any]] | None = None

    @property
    def use_postgres(self) -> bool:
        return postgres_db is not None

    @property
    def use_supabase(self) -> bool:
        return supabase is not None and not self.use_postgres

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
                        insert into profiles (id, email, display_name, avatar_url, role, password_hash, created_at, updated_at)
                        values (%s::uuid, %s, %s, %s, %s, %s, now(), now())
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
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
            self._table("profiles").insert(row).execute()
            self._table("user_stats").insert({"user_id": row["id"], **DEFAULT_STATS, "last_active_at": utc_now(), "updated_at": utc_now()}).execute()
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
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self._users[row["id"]] = row
        self._users_by_email[email] = row["id"]
        self._stats[row["id"]] = {"user_id": row["id"], **deepcopy(DEFAULT_STATS), "last_active_at": utc_now(), "updated_at": utc_now()}
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
            row = postgres_db.fetch_one("select * from user_stats where user_id = %s::uuid", (user_id,))
            if not row:
                self.ensure_user_defaults(user_id)
                row = postgres_db.fetch_one("select * from user_stats where user_id = %s::uuid", (user_id,))
            if not row:
                raise HTTPException(status_code=404, detail="User stats not found")
            return dict(row)
        if self.use_supabase:
            rows = self._table("user_stats").select("*").eq("user_id", user_id).execute().data
            return rows[0]
        return self._stats[user_id]

    def update_stats(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_stats(user_id)
        next_row = {**current, **patch, "updated_at": utc_now()}
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
            assignments = [f"{key} = %s" for key in patch if key in allowed]
            params = [patch[key] for key in patch if key in allowed]
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

    def _ensure_user_defaults_postgres(self, user_id: str, cursor: Any) -> None:
        cursor.execute(
            """
            insert into user_stats (user_id, level, xp, coins, streak, total_quizzes, total_correct_answers, total_study_minutes, last_active_at, updated_at)
            values (%s::uuid, %s, %s, %s, %s, %s, %s, %s, now(), now())
            on conflict (user_id) do nothing
            """,
            (
                user_id,
                DEFAULT_STATS["level"],
                DEFAULT_STATS["xp"],
                DEFAULT_STATS["coins"],
                DEFAULT_STATS["streak"],
                DEFAULT_STATS["total_quizzes"],
                DEFAULT_STATS["total_correct_answers"],
                DEFAULT_STATS["total_study_minutes"],
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
        buddy_rows = [(user_id, buddy["id"], buddy["id"] == "miu", 8 if buddy["id"] == "miu" else 1, 720 if buddy["id"] == "miu" else 0) for buddy in BUDDIES]
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
                self._table("user_stats").insert({"user_id": user_id, **DEFAULT_STATS, "last_active_at": utc_now(), "updated_at": utc_now()}).execute()
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

        self._stats.setdefault(user_id, {"user_id": user_id, **deepcopy(DEFAULT_STATS), "last_active_at": utc_now(), "updated_at": utc_now()})
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
                {"id": str(uuid4()), "user_id": user_id, "buddy_id": buddy["id"], "is_selected": buddy["id"] == "miu", "level": 8, "xp": 720, "created_at": utc_now(), "updated_at": utc_now()}
                for buddy in BUDDIES
            ]
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
        return {
            **buddy,
            "fallbackImage": buddy.get("fallbackImage") or buddy.get("avatar_url"),
            "mood": buddy.get("mood") or buddy.get("default_mood", "idle"),
            "level": (user_buddy or {}).get("level", 8),
            "xp": (user_buddy or {}).get("xp", 720),
            "nextLevelXp": 1200,
            "energy": 76,
            "focus": 68,
            "motivation": 84,
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
            "streak": max(1, stats.get("streak", 0)),
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
                        streak = greatest(1, streak),
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

    def list_models(self) -> list[dict[str, Any]]:
        return [self.format_model(row) for row in COMPANION_MODELS if row.get("source") == "shop"]

    def list_backgrounds(self) -> list[dict[str, Any]]:
        return [self.format_background(row) for row in ROOM_BACKGROUNDS]

    def format_model(self, row: dict[str, Any]) -> dict[str, Any]:
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
            "unlocked": True,
            "vrmUrl": row["model_url"],
            "modelUrl": row["model_url"],
            "actions": row.get("actions", []),
            "accent": row.get("accent", "cyan"),
        }

    def format_background(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row.get("description", ""),
            "imageUrl": row["image_url"],
            "thumbnailUrl": row["thumbnail_url"],
            "price": row["price"],
            "accent": row.get("accent", "cyan"),
            "unlocked": True,
        }

    def equip_model(self, user_id: str, model_id: str) -> dict[str, Any]:
        model = next((item for item in COMPANION_MODELS if item["id"] == model_id), None)
        if not model:
            raise HTTPException(status_code=404, detail="3D model not found")
        return self.update_settings(user_id, {"equipped_model_id": model_id, "buddy_3d_enabled": True})

    def select_background(self, user_id: str, background_id: str) -> dict[str, Any]:
        background = next((item for item in ROOM_BACKGROUNDS if item["id"] == background_id), None)
        if not background:
            raise HTTPException(status_code=404, detail="Room background not found")
        return self.update_settings(user_id, {"room_background_id": background_id})

    def progress_summary(self, user_id: str) -> dict[str, Any]:
        stats = self.get_stats(user_id)
        return self.progress_summary_from_stats(stats)

    def progress_summary_from_stats(self, stats: dict[str, Any]) -> dict[str, Any]:
        total_quizzes = stats.get("total_quizzes", 0)
        total_questions = max(1, total_quizzes * 3)
        return {
            "level": stats["level"],
            "xp": stats["xp"],
            "coins": stats["coins"],
            "streak": stats["streak"],
            "totalQuizzes": total_quizzes,
            "quizCompleted": total_quizzes,
            "accuracy": round((stats.get("total_correct_answers", 0) / total_questions) * 100),
            "studyTime": f"{stats.get('total_study_minutes', 0) // 60}h {stats.get('total_study_minutes', 0) % 60}m",
            "weeklyActivity": [120, 180, 220, 160, 240, 280, 200],
            "xp7Days": [120, 180, 220, 160, 240, 280, 200],
            "topicProgress": [
                {"topic": "Vocabulary", "score": 88},
                {"topic": "Reading", "score": 82},
                {"topic": "Present Perfect", "score": 64},
            ],
            "strongTopics": ["Vocabulary", "Reading", "Basic Grammar"],
            "weakTopics": ["Present Perfect", "Phrasal Verbs", "Academic Writing"],
            "aiRoadmap": [
                "Ôn Present Perfect trong 15 phút.",
                "Làm 1 quiz Grammar mức trung bình.",
                "Ôn lại 8 câu sai gần nhất bằng flashcard.",
            ],
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
            progress_summary = self.progress_summary_from_stats(stats)
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
        progress_summary = self.progress_summary_from_stats(stats)
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
        progress_summary = progress_summary or self.progress_summary_from_stats(stats)
        return {
            "level": stats["level"],
            "xp": stats["xp"],
            "nextLevelXp": next_level_xp(stats["level"]),
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
