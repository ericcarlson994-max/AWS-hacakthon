from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from dms_core.models import DOCTYPES, DocumentMeta, EnrichmentResult

ALLOWED_LANGUAGES = ("en", "ms", "zh", "mixed")

_MONTHS = {
    "jan": 1, "january": 1, "januari": 1,
    "feb": 2, "february": 2, "februari": 2,
    "mar": 3, "march": 3, "mac": 3,
    "apr": 4, "april": 4,
    "may": 5, "mei": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7, "julai": 7,
    "aug": 8, "august": 8, "ogos": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12, "dis": 12, "disember": 12,
}

_DOCTYPE_ALIASES = {
    "standard operating procedure": "sop",
    "procedure": "sop",
    "guidelines": "guideline",
    "guide": "guideline",
    "garis panduan": "guideline",
    "pekeliling": "circular",
    "dasar": "policy",
    "laporan": "report",
    "minit": "minutes",
    "meeting minutes": "minutes",
}

_LANGUAGE_ALIASES = {
    "english": "en",
    "malay": "ms",
    "bahasa melayu": "ms",
    "bm": "ms",
    "my": "ms",
    "chinese": "zh",
    "mandarin": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
}


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        end = text.rfind("}")
        if end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned or cleaned.lower() in {"null", "none", "n/a", "na", "unknown", "-"}:
        return None
    return cleaned


def normalize_doctype(value: Any) -> str:
    cleaned = _clean_string(value)
    if not cleaned:
        return "other"
    lowered = cleaned.lower()
    if lowered in DOCTYPES:
        return lowered
    return _DOCTYPE_ALIASES.get(lowered, "other")


def _safe_date(year: int, month: int, day: int) -> str | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_date(value: Any) -> str | None:
    cleaned = _clean_string(value)
    if not cleaned:
        return None
    text = cleaned.lower().replace(",", " ")
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    text = " ".join(text.split())
    iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[t ].*)?", text)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    day_first = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if day_first:
        return _safe_date(int(day_first.group(3)), int(day_first.group(2)), int(day_first.group(1)))
    day_month_name = re.fullmatch(r"(\d{1,2})[\s\-]+([a-z]+)\.?[\s\-]+(\d{2,4})", text)
    if day_month_name and day_month_name.group(2) in _MONTHS:
        return _safe_date(int(day_month_name.group(3)), _MONTHS[day_month_name.group(2)], int(day_month_name.group(1)))
    month_name_day = re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})\s+(\d{2,4})", text)
    if month_name_day and month_name_day.group(1) in _MONTHS:
        return _safe_date(int(month_name_day.group(3)), _MONTHS[month_name_day.group(1)], int(month_name_day.group(2)))
    return None


def normalize_language(value: Any) -> str | None:
    cleaned = _clean_string(value)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in ALLOWED_LANGUAGES:
        return lowered
    return _LANGUAGE_ALIASES.get(lowered)


def _clean_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [part for part in re.split(r"[,;]", value)]
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_string(item)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            tags.append(cleaned)
    return tags[:4]


def parse_enrichment(raw: str) -> EnrichmentResult:
    data = _extract_json_object(raw or "")
    return EnrichmentResult(
        title=_clean_string(data.get("title")),
        doctype=normalize_doctype(data.get("doctype")),
        agency=_clean_string(data.get("agency")),
        reference_no=_clean_string(data.get("reference_no")),
        effective_date=normalize_date(data.get("effective_date")),
        supersedes_ref=_clean_string(data.get("supersedes_ref")),
        language=normalize_language(data.get("language")),
        tags=_clean_tags(data.get("tags")),
    )


def to_document_meta(result: EnrichmentResult) -> DocumentMeta:
    return DocumentMeta(
        agency=result.agency,
        reference_no=result.reference_no,
        effective_date=result.effective_date,
        supersedes_ref=result.supersedes_ref,
        language=result.language,
    )
