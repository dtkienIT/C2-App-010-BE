from fastapi import APIRouter, Query

from backend.core.errors import ok
from backend.newsfeed import service

router = APIRouter(prefix='/newsfeed', tags=['newsfeed'])


@router.get('')
def get_newsfeed(limit: int = Query(default=8, ge=1, le=20)):
    return ok(service.get_newsfeed(limit=limit))
