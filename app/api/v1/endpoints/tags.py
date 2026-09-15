"""
/tags - the labels that cut across categories (TXN-10).

DELETE needs no question, unlike a category: a transaction that loses a tag is
still a complete transaction. The response says how many lost it.
"""

from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.tags import TagDeletedOut, TagIn, TagOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import tag_service

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=List[TagOut])
def list_tags(
    with_usage: bool = Query(default=False, description="count the transactions carrying each one"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[TagOut]:
    return [TagOut.model_validate(view) for view in tag_service.list_tags(db, ctx.cipher, with_usage=with_usage)]


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    body: TagIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> TagOut:
    return TagOut.model_validate(tag_service.create_tag(db, ctx.cipher, body.model_dump(exclude_unset=True)))


@router.patch("/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: int,
    body: TagIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> TagOut:
    return TagOut.model_validate(tag_service.update_tag(db, ctx.cipher, tag_id, body.model_dump(exclude_unset=True)))


@router.delete("/{tag_id}", response_model=TagDeletedOut)
def delete_tag(
    tag_id: int,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> TagDeletedOut:
    return TagDeletedOut(**tag_service.delete_tag(db, ctx.cipher, tag_id))
