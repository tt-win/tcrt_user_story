"""Single write-time authority for Test Run Item assignee identity.

Legacy clients can still send Lark snapshots or a display name.  This module
keeps those snapshots compatible while only linking a local user when the
identity can be established exactly and the target account can execute work.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import UserRole
from app.models.database_models import TestRunItem, User


ASSIGNEE_INPUT_FIELDS = frozenset({"assignee_user_id", "assignee", "assignee_name"})
_WRITE_CAPABLE_ROLES = {
    UserRole.USER.value,
    UserRole.ADMIN.value,
    UserRole.SUPER_ADMIN.value,
}


class AssigneeValidationError(ValueError):
    """Raised when an assignee payload has no safe, unambiguous meaning."""


@dataclass(frozen=True)
class ResolvedAssignee:
    """The normalized storage representation for one assignment intent."""

    preserve: bool = False
    assignee_user_id: Optional[int] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_en_name: Optional[str] = None
    assignee_email: Optional[str] = None
    assignee_json: Optional[str] = None


def has_assignee_input(payload: Mapping[str, Any]) -> bool:
    """Return whether an update explicitly includes an assignment field."""

    return bool(ASSIGNEE_INPUT_FIELDS.intersection(payload))


def resolve_assignee(
    sync_db: Session,
    *,
    team_id: int,
    payload: Mapping[str, Any],
    for_create: bool = False,
    allow_local_user_id: bool = True,
    allow_structured_local_link: bool = True,
) -> ResolvedAssignee:
    """Validate an assignment intent without mutating an ORM item.

    ``for_create`` turns omitted values into a deliberate unassigned value.
    App-token callers disable both local-user input and automatic structured
    linking so a machine token remains a legacy snapshot-only surface.
    """

    present = [field for field in ASSIGNEE_INPUT_FIELDS if field in payload]
    if not present:
        return ResolvedAssignee(preserve=not for_create)

    structured_for_presence = (
        _coerce_structured_assignee(payload.get("assignee")) if "assignee" in present else None
    )
    if len(present) > 1:
        all_empty = all(
            (
                not any(structured_for_presence.values())
                if field == "assignee" and structured_for_presence is not None
                else _is_empty(payload.get(field))
            )
            for field in present
        )
        if all_empty:
            # Some legacy clients serialize all optional fields as null.  It is
            # still an unambiguous clear, not a competing identity claim.
            return ResolvedAssignee()
        if set(present) != {"assignee_user_id", "assignee"}:
            raise AssigneeValidationError("Only one assignee representation may be supplied")

    if "assignee_name" in present:
        return _resolve_name_only(payload.get("assignee_name"))

    local_raw = payload.get("assignee_user_id") if "assignee_user_id" in present else _MISSING
    structured_raw = payload.get("assignee") if "assignee" in present else _MISSING

    local_empty = local_raw is _MISSING or _is_empty(local_raw)
    structured = structured_for_presence if structured_raw is not _MISSING else None
    structured_empty = structured is None or not any(structured.values())

    if local_empty and structured_empty:
        return ResolvedAssignee()

    if local_raw is not _MISSING and local_empty and structured_raw is not _MISSING:
        raise AssigneeValidationError("A cleared local user cannot be combined with another assignee")
    if structured_raw is not _MISSING and structured_empty and local_raw is not _MISSING:
        raise AssigneeValidationError("A cleared Lark assignee cannot be combined with another assignee")

    local_user: Optional[User] = None
    if not local_empty:
        if not allow_local_user_id:
            raise AssigneeValidationError("This credential cannot assign a local user")
        local_user_id = _coerce_positive_int(local_raw)
        local_user = sync_db.get(User, local_user_id)
        if local_user is None or not _is_write_capable(local_user):
            raise AssigneeValidationError("The selected user is not an active Test Run writer")

    if structured_empty:
        return _resolved_local_user(local_user)

    assert structured is not None
    lark_id = _trim_to_none(structured.get("id"))
    email = _normalize_email(structured.get("email"))
    if not lark_id and not email:
        if local_user is not None:
            raise AssigneeValidationError("A combined Lark assignee requires an id or email")
        # Older clients can send the former object form with only display
        # fields.  Preserve that snapshot, but never infer a local identity
        # from it.
        return _resolved_structured_display(structured)

    lark_candidate, email_candidate = _find_structured_candidates(sync_db, lark_id, email)
    candidate = _resolve_candidate(lark_candidate, email_candidate, lark_id=lark_id, email=email)

    if local_user is not None:
        if candidate is None or candidate.id != local_user.id:
            raise AssigneeValidationError("The local user and Lark assignee do not resolve to the same account")
        return _resolved_local_user(local_user, structured=structured, lark_id=lark_id, email=email)

    linked_user = (
        candidate
        if allow_structured_local_link and candidate is not None and _is_write_capable(candidate)
        else None
    )
    return ResolvedAssignee(
        assignee_user_id=linked_user.id if linked_user else None,
        assignee_id=lark_id,
        assignee_name=_trim_to_none(structured.get("name")) or _display_name(linked_user),
        assignee_en_name=_trim_to_none(structured.get("en_name")),
        assignee_email=email,
        assignee_json=_snapshot_json(
            lark_id=lark_id,
            name=_trim_to_none(structured.get("name")),
            en_name=_trim_to_none(structured.get("en_name")),
            email=email,
        ),
    )


def resolve_clone_assignee(sync_db: Session, *, team_id: int, source: TestRunItem) -> ResolvedAssignee:
    """Revalidate a source item's identity before a restart/re-run clone."""

    if source.assignee_user_id:
        payload: dict[str, Any] = {"assignee_user_id": source.assignee_user_id}
        if source.assignee_id or source.assignee_email:
            payload["assignee"] = {
                "id": source.assignee_id,
                "name": source.assignee_name,
                "en_name": source.assignee_en_name,
                "email": source.assignee_email,
            }
        try:
            return resolve_assignee(sync_db, team_id=team_id, payload=payload)
        except AssigneeValidationError:
            return _resolve_name_only(source.assignee_name)

    if source.assignee_id or source.assignee_email:
        resolved = resolve_assignee(
            sync_db,
            team_id=team_id,
            payload={
                "assignee": {
                    "id": source.assignee_id,
                    "name": source.assignee_name,
                    "en_name": source.assignee_en_name,
                    "email": source.assignee_email,
                }
            },
        )
        if resolved.assignee_user_id is None and _has_disabled_candidate(
            sync_db, source.assignee_id, source.assignee_email
        ):
            return _resolve_name_only(source.assignee_name)
        return resolved

    return _resolve_name_only(source.assignee_name)


