"""Request and response shapes for /tags (TXN-10)."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import Colour


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    colour: Optional[Colour] = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    colour: str
    usage: int = 0


class TagDeletedOut(BaseModel):
    """What a delete did - how many transactions lost the tag."""

    deleted: int
    transactions_untagged: int
