from pydantic import BaseModel


class ActiveBuddyUpdate(BaseModel):
    buddyId: str | None = None
    buddy_id: str | None = None


class EquippedModelUpdate(BaseModel):
    modelId: str | None = None
    model_id: str | None = None


class RoomBackgroundUpdate(BaseModel):
    backgroundId: str | None = None
    background_id: str | None = None

