"""Request and response shapes for /categories (CAT-01..CAT-08)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import Colour, IconName

CategoryKind = Literal["expense", "income"]


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    kind: CategoryKind = "expense"
    parent_id: Optional[int] = None  # one level only (CAT-02)
    icon: Optional[IconName] = None
    colour: Optional[Colour] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=9999)
    archived: bool = False


class ReorderIn(BaseModel):
    """CAT-06 - the ids in the order they were dragged into."""

    ordered_ids: List[int] = Field(min_length=1, max_length=300)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: CategoryKind
    parent_id: Optional[int] = None
    icon: str
    colour: str
    sort_order: int
    archived: bool
    usage: int = 0
    children: List["CategoryOut"] = []


class CategoryDeletedOut(BaseModel):
    """What a delete actually did - including the sub-categories it took."""

    deleted: List[int]
    transactions_moved: int
    reassigned_to: Optional[int] = None
