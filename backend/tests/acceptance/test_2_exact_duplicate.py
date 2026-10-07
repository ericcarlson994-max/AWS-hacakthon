from __future__ import annotations

SOURCE_FILE = "sop_claims_submission.pdf"


def test_reupload_returns_exact_duplicate_ready(login, upload, corpus_dir, find_doc_by_filename):
    headers = login("alice")
    original = find_doc_by_filename(headers, SOURCE_FILE)
    assert original is not None, f"{SOURCE_FILE} has not been seeded"

    response = upload(headers, corpus_dir / SOURCE_FILE, "finance")
    assert response.status_code in (200, 201, 202), response.text
    body = response.json()
    assert body["duplicate"] is not None
    assert body["duplicate"]["tier"] == "exact"
    assert body["status"] == "READY"
