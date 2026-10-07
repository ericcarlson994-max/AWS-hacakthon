from typing import Any

from dms_core.models import SearchFilters
from dms_core.search.filters import build_filter

BM25_FIELDS = ["title^3", "text", "text.cjk", "heading_path^2"]


def build_knn_body(
    vector: list[float],
    groups: list[str],
    filters: SearchFilters | None,
    k: int,
    *,
    leaf_only: bool = False,
) -> dict[str, Any]:
    return {
        "size": k,
        "_source": {"excludes": ["embedding"]},
        "query": {
            "bool": {
                "must": [{"knn": {"embedding": {"vector": list(vector), "k": k}}}],
                "filter": build_filter(groups, filters, leaf_only=leaf_only),
            }
        },
    }


def build_bm25_body(
    query: str,
    groups: list[str],
    filters: SearchFilters | None,
    size: int,
    *,
    leaf_only: bool = False,
) -> dict[str, Any]:
    return {
        "size": size,
        "_source": {"excludes": ["embedding"]},
        "query": {
            "bool": {
                "must": [{"multi_match": {"query": query, "fields": list(BM25_FIELDS), "fuzziness": "AUTO"}}],
                "filter": build_filter(groups, filters, leaf_only=leaf_only),
            }
        },
        "highlight": {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "fields": {"text": {"fragment_size": 180, "number_of_fragments": 1}},
        },
    }


def build_did_you_mean_body(query: str, groups: list[str] | None = None) -> dict[str, Any]:
    phrase: dict[str, Any] = {
        "field": "title.shingle",
        "size": 1,
        "gram_size": 3,
        "direct_generator": [{"field": "title.shingle", "suggest_mode": "always"}],
        "highlight": {"pre_tag": "", "post_tag": ""},
    }
    if groups is not None:
        phrase["collate"] = {
            "query": {
                "source": {
                    "bool": {
                        "must": [{"match": {"title": "{{suggestion}}"}}],
                        "filter": [{"terms": {"allowed_groups": list(groups)}}],
                    }
                }
            },
            "prune": False,
        }
    return {"size": 0, "suggest": {"did_you_mean": {"text": query, "phrase": phrase}}}
