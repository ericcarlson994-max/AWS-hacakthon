from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = BACKEND_ROOT / "samples" / "corpus"
E2E_ENABLED = os.environ.get("E2E") == "1"
TERMINAL_STATUSES = {"READY", "FAILED"}
LIST_PAGE_SIZE = 50


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: talks HTTP to the running stack; runs only when E2E=1")


def is_e2e_test(item: pytest.Item) -> bool:
    path = Path(str(item.fspath))
    return "acceptance" in path.parts or path.name == "test_e2e.py"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_marker = pytest.mark.skip(reason="end-to-end test; set E2E=1 to run against the running stack")
    for item in items:
        if is_e2e_test(item):
            item.add_marker(pytest.mark.e2e)
            if not E2E_ENABLED:
                item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def api_base() -> str:
    return os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    return CORPUS_DIR


@pytest.fixture(scope="session")
def http(api_base: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api_base, timeout=60.0) as client:
        yield client


@pytest.fixture(scope="session")
def login(http: httpx.Client) -> Callable[[str], dict[str, str]]:
    cached_headers: dict[str, dict[str, str]] = {}

    def login_as(username: str) -> dict[str, str]:
        if username not in cached_headers:
            response = http.post("/auth/dev-login", json={"username": username})
            assert response.status_code == 200, response.text
            cached_headers[username] = {"Authorization": f"Bearer {response.json()['token']}"}
        return cached_headers[username]

    return login_as


@pytest.fixture(scope="session")
def wait_ready(http: httpx.Client) -> Callable[..., dict[str, Any]]:
    def wait_until_terminal(doc_id: str, headers: dict[str, str], timeout: float = 180.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = http.get(f"/documents/{doc_id}/status", headers=headers)
            assert response.status_code == 200, response.text
            last_body = response.json()
            if last_body.get("status") in TERMINAL_STATUSES:
                return last_body
            time.sleep(1.5)
        raise AssertionError(f"document {doc_id} not READY after {timeout}s: {last_body}")

    return wait_until_terminal


def list_all_documents(http: httpx.Client, headers: dict[str, str], params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    page = 1
    while True:
        query = {"page": page, "page_size": LIST_PAGE_SIZE, **(params or {})}
        response = http.get("/documents", params=query, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        items = body.get("items", [])
        collected.extend(items)
        if not items or len(collected) >= body.get("total", 0):
            return collected
        page += 1


@pytest.fixture(scope="session")
def list_documents(http: httpx.Client) -> Callable[..., list[dict[str, Any]]]:
    def list_for(headers: dict[str, str], **params: Any) -> list[dict[str, Any]]:
        return list_all_documents(http, headers, params)

    return list_for


def detail_filenames(detail: dict[str, Any]) -> set[str]:
    names = {version.get("original_filename") for version in detail.get("versions", [])}
    names.add(detail.get("original_filename"))
    names.discard(None)
    return names


@pytest.fixture(scope="session")
def find_doc_by_filename(http: httpx.Client) -> Callable[[dict[str, str], str], dict[str, Any] | None]:
    def find(headers: dict[str, str], filename: str) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for summary in list_all_documents(http, headers):
            response = http.get(f"/documents/{summary['id']}", headers=headers)
            if response.status_code != 200:
                continue
            detail = response.json()
            if filename in detail_filenames(detail):
                matches.append(detail)
        if not matches:
            return None
        matches.sort(key=lambda detail: (detail.get("duplicate") is not None, detail.get("created_at") or ""))
        return matches[0]

    return find


@pytest.fixture(scope="session")
def upload(http: httpx.Client) -> Callable[[dict[str, str], Path, str], httpx.Response]:
    def upload_file(headers: dict[str, str], path: Path, department_id: str) -> httpx.Response:
        with open(path, "rb") as handle:
            return http.post(
                "/documents",
                headers=headers,
                data={"department_id": department_id},
                files={"file": (path.name, handle.read())},
            )

    return upload_file


@pytest.fixture(scope="session")
def search(http: httpx.Client) -> Callable[..., dict[str, Any]]:
    def run_search(headers: dict[str, str], query: str, **extra: Any) -> dict[str, Any]:
        response = http.post("/search", headers=headers, json={"query": query, **extra})
        assert response.status_code == 200, response.text
        return response.json()

    return run_search


@pytest.fixture(scope="session")
def suggest(http: httpx.Client) -> Callable[[dict[str, str], str], dict[str, Any]]:
    def run_suggest(headers: dict[str, str], query: str) -> dict[str, Any]:
        response = http.get("/suggest", headers=headers, params={"q": query})
        assert response.status_code == 200, response.text
        return response.json()

    return run_suggest


def parse_sse_lines(lines: list[str]) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    event_name = "message"
    data_parts: list[str] = []
    for raw_line in lines + [""]:
        line = raw_line.rstrip("\r")
        if line == "":
            if data_parts:
                events.append((event_name, "\n".join(data_parts)))
            event_name = "message"
            data_parts = []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_parts.append(line[len("data:"):].lstrip(" "))
    return events


@pytest.fixture(scope="session")
def ask(http: httpx.Client) -> Callable[[dict[str, str], str], list[tuple[str, str]]]:
    def run_ask(headers: dict[str, str], question: str) -> list[tuple[str, str]]:
        with http.stream("POST", "/ask", headers=headers, json={"question": question}, timeout=120.0) as response:
            body_text = response.read().decode("utf-8")
            assert response.status_code == 200, body_text
        return parse_sse_lines(body_text.splitlines())

    return run_ask
