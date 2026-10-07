from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from dms_core.models import DepartmentMembership, DocumentRow, TagRef, TagRow, User


class StubRepo:
    def __init__(self) -> None:
        self.documents: dict[UUID, DocumentRow] = {}
        self.tags: list[TagRow] = []
        self.document_tags: dict[UUID, list[TagRef]] = {}

    def add_document(self, department_id: str, title: str, **fields: Any) -> DocumentRow:
        now = datetime.now(UTC)
        row = DocumentRow(id=uuid4(), department_id=department_id, title=title, created_at=now, updated_at=now, **fields)
        self.documents[row.id] = row
        return row

    def get_documents(self, ids: list[UUID]) -> list[DocumentRow]:
        return [self.documents[i] for i in ids if i in self.documents]

    def get_document_tags(self, document_id: UUID) -> list[TagRef]:
        return self.document_tags.get(document_id, [])

    def list_tags(self, department_ids: list[str] | None = None) -> list[TagRow]:
        return [t for t in self.tags if t.department_id is None or department_ids is None or t.department_id in department_ids]


def make_user(*departments: str) -> User:
    return User(
        id="u1",
        username="alice",
        display_name="Alice",
        departments=[DepartmentMembership(id=d, name=d, role="viewer") for d in departments],
    )


@pytest.fixture
def repo() -> StubRepo:
    return StubRepo()
