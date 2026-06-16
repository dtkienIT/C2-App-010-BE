from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
from typing import Any

from backend.core.config import settings


@dataclass(frozen=True)
class EmailSendResult:
    status: str
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_skipped(self) -> bool:
        return self.status == "skipped"

    @property
    def is_configuration_error(self) -> bool:
        return self.status == "configuration"

    @property
    def is_transient(self) -> bool:
        return self.status == "transient"


class StudyReminderEmailClient:
    def send(self, profile: dict[str, Any], payload: dict[str, Any]) -> EmailSendResult:
        if not settings.email_notifications_enabled:
            return EmailSendResult("skipped", "email_disabled", "Email notifications are disabled")
        if not settings.smtp_host or not settings.smtp_from_email:
            return EmailSendResult("configuration", "smtp_not_configured", "SMTP host and from email are required")

        recipient = str(profile.get("email") or "").strip()
        if not recipient:
            return EmailSendResult("configuration", "recipient_email_missing", "Learner email is missing")

        message = build_message(profile, payload, recipient)
        try:
            if settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as smtp:
                    authenticate(smtp)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as smtp:
                    smtp.ehlo()
                    if settings.smtp_use_tls:
                        smtp.starttls()
                        smtp.ehlo()
                    authenticate(smtp)
                    smtp.send_message(message)
            return EmailSendResult("success")
        except Exception as exc:  # pragma: no cover - SMTP/network boundary.
            return EmailSendResult("transient", type(exc).__name__, safe_message(exc))


def authenticate(smtp: smtplib.SMTP) -> None:
    if settings.smtp_username:
        smtp.login(settings.smtp_username, settings.smtp_password)


def build_message(profile: dict[str, Any], payload: dict[str, Any], recipient: str) -> EmailMessage:
    title = str(payload.get("title") or "Đến giờ học rồi!")
    body = str(payload.get("body") or "Buddy đang chờ bạn. Bắt đầu một phiên tập trung ngắn nhé!")
    display_name = str(profile.get("display_name") or profile.get("name") or recipient.split("@")[0])
    target_url = absolute_target_url(str(payload.get("targetUrl") or "/buddy-room"))

    message = EmailMessage()
    message["Subject"] = title
    message["From"] = format_sender()
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                f"Chào {display_name},",
                "",
                body,
                "",
                f"Vào học ngay: {target_url}",
                "",
                "Study Buddy",
            ]
        )
    )
    message.add_alternative(
        f"""
        <html>
          <body>
            <p>Chào {escape_html(display_name)},</p>
            <p>{escape_html(body)}</p>
            <p><a href="{escape_html(target_url)}">Vào học ngay</a></p>
            <p>Study Buddy</p>
          </body>
        </html>
        """,
        subtype="html",
    )
    return message


def format_sender() -> str:
    name = settings.smtp_from_name.strip()
    email = settings.smtp_from_email.strip()
    return f"{name} <{email}>" if name else email


def absolute_target_url(target_url: str) -> str:
    base_url = settings.frontend_base_url.rstrip("/") or "http://localhost:5173"
    if target_url.startswith("/"):
        return f"{base_url}{target_url}"
    return base_url


def escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def safe_message(exc: Exception) -> str:
    message = str(exc)
    if len(message) > 500:
        return f"{message[:497]}..."
    return message


client = StudyReminderEmailClient()
