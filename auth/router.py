from fastapi import APIRouter, Depends

from backend.auth import service
from backend.auth.schemas import AuthRequest
from backend.core.errors import ok
from backend.core.security import get_current_user_id

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: AuthRequest):
    return ok(service.register(payload.email, payload.password))


@router.post("/login")
def login(payload: AuthRequest):
    return ok(service.login(payload.email, payload.password))


@router.get("/me")
def me(user_id: str = Depends(get_current_user_id)):
    return ok(service.me(user_id))


@router.post("/logout")
def logout():
    return ok({"loggedOut": True})

