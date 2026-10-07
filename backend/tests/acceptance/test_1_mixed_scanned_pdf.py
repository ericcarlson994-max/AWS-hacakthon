from __future__ import annotations

SCANNED_FILE = "report_digital_services_2025_scanned.pdf"
PAGE_TWO_PHRASE = "online business licence renewal service"


def test_scanned_pdf_is_ready_with_four_pages(http, login, find_doc_by_filename, search):
    headers = login("admin")
    document = find_doc_by_filename(headers, SCANNED_FILE)
    assert document is not None, f"{SCANNED_FILE} has not been seeded"
    assert document["status"] == "READY", document.get("status_detail")
    assert document["page_count"] == 4
    assert document["mime_type"] == "application/pdf"

    health = http.get("/health").json()
    live_ocr = bool(health.get("deps", {}).get("openrouter"))
    response = search(headers, PAGE_TWO_PHRASE, page_size=10)
    found_ids = {result["document_id"] for result in response["results"]}
    if live_ocr:
        assert document["id"] in found_ids
    else:
        assert response["total"] >= 0
