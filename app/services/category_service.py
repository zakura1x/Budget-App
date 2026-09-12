"""
category_service - categories, sub-categories, and the two rules no database
can keep for us (CAT-01..CAT-08).

`parent_id` and every reference to a category live INSIDE a ciphertext, so:

  * PARENT/CHILD INTEGRITY is enforced here. One level only (CAT-02): a
    parent must exist, must belong to the same kind, and must not itself be
    a child. A category with children can never become one.

  * DELETE MUST REASSIGN, NEVER ORPHAN (CAT-08). And the reassignment has to
    walk EVERY SPLIT of every transaction, not a top-level field: splits
    (TXN-16) put category_id one level deeper inside the payload, where a
    missed reference is invisible to SQL, to the constraint system, and to
    every report that later reads it.

Deleting is soft (is_deleted) like every other row, so the audit trail and any
backup taken before today stay honest.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import audit_service

KINDS: Tuple[str, ...] = ("expense", "income")

NAME_MAX = 40
MAX_CATEGORIES = 300


@dataclass(frozen=True)
class CategoryView:
    id: int
    name: str
    kind: str
    parent_id: Optional[int]
    icon: str
    colour: str
    sort_order: int
    archived: bool
    children: Tuple["CategoryView", ...] = ()
    usage: int = 0  # transactions pointing at this category, splits included


# ------------------------------------------------------------------ reading


def list_categories(
    db: Session,
    cipher: UserCipher,
    *,
    kind: Optional[str] = None,
    include_archived: bool = True,
    with_usage: bool = False,
) -> List[CategoryView]:
    """
    The tree, parents in sort order with their children nested under them.
    A child whose parent is missing is returned at the top level rather than
    hidden - losing sight of a category is worse than an untidy list.
    """
    records = CategoryRepository(db, cipher).list()
    views = {record.id: _view(record.id, record.data) for record in records}

    usage = _usage_counts(db, cipher) if with_usage else {}
    if usage:
        views = {cid: _replace(view, usage=usage.get(cid, 0)) for cid, view in views.items()}

    roots: List[CategoryView] = []
    children: Dict[int, List[CategoryView]] = {}
    for view in views.values():
        if view.parent_id is not None and view.parent_id in views:
            children.setdefault(view.parent_id, []).append(view)
        else:
            roots.append(view)

    def visible(items: Iterable[CategoryView]) -> List[CategoryView]:
        return [v for v in items if include_archived or not v.archived]

    tree = [
        _replace(root, children=tuple(_sorted(visible(children.get(root.id, ())))))
        for root in _sorted(visible(roots))
    ]
    if kind:
        tree = [view for view in tree if view.kind == kind]
    return tree


def get_category(db: Session, cipher: UserCipher, category_id: int) -> CategoryView:
    record = CategoryRepository(db, cipher).get(category_id)
    if record is None:
        raise NotFoundException("Category not found")
    return _view(record.id, record.data)


# ------------------------------------------------------------------ writing


def create_category(db: Session, cipher: UserCipher, payload: Mapping[str, Any]) -> CategoryView:
    repo = CategoryRepository(db, cipher)
    existing = repo.list()
    if len(existing) >= MAX_CATEGORIES:
        raise BusinessRuleException(f"At most {MAX_CATEGORIES} categories")

    data = _clean(payload, existing=None, siblings=existing, category_id=None)
    if data.get("sort_order") is None:
        data["sort_order"] = _next_sort_order(existing, data["parent_id"])

    record = repo.create(data)
    audit_service.record(
        db, audit_service.CREATE, user_id=cipher.user_id, entity="categories",
        entity_id=record.id, cipher=cipher, detail={"name": data["name"], "kind": data["kind"]},
    )
    db.commit()
    return _view(record.id, record.data)


def update_category(db: Session, cipher: UserCipher, category_id: int, payload: Mapping[str, Any]) -> CategoryView:
    repo = CategoryRepository(db, cipher)
    record = repo.get(category_id)
    if record is None:
        raise NotFoundException("Category not found")

    existing = repo.list()
    data = _clean(payload, existing=record.data, siblings=existing, category_id=category_id)

    if data["parent_id"] is not None and _children_of(existing, category_id):
        # One level (CAT-02). Letting this through would create a grandchild
        # the UI cannot show and the budget roll-up would double-count.
        raise BusinessRuleException("This category has sub-categories, so it cannot become one")

    updated = repo.update(category_id, data)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="categories",
        entity_id=category_id, cipher=cipher, detail={"name": data["name"], "kind": data["kind"]},
    )
    db.commit()
    return _view(category_id, updated.data)


def reorder(db: Session, cipher: UserCipher, ordered_ids: Sequence[int]) -> List[CategoryView]:
    """CAT-06. The order the user dragged them into, written in one go."""
    repo = CategoryRepository(db, cipher)
    by_id = {record.id: record for record in repo.list()}
    unknown = [cid for cid in ordered_ids if cid not in by_id]
    if unknown:
        raise NotFoundException("Category not found")

    for position, category_id in enumerate(ordered_ids):
        record = by_id[category_id]
        if int(record.data.get("sort_order") or 0) == position:
            continue  # nothing to re-seal
        data = dict(record.data)
        data["sort_order"] = position
        repo.update(category_id, data)

    audit_service.record(
        db, audit_service.REORDER, user_id=cipher.user_id, entity="categories",
        cipher=cipher, detail={"count": len(ordered_ids)},
    )
    db.commit()
    return list_categories(db, cipher)


def delete_category(
    db: Session,
    cipher: UserCipher,
    category_id: int,
    *,
    reassign_to: Optional[int] = None,
) -> Dict[str, Any]:
    """
    CAT-08. Delete a category, moving everything that pointed at it somewhere
    real first - or refuse, and say how many transactions are in the way.

    Deleting a parent takes its sub-categories with it: a child of a category
    that no longer exists is exactly the orphan this rule exists to prevent.
    Everything that pointed at the parent OR at any of those children is
    reassigned in the same transaction.
    """
    repo = CategoryRepository(db, cipher)
    record = repo.get(category_id)
    if record is None:
        raise NotFoundException("Category not found")

    existing = repo.list()
    doomed: Set[int] = {category_id} | {child.id for child in _children_of(existing, category_id)}

    usage = _usage_counts(db, cipher)
    in_use = sum(usage.get(cid, 0) for cid in doomed)

    if in_use:
        if reassign_to is None:
            raise ConflictException(
                "Choose a category to move these transactions to",
                extra={"usage": in_use, "category_ids": sorted(doomed)},
            )
        if reassign_to in doomed:
            raise BusinessRuleException("Choose a category that is not being deleted")
        target = repo.get(reassign_to)
        if target is None:
            raise NotFoundException("The category to move them to does not exist")
        if target.data.get("kind") != record.data.get("kind"):
            # An expense moved onto an income category would flip its sign in
            # every report that reads it.
            raise BusinessRuleException("Move them to a category of the same kind")
        moved = _reassign(db, cipher, doomed, reassign_to)
    else:
        moved = 0

    for cid in sorted(doomed):
        repo.soft_delete(cid)

    audit_service.record(
        db, audit_service.DELETE, user_id=cipher.user_id, entity="categories",
        entity_id=category_id, cipher=cipher,
        detail={"name": record.data.get("name"), "also_deleted": sorted(doomed - {category_id}),
                "reassigned_to": reassign_to, "transactions_moved": moved},
    )
    db.commit()
    return {"deleted": sorted(doomed), "transactions_moved": moved, "reassigned_to": reassign_to}


# ---------------------------------------------------------------- the walk


def _usage_counts(db: Session, cipher: UserCipher) -> Dict[int, int]:
    """
    How many transactions point at each category - counting SPLITS, which is
    the whole point (TXN-16). A transaction is counted once per category it
    touches, so a two-way split of one purchase counts against both.
    """
    counts: Dict[int, int] = {}
    for record in TransactionRepository(db, cipher).list():
        for cid in _category_ids(record.data):
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def _category_ids(payload: Mapping[str, Any]) -> Set[int]:
    """Every category this transaction refers to, at either depth."""
    found: Set[int] = set()
    top = payload.get("category_id")
    if isinstance(top, int):
        found.add(top)
    splits = payload.get("splits")
    if isinstance(splits, list):
        for split in splits:
            if isinstance(split, Mapping) and isinstance(split.get("category_id"), int):
                found.add(split["category_id"])
    return found


def _reassign(db: Session, cipher: UserCipher, doomed: Set[int], target: int) -> int:
    """Rewrite every reference to a doomed category. Returns rows touched."""
    repo = TransactionRepository(db, cipher)
    moved = 0
    for record in repo.list():
        if not (_category_ids(record.data) & doomed):
            continue
        data = dict(record.data)
        if data.get("category_id") in doomed:
            data["category_id"] = target
        splits = data.get("splits")
        if isinstance(splits, list):
            data["splits"] = [
                {**split, "category_id": target}
                if isinstance(split, Mapping) and split.get("category_id") in doomed
                else split
                for split in splits
            ]
        repo.update(record.id, data)
        moved += 1
    return moved


# ---------------------------------------------------------------- internals


def _view(category_id: int, data: Mapping[str, Any]) -> CategoryView:
    parent = data.get("parent_id")
    return CategoryView(
        id=category_id,
        name=str(data.get("name", "")),
        kind=str(data.get("kind") or "expense"),
        parent_id=int(parent) if isinstance(parent, int) else None,
        icon=str(data.get("icon") or "tag"),
        colour=str(data.get("colour") or "#8E8E93"),
        sort_order=int(data.get("sort_order") or 0),
        archived=bool(data.get("archived", False)),
    )


def _replace(view: CategoryView, **changes) -> CategoryView:
    from dataclasses import replace

    return replace(view, **changes)


def _sorted(views: Iterable[CategoryView]) -> List[CategoryView]:
    return sorted(views, key=lambda v: (v.archived, v.sort_order, v.name.lower(), v.id))


def _children_of(records: Sequence, parent_id: int) -> List:
    return [record for record in records if record.data.get("parent_id") == parent_id]


def _next_sort_order(records: Sequence, parent_id: Optional[int]) -> int:
    orders = [
        int(record.data.get("sort_order") or 0)
        for record in records
        if record.data.get("parent_id") == parent_id
    ]
    return (max(orders) + 1) if orders else 0


def _clean(
    payload: Mapping[str, Any],
    existing: Optional[Mapping[str, Any]],
    siblings: Sequence,
    category_id: Optional[int],
) -> Dict[str, Any]:
    data: Dict[str, Any] = dict(existing or {})

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationException("A category needs a name")
    if len(name) > NAME_MAX:
        raise ValidationException(f"A category name is at most {NAME_MAX} characters")
    data["name"] = name

    kind = str(payload.get("kind") or (existing or {}).get("kind") or "expense").strip().lower()
    if kind not in KINDS:
        raise ValidationException("A category is either expense or income")
    data["kind"] = kind

    parent_id = payload.get("parent_id")
    data["parent_id"] = _parent(parent_id, kind, siblings, category_id) if parent_id is not None else None

    data["icon"] = _slug(payload.get("icon")) or "tag"
    data["colour"] = _colour(payload.get("colour"))
    data["archived"] = bool(payload.get("archived", data.get("archived", False)))
    if payload.get("sort_order") is not None:
        data["sort_order"] = int(payload["sort_order"])

    _reject_duplicate_name(siblings, name, data["parent_id"], kind, category_id)
    return data


def _parent(parent_id: Any, kind: str, siblings: Sequence, category_id: Optional[int]) -> int:
    try:
        parent_id = int(parent_id)
    except (TypeError, ValueError):
        raise ValidationException("parent_id must be a category id") from None
    if parent_id == category_id:
        raise BusinessRuleException("A category cannot be its own parent")

    parent = next((record for record in siblings if record.id == parent_id), None)
    if parent is None:
        # No foreign key can say this; the service is the only thing that can.
        raise ValidationException("That parent category does not exist")
    if parent.data.get("parent_id") is not None:
        raise BusinessRuleException("Sub-categories go one level deep (CAT-02)")
    if parent.data.get("kind") != kind:
        raise BusinessRuleException("A sub-category has the same kind as its parent")
    return parent_id


def _colour(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "#8E8E93"
    if len(text) != 7 or not text.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in text[1:]):
        raise ValidationException("A colour is #RRGGBB")
    return text.upper()


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if len(text) > 32 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in text):
        raise ValidationException("An icon is a short name like 'shopping-cart'")
    return text


def _reject_duplicate_name(
    siblings: Sequence,
    name: str,
    parent_id: Optional[int],
    kind: str,
    category_id: Optional[int],
) -> None:
    lowered = name.casefold()
    for record in siblings:
        if record.id == category_id:
            continue
        if (
            str(record.data.get("name", "")).casefold() == lowered
            and record.data.get("parent_id") == parent_id
            and record.data.get("kind") == kind
        ):
            where = "under that parent" if parent_id else f"in your {kind} categories"
            raise BusinessRuleException(f"You already have {name} {where}")
