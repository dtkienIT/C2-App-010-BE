from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from backend.core.config import settings


@dataclass(frozen=True)
class PushSendResult:
    status: str
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_permanent(self) -> bool:
        return self.status == "permanent"

    @property
    def is_transient(self) -> bool:
        return self.status == "transient"

    @property
    def is_configuration_error(self) -> bool:
        return self.status == "configuration"


class WebPushClient:
    def send(self, subscription: dict[str, Any], payload: dict[str, str]) -> PushSendResult:
        if not settings.web_push_enabled:
            return PushSendResult("configuration", "web_push_disabled", "Web Push is disabled")
        if not settings.web_push_vapid_private_key or not settings.web_push_vapid_subject:
            return PushSendResult("configuration", "vapid_not_configured", "VAPID private key and subject are required")

        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            return PushSendResult("configuration", "pywebpush_missing", "pywebpush is not installed")

        subscription_info = {
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["p256dh_key"],
                "auth": subscription["auth_key"],
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=settings.web_push_vapid_private_key,
                vapid_claims={"sub": settings.web_push_vapid_subject},
                ttl=max(60, settings.web_push_ttl_seconds),
                headers={"Urgency": "high"},
            )
            return PushSendResult("success")
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            message = safe_message(exc)
            if status_code in {404, 410}:
                return PushSendResult("permanent", f"http_{status_code}", message)
            if status_code == 429 or (status_code is not None and status_code >= 500):
                return PushSendResult("transient", f"http_{status_code}", message)
            if status_code in {400, 401, 403}:
                return PushSendResult("configuration", f"http_{status_code}", message)
            return PushSendResult("transient", f"http_{status_code or 'unknown'}", message)
        except Exception as exc:  # pragma: no cover - defensive SDK boundary.
            return PushSendResult("transient", type(exc).__name__, safe_message(exc))


def safe_message(exc: Exception) -> str:
    message = str(exc)
    if len(message) > 500:
        return f"{message[:497]}..."
    return message


client = WebPushClient()
