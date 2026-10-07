from __future__ import annotations

CLAIMS_FILE = "sop_claims_submission.pdf"


def test_claims_search_ranks_sop_in_top_five(login, search, find_doc_by_filename):
    headers = login("alice")
    claims = find_doc_by_filename(headers, CLAIMS_FILE)
    assert claims is not None, f"{CLAIMS_FILE} has not been seeded"

    response = search(headers, "claims submission", page_size=10)
    top_titles_and_ids = [(result["document_id"], result["title"]) for result in response["results"][:5]]
    claims_family_titles = {claims["title"].lower()}
    assert any(
        document_id == claims["id"] or title.lower() in claims_family_titles
        for document_id, title in top_titles_and_ids
    ), top_titles_and_ids
    assert response["total"] >= 1
    for facet_name in ("doctype", "tags", "department_id"):
        assert facet_name in response["facets"]
    assert response["facets"]["department_id"]
