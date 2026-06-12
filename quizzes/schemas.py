from pydantic import BaseModel


class QuizAnswer(BaseModel):
    questionId: str
    selectedOptionId: str


class QuizAttemptCreate(BaseModel):
    answers: list[QuizAnswer]


class GeneratedQuizAttemptCreate(BaseModel):
    quizId: str
    answers: list[QuizAnswer]
