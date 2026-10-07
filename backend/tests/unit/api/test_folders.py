from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from api_support import DOCX_MIME, Session, make_docx
from dms_core.folders import DEFAULT_FOLDERS
from dms_core.ports import Container


def upload_to(session: Session, department_id: str, filename: str, data: bytes, folder_id: str | None = None) -> Any:
    form = {"department_id": department_id}
    if folder_id is not None:
        form["folder_id"] = folder_id
    return session.post("/documents", files={"file": (filename, data, DOCX_MIME)}, data=form)


def unique_docx(label: str) -> bytes:
    return make_docx(f"Document {label}", [f"Unique content for {label}.", "Second paragraph."])


def folders_by_id(session: Session) -> dict[str, dict[str, Any]]:
    response = session.get("/folders")
    assert response.status_code == 200, response.text
    return {folder["id"]: folder for folder in response.json()}


def test_seeded_folders_listed_with_shape(alice: Session) -> None:
    folders = folders_by_id(alice)
    assert set(folders) == {folder_id for folder_id, _, _ in DEFAULT_FOLDERS}
    assert folders["sop-fin"] == {"id": "sop-fin", "name": "Finance", "parent_id": "sops", "doc_count": 0}
    assert alice.get("/folders").json()[0]["id"] == "inbox"


def test_folders_require_auth(client: TestClient) -> None:
    assert client.get("/folders").status_code == 401
    assert client.post("/folders", json={"name": "x"}).status_code == 401


