from fastapi import APIRouter, Depends, Query

from backend.core.errors import ok
from backend.core.security import get_current_user_id
from backend.quizzes import service
from backend.quizzes.schemas import GeneratedQuizAttemptCreate, QuizAttemptCreate

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.get("")
def list_quizzes(_user_id: str = Depends(get_current_user_id)):
    return ok(service.list_quizzes())


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, _user_id: str = Depends(get_current_user_id)):
    return ok(service.get_attempt(attempt_id))


@router.get("/generate")
def generate_quiz(
    count: int = Query(default=10, ge=1, le=50),
    difficulty: str = "beginner",
    questionTypes: str = "meaning,reverse,pronunciation,type,fill_blank",
    user_id: str = Depends(get_current_user_id),
):
    question_types = [item.strip() for item in questionTypes.split(",") if item.strip()]
    return ok(service.generate_quiz(user_id, count, difficulty, question_types))


@router.post("/generated/attempts")
def submit_generated_attempt(payload: GeneratedQuizAttemptCreate, user_id: str = Depends(get_current_user_id)):
    answers = [answer.model_dump() for answer in payload.answers]
    return ok(service.submit_generated_attempt(user_id, payload.quizId, answers))


@router.get("/{quiz_id}")
def get_quiz(quiz_id: str, _user_id: str = Depends(get_current_user_id)):
    return ok(service.get_quiz(quiz_id))


@router.post("/{quiz_id}/attempts")
def submit_attempt(quiz_id: str, payload: QuizAttemptCreate, user_id: str = Depends(get_current_user_id)):
    answers = [answer.model_dump() for answer in payload.answers]
    return ok(service.submit_attempt(user_id, quiz_id, answers))
