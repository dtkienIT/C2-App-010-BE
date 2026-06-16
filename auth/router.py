from fastapi import APIRouter, Depends, Request

from backend.auth import service
from backend.auth.schemas import AuthRequest, ResendVerificationOtpRequest, VerifyEmailRequest
from backend.core.errors import ok
from backend.core.security import get_current_user_id

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: AuthRequest, request: Request):
    return ok(service.register(payload.email, payload.password, request))


@router.post("/login")
def login(payload: AuthRequest):
    return ok(service.login(payload.email, payload.password))


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest):
    return ok(service.verify_email(payload.verification_session_id, payload.otp))


@router.post("/resend-verification-otp")
def resend_verification_otp(payload: ResendVerificationOtpRequest, request: Request):
    return ok(service.resend_verification_otp(payload.verification_session_id, request))


@router.get("/me")
def me(user_id: str = Depends(get_current_user_id)):
    return ok(service.me(user_id))


@router.post("/logout")
def logout():
    return ok({"loggedOut": True})
