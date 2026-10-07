from __future__ import annotations

import math
from collections.abc import Sequence

from dms_core.models import TagRow

DEFAULT_TAG_THRESHOLD = 0.55


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def suggest_tags(
    doc_vec: Sequence[float] | None, tags: list[TagRow], threshold: float = DEFAULT_TAG_THRESHOLD
) -> list[tuple[TagRow, float]]:
    if not doc_vec:
        return []
    scored: list[tuple[TagRow, float]] = []
    for tag in tags:
        if not tag.centroid:
            continue
        similarity = cosine(doc_vec, tag.centroid)
        if similarity >= threshold:
            scored.append((tag, similarity))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def match_llm_tags(names: list[str], tags: list[TagRow]) -> list[TagRow]:
    by_name: dict[str, TagRow] = {}
    for tag in tags:
        by_name.setdefault(" ".join(tag.name.split()).lower(), tag)
    matched: list[TagRow] = []
    seen_ids: set[int] = set()
    for name in names:
        tag = by_name.get(" ".join(name.split()).lower())
        if tag is not None and tag.id not in seen_ids:
            seen_ids.add(tag.id)
            matched.append(tag)
    return matched


def recompute_centroid(vectors: Sequence[Sequence[float] | None]) -> list[float] | None:
    usable = [list(vector) for vector in vectors if vector]
    if not usable:
        return None
    dimension = len(usable[0])
    usable = [vector for vector in usable if len(vector) == dimension]
    mean = [sum(column) / len(usable) for column in zip(*usable)]
    norm = math.sqrt(sum(x * x for x in mean))
    if norm == 0.0:
        return None
    return [x / norm for x in mean]
