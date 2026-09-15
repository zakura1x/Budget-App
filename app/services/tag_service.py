"""
tag_service - tags, and the delete that leaves nothing pointing at a tag
that is gone (TXN-10).

A tag is a label that cuts ACROSS categories - "Boracay trip", "wedding" -
so one purchase can carry several and a category never implies one. Its id
lives inside every transaction payload that uses it (`tag_ids`), where no
foreign key can reach, so:

  * transaction_service checks every id against this user's tags on write
    (`known_ids`), the same rule it keeps for category_id;
  * deleting a tag WALKS EVERY TRANSACTION and drops the id, in the same
    database transaction as the delete (CAT-08's rule, for tags). There is
    nothing to reassign: a transaction without that tag is still complete.

Deleting is soft, like every other row.
"""

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Set

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, NotFoundException, ValidationException
from app.db.repositories.recurring_repository import RecurringRuleRepository
from app.db.repositories.tag_repository import TagRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import audit_service

NAME_MAX = 30
MAX_TAGS = 100
DEFAULT_COLOUR = "#6E7B8B"


@dataclass(frozen=True)
class TagView:
    id: int
    name: str
    colour: str
    usage: int = 0  # transactions carrying this tag


# ------------------------------------------------------------------ reading


def list_tags(db: Session, cipher: UserCipher, *, with_usage: bool = False) -> List[TagView]:
    """Alphabetical - a tag list has no order worth dragging into."""
    views = [_view(record.id, record.data) for record in TagRepository(db, cipher).list()]
    if with_usage:
        usage = _usage_counts(db, cipher)
        views = [replace(view, usage=usage.get(view.id, 0)) for view in views]
    return sorted(views, key=lambda v: (v.name.casefold(), v.id))


def known_ids(db: Session, cipher: UserCipher) -> Set[int]:
    """Every live tag id this user has - what a transaction's tag_ids are checked against."""
    return {record.id for record in TagRepository(db, cipher).list()}


# ------------------------------------------------------------------ writing


def create_tag(db: Session, cipher: UserCipher, payload: Mapping[str, Any]) -> TagView:
    repo = TagRepository(db, cipher)
    existing = repo.list()
    if len(existing) >= MAX_TAGS:
        raise BusinessRuleException(f"At most {MAX_TAGS} tags")
    data = _clean(payload, existing=None, siblings=existing, tag_id=None)
    record = repo.create(data)
    audit_service.record(
        db, audit_service.CREATE, user_id=cipher.user_id, entity="tags",
        entity_id=record.id, cipher=cipher, detail={"name": data["name"]},
    )
    db.commit()
    return _view(record.id, record.data)


def update_tag(db: Session, cipher: UserCipher, tag_id: int, payload: Mapping[str, Any]) -> TagView:
    repo = TagRepository(db, cipher)
    record = repo.get(tag_id)
    if record is None:
        raise NotFoundException("Tag not found")
    data = _clean(payload, existing=record.data, siblings=repo.list(), tag_id=tag_id)
    updated = repo.update(tag_id, data)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="tags",
        entity_id=tag_id, cipher=cipher, detail={"name": data["name"]},
    )
    db.commit()
    return _view(tag_id, updated.data)


def delete_tag(db: Session, cipher: UserCipher, tag_id: int) -> Dict[str, Any]:
    """
    Delete a tag and take its id out of every transaction that carried it -
    all in one database transaction, so there is no moment at which a
    transaction names a tag that does not exist.
    """
    repo = TagRepository(db, cipher)
    record = repo.get(tag_id)
    if record is None:
        raise NotFoundException("Tag not found")

    transactions = TransactionRepository(db, cipher)
    untagged = 0
    # Read from the working set; each update is written through to it on commit.
    for row in transactions.cached():
        ids = row.data.get("tag_ids") or []
        if tag_id not in ids:
            continue
        transactions.update(row.id, {**row.data, "tag_ids": [i for i in ids if i != tag_id]})
        untagged += 1
    # A recurring rule copies its tags into everything it posts (REC-03).
    rules = RecurringRuleRepository(db, cipher)
    for rule in rules.list():
        ids = rule.data.get("tag_ids") or []
        if tag_id in ids:
            rules.update(rule.id, {**rule.data, "tag_ids": [i for i in ids if i != tag_id]})

    repo.soft_delete(tag_id)
    audit_service.record(
        db, audit_service.DELETE, user_id=cipher.user_id, entity="tags", entity_id=tag_id,
        cipher=cipher, detail={"name": record.data.get("name"), "transactions_untagged": untagged},
    )
    db.commit()
    return {"deleted": tag_id, "transactions_untagged": untagged}


# ---------------------------------------------------------------- internals


def _usage_counts(db: Session, cipher: UserCipher) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for record in TransactionRepository(db, cipher).cached():
        for tag_id in set(record.data.get("tag_ids") or ()):
            counts[tag_id] = counts.get(tag_id, 0) + 1
    return counts


def _view(tag_id: int, data: Mapping[str, Any]) -> TagView:
    return TagView(id=tag_id, name=str(data.get("name", "")), colour=str(data.get("colour") or DEFAULT_COLOUR))


def _clean(
    payload: Mapping[str, Any],
    existing: Optional[Mapping[str, Any]],
    siblings: List,
    tag_id: Optional[int],
) -> Dict[str, Any]:
    name = " ".join(str(payload.get("name") or "").split())
    if not name:
        raise ValidationException("A tag needs a name")
    if len(name) > NAME_MAX:
        raise ValidationException(f"A tag name is at most {NAME_MAX} characters")
    lowered = name.casefold()
    for record in siblings:
        if record.id != tag_id and str(record.data.get("name", "")).casefold() == lowered:
            raise BusinessRuleException(f"You already have a tag called {name}")

    colour = payload.get("colour")
    if colour is None:
        colour = (existing or {}).get("colour") or DEFAULT_COLOUR
    text = str(colour).strip()
    if len(text) != 7 or not text.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in text[1:]):
        raise ValidationException("A colour is #RRGGBB")
    return {**(existing or {}), "name": name, "colour": text.upper()}