def apply_resolved_assignee(item: TestRunItem, resolved: ResolvedAssignee) -> None:
    """Apply a prevalidated assignment intent to an ORM item."""

    if resolved.preserve:
        return
    item.assignee_user_id = resolved.assignee_user_id
    item.assignee_id = resolved.assignee_id
    item.assignee_name = resolved.assignee_name
    item.assignee_en_name = resolved.assignee_en_name
    item.assignee_email = resolved.assignee_email
    item.assignee_json = resolved.assignee_json


def _resolve_name_only(value: Any) -> ResolvedAssignee:
    name = _trim_to_none(value)
    return ResolvedAssignee(assignee_name=name)


def _resolved_local_user(
    user: Optional[User],
    *,
    structured: Optional[Mapping[str, Optional[str]]] = None,
    lark_id: Optional[str] = None,
    email: Optional[str] = None,
) -> ResolvedAssignee:
    if user is None:
        return ResolvedAssignee()
    return ResolvedAssignee(
        assignee_user_id=user.id,
        assignee_id=lark_id,
        assignee_name=(
            _trim_to_none(structured.get("name")) if structured else None
        )
        or _display_name(user),
        assignee_en_name=_trim_to_none(structured.get("en_name")) if structured else None,
        assignee_email=email,
        assignee_json=(
            _snapshot_json(
                lark_id=lark_id,
                name=_trim_to_none(structured.get("name")),
                en_name=_trim_to_none(structured.get("en_name")),
                email=email,
            )
            if structured
            else None
        ),
    )


