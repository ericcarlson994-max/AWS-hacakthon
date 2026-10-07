from datetime import UTC, datetime
from uuid import uuid4

from dms_core.access.guard import can_read, can_write
from dms_core.models import DepartmentMembership, DocumentRow, User


def make_user(*memberships: tuple[str, str]) -> User:
    return User(
        id="u1",
        username="alice",
        display_name="Alice",
        departments=[DepartmentMembership(id=dept, name=dept, role=role) for dept, role in memberships],
    )


def make_doc(department_id: str) -> DocumentRow:
    now = datetime.now(UTC)
    return DocumentRow(id=uuid4(), department_id=department_id, created_at=now, updated_at=now)


def test_can_read_only_own_departments() -> None:
    user = make_user(("finance", "viewer"))
    assert can_read(user, make_doc("finance"))
    assert not can_read(user, make_doc("hr"))


def test_can_write_requires_contributor_or_admin() -> None:
    user = make_user(("finance", "viewer"), ("ops", "contributor"), ("it", "admin"))
    assert not can_write(user, make_doc("finance"))
    assert can_write(user, make_doc("ops"))
    assert can_write(user, make_doc("it"))
    assert not can_write(user, make_doc("hr"))
