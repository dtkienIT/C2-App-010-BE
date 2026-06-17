from fastapi import APIRouter, Query

from backend.core.errors import ok
from backend.newsfeed import service
from backend.newsfeed.schemas import BreakQuestRequest

router = APIRouter(prefix='/newsfeed', tags=['newsfeed'])


@router.get('')
def get_newsfeed(limit: int = Query(default=8, ge=1, le=20)):
    return ok(service.get_newsfeed(limit=limit))


@router.post('/break-quest')
def generate_break_quest(payload: BreakQuestRequest):
    return ok(service.generate_break_quest(payload.article.model_dump()))


@router.get('/motivational-lines')
def get_motivational_lines():
    return ok(service.generate_motivational_lines())
