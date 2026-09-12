"""
/categories - the tree, and the delete that has to clean up after itself.

DELETE takes `reassign_to`. Without it, a category that transactions point at
returns 409 CONFLICT carrying the count, and the frontend asks where those
transactions should go (CAT-08). Nothing is orphaned, because nothing but this
service can see the references at all - they are inside the ciphertext.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.categories import CategoryDeletedOut, CategoryIn, CategoryOut, ReorderIn
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=List[CategoryOut])
def list_categories(
    kind: Optional[str] = Query(default=None, pattern="^(expense|income)$"),
    include_archived: bool = Query(default=True),
    with_usage: bool = Query(default=False, description="count the transactions pointing at each one"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[CategoryOut]:
    views = category_service.list_categories(
        db, ctx.cipher, kind=kind, include_archived=include_archived, with_usage=with_usage
    )
    return [CategoryOut.model_validate(view) for view in views]


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> CategoryOut:
    return CategoryOut.model_validate(
        category_service.create_category(db, ctx.cipher, body.model_dump(exclude_unset=True))
    )


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> CategoryOut:
    return CategoryOut.model_validate(
        category_service.update_category(db, ctx.cipher, category_id, body.model_dump(exclude_unset=True))
    )


@router.post("/reorder", response_model=List[CategoryOut])
def reorder(
    body: ReorderIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[CategoryOut]:
    views = category_service.reorder(db, ctx.cipher, body.ordered_ids)
    return [CategoryOut.model_validate(view) for view in views]


@router.delete("/{category_id}", response_model=CategoryDeletedOut)
def delete_category(
    category_id: int,
    reassign_to: Optional[int] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> CategoryDeletedOut:
    result = category_service.delete_category(db, ctx.cipher, category_id, reassign_to=reassign_to)
    return CategoryDeletedOut(**result)
