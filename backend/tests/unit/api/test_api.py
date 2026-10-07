from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from dms_core.ports import Container
from dms_core.search.mappings import CHUNKS_INDEX

from api_support import Session, make_docx


def find_allowed_groups(node: Any) -> list[list[str]]:
    found: list[list[str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "allowed_groups" and isinstance(value, list):
                found.append(value)
            else:
                found.extend(find_allowed_groups(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(find_allowed_groups(item))
    return found


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if name:
            events.append((name, json.loads("\n".join(data_lines) or "{}")))
    return events


def test_health_and_error_shape(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body["deps"]) == {"postgres", "opensearch", "minio", "openrouter"}
    assert body["status"] == "ok"
    unauthorized = client.get("/me")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"
    bad_token = client.get("/me", headers={"Authorization": "Bearer nope"})
    assert bad_token.status_code == 401


def test_dev_login_and_me(client: TestClient, alice: Session) -> None:
    me = alice.get("/me")
    assert me.status_code == 200
    body = me.json()
    assert body["id"] == "alice"
    assert {d["id"]: d["role"] for d in body["departments"]} == {"finance": "contributor", "public": "viewer"}
    unknown = client.post("/auth/dev-login", json={"username": "mallory"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"
    invalid = client.post("/auth/dev-login", json={})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    departments = alice.get("/departments").json()
    assert sorted(d["id"] for d in departments) == ["finance", "public"]


def test_upload_enqueues_extract_and_exact_duplicate_short_circuits(
    container: Container, alice: Session, budget_docx: bytes
) -> None:
    first = alice.upload("finance", "budget.docx", budget_docx)
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["status"] == "UPLOADED"
    assert first_body["duplicate"] is None
    jobs = container.repo.list_jobs(UUID(first_body["document_id"]))
    assert [(j.stage, j.status) for j in jobs] == [("extract", "queued")]
    container.repo.update_document(UUID(first_body["document_id"]), title="Budget Circular 2026")
    total_jobs_before = len(container.jobs.jobs)
    second = alice.upload("finance", "budget_copy.docx", budget_docx)
    assert second.status_code == 202, second.text
    second_body = second.json()
    assert second_body["duplicate"] == {
        "document_id": first_body["document_id"],
        "title": "Budget Circular 2026",
        "tier": "exact",
    }
    assert second_body["status"] == "READY"
    assert len(container.jobs.jobs) == total_jobs_before
    detail = alice.get(f"/documents/{second_body['document_id']}").json()
    assert detail["duplicate"]["tier"] == "exact"
    assert detail["status"] == "READY"
    assert detail["original_filename"] == "budget_copy.docx"
    listing = alice.get("/documents").json()
    assert listing["total"] == 2
    assert all(item["current_version_no"] == 1 for item in listing["items"])


def test_department_isolation(alice: Session, ben: Session, budget_docx: bytes) -> None:
    uploaded = alice.upload("finance", "budget.docx", budget_docx).json()
    document_id = uploaded["document_id"]
    assert ben.get(f"/documents/{document_id}").status_code == 404
    assert ben.get(f"/documents/{document_id}/status").status_code == 404
    assert ben.get(f"/documents/{document_id}/file").status_code == 404
    assert ben.patch(f"/documents/{document_id}", json={"title": "x"}).status_code == 404
    forbidden = ben.upload("finance", "budget.docx", budget_docx)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
    assert alice.upload("public", "budget.docx", budget_docx).status_code == 403
    assert ben.get("/documents").json()["total"] == 0
    assert ben.get("/documents", params={"department_id": "finance"}).status_code == 403
    ben_copy = ben.upload("hr", "budget.docx", budget_docx).json()
    assert ben_copy["duplicate"] is None


def test_unsupported_file_rejected(alice: Session) -> None:
    response = alice.upload("finance", "notes.txt", b"just some plain text", "text/plain")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_file_download_and_status(alice: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "Bajet 2026.docx", budget_docx).json()["document_id"]
    download = alice.get(f"/documents/{document_id}/file")
    assert download.status_code == 200
    assert download.content == budget_docx
    assert "wordprocessingml" in download.headers["content-type"]
    assert "Bajet%202026.docx" in download.headers["content-disposition"]
    assert alice.get(f"/documents/{document_id}/file", params={"version_no": 9}).status_code == 404
    status = alice.get(f"/documents/{document_id}/status").json()
    assert status["status"] == "UPLOADED"
    assert [s["stage"] for s in status["stages"]] == ["extract"]


def test_patch_title_and_doctype(alice: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    patched = alice.patch(f"/documents/{document_id}", json={"title": "  FY2026 Budget  ", "doctype": "circular"})
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["title"] == "FY2026 Budget"
    assert body["title_source"] == "user"
    assert body["title_confidence"] == 1.0
    assert body["doctype"] == "circular"
    invalid = alice.patch(f"/documents/{document_id}", json={"doctype": "poem"})
    assert invalid.status_code == 422


def test_viewer_cannot_write(client: TestClient, alice: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    chloe = Session(client, "chloe")
    assert chloe.get(f"/documents/{document_id}").status_code == 200
    assert chloe.patch(f"/documents/{document_id}", json={"title": "x"}).status_code == 403
    assert chloe.post(f"/documents/{document_id}/tags", json={"name": "Budget"}).status_code == 403


def test_tags_add_confirm_remove(container: Container, alice: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    container.repo.upsert_chunks([])
    added = alice.post(f"/documents/{document_id}/tags", json={"name": "Budget"})
    assert added.status_code == 200, added.text
    refs = added.json()
    assert [(r["name"], r["status"], r["source"]) for r in refs] == [("Budget", "confirmed", "user")]
    tag_id = refs[0]["id"]
    suggested = container.repo.get_or_create_tag("Procurement", "finance")
    container.repo.set_document_tag(UUID(document_id), suggested.id, "ai", "suggested", 0.7)
    confirmed = alice.put(f"/documents/{document_id}/tags/{suggested.id}", json={"status": "confirmed"}).json()
    statuses = {r["name"]: (r["status"], r["source"]) for r in confirmed}
    assert statuses["Procurement"] == ("confirmed", "ai")
    removed = alice.delete(f"/documents/{document_id}/tags/{tag_id}")
    assert removed.status_code == 200
    assert [r["name"] for r in removed.json()] == ["Procurement"]
    assert alice.delete(f"/documents/{document_id}/tags/{tag_id}").status_code == 404
    tags = alice.get("/tags").json()
    assert {t["name"] for t in tags} >= {"Budget", "Procurement"}
    assert alice.get("/tags", params={"department_id": "hr"}).status_code == 403


def test_versions_upload_and_list(container: Container, alice: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    revised = make_docx("Budget Circular 2026", ["Budget requests are due by April.", "Overtime needs approval."])
    response = alice.post(
        f"/documents/{document_id}/versions",
        files={"file": ("budget_v2.docx", revised, "application/octet-stream")},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["version_no"] == 2
    assert body["status"] == "UPLOADED"
    versions = alice.get(f"/documents/{document_id}/versions").json()
    assert [v["version_no"] for v in versions] == [1, 2]
    assert versions[1]["original_filename"] == "budget_v2.docx"
    extract_jobs = [j for j in container.repo.list_jobs(UUID(document_id)) if j.stage == "extract"]
    assert len(extract_jobs) == 2
    assert alice.get(f"/documents/{document_id}").json()["current_version_no"] == 2


def test_search_filters_by_caller_groups(container: Container, alice: Session, ben: Session) -> None:
    index = container.index
    response = alice.post("/search", json={"query": "budget circular"})
    assert response.status_code == 200, response.text
    alice_groups = [g for _, body in index.queries for g in find_allowed_groups(body)]
    assert alice_groups and all(sorted(groups) == ["finance", "public"] for groups in alice_groups)
    index.queries.clear()
    ben.post("/search", json={"query": "leave policy"})
    ben_groups = [g for _, body in index.queries for g in find_allowed_groups(body)]
    assert ben_groups and all(sorted(groups) == ["hr", "public"] for groups in ben_groups)
    index.queries.clear()
    suggest = alice.get("/suggest", params={"q": "bud"})
    assert suggest.status_code == 200
    assert all(sorted(g) == ["finance", "public"] for _, body in index.queries for g in find_allowed_groups(body))


def test_search_hides_other_department_hits(container: Container, alice: Session, ben: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    container.index.responder = chunk_responder(document_id)
    alice_results = alice.post("/search", json={"query": "budget"}).json()
    assert [r["document_id"] for r in alice_results["results"]] == [document_id]
    ben_results = ben.post("/search", json={"query": "budget"}).json()
    assert ben_results["results"] == []


def chunk_responder(document_id: str) -> Any:
    def respond(index: str, body: dict[str, Any]) -> dict[str, Any]:
        if index != CHUNKS_INDEX:
            return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}, "suggest": {}}
        return {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_id": "chunk-1",
                        "_score": 1.0,
                        "_source": {
                            "chunk_id": "chunk-1",
                            "document_id": document_id,
                            "level": 0,
                            "title": "Budget Circular 2026",
                            "text": "All departments must submit budget requests by March.",
                            "heading_path": ["Budget Circular 2026"],
                            "page_from": 1,
                        },
                    }
                ],
            },
            "aggregations": {},
        }

    return respond


def test_ask_streams_tokens_citations_done(container: Container, alice: Session, budget_docx: bytes) -> None:
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    container.index.responder = chunk_responder(document_id)
    response = alice.post("/ask", json={"question": "When are budget requests due?"})
    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert "token" in names
    assert names[-2:] == ["citations", "done"]
    citations = dict(events)["citations"]["citations"]
    assert citations and citations[0]["document_id"] == document_id
    assert citations[0]["chunk_id"] == "chunk-1"


def test_ask_requires_auth(client: TestClient) -> None:
    assert client.post("/ask", json={"question": "hi"}).status_code == 401


def test_pipeline_drain_reaches_ready(container: Container, alice: Session, budget_docx: bytes) -> None:
    try:
        from dms_workers.run import drain
    except ImportError:
        pytest.skip("dms_workers.run.drain is not available")
    document_id = alice.upload("finance", "budget.docx", budget_docx).json()["document_id"]
    drain(container)
    detail = alice.get(f"/documents/{document_id}").json()
    assert detail["status"] == "READY", detail
    assert detail["title"]
    assert detail["page_count"] is not None or detail["mime_type"]
