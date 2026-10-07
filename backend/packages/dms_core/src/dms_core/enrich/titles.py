from __future__ import annotations

import re
from pathlib import PurePath

from dms_core.models import DEFAULT_TITLE, Block, TitleSuggestion

METADATA_CONFIDENCE = 0.9
HEADING_CONFIDENCE = 0.75
FILENAME_CONFIDENCE = 0.4
MIN_TITLE_LENGTH = 3
MAX_TITLE_LENGTH = 120

_EXTENSION_PATTERN = re.compile(r"\.[a-z0-9]{2,5}$", re.IGNORECASE)
_JUNK_METADATA_PATTERN = re.compile(
    r"^(microsoft\s+(word|excel|powerpoint)\s*-|untitled\b|document\d*$|doc\d*$|slide\s*\d+$|presentation\d*$)",
    re.IGNORECASE,
)
_DATE_PATTERNS = (
    re.compile(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}$"),
    re.compile(r"^\d{1,2}\s+[a-z]+\.?,?\s+\d{2,4}$", re.IGNORECASE),
    re.compile(r"^[a-z]+\.?\s+\d{1,2},?\s+\d{2,4}$", re.IGNORECASE),
    re.compile(r"^[a-z]+\s+\d{4}$", re.IGNORECASE),
)
_MONTH_WORDS = {
    "jan", "january", "januari", "feb", "february", "februari", "mar", "march", "mac", "apr", "april",
    "may", "mei", "jun", "june", "jul", "july", "julai", "aug", "august", "ogos", "sep", "sept",
    "september", "oct", "october", "okt", "oktober", "nov", "november", "dec", "december", "dis", "disember",
}


def _looks_like_filename(title: str, filename: str) -> bool:
    lowered = title.lower()
    name = PurePath(filename.replace("\\", "/")).name.lower() if filename else ""
    stem = _filename_stem(name) if name else ""
    if lowered in {name, stem} - {""}:
        return True
    return not re.search(r"\s", title) and bool(re.search(r"[_\-]", title))


def _filename_stem(filename: str) -> str:
    name = PurePath(filename.replace("\\", "/")).name
    stem = _EXTENSION_PATTERN.sub("", name)
    return stem


def _collapse(text: str) -> str:
    return " ".join(text.split())


def is_junk_metadata_title(title: str, filename: str) -> bool:
    cleaned = _collapse(title)
    if len(cleaned) < MIN_TITLE_LENGTH:
        return True
    if _EXTENSION_PATTERN.search(cleaned):
        return True
    if _JUNK_METADATA_PATTERN.search(cleaned):
        return True
    return _looks_like_filename(cleaned, filename)


def looks_like_date(text: str) -> bool:
    candidate = text.strip()
    if any(pattern.match(candidate) for pattern in _DATE_PATTERNS):
        words = re.findall(r"[a-z]+", candidate.lower())
        return all(word in _MONTH_WORDS for word in words)
    return False


def is_acceptable_heading(text: str) -> bool:
    cleaned = _collapse(text)
    if not MIN_TITLE_LENGTH <= len(cleaned) <= MAX_TITLE_LENGTH:
        return False
    if re.fullmatch(r"[\d\W_]+", cleaned):
        return False
    if looks_like_date(cleaned):
        return False
    return True


def _heading_candidate(blocks: list[Block]) -> str | None:
    first_page_blocks = sorted((b for b in blocks if b.page == 1), key=lambda b: b.order)
    for block in first_page_blocks:
        if block.type == "heading" and is_acceptable_heading(block.text):
            return _collapse(block.text)
    top_third_count = max(1, -(-len(first_page_blocks) // 3))
    top_third = [b for b in first_page_blocks[:top_third_count] if b.font_size is not None]
    for block in sorted(top_third, key=lambda b: (-(b.font_size or 0.0), b.order)):
        if is_acceptable_heading(block.text):
            return _collapse(block.text)
    return None


def clean_filename(filename: str) -> str | None:
    stem = _filename_stem(filename)
    spaced = _collapse(re.sub(r"[_\-.]+", " ", stem))
    if len(spaced) < MIN_TITLE_LENGTH or re.fullmatch(r"[\d\s]+", spaced):
        return None
    return " ".join(word if word.isupper() and len(word) > 1 else word.capitalize() for word in spaced.split())


def suggest_title(embedded_title: str | None, blocks: list[Block], filename: str) -> TitleSuggestion:
    if embedded_title and not is_junk_metadata_title(embedded_title, filename):
        return TitleSuggestion(title=_collapse(embedded_title)[:MAX_TITLE_LENGTH], source="metadata", confidence=METADATA_CONFIDENCE)
    heading = _heading_candidate(blocks)
    if heading:
        return TitleSuggestion(title=heading, source="heading", confidence=HEADING_CONFIDENCE)
    from_filename = clean_filename(filename) if filename else None
    if from_filename:
        return TitleSuggestion(title=from_filename[:MAX_TITLE_LENGTH], source="filename", confidence=FILENAME_CONFIDENCE)
    return TitleSuggestion(title=DEFAULT_TITLE, source="default", confidence=0.0)
