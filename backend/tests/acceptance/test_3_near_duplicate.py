from __future__ import annotations

RESAVED_FILE = "sop_claims_submission_resaved.pdf"


def test_resaved_pdf_is_flagged_near_duplicate(login, find_doc_by_filename, wait_ready):
    headers = login("alice")
    document = find_doc_by_filename(headers, RESAVED_FILE)
    assert document is not None, f"{RESAVED_FILE} has not been seeded"
    wait_ready(document["id"], headers)
    document = find_doc_by_filename(headers, RESAVED_FILE)
    assert document["duplicate"] is not None, "resaved copy was not flagged as a duplicate"
    assert document["duplicate"]["tier"] in ("near", "semantic")
