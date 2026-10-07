from typing import Any


def build_suggest_body(q: str, groups: list[str], size: int = 8) -> dict[str, Any]:
    return {
        "size": size,
        "_source": ["document_id", "title", "doctype", "department_id", "tags"],
        "query": {
            "bool": {
                "should": [
                    {"term": {"title.raw": {"value": q, "boost": 10}}},
                    {"match_phrase_prefix": {"title": {"query": q, "boost": 6}}},
                    {"match": {"title.edge": {"query": q, "boost": 3}}},
                    {"match": {"title.tri": {"query": q, "minimum_should_match": "70%", "boost": 1}}},
                    {"match": {"title": {"query": q, "fuzziness": "AUTO", "prefix_length": 2, "boost": 0.5}}},
                    {"match": {"title.cjk": {"query": q, "boost": 2}}},
                ],
                "minimum_should_match": 1,
                "filter": [{"terms": {"allowed_groups": list(groups)}}],
            }
        },
        "aggs": {"tags": {"terms": {"field": "tags", "size": 5}}},
    }
