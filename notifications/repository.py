from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import json
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.database.connection import postgres_db
from psycopg.errors import UndefinedTable
from backend.notifications.constants import (
    DAILY_STUDY_REMINDER,
    DELIVERY_PENDING,
    DELIVERY_PERMANENT_FAILURE,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    DELIVERY_TRANSIENT_FAILURE,
    OUTBOX_CANCELLED,
    OUTBOX_FAILED,
    OUTBOX_PARTIAL,
    OUTBOX_PENDING,
    OUTBOX_PROCESSING,
    OUTBOX_SENT,
    OUTBOX_SKIPPED,
    USER_NOTIFICATION_STORED,
)
from backend.notifications.reminder_time import calculate_next_run, parse_reminder_time


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_jsonb(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    next_row = dict(row)
    for key in ("id", "user_id", "reminder_id", "outbox_id", "subscription_id"):
        if key in next_row and next_row[key] is not None:
            next_row[key] = str(next_row[key])
    return next_row


class NotificationRepository:
    def __init__(self, use_postgres: bool | None = None) -> None:
        self._force_postgres = use_postgres
        self._lock = Lock()
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._reminders: dict[str, dict[str, Any]] = {}
        self._outbox: dict[str, dict[str, Any]] = {}
        self._deliveries: dict[str, dict[str, Any]] = {}
        self._email_deliveries: dict[str, dict[str, Any]] = {}
        self._user_notifications: dict[str, dict[str, Any]] = {}
        self._profiles: dict[str, dict[str, Any]] = {}

    @property
    def use_postgres(self) -> bool:
        if self._force_postgres is not None:
            return self._force_postgres
        return postgres_db is not None

    def upsert_subscription(
        self,
        *,
        user_id: str,
        installation_id: str,
        endpoint: str,
        p256dh_key: str,
        auth_key: str,
        content_encoding: str | None,
        platform: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select id, user_id, installation_id from web_push_subscriptions where endpoint = %s", (endpoint,))
                    existing_endpoint = cursor.fetchone()
                    if existing_endpoint and (
                        str(existing_endpoint["user_id"]) != user_id or existing_endpoint["installation_id"] != installation_id
                    ):
                        cursor.execute(
                            """
                            update web_push_subscriptions
                            set endpoint = 'revoked:' || id::text,
                                is_active = false,
                                revoked_at = coalesce(revoked_at, now()),
                                updated_at = now()
                            where id = %s::uuid
                            """,
                            (str(existing_endpoint["id"]),),
                        )
                    cursor.execute(
                        """
                        insert into web_push_subscriptions (
                          id, user_id, installation_id, endpoint, p256dh_key, auth_key,
                          content_encoding, user_agent, platform, is_active,
                          last_seen_at, created_at, updated_at, revoked_at
                        )
                        values (
                          %s::uuid, %s::uuid, %s, %s, %s, %s,
                          %s, %s, %s, true,
                          now(), now(), now(), null
                        )
                        on conflict (user_id, installation_id)
                        do update set
                          endpoint = excluded.endpoint,
                          p256dh_key = excluded.p256dh_key,
                          auth_key = excluded.auth_key,
                          content_encoding = excluded.content_encoding,
                          user_agent = excluded.user_agent,
                          platform = excluded.platform,
                          is_active = true,
                          last_seen_at = now(),
                          updated_at = now(),
                          revoked_at = null
                        returning *
                        """,
                        (
                            str(uuid4()),
                            user_id,
                            installation_id,
                            endpoint,
                            p256dh_key,
                            auth_key,
                            content_encoding,
                            user_agent,
                            platform,
                        ),
                    )
                    row = cursor.fetchone()
                connection.commit()
            return normalize_row(row) or {}

        with self._lock:
            now = utc_now()
            for row in self._subscriptions.values():
                if row["endpoint"] == endpoint and (row["user_id"] != user_id or row["installation_id"] != installation_id):
                    row["endpoint"] = f"revoked:{row['id']}"
                    row["is_active"] = False
                    row["revoked_at"] = now
                    row["updated_at"] = now
            existing_id = next(
                (
                    item_id
                    for item_id, row in self._subscriptions.items()
                    if row["user_id"] == user_id and row["installation_id"] == installation_id
                ),
                None,
            )
            subscription_id = existing_id or str(uuid4())
            created_at = self._subscriptions.get(subscription_id, {}).get("created_at", now)
            self._subscriptions[subscription_id] = {
                "id": subscription_id,
                "user_id": user_id,
                "installation_id": installation_id,
                "endpoint": endpoint,
                "p256dh_key": p256dh_key,
                "auth_key": auth_key,
                "content_encoding": content_encoding,
                "user_agent": user_agent,
                "platform": platform,
                "is_active": True,
                "last_seen_at": now,
                "created_at": created_at,
                "updated_at": now,
                "revoked_at": None,
            }
            return deepcopy(self._subscriptions[subscription_id])

    def list_subscriptions(self, user_id: str) -> list[dict[str, Any]]:
        if self.use_postgres:
            rows = postgres_db.fetch_all(
                """
                select *
                from web_push_subscriptions
                where user_id = %s::uuid
                order by last_seen_at desc
                """,
                (user_id,),
            )
            return [normalize_row(row) or {} for row in rows]
        return [deepcopy(row) for row in self._subscriptions.values() if row["user_id"] == user_id]

    def active_subscriptions(self, user_id: str) -> list[dict[str, Any]]:
        if self.use_postgres:
            rows = postgres_db.fetch_all(
                """
                select *
                from web_push_subscriptions
                where user_id = %s::uuid
                  and is_active = true
                order by last_seen_at desc
                """,
                (user_id,),
            )
            return [normalize_row(row) or {} for row in rows]
        return [deepcopy(row) for row in self._subscriptions.values() if row["user_id"] == user_id and row["is_active"]]

    def upsert_user_profile(self, *, user_id: str, email: str, display_name: str | None = None, role: str = "student") -> dict[str, Any]:
        row = {
            "id": user_id,
            "email": email,
            "display_name": display_name or email.split("@")[0],
            "role": role,
        }
        self._profiles[user_id] = row
        return deepcopy(row)

    def get_user_notification_profile(self, user_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            row = postgres_db.fetch_one(
                """
                select id, email, display_name, role
                from profiles
                where id = %s::uuid
                """,
                (user_id,),
            )
            return normalize_row(row)
        row = self._profiles.get(user_id)
        return deepcopy(row) if row else None

    def deactivate_subscription(self, user_id: str, installation_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                update web_push_subscriptions
                set endpoint = case when endpoint like 'revoked:%%' then endpoint else 'revoked:' || id::text end,
                    is_active = false,
                    revoked_at = coalesce(revoked_at, now()),
                    updated_at = now()
                where user_id = %s::uuid
                  and installation_id = %s
                returning *
                """,
                (user_id, installation_id),
            )
            return normalize_row(row)
        with self._lock:
            row = next(
                (
                    item
                    for item in self._subscriptions.values()
                    if item["user_id"] == user_id and item["installation_id"] == installation_id
                ),
                None,
            )
            if not row:
                return None
            row["endpoint"] = f"revoked:{row['id']}"
            row["is_active"] = False
            row["revoked_at"] = utc_now()
            row["updated_at"] = row["revoked_at"]
            return deepcopy(row)

    def deactivate_subscription_by_id(self, subscription_id: str) -> None:
        if self.use_postgres:
            postgres_db.execute(
                """
                update web_push_subscriptions
                set endpoint = case when endpoint like 'revoked:%%' then endpoint else 'revoked:' || id::text end,
                    is_active = false,
                    revoked_at = coalesce(revoked_at, now()),
                    updated_at = now()
                where id = %s::uuid
                """,
                (subscription_id,),
            )
            return
        with self._lock:
            row = self._subscriptions.get(subscription_id)
            if row:
                row["endpoint"] = f"revoked:{row['id']}"
                row["is_active"] = False
                row["revoked_at"] = utc_now()
                row["updated_at"] = row["revoked_at"]

    def list_reminders(self, user_id: str) -> list[dict[str, Any]]:
        if self.use_postgres:
            rows = postgres_db.fetch_all(
                """
                select *
                from study_reminders
                where user_id = %s::uuid
                order by reminder_time, created_at
                """,
                (user_id,),
            )
            return [normalize_row(row) or {} for row in rows]
        return [deepcopy(row) for row in self._reminders.values() if row["user_id"] == user_id]

    def count_reminders(self, user_id: str) -> int:
        if self.use_postgres:
            row = postgres_db.fetch_one("select count(*) as count from study_reminders where user_id = %s::uuid", (user_id,))
            return int(row["count"] if row else 0)
        return len([row for row in self._reminders.values() if row["user_id"] == user_id])

    def create_reminder(
        self,
        *,
        user_id: str,
        reminder_time: time,
        days_of_week: list[int],
        timezone_name: str,
        is_enabled: bool,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        now = as_utc(now_utc or utc_now())
        next_run_at = calculate_next_run(reminder_time, days_of_week, timezone_name, now)
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                insert into study_reminders (
                  id, user_id, reminder_time, days_of_week, timezone, is_enabled,
                  next_run_at, created_at, updated_at
                )
                values (%s::uuid, %s::uuid, %s, %s::smallint[], %s, %s, %s, now(), now())
                returning *
                """,
                (str(uuid4()), user_id, reminder_time, days_of_week, timezone_name, is_enabled, next_run_at),
            )
            return normalize_row(row) or {}
        with self._lock:
            row = {
                "id": str(uuid4()),
                "user_id": user_id,
                "reminder_time": reminder_time,
                "days_of_week": days_of_week,
                "timezone": timezone_name,
                "is_enabled": is_enabled,
                "next_run_at": next_run_at,
                "last_sent_at": None,
                "created_at": now,
                "updated_at": now,
            }
            self._reminders[row["id"]] = row
            return deepcopy(row)

    def update_reminder(
        self,
        *,
        user_id: str,
        reminder_id: str,
        patch: dict[str, Any],
        now_utc: datetime | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_reminder(user_id, reminder_id)
        if not current:
            return None
        next_time = patch.get("reminder_time", current["reminder_time"])
        if isinstance(next_time, str):
            next_time = parse_reminder_time(next_time)
        next_days = patch.get("days_of_week", list(current["days_of_week"]))
        next_timezone = patch.get("timezone", current["timezone"])
        next_enabled = patch.get("is_enabled", current["is_enabled"])
        now = as_utc(now_utc or utc_now())
        next_run_at = calculate_next_run(next_time, next_days, next_timezone, now)
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                update study_reminders
                set reminder_time = %s,
                    days_of_week = %s::smallint[],
                    timezone = %s,
                    is_enabled = %s,
                    next_run_at = %s,
                    updated_at = now()
                where id = %s::uuid
                  and user_id = %s::uuid
                returning *
                """,
                (next_time, next_days, next_timezone, next_enabled, next_run_at, reminder_id, user_id),
            )
            return normalize_row(row)
        with self._lock:
            row = self._reminders[reminder_id]
            row.update(
                {
                    "reminder_time": next_time,
                    "days_of_week": next_days,
                    "timezone": next_timezone,
                    "is_enabled": next_enabled,
                    "next_run_at": next_run_at,
                    "updated_at": now,
                }
            )
            return deepcopy(row)

    def get_reminder(self, user_id: str, reminder_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            return normalize_row(
                postgres_db.fetch_one(
                    "select * from study_reminders where id = %s::uuid and user_id = %s::uuid",
                    (reminder_id, user_id),
                )
            )
        row = self._reminders.get(reminder_id)
        if not row or row["user_id"] != user_id:
            return None
        return deepcopy(row)

    def disable_reminder(self, user_id: str, reminder_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        update study_reminders
                        set is_enabled = false,
                            updated_at = now()
                        where id = %s::uuid
                          and user_id = %s::uuid
                        returning *
                        """,
                        (reminder_id, user_id),
                    )
                    row = cursor.fetchone()
                    cursor.execute(
                        """
                        update notification_outbox
                        set status = 'cancelled',
                            updated_at = now(),
                            processed_at = now()
                        where reminder_id = %s::uuid
                          and user_id = %s::uuid
                          and status in ('pending', 'processing')
                        """,
                        (reminder_id, user_id),
                    )
                connection.commit()
            return normalize_row(row)
        with self._lock:
            row = self._reminders.get(reminder_id)
            if not row or row["user_id"] != user_id:
                return None
            row["is_enabled"] = False
            row["updated_at"] = utc_now()
            for event in self._outbox.values():
                if event.get("reminder_id") == reminder_id and event["user_id"] == user_id and event["status"] in {OUTBOX_PENDING, OUTBOX_PROCESSING}:
                    event["status"] = OUTBOX_CANCELLED
                    event["processed_at"] = utc_now()
                    event["updated_at"] = event["processed_at"]
            return deepcopy(row)

    def delete_reminder(self, user_id: str, reminder_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        update notification_outbox
                        set status = 'cancelled',
                            updated_at = now(),
                            processed_at = now()
                        where reminder_id = %s::uuid
                          and user_id = %s::uuid
                          and status in ('pending', 'processing')
                        """,
                        (reminder_id, user_id),
                    )
                    cursor.execute(
                        """
                        delete from study_reminders
                        where id = %s::uuid
                          and user_id = %s::uuid
                        returning *
                        """,
                        (reminder_id, user_id),
                    )
                    row = cursor.fetchone()
                connection.commit()
            return normalize_row(row)
        with self._lock:
            row = self._reminders.get(reminder_id)
            if not row or row["user_id"] != user_id:
                return None
            deleted = deepcopy(row)
            for event in self._outbox.values():
                if event.get("reminder_id") == reminder_id and event["user_id"] == user_id and event["status"] in {OUTBOX_PENDING, OUTBOX_PROCESSING}:
                    event["status"] = OUTBOX_CANCELLED
                    event["processed_at"] = utc_now()
                    event["updated_at"] = event["processed_at"]
            del self._reminders[reminder_id]
            return deleted

    def claim_due_reminders(self, *, limit: int, worker_id: str, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        now = as_utc(now_utc or utc_now())
        if self.use_postgres:
            claimed_events: list[dict[str, Any]] = []
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select *
                        from study_reminders
                        where is_enabled = true
                          and next_run_at <= %s
                        order by next_run_at, created_at
                        for update skip locked
                        limit %s
                        """,
                        (now, limit),
                    )
                    reminders = cursor.fetchall()
                    for reminder in reminders:
                        occurrence = as_utc(reminder["next_run_at"])
                        payload = build_payload(str(reminder["id"]), occurrence)
                        dedupe_key = reminder_dedupe_key(str(reminder["id"]), occurrence)
                        cursor.execute(
                            """
                            insert into notification_outbox (
                              id, user_id, reminder_id, event_type, scheduled_at, status,
                              attempts, payload, dedupe_key, created_at, updated_at
                            )
                            values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, 0, %s::jsonb, %s, now(), now())
                            on conflict (dedupe_key) do update set updated_at = notification_outbox.updated_at
                            returning *
                            """,
                            (
                                str(uuid4()),
                                str(reminder["user_id"]),
                                str(reminder["id"]),
                                DAILY_STUDY_REMINDER,
                                occurrence,
                                OUTBOX_PENDING,
                                to_jsonb(payload),
                                dedupe_key,
                            ),
                        )
                        event = cursor.fetchone()
                        next_run_at = calculate_next_run(
                            reminder["reminder_time"],
                            list(reminder["days_of_week"]),
                            reminder["timezone"],
                            occurrence + timedelta(seconds=1),
                        )
                        cursor.execute(
                            """
                            update study_reminders
                            set last_sent_at = %s,
                                next_run_at = %s,
                                updated_at = now()
                            where id = %s::uuid
                            """,
                            (occurrence, next_run_at, str(reminder["id"])),
                        )
                        if event:
                            claimed_events.append(normalize_row(event) or {})
                connection.commit()
            return claimed_events

        with self._lock:
            due = [
                row
                for row in self._reminders.values()
                if row["is_enabled"] and as_utc(row["next_run_at"]) <= now
            ]
            due.sort(key=lambda row: (row["next_run_at"], row["created_at"]))
            events = []
            for reminder in due[:limit]:
                occurrence = as_utc(reminder["next_run_at"])
                event = self.enqueue_outbox(
                    user_id=reminder["user_id"],
                    reminder_id=reminder["id"],
                    scheduled_at=occurrence,
                    payload=build_payload(reminder["id"], occurrence),
                )
                reminder["last_sent_at"] = occurrence
                reminder["next_run_at"] = calculate_next_run(
                    reminder["reminder_time"],
                    list(reminder["days_of_week"]),
                    reminder["timezone"],
                    occurrence + timedelta(seconds=1),
                )
                reminder["updated_at"] = now
                events.append(event)
            return events

    def enqueue_outbox(self, *, user_id: str, reminder_id: str | None, scheduled_at: datetime, payload: dict[str, Any]) -> dict[str, Any]:
        scheduled_at = as_utc(scheduled_at)
        dedupe_key = reminder_dedupe_key(reminder_id or payload["reminderId"], scheduled_at)
        if self.use_postgres:
            row = postgres_db.execute_returning(
                """
                insert into notification_outbox (
                  id, user_id, reminder_id, event_type, scheduled_at, status,
                  attempts, payload, dedupe_key, created_at, updated_at
                )
                values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, 0, %s::jsonb, %s, now(), now())
                on conflict (dedupe_key) do update set updated_at = notification_outbox.updated_at
                returning *
                """,
                (
                    str(uuid4()),
                    user_id,
                    reminder_id,
                    DAILY_STUDY_REMINDER,
                    scheduled_at,
                    OUTBOX_PENDING,
                    to_jsonb(payload),
                    dedupe_key,
                ),
            )
            return normalize_row(row) or {}
        existing = next((row for row in self._outbox.values() if row["dedupe_key"] == dedupe_key), None)
        if existing:
            return deepcopy(existing)
        now = utc_now()
        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "reminder_id": reminder_id,
            "event_type": DAILY_STUDY_REMINDER,
            "scheduled_at": scheduled_at,
            "status": OUTBOX_PENDING,
            "attempts": 0,
            "next_attempt_at": None,
            "locked_at": None,
            "worker_id": None,
            "payload": deepcopy(payload),
            "dedupe_key": dedupe_key,
            "last_error_code": None,
            "last_error_message": None,
            "processed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._outbox[row["id"]] = row
        return deepcopy(row)

    def get_outbox(self, outbox_id: str) -> dict[str, Any] | None:
        if self.use_postgres:
            return normalize_row(
                postgres_db.fetch_one(
                    "select * from notification_outbox where id = %s::uuid",
                    (outbox_id,),
                )
            )
        row = self._outbox.get(outbox_id)
        return deepcopy(row) if row else None

    def list_recent_delivered_outbox(self, *, user_id: str, limit: int, since: datetime) -> list[dict[str, Any]]:
        since = as_utc(since)
        if self.use_postgres:
            rows = postgres_db.fetch_all(
                """
                select *
                from notification_outbox
                where user_id = %s::uuid
                  and status in ('sent', 'partial')
                  and processed_at is not null
                  and processed_at >= %s
                order by processed_at desc, created_at desc
                limit %s
                """,
                (user_id, since, limit),
            )
            return [normalize_row(row) or {} for row in rows]
        rows = [
            deepcopy(row)
            for row in self._outbox.values()
            if row["user_id"] == user_id
            and row["status"] in {OUTBOX_SENT, OUTBOX_PARTIAL}
            and row.get("processed_at") is not None
            and as_utc(row["processed_at"]) >= since
        ]
        rows.sort(key=lambda row: (row["processed_at"], row["created_at"]), reverse=True)
        return rows[:limit]

    def purge_expired_user_notifications(self, *, user_id: str | None = None, now_utc: datetime | None = None) -> int:
        now = as_utc(now_utc or utc_now())
        if self.use_postgres:
            try:
                if user_id:
                    with postgres_db.connect() as connection:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                delete from user_notifications
                                where user_id = %s::uuid
                                  and expires_at <= %s
                                """,
                                (user_id, now),
                            )
                            deleted_count = cursor.rowcount or 0
                        connection.commit()
                    return deleted_count

                with postgres_db.connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            delete from user_notifications
                            where expires_at <= %s
                            """,
                            (now,),
                        )
                        deleted_count = cursor.rowcount or 0
                    connection.commit()
                return deleted_count
            except UndefinedTable:
                return 0

        expired_ids = [
            notification_id
            for notification_id, row in self._user_notifications.items()
            if (user_id is None or row["user_id"] == user_id) and as_utc(row["expires_at"]) <= now
        ]
        for notification_id in expired_ids:
            self._user_notifications.pop(notification_id, None)
        return len(expired_ids)

    def create_user_notification(
        self,
        *,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = as_utc(utc_now())
        expires_at = as_utc(expires_at or (now + timedelta(days=15)))
        next_payload = deepcopy(payload)
        next_payload.setdefault("createdAt", now.isoformat())
        next_payload.setdefault("expiresAt", expires_at.isoformat())
        self.purge_expired_user_notifications(user_id=user_id, now_utc=now)

        if self.use_postgres:
            try:
                row = postgres_db.execute_returning(
                    """
                    insert into user_notifications (
                      id, user_id, event_type, status, payload, expires_at, created_at, updated_at
                    )
                    values (%s::uuid, %s::uuid, %s, %s, %s::jsonb, %s, now(), now())
                    returning *
                    """,
                    (
                        str(uuid4()),
                        user_id,
                        event_type,
                        USER_NOTIFICATION_STORED,
                        to_jsonb(next_payload),
                        expires_at,
                    ),
                )
                return normalize_row(row) or {}
            except UndefinedTable:
                return {}

        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "event_type": event_type,
            "status": USER_NOTIFICATION_STORED,
            "payload": next_payload,
            "expires_at": expires_at,
            "created_at": now,
            "updated_at": now,
        }
        self._user_notifications[row["id"]] = row
        return deepcopy(row)

    def list_user_notifications(self, *, user_id: str, limit: int = 20, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        now = as_utc(now_utc or utc_now())
        self.purge_expired_user_notifications(user_id=user_id, now_utc=now)
        if self.use_postgres:
            try:
                rows = postgres_db.fetch_all(
                    """
                    select *
                    from user_notifications
                    where user_id = %s::uuid
                      and expires_at > %s
                    order by created_at desc
                    limit %s
                    """,
                    (user_id, now, limit),
                )
                return [normalize_row(row) or {} for row in rows]
            except UndefinedTable:
                return []

        rows = [
            deepcopy(row)
            for row in self._user_notifications.values()
            if row["user_id"] == user_id and as_utc(row["expires_at"]) > now
        ]
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return rows[:limit]

    def claim_due_outbox(self, *, limit: int, worker_id: str, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        now = as_utc(now_utc or utc_now())
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        with claimed as (
                          select id
                          from notification_outbox
                          where status = 'pending'
                            and scheduled_at <= %s
                            and (next_attempt_at is null or next_attempt_at <= %s)
                          order by scheduled_at, created_at
                          for update skip locked
                          limit %s
                        )
                        update notification_outbox outbox
                        set status = 'processing',
                            attempts = outbox.attempts + 1,
                            locked_at = now(),
                            worker_id = %s,
                            updated_at = now()
                        from claimed
                        where outbox.id = claimed.id
                        returning outbox.*
                        """,
                        (now, now, limit, worker_id),
                    )
                    rows = cursor.fetchall()
                connection.commit()
            return [normalize_row(row) or {} for row in rows]
        with self._lock:
            due = [
                row
                for row in self._outbox.values()
                if row["status"] == OUTBOX_PENDING
                and as_utc(row["scheduled_at"]) <= now
                and (row["next_attempt_at"] is None or as_utc(row["next_attempt_at"]) <= now)
            ]
            due.sort(key=lambda row: (row["scheduled_at"], row["created_at"]))
            claimed = []
            for row in due[:limit]:
                row["status"] = OUTBOX_PROCESSING
                row["attempts"] += 1
                row["locked_at"] = now
                row["worker_id"] = worker_id
                row["updated_at"] = now
                claimed.append(deepcopy(row))
            return claimed

    def ensure_delivery(self, outbox_id: str, subscription_id: str) -> dict[str, Any]:
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into notification_deliveries (
                          id, outbox_id, subscription_id, status, attempts, created_at, updated_at
                        )
                        values (%s::uuid, %s::uuid, %s::uuid, %s, 0, now(), now())
                        on conflict (outbox_id, subscription_id) do nothing
                        returning *
                        """,
                        (str(uuid4()), outbox_id, subscription_id, DELIVERY_PENDING),
                    )
                    row = cursor.fetchone()
                    if not row:
                        cursor.execute(
                            """
                            select *
                            from notification_deliveries
                            where outbox_id = %s::uuid
                              and subscription_id = %s::uuid
                            """,
                            (outbox_id, subscription_id),
                        )
                        row = cursor.fetchone()
                connection.commit()
            return normalize_row(row) or {}
        existing = next(
            (
                row
                for row in self._deliveries.values()
                if row["outbox_id"] == outbox_id and row["subscription_id"] == subscription_id
            ),
            None,
        )
        if existing:
            return deepcopy(existing)
        now = utc_now()
        row = {
            "id": str(uuid4()),
            "outbox_id": outbox_id,
            "subscription_id": subscription_id,
            "status": DELIVERY_PENDING,
            "attempts": 0,
            "error_code": None,
            "error_message": None,
            "sent_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._deliveries[row["id"]] = row
        return deepcopy(row)

    def ensure_email_delivery(self, *, outbox_id: str, user_id: str, email: str) -> dict[str, Any]:
        if self.use_postgres:
            with postgres_db.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into notification_email_deliveries (
                          id, outbox_id, user_id, email, status, attempts, created_at, updated_at
                        )
                        values (%s::uuid, %s::uuid, %s::uuid, %s, %s, 0, now(), now())
                        on conflict (outbox_id, user_id)
                        do update set email = excluded.email,
                                      updated_at = notification_email_deliveries.updated_at
                        returning *
                        """,
                        (str(uuid4()), outbox_id, user_id, email, DELIVERY_PENDING),
                    )
                    row = cursor.fetchone()
                connection.commit()
            return normalize_row(row) or {}
        existing = next(
            (
                row
                for row in self._email_deliveries.values()
                if row["outbox_id"] == outbox_id and row["user_id"] == user_id
            ),
            None,
        )
        if existing:
            existing["email"] = email
            return deepcopy(existing)
        now = utc_now()
        row = {
            "id": str(uuid4()),
            "outbox_id": outbox_id,
            "user_id": user_id,
            "email": email,
            "status": DELIVERY_PENDING,
            "attempts": 0,
            "error_code": None,
            "error_message": None,
            "sent_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._email_deliveries[row["id"]] = row
        return deepcopy(row)

    def record_delivery_sent(self, delivery_id: str) -> None:
        self._update_delivery(delivery_id, status=DELIVERY_SENT, error_code=None, error_message=None, sent_at=utc_now())

    def record_delivery_failure(self, delivery_id: str, *, status: str, error_code: str, error_message: str) -> None:
        self._update_delivery(delivery_id, status=status, error_code=error_code, error_message=error_message[:500], sent_at=None)

    def record_email_sent(self, delivery_id: str) -> None:
        self._update_email_delivery(delivery_id, status=DELIVERY_SENT, error_code=None, error_message=None, sent_at=utc_now())

    def record_email_failure(self, delivery_id: str, *, status: str, error_code: str, error_message: str) -> None:
        self._update_email_delivery(delivery_id, status=status, error_code=error_code, error_message=error_message[:500], sent_at=None)

    def record_email_skipped(self, delivery_id: str, *, error_code: str, error_message: str) -> None:
        self._update_email_delivery(delivery_id, status=DELIVERY_SKIPPED, error_code=error_code, error_message=error_message[:500], sent_at=None)

    def _update_delivery(self, delivery_id: str, *, status: str, error_code: str | None, error_message: str | None, sent_at: datetime | None) -> None:
        if self.use_postgres:
            postgres_db.execute(
                """
                update notification_deliveries
                set status = %s,
                    attempts = attempts + 1,
                    error_code = %s,
                    error_message = %s,
                    sent_at = coalesce(%s, sent_at),
                    updated_at = now()
                where id = %s::uuid
                """,
                (status, error_code, error_message, sent_at, delivery_id),
            )
            return
        row = self._deliveries[delivery_id]
        row["status"] = status
        row["attempts"] += 1
        row["error_code"] = error_code
        row["error_message"] = error_message
        row["sent_at"] = sent_at or row.get("sent_at")
        row["updated_at"] = utc_now()

    def _update_email_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        error_code: str | None,
        error_message: str | None,
        sent_at: datetime | None,
    ) -> None:
        if self.use_postgres:
            postgres_db.execute(
                """
                update notification_email_deliveries
                set status = %s,
                    attempts = attempts + 1,
                    error_code = %s,
                    error_message = %s,
                    sent_at = coalesce(%s, sent_at),
                    updated_at = now()
                where id = %s::uuid
                """,
                (status, error_code, error_message, sent_at, delivery_id),
            )
            return
        row = self._email_deliveries[delivery_id]
        row["status"] = status
        row["attempts"] += 1
        row["error_code"] = error_code
        row["error_message"] = error_message
        row["sent_at"] = sent_at or row.get("sent_at")
        row["updated_at"] = utc_now()

    def mark_outbox_sent(self, outbox_id: str) -> None:
        self._mark_outbox_terminal(outbox_id, OUTBOX_SENT, None, None)

    def mark_outbox_partial(self, outbox_id: str, error_code: str, error_message: str) -> None:
        self._mark_outbox_terminal(outbox_id, OUTBOX_PARTIAL, error_code, error_message)

    def mark_outbox_failed(self, outbox_id: str, error_code: str, error_message: str) -> None:
        self._mark_outbox_terminal(outbox_id, OUTBOX_FAILED, error_code, error_message)

    def mark_outbox_skipped(self, outbox_id: str, error_code: str, error_message: str) -> None:
        self._mark_outbox_terminal(outbox_id, OUTBOX_SKIPPED, error_code, error_message)

    def reschedule_outbox_retry(self, outbox_id: str, *, next_attempt_at: datetime, error_code: str, error_message: str) -> None:
        next_attempt_at = as_utc(next_attempt_at)
        if self.use_postgres:
            postgres_db.execute(
                """
                update notification_outbox
                set status = %s,
                    next_attempt_at = %s,
                    locked_at = null,
                    worker_id = null,
                    last_error_code = %s,
                    last_error_message = %s,
                    updated_at = now()
                where id = %s::uuid
                """,
                (OUTBOX_PENDING, next_attempt_at, error_code, error_message[:500], outbox_id),
            )
            return
        row = self._outbox[outbox_id]
        row["status"] = OUTBOX_PENDING
        row["next_attempt_at"] = next_attempt_at
        row["locked_at"] = None
        row["worker_id"] = None
        row["last_error_code"] = error_code
        row["last_error_message"] = error_message[:500]
        row["updated_at"] = utc_now()

    def _mark_outbox_terminal(self, outbox_id: str, status: str, error_code: str | None, error_message: str | None) -> None:
        if self.use_postgres:
            postgres_db.execute(
                """
                update notification_outbox
                set status = %s,
                    next_attempt_at = null,
                    locked_at = null,
                    worker_id = null,
                    last_error_code = %s,
                    last_error_message = %s,
                    processed_at = now(),
                    updated_at = now()
                where id = %s::uuid
                """,
                (status, error_code, (error_message or "")[:500] if error_message else None, outbox_id),
            )
            return
        row = self._outbox[outbox_id]
        row["status"] = status
        row["next_attempt_at"] = None
        row["locked_at"] = None
        row["worker_id"] = None
        row["last_error_code"] = error_code
        row["last_error_message"] = (error_message or "")[:500] if error_message else None
        row["processed_at"] = utc_now()
        row["updated_at"] = row["processed_at"]


def reminder_dedupe_key(reminder_id: str, scheduled_at: datetime) -> str:
    return f"study-reminder:{reminder_id}:{as_utc(scheduled_at).isoformat()}"


def build_payload(reminder_id: str, created_at: datetime) -> dict[str, str]:
    from backend.notifications.constants import DAILY_STUDY_REMINDER_TYPE, REMINDER_BODY, REMINDER_ICON, REMINDER_TITLE

    return {
        "type": DAILY_STUDY_REMINDER_TYPE,
        "reminderId": reminder_id,
        "title": REMINDER_TITLE,
        "body": REMINDER_BODY,
        "targetUrl": f"/buddy-room?mode=focus&source=study_reminder&reminderId={reminder_id}",
        "icon": REMINDER_ICON,
        "tag": f"study-reminder:{reminder_id}",
        "createdAt": as_utc(created_at).isoformat(),
    }


repository = NotificationRepository()
