import re

from dms_core.models import Citation, SearchHit

CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
QUOTE_CHARS = 300


def extract_cited_numbers(text: str) -> list[int]:
    numbers: list[int] = []
    for match in CITATION_PATTERN.finditer(text or ""):
        for part in match.group(1).split(","):
            number = int(part.strip())
            if number not in numbers:
                numbers.append(number)
    return numbers


def build_citations(hits: list[SearchHit], numbers: list[int]) -> list[Citation]:
    citations: list[Citation] = []
    for number in numbers:
        if number < 1 or number > len(hits):
            continue
        hit = hits[number - 1]
        citations.append(
            Citation(
                n=number,
                document_id=hit.document_id,
                title=hit.title or "Untitled document",
                chunk_id=hit.chunk_id,
                page=hit.page,
                quote=hit.text[:QUOTE_CHARS],
            )
        )
    return citations
