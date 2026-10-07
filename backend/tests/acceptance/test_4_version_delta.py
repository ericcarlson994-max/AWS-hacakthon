from __future__ import annotations

BASE_FILE = "policy_procurement.docx"


def test_one_section_edit_reuses_most_chunks(http, login, find_doc_by_filename, wait_ready):
    headers = login("alice")
    document = find_doc_by_filename(headers, BASE_FILE)
    assert document is not None, f"{BASE_FILE} has not been seeded"
    wait_ready(document["id"], headers)

    response = http.get(f"/documents/{document['id']}/versions", headers=headers)
    assert response.status_code == 200, response.text
    versions = sorted(response.json(), key=lambda version: version["version_no"])
    assert len(versions) >= 2

    previous, latest = versions[-2], versions[-1]
    stats = latest["delta_stats"]
    assert stats is not None
    total = stats["reused"] + stats["added"]
    assert total > 0
    assert stats["reused"] / total >= 0.8
    assert previous["merkle_root"] and latest["merkle_root"]
    assert previous["merkle_root"] != latest["merkle_root"]
