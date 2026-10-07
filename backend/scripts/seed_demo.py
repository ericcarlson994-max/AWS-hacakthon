from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
CORPUS_DIR = Path(__file__).resolve().parent.parent / "samples" / "corpus"
POLL_INTERVAL_SECONDS = 1.5
POLL_TIMEOUT_SECONDS = 180.0
TERMINAL_STATUSES = {"READY", "FAILED"}

DEPARTMENTS = [
    ("finance", "Finance Division"),
    ("hr", "Human Resources Division"),
    ("public", "Agency-wide"),
]

USERS = [
    ("alice", "Alice Tan", [("finance", "contributor"), ("public", "viewer")]),
    ("ben", "Ben Rahman", [("hr", "contributor"), ("public", "viewer")]),
    ("chloe", "Chloe Lim", [("finance", "viewer"), ("hr", "viewer"), ("public", "viewer")]),
    ("admin", "Agency Admin", [("finance", "admin"), ("hr", "admin"), ("public", "admin")]),
]

SEED_TAGS = {
    "finance": ["Budget", "Procurement", "Claims", "Audit"],
    "hr": ["Leave", "Remote Work", "Recruitment", "Conduct"],
    "public": ["Digital Services", "Data Governance", "Meetings"],
}

UPLOAD_ORDER_FIRST = ["circular_2024_07_remote_work.pdf", "circular_2026_03_remote_work.docx"]
VERSION_BASE_FILE = "policy_procurement.docx"
VERSION_NEW_FILE = "policy_procurement_v2.docx"


def seed_reference_data() -> dict[str, str]:
    from dms_adapters.container import build_container

    container = build_container()
    repo = container.repo
    for department_id, name in DEPARTMENTS:
        repo.upsert_department(department_id, name)
    for username, display_name, memberships in USERS:
        repo.upsert_user(username, username, display_name)
        for department_id, role in memberships:
            repo.set_membership(username, department_id, role)
    for department_id, tag_names in SEED_TAGS.items():
        for tag_name in tag_names:
            repo.get_or_create_tag(tag_name, department_id)
    print(f"Seeded {len(DEPARTMENTS)} departments, {len(USERS)} users, {sum(len(v) for v in SEED_TAGS.values())} tags")
    return existing_documents_by_filename(repo)


def existing_documents_by_filename(repo: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    try:
        page = 1
        while True:
            rows, total = repo.list_documents(
                department_ids=[department_id for department_id, _ in DEPARTMENTS], page=page, page_size=100
            )
            for row in rows:
                for version in repo.list_versions(row.id):
                    if row.duplicate_of is None:
                        found.setdefault(version.original_filename, str(row.id))
            if page * 100 >= total or not rows:
                break
            page += 1
    except Exception as error:
        print(f"Could not list existing documents ({error}); uploading everything")
    return found


class ApiSession:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}

    def headers(self, username: str) -> dict[str, str]:
        if username not in self.tokens:
            response = self.client.post("/auth/dev-login", json={"username": username})
            response.raise_for_status()
            self.tokens[username] = response.json()["token"]
        return {"Authorization": f"Bearer {self.tokens[username]}"}

    def upload(self, username: str, path: Path, department_id: str) -> dict[str, Any]:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            response = self.client.post(
                "/documents",
                headers=self.headers(username),
                files={"file": (path.name, handle, content_type)},
                data={"department_id": department_id},
            )
        response.raise_for_status()
        return response.json()

    def upload_version(self, username: str, document_id: str, path: Path) -> dict[str, Any]:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            response = self.client.post(
                f"/documents/{document_id}/versions",
                headers=self.headers(username),
                files={"file": (path.name, handle, content_type)},
            )
        response.raise_for_status()
        return response.json()

    def status(self, username: str, document_id: str) -> dict[str, Any]:
        response = self.client.get(f"/documents/{document_id}/status", headers=self.headers(username))
        response.raise_for_status()
        return response.json()

    def versions(self, username: str, document_id: str) -> list[dict[str, Any]]:
        response = self.client.get(f"/documents/{document_id}/versions", headers=self.headers(username))
        response.raise_for_status()
        return response.json()

    def detail(self, username: str, document_id: str) -> dict[str, Any]:
        response = self.client.get(f"/documents/{document_id}", headers=self.headers(username))
        response.raise_for_status()
        return response.json()

    def wait_ready(self, username: str, document_id: str, minimum_wait: float = 0.0) -> tuple[str, float]:
        started = time.monotonic()
        last_status = "UNKNOWN"
        while time.monotonic() - started < POLL_TIMEOUT_SECONDS:
            try:
                payload = self.status(username, document_id)
                last_status = payload.get("status", "UNKNOWN")
            except httpx.HTTPError as error:
                last_status = f"ERROR {error}"
            if last_status in TERMINAL_STATUSES and time.monotonic() - started >= minimum_wait:
                return last_status, time.monotonic() - started
            time.sleep(POLL_INTERVAL_SECONDS)
        return f"TIMEOUT ({last_status})", time.monotonic() - started


