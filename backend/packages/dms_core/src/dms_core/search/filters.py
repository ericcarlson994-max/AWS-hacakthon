from typing import Any

from dms_core.models import SearchFilters


def build_filter(
    groups: list[str], filters: SearchFilters | None, *, leaf_only: bool = False
) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = [{"terms": {"allowed_groups": list(groups)}}]
    if filters is not None:
        if filters.doctype:
            clauses.append({"terms": {"doctype": list(filters.doctype)}})
        if filters.department_id:
            clauses.append({"terms": {"department_id": list(filters.department_id)}})
        if filters.document_ids:
            clauses.append({"terms": {"document_id": list(filters.document_ids)}})
        if filters.tags:
            clauses.append({"terms": {"tags": list(filters.tags)}})
        date_range: dict[str, str] = {}
        if filters.date_from:
            date_range["gte"] = filters.date_from
        if filters.date_to:
            date_range["lte"] = filters.date_to
        if date_range:
            clauses.append({"range": {"effective_date": date_range}})
        if not filters.include_superseded:
            clauses.append({"term": {"superseded": False}})
    if leaf_only:
        clauses.append({"term": {"level": 0}})
    return clauses
