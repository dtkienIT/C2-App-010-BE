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


class PurchaseModelPayload(BaseModel):
    modelId: str | None = None
    model_id: str | None = None


class PurchaseBackgroundPayload(BaseModel):
    backgroundId: str | None = None
    background_id: str | None = None


class BuddyRewardApplyPayload(BaseModel):
    activityType: str = "mini_quiz"
    attemptId: str | None = None
    difficulty: str | None = "beginner"
    totalQuestions: int | None = None
    correctAnswers: int | None = None
    durationSeconds: int | None = None
    source: str | None = None