def wait_for_delta_stats(session: ApiSession, username: str, document_id: str, version_no: int) -> dict[str, Any] | None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        for version in session.versions(username, document_id):
            if version.get("version_no") == version_no and version.get("delta_stats"):
                return version["delta_stats"]
        time.sleep(POLL_INTERVAL_SECONDS)
    return None


def ordered_entries(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = [entry for entry in manifest if "version_of" not in entry]
    first = [entry for name in UPLOAD_ORDER_FIRST for entry in primary if entry["file"] == name]
    rest = [entry for entry in primary if entry["file"] not in UPLOAD_ORDER_FIRST]
    return first + rest


def print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [max(len(str(value)) for value in column) for column in zip(headers, *rows)]
    line = "  ".join(header.ljust(width) for header, width in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(value).ljust(width) for value, width in zip(row, widths)))


def main() -> int:
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    existing = seed_reference_data()
    summary: list[list[str]] = []
    uploaded_ids: dict[str, str] = {}
    with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
        session = ApiSession(client)
        for entry in ordered_entries(manifest):
            file_name = entry["file"]
            uploader = entry["uploader"]
            path = CORPUS_DIR / file_name
            if file_name in existing:
                document_id = existing[file_name]
                uploaded_ids[file_name] = document_id
                try:
                    current = session.status(uploader, document_id)["status"]
                except httpx.HTTPError:
                    current = "UNKNOWN"
                summary.append([file_name, entry["department_id"], document_id, current, "-", "already seeded"])
                continue
            try:
                response = session.upload(uploader, path, entry["department_id"])
            except httpx.HTTPError as error:
                summary.append([file_name, entry["department_id"], "-", "UPLOAD ERROR", "-", str(error)[:60]])
                continue
            document_id = str(response["document_id"])
            uploaded_ids[file_name] = document_id
            duplicate = response.get("duplicate")
            if duplicate and duplicate.get("tier") == "exact":
                note = f"exact duplicate of {duplicate.get('title')}"
                summary.append([file_name, entry["department_id"], document_id, response.get("status", "?"), "0.0s", note])
                print(f"{file_name}: {note}")
                continue
            final_status, elapsed = session.wait_ready(uploader, document_id)
            note = ""
            if final_status in TERMINAL_STATUSES:
                detail = session.detail(uploader, document_id)
                if detail.get("duplicate"):
                    note = f"{detail['duplicate'].get('tier')} duplicate of {detail['duplicate'].get('title')}"
                else:
                    note = detail.get("title", "")
            summary.append([file_name, entry["department_id"], document_id, final_status, f"{elapsed:.1f}s", note])
            print(f"{file_name}: {final_status} in {elapsed:.1f}s {note}")

        version_entry = next((entry for entry in manifest if entry["file"] == VERSION_NEW_FILE), None)
        base_document_id = uploaded_ids.get(VERSION_BASE_FILE)
        if version_entry and base_document_id:
            uploader = version_entry["uploader"]
            versions = session.versions(uploader, base_document_id)
            if any(version.get("original_filename") == VERSION_NEW_FILE for version in versions):
                summary.append([VERSION_NEW_FILE, "finance", base_document_id, "-", "-", "version already uploaded"])
            else:
                try:
                    created = session.upload_version(uploader, base_document_id, CORPUS_DIR / VERSION_NEW_FILE)
                    final_status, elapsed = session.wait_ready(uploader, base_document_id, minimum_wait=POLL_INTERVAL_SECONDS)
                    stats = wait_for_delta_stats(session, uploader, base_document_id, int(created["version_no"]))
                    print(f"{VERSION_NEW_FILE}: version {created['version_no']} {final_status} delta_stats={json.dumps(stats)}")
                    summary.append(
                        [VERSION_NEW_FILE, "finance", base_document_id, final_status, f"{elapsed:.1f}s", f"v{created['version_no']} delta {json.dumps(stats)}"]
                    )
                except httpx.HTTPError as error:
                    summary.append([VERSION_NEW_FILE, "finance", base_document_id, "VERSION ERROR", "-", str(error)[:60]])

    print()
    print_table(summary, ["file", "dept", "document_id", "status", "time", "notes"])
    failures = [row for row in summary if row[3] not in ("READY", "-") and not row[5].startswith("exact")]
    for row in failures:
        print(f"FAILED: {row[0]} status={row[3]} {row[5]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
