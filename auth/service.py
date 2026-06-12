from backend.core.security import create_access_token
from backend.database.store import public_user, store


def register(email: str, password: str) -> dict[str, object]:
    user = store.register_user(email=email, password=password)
    token = create_access_token(str(user["id"]), {"email": user["email"], "role": user.get("role", "student")})
    return {"access_token": token, "token_type": "bearer", "user": public_user(user)}


def login(email: str, password: str) -> dict[str, object]:
    user = store.authenticate_user(email=email, password=password)
    token = create_access_token(str(user["id"]), {"email": user["email"], "role": user.get("role", "student")})
    return {"access_token": token, "token_type": "bearer", "user": public_user(user)}


def me(user_id: str) -> dict[str, object]:
    return public_user(store.get_user(user_id))
