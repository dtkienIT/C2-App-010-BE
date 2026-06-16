from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import hmac
import secrets
import smtplib
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, status

from backend.core.config import settings
from backend.notifications.email_client import authenticate, escape_html, format_sender, safe_message


OTP_WINDOW_SECONDS = 15 * 60
_ip_send_windows: dict[str, list[datetime]] = {}


@dataclass(frozen=True)
class OtpEmailResult:
    status: str
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "success"


class EmailOtpClient:
    def send(self, recipient: str, otp: str) -> OtpEmailResult:
        if not settings.email_notifications_enabled:
            return OtpEmailResult("configuration", "email_disabled", "Email notifications are disabled")
        if not settings.smtp_host or not settings.smtp_from_email:
            return OtpEmailResult("configuration", "smtp_not_configured", "SMTP host and from email are required")

        message = build_otp_message(recipient, otp)
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
            return OtpEmailResult("success")
        except Exception as exc:  # pragma: no cover - SMTP boundary.
            return OtpEmailResult("transient", type(exc).__name__, safe_message(exc))


def build_otp_message(recipient: str, otp: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Ma xac thuc tai khoan Study Buddy"
    message["From"] = format_sender()
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                "Xin chao,",
                "",
                "Ma xac thuc tai khoan Study Buddy cua ban la:",
                "",
                otp,
                "",
                f"Ma nay co hieu luc trong {settings.otp_expires_minutes} phut. Khong chia se ma nay voi bat ky ai.",
                "",
                "Neu ban khong thuc hien yeu cau dang ky, ban co the bo qua email nay.",
            ]
        )
    )
    message.add_alternative(
        f"""
        <html>
          <body style="margin:0;background:#f6f7fb;font-family:Arial,sans-serif;color:#172033">
            <div style="max-width:560px;margin:0 auto;padding:28px 16px">
              <div style="background:#ffffff;border-radius:18px;padding:28px;border:1px solid #e5e7eb">
                <p style="font-size:14px;color:#6b7280;margin:0 0 12px">Study Buddy</p>
                <h1 style="font-size:24px;margin:0 0 16px">Xac thuc email cua ban</h1>
                <p style="font-size:15px;line-height:1.6">Nhap ma 6 chu so duoi day de hoan tat dang ky.</p>
                <div style="font-size:36px;letter-spacing:10px;font-weight:800;text-align:center;background:#f3f4f6;border-radius:14px;padding:18px;margin:22px 0">{escape_html(otp)}</div>
                <p style="font-size:14px;line-height:1.6">Ma nay co hieu luc trong {settings.otp_expires_minutes} phut. Khong chia se ma nay voi bat ky ai.</p>
                <p style="font-size:13px;color:#6b7280;line-height:1.6">Neu ban khong thuc hien yeu cau dang ky, ban co the bo qua email nay.</p>
              </div>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )
    return message


def generate_otp() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(6))


def hash_otp(otp: str, verification_session_id: str) -> str:
    key = settings.otp_pepper.encode("utf-8")
    message = f"{verification_session_id}:{otp}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def otp_matches(otp: str, verification_session_id: str, otp_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(otp, verification_session_id), otp_hash)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def otp_error(code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def check_ip_rate_limit(ip: str) -> None:
    current = now_utc()
    window_start = current - timedelta(seconds=OTP_WINDOW_SECONDS)
    entries = [item for item in _ip_send_windows.get(ip, []) if item >= window_start]
    if len(entries) >= settings.otp_max_sends_per_15_minutes:
        _ip_send_windows[ip] = entries
        raise otp_error("OTP_RATE_LIMITED", "Ban da yeu cau qua nhieu ma xac thuc. Vui long thu lai sau.", status.HTTP_429_TOO_MANY_REQUESTS)
    entries.append(current)
    _ip_send_windows[ip] = entries


def new_session_id() -> str:
    return str(uuid4())


otp_email_client = EmailOtpClient()
