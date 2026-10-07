from __future__ import annotations

import json

import pytest

QUERY = "remote work"
QUESTION = "What is the current policy on remote work?"


@pytest.fixture(scope="module")
def hr_document_ids(login, list_documents) -> set[str]:
    documents = list_documents(login("admin"), department_id="hr")
    ids = {document["id"] for document in documents if document["department_id"] == "hr"}
    assert ids, "no hr documents seeded"
    return ids


def test_search_returns_no_hr_documents(login, search, hr_document_ids):
    response = search(login("alice"), QUERY, page_size=50)
    for result in response["results"]:
        assert result["department_id"] != "hr"
        assert result["document_id"] not in hr_document_ids
    department_facets = {bucket["value"] for bucket in response["facets"].get("department_id", [])}
    assert "hr" not in department_facets


def test_suggest_returns_no_hr_documents(login, suggest, hr_document_ids):
    response = suggest(login("alice"), QUERY)
    for item in response["documents"]:
        assert item["department_id"] != "hr"
        assert item["id"] not in hr_document_ids


def test_ask_cites_no_hr_documents(login, ask, hr_document_ids):
    events = ask(login("alice"), QUESTION)
    citation_payloads = [json.loads(data) for name, data in events if name == "citations"]
    assert citation_payloads, events
    for payload in citation_payloads:
        for citation in payload["citations"]:
            assert citation["document_id"] not in hr_document_ids


def test_hr_document_detail_is_not_found(http, login, hr_document_ids):
    headers = login("alice")
    for document_id in hr_document_ids:
        response = http.get(f"/documents/{document_id}", headers=headers)
        assert response.status_code == 404, response.text
