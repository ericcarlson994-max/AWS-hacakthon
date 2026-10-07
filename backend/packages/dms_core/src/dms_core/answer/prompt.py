from collections.abc import Collection
from typing import Any
from uuid import UUID

from dms_core.models import SearchHit

SYSTEM_PROMPT = (
    "You are a careful assistant answering questions about government documents. "
    "Answer only from the sources provided. Cite every claim as [n] using the source numbers. "
    "If a source is superseded, say so and prefer the newer one. "
    "If the answer is not in the sources, say you couldn't find it in the documents. "
    "Be concise and do not invent sources or numbers."
)


def format_source(number: int, hit: SearchHit, superseded: bool) -> str:
    header = [f"[{number}] {hit.title or 'Untitled document'}"]
    if hit.page is not None:
        header.append(f"page {hit.page}")
    if hit.heading_path:
        header.append(" > ".join(hit.heading_path))
    if hit.level > 0:
        header.append("document summary")
    if superseded:
        header.append("SUPERSEDED by a newer document")
    return " | ".join(header) + "\n" + hit.text.strip()


def build_messages(
    question: str,
    hits: list[SearchHit],
    superseded_document_ids: Collection[UUID] = (),
) -> list[dict[str, Any]]:
    superseded = set(superseded_document_ids)
    sources = "\n\n".join(
        format_source(number, hit, hit.document_id in superseded) for number, hit in enumerate(hits, start=1)
    )
    user_content = f"Sources:\n\n{sources}\n\nQuestion: {question.strip()}\n\nAnswer with citations like [1]."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
