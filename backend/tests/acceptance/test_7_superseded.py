from __future__ import annotations

OLD_CIRCULAR = "circular_2024_07_remote_work.pdf"
NEW_CIRCULAR = "circular_2026_03_remote_work.docx"


def test_old_circular_is_superseded_by_new(login, find_doc_by_filename, wait_ready):
    headers = login("ben")
    old_document = find_doc_by_filename(headers, OLD_CIRCULAR)
    new_document = find_doc_by_filename(headers, NEW_CIRCULAR)
    assert old_document is not None and new_document is not None
    wait_ready(new_document["id"], headers)
    refreshed_old = find_doc_by_filename(headers, OLD_CIRCULAR)
    assert refreshed_old["superseded_by"] == new_document["id"]
    assert new_document["superseded_by"] is None
