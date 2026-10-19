from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user
from app.modules.comments.schemas import CommentCreate
from app.modules.comments.service import comment_view, create_comment, list_comments

router = APIRouter(tags=["Comments"])


@router.get("/issues/{identifier}/comments")
async def comments(identifier: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return {"data": [comment_view(c) for c in await list_comments(session, user, identifier)]}


@router.post("/issues/{identifier}/comments", status_code=201)
async def comment_create(identifier: str, payload: CommentCreate, request: Request,
                         session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    comment = await create_comment(session, user, identifier, payload.content, getattr(request.state, "request_id", None))
    return {"data": comment_view(comment)}
