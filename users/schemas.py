from pydantic import BaseModel


class ProfilePatch(BaseModel):
    displayName: str | None = None
    display_name: str | None = None
    avatarUrl: str | None = None
    avatar_url: str | None = None

