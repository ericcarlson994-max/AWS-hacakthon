from __future__ import annotations

import subprocess
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

PROCUREMENT_FILE = "policy_procurement.docx"


def test_rebuild_index_restores_search(login, search, find_doc_by_filename):
    headers = login("alice")
    procurement = find_doc_by_filename(headers, PROCUREMENT_FILE)
    assert procurement is not None, f"{PROCUREMENT_FILE} has not been seeded"

    completed = subprocess.run(
        ["uv", "run", "--no-sync", "python", "scripts/rebuild_index.py"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    deadline = time.monotonic() + 30
    found_ids: set[str] = set()
    while time.monotonic() < deadline:
        response = search(headers, "procurement", page_size=10)
        found_ids = {result["document_id"] for result in response["results"]}
        if procurement["id"] in found_ids:
            break
        time.sleep(1)
    assert procurement["id"] in found_ids
