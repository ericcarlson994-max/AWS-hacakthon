from __future__ import annotations

from typing import Any

from dms_core.models import DOCTYPES

ENRICHMENT_SAMPLE_CHARS = 6000
SUMMARY_INPUT_CHARS = 12000

_ENRICHMENT_SYSTEM = (
    "You are a records officer cataloguing Malaysian government documents. "
    "Read the document excerpt and reply with ONE strict JSON object and nothing else. "
    "Keys: "
    '"title" (string, the formal document title), '
    f'"doctype" (one of: {", ".join(DOCTYPES)}), '
    '"agency" (issuing agency or null), '
    '"reference_no" (the document reference number or null), '
    '"effective_date" (YYYY-MM-DD or null), '
    '"supersedes_ref" (reference number of a document this one replaces, or null), '
    '"language" (one of: en, ms, zh, mixed), '
    '"tags" (array of at most 4 names chosen only from the provided taxonomy). '
    "Use null when a value is not stated. Do not invent values."
)

_SUMMARY_SYSTEM = "You summarise government documents accurately and concisely. Never invent facts."


def _join_sections(texts: list[str], limit: int = SUMMARY_INPUT_CHARS) -> str:
    sections: list[str] = []
    remaining = limit
    for index, text in enumerate(texts, start=1):
        if remaining <= 0:
            break
        piece = text.strip()[:remaining]
        sections.append(f"[{index}]\n{piece}")
        remaining -= len(piece)
    return "\n\n".join(sections)


def enrichment_messages(text_sample: str, filename: str, taxonomy: list[str]) -> list[dict[str, Any]]:
    taxonomy_line = ", ".join(taxonomy) if taxonomy else "(none)"
    user = (
        f"Filename: {filename}\n"
        f"Tag taxonomy: {taxonomy_line}\n\n"
        f"Document excerpt:\n{text_sample[:ENRICHMENT_SAMPLE_CHARS]}"
    )
    return [{"role": "system", "content": _ENRICHMENT_SYSTEM}, {"role": "user", "content": user}]


def cluster_summary_messages(texts: list[str]) -> list[dict[str, Any]]:
    user = (
        "Summarise the following related passages from one document in at most 120 words. "
        "Keep concrete rules, amounts, dates and names.\n\n" + _join_sections(texts)
    )
    return [{"role": "system", "content": _SUMMARY_SYSTEM}, {"role": "user", "content": user}]


def root_summary_messages(texts: list[str]) -> list[dict[str, Any]]:
    user = (
        "Write an overall summary of the document described by these section summaries in at most 150 words "
        "of plain prose (no lists, no headings). State the document's purpose, its key rules, and any important dates.\n\n"
        + _join_sections(texts)
    )
    return [{"role": "system", "content": _SUMMARY_SYSTEM}, {"role": "user", "content": user}]


def single_summary_messages(text: str) -> list[dict[str, Any]]:
    user = (
        "Summarise this document in at most 150 words of plain prose. "
        "State its purpose, its key rules, and any important dates.\n\n" + text[:SUMMARY_INPUT_CHARS]
    )
    return [{"role": "system", "content": _SUMMARY_SYSTEM}, {"role": "user", "content": user}]
