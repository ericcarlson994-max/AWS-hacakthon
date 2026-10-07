import hashlib
from uuid import UUID

from dms_core.chunking.tokens import normalize_text


def make_chunk_id(document_id: UUID, text: str) -> str:
    digest = hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()[:16]
    return f"{document_id}:{digest}"
