from __future__ import annotations

from datetime import time
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from backend.notifications.constants import (
    AUTH_MAX_LENGTH,
    AUTH_MIN_LENGTH,
    ENDPOINT_MAX_LENGTH,
    ENDPOINT_MIN_LENGTH,
    INSTALLATION_ID_MAX_LENGTH,
    INSTALLATION_ID_MIN_LENGTH,
    P256DH_MAX_LENGTH,
    P256DH_MIN_LENGTH,
)
from backend.notifications.reminder_time import parse_reminder_time, validate_days_of_week, validate_timezone


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=P256DH_MIN_LENGTH, max_length=P256DH_MAX_LENGTH)
    auth: str = Field(min_length=AUTH_MIN_LENGTH, max_length=AUTH_MAX_LENGTH)


class PushSubscriptionRequest(BaseModel):
    installation_id: str = Field(min_length=INSTALLATION_ID_MIN_LENGTH, max_length=INSTALLATION_ID_MAX_LENGTH)
    endpoint: str = Field(min_length=ENDPOINT_MIN_LENGTH, max_length=ENDPOINT_MAX_LENGTH)
    keys: PushSubscriptionKeys
    content_encoding: str | None = Field(default="aes128gcm", max_length=32)
    platform: str = Field(default="web", min_length=1, max_length=32)

    @field_validator("installation_id")
    @classmethod
    def validate_installation_id(cls, value: str) -> str:
        value = value.strip()
        try:
            UUID(value)
        except ValueError as exc:
            raise ValueError("installation_id must be a UUID") from exc
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("https://"):
            raise ValueError("endpoint must be HTTPS")
        return value

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        return value.strip().lower() or "web"


class SubscriptionDeactivateRequest(BaseModel):
    installation_id: str = Field(min_length=INSTALLATION_ID_MIN_LENGTH, max_length=INSTALLATION_ID_MAX_LENGTH)

    @field_validator("installation_id")
    @classmethod
    def validate_installation_id(cls, value: str) -> str:
        value = value.strip()
        try:
            UUID(value)
        except ValueError as exc:
            raise ValueError("installation_id must be a UUID") from exc
        return value


class StudyReminderCreateRequest(BaseModel):
    reminder_time: str
    days_of_week: list[int]
    timezone: str
    is_enabled: bool = True

    @field_validator("reminder_time")
    @classmethod
    def validate_reminder_time(cls, value: str) -> str:
        parsed = parse_reminder_time(value)
        return parsed.strftime("%H:%M")

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        return validate_days_of_week(value)

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, value: str) -> str:
        return validate_timezone(value)

    @property
    def parsed_time(self) -> time:
        return parse_reminder_time(self.reminder_time)


class StudyReminderUpdateRequest(BaseModel):
    reminder_time: str | None = None
    days_of_week: list[int] | None = None
    timezone: str | None = None
    is_enabled: bool | None = None

    @field_validator("reminder_time")
    @classmethod
    def validate_reminder_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = parse_reminder_time(value)
        return parsed.strftime("%H:%M")

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        return validate_days_of_week(value)

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_timezone(value)
