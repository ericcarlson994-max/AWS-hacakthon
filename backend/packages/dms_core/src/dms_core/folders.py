from __future__ import annotations

import re
import secrets

from dms_core.models import DocumentMeta

INBOX_FOLDER_ID = "inbox"

DEFAULT_FOLDERS: tuple[tuple[str, str, str | None], ...] = (
    ("inbox", "Inbox", None),
    ("policies", "Policies", None),
    ("sops", "SOPs", None),
    ("circulars", "Circulars", None),
    ("guidelines", "Guidelines", None),
    ("reports", "Reports", None),
    ("minutes", "Minutes", None),
    ("sop-fin", "Finance", "sops"),
    ("sop-hr", "Human resources", "sops"),
    ("circ-2024", "2024", "circulars"),
    ("circ-2026", "2026", "circulars"),
    ("min-mgmt", "Management meetings", "minutes"),
)

DOCTYPE_ROOT_FOLDERS: dict[str, str] = {
    "policy": "policies",
    "sop": "sops",
    "circular": "circulars",
    "guideline": "guidelines",
    "report": "reports",
    "minutes": "minutes",
}

CIRCULAR_YEAR_FOLDERS: dict[str, str] = {"2024": "circ-2024", "2026": "circ-2026"}
SOP_DEPARTMENT_FOLDERS: dict[str, str] = {"finance": "sop-fin", "hr": "sop-hr"}
MINUTES_FOLDER = "min-mgmt"
SLUG_MAX_CHARS = 40


class FolderConflict(Exception):
    pass


class FolderCycle(Exception):
    pass


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX_CHARS].strip("-")
    return slug or "folder"


def new_folder_id(name: str) -> str:
    return f"{slugify(name)}-{secrets.token_hex(3)}"


def normalize_folder_name(name: str | None) -> str:
    return " ".join((name or "").split())


def auto_folder_candidates(doctype: str | None, department_id: str, meta: DocumentMeta) -> list[str]:
    root = DOCTYPE_ROOT_FOLDERS.get(doctype or "")
    if root is None:
        return []
    specific: str | None = None
    if doctype == "circular":
        year = (meta.effective_date or "")[:4]
        specific = CIRCULAR_YEAR_FOLDERS.get(year)
    elif doctype == "sop":
        specific = SOP_DEPARTMENT_FOLDERS.get(department_id)
    elif doctype == "minutes":
        specific = MINUTES_FOLDER
    return [folder for folder in (specific, root) if folder]