def test_create_folder_validation(alice: Session) -> None:
    created = alice.post("/folders", json={"name": "  Budget   2027 ", "parent_id": "circulars"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Budget 2027"
    assert body["parent_id"] == "circulars"
    assert body["doc_count"] == 0
    assert body["id"].startswith("budget-2027-")
    assert alice.post("/folders", json={"name": "   "}).status_code == 400
    missing_parent = alice.post("/folders", json={"name": "Orphan", "parent_id": "nope"})
    assert missing_parent.status_code == 404
    duplicate = alice.post("/folders", json={"name": "budget 2027", "parent_id": "circulars"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"
    assert alice.post("/folders", json={"name": "Budget 2027"}).status_code == 201


def test_viewer_only_user_cannot_create_folder(client: TestClient) -> None:
    chloe = Session(client, "chloe")
    assert chloe.post("/folders", json={"name": "Mine"}).status_code == 403


def test_patch_folder_rename_move_and_cycles(alice: Session) -> None:
    parent = alice.post("/folders", json={"name": "Projects"}).json()
    child = alice.post("/folders", json={"name": "Alpha", "parent_id": parent["id"]}).json()
    renamed = alice.patch(f"/folders/{child['id']}", json={"name": "Beta"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Beta"
    assert renamed.json()["parent_id"] == parent["id"]
    to_root = alice.patch(f"/folders/{child['id']}", json={"parent_id": None})
    assert to_root.json()["parent_id"] is None
    back = alice.patch(f"/folders/{child['id']}", json={"parent_id": parent["id"]})
    assert back.json()["parent_id"] == parent["id"]
    cycle = alice.patch(f"/folders/{parent['id']}", json={"parent_id": child["id"]})
    assert cycle.status_code == 400
    self_parent = alice.patch(f"/folders/{parent['id']}", json={"parent_id": parent["id"]})
    assert self_parent.status_code == 400
    assert alice.patch(f"/folders/{child['id']}", json={"name": ""}).status_code == 400
    assert alice.patch(f"/folders/{child['id']}", json={"parent_id": "nope"}).status_code == 404
    assert alice.patch("/folders/nope", json={"name": "x"}).status_code == 404
    clash = alice.patch("/folders/policies", json={"name": "sops"})
    assert clash.status_code == 409
    assert alice.patch("/folders/inbox", json={"name": "Other"}).status_code == 400
    assert alice.patch("/folders/inbox", json={"parent_id": "policies"}).status_code == 400


def test_doc_count_only_counts_readable_documents(alice: Session, ben: Session) -> None:
    assert upload_to(alice, "finance", "a.docx", unique_docx("a"), "policies").status_code == 202
    assert upload_to(alice, "finance", "b.docx", unique_docx("b"), "policies").status_code == 202
    assert upload_to(ben, "hr", "c.docx", unique_docx("c"), "policies").status_code == 202
    assert upload_to(ben, "hr", "d.docx", unique_docx("d"), "sop-hr").status_code == 202
    alice_folders = folders_by_id(alice)
    ben_folders = folders_by_id(ben)
    assert alice_folders["policies"]["doc_count"] == 2
    assert ben_folders["policies"]["doc_count"] == 1
    assert alice_folders["sops"]["doc_count"] == 0
    assert ben_folders["sop-hr"]["doc_count"] == 1


def test_upload_defaults_to_inbox_and_rejects_unknown_folder(alice: Session) -> None:
    default = upload_to(alice, "finance", "a.docx", unique_docx("a"))
    assert default.status_code == 202
    detail = alice.get(f"/documents/{default.json()['document_id']}").json()
    assert detail["folder_id"] == "inbox"
    targeted = upload_to(alice, "finance", "b.docx", unique_docx("b"), "reports")
    assert alice.get(f"/documents/{targeted.json()['document_id']}").json()["folder_id"] == "reports"
    missing = upload_to(alice, "finance", "c.docx", unique_docx("c"), "nope")
    assert missing.status_code == 404


def test_exact_duplicate_goes_to_requested_folder(alice: Session) -> None:
    data = unique_docx("dup")
    upload_to(alice, "finance", "first.docx", data, "policies")
    second = upload_to(alice, "finance", "second.docx", data, "reports")
    assert second.json()["duplicate"]["tier"] == "exact"
    assert alice.get(f"/documents/{second.json()['document_id']}").json()["folder_id"] == "reports"


def test_summary_has_new_fields(alice: Session) -> None:
    data = unique_docx("fields")
    document_id = upload_to(alice, "finance", "fields.docx", data, "policies").json()["document_id"]
    items = alice.get("/documents", params={"folder_id": "policies"}).json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == document_id
    assert item["folder_id"] == "policies"
    assert item["size_bytes"] == len(data)
    assert item["original_filename"] == "fields.docx"
    assert item["created_by"] == "alice"
    assert item["updated_at"]
    assert "page_count" in item


def test_move_document_via_patch(alice: Session, ben: Session) -> None:
    document_id = upload_to(alice, "finance", "m.docx", unique_docx("m")).json()["document_id"]
    moved = alice.patch(f"/documents/{document_id}", json={"folder_id": "guidelines"})
    assert moved.status_code == 200
    assert moved.json()["folder_id"] == "guidelines"
    assert alice.patch(f"/documents/{document_id}", json={"folder_id": "nope"}).status_code == 404
    assert ben.patch(f"/documents/{document_id}", json={"folder_id": "inbox"}).status_code == 404
    assert folders_by_id(alice)["guidelines"]["doc_count"] == 1


def test_recursive_listing(alice: Session) -> None:
    upload_to(alice, "finance", "root.docx", unique_docx("root"), "sops")
    upload_to(alice, "finance", "child.docx", unique_docx("child"), "sop-fin")
    upload_to(alice, "finance", "other.docx", unique_docx("other"), "policies")
    direct = alice.get("/documents", params={"folder_id": "sops"}).json()
    assert direct["total"] == 1
    recursive = alice.get("/documents", params={"folder_id": "sops", "recursive": "true"}).json()
    assert recursive["total"] == 2
    assert {item["folder_id"] for item in recursive["items"]} == {"sops", "sop-fin"}
    assert alice.get("/documents").json()["total"] == 3
    assert alice.get("/documents", params={"folder_id": "nope"}).status_code == 404
    assert alice.get("/documents", params={"page_size": 200}).status_code == 200


def test_delete_document_hides_it_and_removes_from_index(container: Container, alice: Session, ben: Session) -> None:
    data = unique_docx("del")
    document_id = upload_to(alice, "finance", "del.docx", data, "policies").json()["document_id"]
    container.index.titles[document_id] = {"document_id": document_id}
    container.index.chunks["c1"] = {"chunk_id": "c1", "document_id": document_id}
    assert ben.delete(f"/documents/{document_id}").status_code == 404
    response = alice.delete(f"/documents/{document_id}")
    assert response.status_code == 204
    assert document_id not in container.index.titles
    assert "c1" not in container.index.chunks
    assert alice.get(f"/documents/{document_id}").status_code == 404
    assert alice.get("/documents").json()["total"] == 0
    assert folders_by_id(alice)["policies"]["doc_count"] == 0
    assert alice.delete(f"/documents/{document_id}").status_code == 404
    again = upload_to(alice, "finance", "del.docx", data, "policies").json()
    assert again["duplicate"] is None


def test_viewer_cannot_delete_document(client: TestClient, alice: Session) -> None:
    document_id = upload_to(alice, "finance", "v.docx", unique_docx("v")).json()["document_id"]
    chloe = Session(client, "chloe")
    assert chloe.delete(f"/documents/{document_id}").status_code == 403


def test_delete_document_keeps_superseded_links(container: Container, alice: Session) -> None:
    old_id = upload_to(alice, "finance", "old.docx", unique_docx("old")).json()["document_id"]
    new_id = upload_to(alice, "finance", "new.docx", unique_docx("new")).json()["document_id"]
    container.repo.update_document(old_id, superseded_by=new_id)
    assert alice.delete(f"/documents/{new_id}").status_code == 204
    assert alice.get(f"/documents/{old_id}").json()["superseded_by"] == new_id


def test_delete_folder_cascades_and_soft_deletes(container: Container, alice: Session) -> None:
    parent = alice.post("/folders", json={"name": "Temp"}).json()
    child = alice.post("/folders", json={"name": "Inner", "parent_id": parent["id"]}).json()
    document_id = upload_to(alice, "finance", "t.docx", unique_docx("t"), child["id"]).json()["document_id"]
    response = alice.delete(f"/folders/{parent['id']}")
    assert response.status_code == 204
    folders = folders_by_id(alice)
    assert parent["id"] not in folders and child["id"] not in folders
    assert alice.get(f"/documents/{document_id}").status_code == 404
    assert alice.delete("/folders/nope").status_code == 404
    assert alice.delete("/folders/inbox").status_code == 400


def test_delete_folder_blocked_by_other_department_document(alice: Session, ben: Session) -> None:
    folder = alice.post("/folders", json={"name": "Shared"}).json()
    mine = upload_to(alice, "finance", "mine.docx", unique_docx("mine"), folder["id"]).json()["document_id"]
    upload_to(ben, "hr", "theirs.docx", unique_docx("theirs"), folder["id"])
    response = alice.delete(f"/folders/{folder['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "forbidden_contents"
    assert folder["id"] in folders_by_id(alice)
    assert alice.get(f"/documents/{mine}").status_code == 200


def test_search_and_ask_forward_document_ids(container: Container, alice: Session) -> None:
    index = container.index
    scope = {"document_ids": ["11111111-1111-1111-1111-111111111111"]}
    assert alice.post("/search", json={"query": "budget", "filters": scope}).status_code == 200
    expected = {"terms": {"document_id": scope["document_ids"]}}
    searched = [body for _, body in index.queries if expected in str_filters(body)]
    assert searched
    index.queries.clear()
    for mode in ("rag", "agent"):
        response = alice.post("/ask", json={"question": "budget?", "filters": scope, "mode": mode})
        assert response.status_code == 200
        assert any(expected in str_filters(body) for _, body in index.queries)
        index.queries.clear()


def str_filters(node: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "filter" and isinstance(value, list):
                found.extend(value)
            else:
                found.extend(str_filters(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(str_filters(item))
    return found
