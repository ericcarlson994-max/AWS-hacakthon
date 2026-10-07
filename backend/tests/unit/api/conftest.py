from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api_support import Session, make_docx, seed
from dms_adapters.container import build_fake_container
from dms_api.main import create_app
from dms_core.ports import Container


@pytest.fixture
def container() -> Container:
    built = build_fake_container()
    seed(built)
    return built


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client


@pytest.fixture
def alice(client: TestClient) -> Session:
    return Session(client, "alice")


@pytest.fixture
def ben(client: TestClient) -> Session:
    return Session(client, "ben")


@pytest.fixture
def budget_docx() -> bytes:
    return make_docx(
        "Budget Circular 2026",
        ["All departments must submit budget requests by March.", "Overtime claims require approval."],
    )