def _resolved_structured_display(
    structured: Mapping[str, Optional[str]],
) -> ResolvedAssignee:
    name = _trim_to_none(structured.get("name"))
    en_name = _trim_to_none(structured.get("en_name"))
    return ResolvedAssignee(
        assignee_name=name or en_name,
        assignee_en_name=en_name,
        assignee_json=_snapshot_json(
            lark_id=None,
            name=name,
            en_name=en_name,
            email=None,
        ),
    )


def _coerce_structured_assignee(value: Any) -> Optional[dict[str, Optional[str]]]:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, Mapping):
        raise AssigneeValidationError("The structured assignee must be an object")
    unknown = set(value).difference({"id", "name", "en_name", "email"})
    if unknown:
        raise AssigneeValidationError("The structured assignee contains unsupported fields")
    return {
        "id": _trim_to_none(value.get("id")),
        "name": _trim_to_none(value.get("name")),
        "en_name": _trim_to_none(value.get("en_name")),
        "email": _normalize_email(value.get("email")),
    }


def _find_structured_candidates(
    sync_db: Session, lark_id: Optional[str], email: Optional[str]
) -> tuple[list[User], list[User]]:
    lark_users: list[User] = []
    email_users: list[User] = []
    if lark_id:
        lark_users = (
            sync_db.query(User)
            .filter(func.trim(User.lark_user_id) == lark_id)
            .all()
        )
    if email:
        email_users = (
            sync_db.query(User)
            .filter(func.lower(func.trim(User.email)) == email)
            .all()
        )
    return lark_users, email_users


def _resolve_candidate(
    lark_users: list[User], email_users: list[User], *, lark_id: Optional[str], email: Optional[str]
) -> Optional[User]:
    if lark_id and len(lark_users) != 1:
        if email:
            raise AssigneeValidationError("The Lark id and email must each resolve to one account")
        return None
    if email and len(email_users) != 1:
        if lark_id:
            raise AssigneeValidationError("The Lark id and email must each resolve to one account")
        return None
    lark_user = lark_users[0] if lark_users else None
    email_user = email_users[0] if email_users else None
    if lark_user and email_user and lark_user.id != email_user.id:
        raise AssigneeValidationError("The Lark id and email resolve to different accounts")
    return lark_user or email_user


def _has_disabled_candidate(sync_db: Session, lark_id: Optional[str], email: Optional[str]) -> bool:
    lark_users, email_users = _find_structured_candidates(
        sync_db, _trim_to_none(lark_id), _normalize_email(email)
    )
    candidates = {user.id: user for user in [*lark_users, *email_users]}
    return bool(candidates) and any(not _is_write_capable(user) for user in candidates.values())


def _is_write_capable(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else str(user.role or "")
    return bool(user.is_active) and role.strip().lower() in _WRITE_CAPABLE_ROLES


def _display_name(user: Optional[User]) -> Optional[str]:
    if user is None:
        return None
    return _trim_to_none(user.full_name) or _trim_to_none(user.username)


def _snapshot_json(
    *, lark_id: Optional[str], name: Optional[str], en_name: Optional[str], email: Optional[str]
) -> Optional[str]:
    payload = {
        key: value
        for key, value in {
            "id": lark_id,
            "name": name,
            "en_name": en_name,
            "email": email,
        }.items()
        if value is not None
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload else None


def _trim_to_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_email(value: Any) -> Optional[str]:
    text = _trim_to_none(value)
    return text.lower() if text else None


def _coerce_positive_int(value: Any) -> int:
    if isinstance(value, bool):
        raise AssigneeValidationError("The local assignee user id must be a positive integer")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AssigneeValidationError("The local assignee user id must be a positive integer") from exc
    if number <= 0:
        raise AssigneeValidationError("The local assignee user id must be a positive integer")
    return number


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


_MISSING = object()
