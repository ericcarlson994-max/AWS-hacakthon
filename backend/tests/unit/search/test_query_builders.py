from dms_core.models import SearchFilters
from dms_core.search.facets import parse_facets
from dms_core.search.filters import build_filter
from dms_core.search.fusion import rrf
from dms_core.search.hybrid_query import build_bm25_body, build_did_you_mean_body, build_knn_body
from dms_core.search.suggest_query import build_suggest_body


def test_build_filter_always_has_groups_and_optional_clauses() -> None:
    assert build_filter(["finance"], None) == [{"terms": {"allowed_groups": ["finance"]}}]
    filters = SearchFilters(
        doctype=["policy"], department_id=["finance"], tags=["budget"], date_from="2024-01-01", include_superseded=False
    )
    clauses = build_filter(["finance", "public"], filters, leaf_only=True)
    assert clauses[0] == {"terms": {"allowed_groups": ["finance", "public"]}}
    assert {"terms": {"doctype": ["policy"]}} in clauses
    assert {"terms": {"department_id": ["finance"]}} in clauses
    assert {"terms": {"tags": ["budget"]}} in clauses
    assert {"range": {"effective_date": {"gte": "2024-01-01"}}} in clauses
    assert {"term": {"superseded": False}} in clauses
    assert {"term": {"level": 0}} in clauses


def test_suggest_body_tiers_and_filter() -> None:
    body = build_suggest_body("leave", ["hr"])
    should = body["query"]["bool"]["should"]
    assert should[0] == {"term": {"title.raw": {"value": "leave", "boost": 10}}}
    assert should[1]["match_phrase_prefix"]["title"]["boost"] == 6
    assert should[2]["match"]["title.edge"]["boost"] == 3
    assert should[3]["match"]["title.tri"]["minimum_should_match"] == "70%"
    assert should[4]["match"]["title"]["fuzziness"] == "AUTO"
    assert should[4]["match"]["title"]["prefix_length"] == 2
    assert body["query"]["bool"]["filter"] == [{"terms": {"allowed_groups": ["hr"]}}]
    assert body["aggs"]["tags"]["terms"] == {"field": "tags", "size": 5}
    assert body["size"] == 8


def test_knn_and_bm25_bodies() -> None:
    knn = build_knn_body([0.1, 0.2], ["hr"], None, 50)
    assert knn["query"]["bool"]["must"][0]["knn"]["embedding"] == {"vector": [0.1, 0.2], "k": 50}
    assert knn["_source"] == {"excludes": ["embedding"]}
    bm25 = build_bm25_body("leave", ["hr"], None, 50)
    multi = bm25["query"]["bool"]["must"][0]["multi_match"]
    assert multi["fields"] == ["title^3", "text", "text.cjk", "heading_path^2"]
    assert multi["fuzziness"] == "AUTO"
    assert bm25["highlight"]["pre_tags"] == ["<mark>"]
    assert bm25["highlight"]["fields"]["text"]["fragment_size"] == 180
    assert "aggs" not in bm25
    assert knn["query"]["bool"]["filter"] == bm25["query"]["bool"]["filter"]


def test_did_you_mean_body_uses_shingle_field() -> None:
    body = build_did_you_mean_body("anual leav")
    assert body["suggest"]["did_you_mean"]["phrase"]["field"] == "title.shingle"
    assert body["suggest"]["did_you_mean"]["text"] == "anual leav"


def test_rrf_orders_by_combined_rank() -> None:
    scores = rrf([["a", "b", "c"], ["b", "c", "a"]], k=60)
    assert list(scores) == ["b", "a", "c"]
    assert abs(scores["b"] - (1 / 62 + 1 / 61)) < 1e-12
    only = rrf([["x"], []])
    assert only == {"x": 1 / 61}


def test_parse_facets() -> None:
    facets = parse_facets({"doctype": {"buckets": [{"key": "policy", "doc_count": 3}]}, "noise": {"value": 1}})
    assert list(facets) == ["doctype"]
    assert facets["doctype"][0].value == "policy"
    assert facets["doctype"][0].count == 3


def test_build_filter_document_ids_scope() -> None:
    assert not any("document_id" in clause.get("terms", {}) for clause in build_filter(["finance"], SearchFilters()))
    clauses = build_filter(["finance"], SearchFilters(document_ids=["a", "b"]))
    assert {"terms": {"document_id": ["a", "b"]}} in clauses
