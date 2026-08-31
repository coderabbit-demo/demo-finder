from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import SearchLog
from ..services.search import search as run_search

router = APIRouter(tags=["search"])


class SearchIn(BaseModel):
    query: str


@router.post("/search")
async def nl_search(body: SearchIn, session: AsyncSession = Depends(get_session)):
    result = await run_search(session, body.query)
    session.add(SearchLog(query=body.query, parsed_intent=result["intent"],
                          results=result["results"]))
    await session.commit()
    return result
