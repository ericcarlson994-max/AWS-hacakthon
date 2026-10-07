from collections import Counter
from collections.abc import Iterable
from typing import Any

from dms_core.models import FacetBucket

FACET_FIELDS = ("doctype", "tags", "department_id")


def parse_facets(aggregations: dict[str, Any] | None) -> dict[str, list[FacetBucket]]:
    facets: dict[str, list[FacetBucket]] = {}
    for name, aggregation in (aggregations or {}).items():
        if not isinstance(aggregation, dict) or "buckets" not in aggregation:
            continue
        facets[name] = [
            FacetBucket(value=str(bucket.get("key")), count=int(bucket.get("doc_count", 0)))
            for bucket in aggregation["buckets"]
        ]
    return facets


def document_facets(entries: Iterable[tuple[str | None, str | None, list[str]]]) -> dict[str, list[FacetBucket]]:
    counters: dict[str, Counter[str]] = {name: Counter() for name in FACET_FIELDS}
    for doctype, department_id, tags in entries:
        if doctype:
            counters["doctype"][doctype] += 1
        if department_id:
            counters["department_id"][department_id] += 1
        for tag in dict.fromkeys(tags):
            counters["tags"][tag] += 1
    return {
        name: [FacetBucket(value=value, count=count) for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]
        for name, counter in counters.items()
    }
