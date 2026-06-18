from datetime import timedelta
from typing import Any

from fastapi import Request, status
from fastapi import HTTPException

from backend.auth.email_otp import (
    check_ip_rate_limit,
    client_ip,
    generate_otp,
    hash_otp,
    new_session_id,
    now_utc,
    otp_email_client,
    otp_error,
    otp_matches,
)
from backend.core.config import settings
from backend.core.security import create_access_token
from backend.database.store import parse_datetime
from backend.database.store import public_user, store


def issue_token(user: dict[str, Any], daily_check_in: dict[str, Any] | None = None) -> dict[str, object]:
    token = create_access_token(str(user["id"]), {"email": user["email"], "role": user.get("role", "student")})
    response: dict[str, object] = {"access_token": token, "token_type": "bearer", "user": public_user(user)}
    if daily_check_in is not None:
        response["dailyCheckIn"] = daily_check_in
    return response


def is_verified(user: dict[str, Any]) -> bool:
    return bool(user.get("is_email_verified") or user.get("email_verified_at") or user.get("status") == "active")


def ensure_can_send_otp(user_id: str, request: Request | None, enforce_cooldown: bool = True) -> None:
    latest = store.get_latest_email_otp_for_user(user_id)
    if enforce_cooldown and latest and not latest.get("used_at") and not latest.get("locked_at"):
        elapsed = (now_utc() - parse_datetime(latest["last_sent_at"])).total_seconds()
        if elapsed < settings.otp_resend_cooldown_seconds:
            raise otp_error("OTP_RESEND_TOO_SOON", "Vui long doi truoc khi yeu cau gui lai ma.", status.HTTP_429_TOO_MANY_REQUESTS)

    since = now_utc() - timedelta(minutes=15)
    if store.count_recent_email_otps_for_user(user_id, since) >= settings.otp_max_sends_per_15_minutes:
        raise otp_error("OTP_RATE_LIMITED", "Ban da yeu cau qua nhieu ma xac thuc. Vui long thu lai sau.", status.HTTP_429_TOO_MANY_REQUESTS)
    check_ip_rate_limit(client_ip(request))


def create_and_send_otp(user: dict[str, Any], request: Request | None, enforce_cooldown: bool = True) -> dict[str, object]:
    user_id = str(user["id"])
    ensure_can_send_otp(user_id, request, enforce_cooldown=enforce_cooldown)
    verification_session_id = new_session_id()
    otp = generate_otp()
    expires_at = now_utc() + timedelta(minutes=settings.otp_expires_minutes)

    store.invalidate_pending_email_otps(user_id)
    store.create_email_verification_otp(
        user_id=user_id,
        verification_session_id=verification_session_id,
        otp_hash=hash_otp(otp, verification_session_id),
        expires_at=expires_at,
    )

    result = otp_email_client.send(str(user["email"]), otp)
    if not result.is_success:
        store.update_email_verification_otp(verification_session_id, {"used_at": now_utc()})
        raise otp_error("EMAIL_SEND_FAILED", "Chua gui duoc email xac thuc. Vui long thu lai.", status.HTTP_503_SERVICE_UNAVAILABLE)

    return {
        "message": "Ma xac thuc da duoc gui den email cua ban.",
        "verification_required": True,
        "verification_session_id": verification_session_id,
        "email": user["email"],
    }


def register(email: str, password: str, request: Request | None = None) -> dict[str, object]:
    normalized_email = email.strip().lower()
    existing = store.get_user_by_email(normalized_email)
    if existing:
        if is_verified(existing):
            raise otp_error("EMAIL_ALREADY_REGISTERED", "Email nay da duoc dang ky.", status.HTTP_409_CONFLICT)
        return create_and_send_otp(existing, request, enforce_cooldown=True)

    user = store.register_user(email=normalized_email, password=password)
    return create_and_send_otp(user, request, enforce_cooldown=False)


def login(email: str, password: str) -> dict[str, object]:
    user = store.authenticate_user(email=email, password=password)
    if not is_verified(user):
        latest = store.get_latest_email_otp_for_user(str(user["id"]))
        details = {"code": "EMAIL_NOT_VERIFIED", "message": "Email cua ban chua duoc xac thuc."}
        if latest:
            details["verification_session_id"] = str(latest["verification_session_id"])
            details["email"] = user["email"]
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=details)
    daily_check_in = store.get_stats_with_daily_check_in(str(user["id"]))["dailyCheckIn"]
    return issue_token(user, daily_check_in)


def verify_email(verification_session_id: str, otp: str) -> dict[str, object]:
    row = store.get_email_verification_otp(verification_session_id)
    if not row:
        raise otp_error("VERIFICATION_SESSION_INVALID", "Phien xac thuc khong hop le.", status.HTTP_404_NOT_FOUND)
    user = store.get_user(str(row["user_id"]))
    if is_verified(user):
        raise otp_error("OTP_ALREADY_USED", "Email nay da duoc xac thuc.")
    if row.get("used_at"):
        raise otp_error("OTP_ALREADY_USED", "Ma xac thuc da duoc su dung.")
    if row.get("locked_at") or int(row.get("attempt_count") or 0) >= settings.otp_max_attempts:
        raise otp_error("OTP_MAX_ATTEMPTS_EXCEEDED", "Ban da nhap sai qua so lan cho phep. Vui long yeu cau ma moi.", status.HTTP_429_TOO_MANY_REQUESTS)
    if parse_datetime(row["expires_at"]) <= now_utc():
        raise otp_error("OTP_EXPIRED", "Ma xac thuc da het han. Vui long yeu cau ma moi.")

    if not otp_matches(otp, verification_session_id, str(row["otp_hash"])):
        next_attempt_count = int(row.get("attempt_count") or 0) + 1
        patch: dict[str, Any] = {"attempt_count": next_attempt_count}
        if next_attempt_count >= settings.otp_max_attempts:
            patch["locked_at"] = now_utc()
            store.update_email_verification_otp(verification_session_id, patch)
            raise otp_error("OTP_MAX_ATTEMPTS_EXCEEDED", "Ban da nhap sai qua so lan cho phep. Vui long yeu cau ma moi.", status.HTTP_429_TOO_MANY_REQUESTS)
        store.update_email_verification_otp(verification_session_id, patch)
        raise otp_error("OTP_INVALID", "Ma xac thuc khong dung.")

    store.update_email_verification_otp(verification_session_id, {"used_at": now_utc()})
    verified_user = store.mark_email_verified(str(user["id"]))
    daily_check_in = store.get_stats_with_daily_check_in(str(user["id"]))["dailyCheckIn"]
    return issue_token(verified_user, daily_check_in)


def resend_verification_otp(verification_session_id: str, request: Request | None = None) -> dict[str, object]:
    row = store.get_email_verification_otp(verification_session_id)
    if not row:
        raise otp_error("VERIFICATION_SESSION_INVALID", "Phien xac thuc khong hop le.", status.HTTP_404_NOT_FOUND)
    user = store.get_user(str(row["user_id"]))
    if is_verified(user):
        raise otp_error("OTP_ALREADY_USED", "Email nay da duoc xac thuc.")
    return create_and_send_otp(user, request, enforce_cooldown=True)


def me(user_id: str) -> dict[str, object]:
    daily_result = store.get_stats_with_daily_check_in(user_id)
    return {**public_user(store.get_user(user_id)), "dailyCheckIn": daily_result["dailyCheckIn"]}
