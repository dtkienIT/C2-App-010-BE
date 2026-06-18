from pydantic import BaseModel


class QuizAnswer(BaseModel):
    questionId: str
    selectedOptionId: str


class QuizAttemptCreate(BaseModel):
    answers: list[QuizAnswer]
    submissionToken: str | None = None


class GeneratedQuizAttemptCreate(BaseModel):
    quizId: str
    answers: list[QuizAnswer]
    submissionToken: str | None = None
