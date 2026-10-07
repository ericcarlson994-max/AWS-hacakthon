from typing import Any

from conftest import StubRepo, make_user
from dms_adapters.fakes.ai import FakeEmbedder
from dms_adapters.fakes.storage import FakeSearchIndex
from dms_core.config import Settings
from dms_core.models import TagRef, TagRow
from dms_core.search.mappings import CHUNKS_INDEX, TITLES_INDEX
from dms_core.search.service import SearchService


def chunk_hit(chunk_id: str, document_id: Any, text: str, highlight: str | None = None, **source: Any) -> dict[str, Any]:
    hit: dict[str, Any] = {
        "_id": chunk_id,
        "_score": 1.0,
        "_source": {"chunk_id": chunk_id, "document_id": str(document_id), "text": text, "level": 0, **source},
    }
    if highlight:
        hit["highlight"] = {"text": [highlight]}
    return hit


def response(hits: list[dict[str, Any]], aggregations: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"hits": {"total": {"value": len(hits)}, "hits": hits}, "aggregations": aggregations or {}, "suggest": {}}


def is_knn(body: dict[str, Any]) -> bool:
    must = body.get("query", {}).get("bool", {}).get("must", [])
    return bool(must) and "knn" in must[0]


def make_index(knn_hits: list[dict[str, Any]], bm25_hits: list[dict[str, Any]], aggregations: dict[str, Any] | None = None) -> FakeSearchIndex:
    def responder(index: str, body: dict[str, Any]) -> dict[str, Any]:
        if index == CHUNKS_INDEX:
            return response(knn_hits) if is_knn(body) else response(bm25_hits, aggregations)
        return {"hits": {"hits": []}, "suggest": {"did_you_mean": [{"options": [{"text": "annual leave"}]}]}}

    return FakeSearchIndex(responder)


def make_service(index: FakeSearchIndex, repo: StubRepo) -> tuple[SearchService, FakeEmbedder]:
    embedder = FakeEmbedder(dim=16)
    return SearchService(index, embedder, repo, Settings(fake_ai=True)), embedder


def group_filters(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in body["query"]["bool"]["filter"] if "terms" in c and "allowed_groups" in c["terms"]]


def test_every_query_carries_exact_user_groups(repo: StubRepo) -> None:
    doc = repo.add_document("finance", "Budget policy")
    index = make_index([chunk_hit("c1", doc.id, "budget")], [chunk_hit("c1", doc.id, "budget")])
    service, _ = make_service(index, repo)
    user = make_user("public", "finance")
    service.suggest(user, "budget")
    service.search(user, "budget")
    service.retrieve(user, "budget")
    query_bodies = [body for _, body in index.queries if "query" in body]
    assert len(query_bodies) == 5
    for body in query_bodies:
        assert group_filters(body) == [{"terms": {"allowed_groups": ["finance", "public"]}}]


def test_search_rrf_collapse_and_snippets(repo: StubRepo) -> None:
    first = repo.add_document("finance", "Travel policy", doctype="policy")
    second = repo.add_document("public", "Procurement SOP", doctype="sop")
    repo.document_tags[first.id] = [TagRef(id=1, name="travel", status="confirmed", source="user")]
    long_text = "x" * 500
    knn_hits = [chunk_hit("a2", first.id, "per diem"), chunk_hit("a1", first.id, "travel claims"), chunk_hit("b1", second.id, long_text)]
    bm25_hits = [chunk_hit("a1", first.id, "travel claims", "<mark>travel</mark> claims"), chunk_hit("b1", second.id, long_text)]
    aggregations = {"doctype": {"buckets": [{"key": "minutes", "doc_count": 12}]}}
    service, _ = make_service(make_index(knn_hits, bm25_hits, aggregations), repo)
    result = service.search(make_user("finance", "public"), "travel")
    assert result.total == 2
    assert [r.document_id for r in result.results] == [first.id, second.id]
    assert result.results[0].snippet == "<mark>travel</mark> claims"
    assert result.results[0].tags == ["travel"]
    assert result.results[1].snippet == "x" * 240
    assert [(b.value, b.count) for b in result.facets["doctype"]] == [("policy", 1), ("sop", 1)]
    assert [(b.value, b.count) for b in result.facets["department_id"]] == [("finance", 1), ("public", 1)]
    assert [(b.value, b.count) for b in result.facets["tags"]] == [("travel", 1)]
    assert result.did_you_mean is None


def test_superseded_documents_are_down_ranked(repo: StubRepo) -> None:
    newer = repo.add_document("finance", "Policy v2")
    older = repo.add_document("finance", "Policy v1", superseded_by=newer.id)
    hits = [chunk_hit("old", older.id, "policy"), chunk_hit("new", newer.id, "policy")]
    service, _ = make_service(make_index(hits, hits), repo)
    result = service.search(make_user("finance"), "policy")
    assert [r.document_id for r in result.results] == [newer.id, older.id]
    assert result.results[1].superseded_by == newer.id
    undecayed = 2 / 61
    assert abs(result.results[1].score - undecayed * 0.7) < 1e-12


def test_guard_drops_foreign_documents(repo: StubRepo) -> None:
    mine = repo.add_document("finance", "Finance doc")
    foreign = repo.add_document("hr", "HR secret")
    hits = [chunk_hit("f1", foreign.id, "secret"), chunk_hit("m1", mine.id, "ok")]
    service, _ = make_service(make_index(hits, hits), repo)
    user = make_user("finance")
    result = service.search(user, "secret")
    assert [r.document_id for r in result.results] == [mine.id]
    assert result.total == 1
    retrieved = service.retrieve(user, "secret")
    assert [h.document_id for h in retrieved] == [mine.id]
    assert retrieved[0].title == "Finance doc"


def test_zero_hits_triggers_did_you_mean(repo: StubRepo) -> None:
    index = make_index([], [])
    service, _ = make_service(index, repo)
    result = service.search(make_user("finance"), "anual leav")
    assert result.total == 0
    assert result.did_you_mean == "annual leave"
    assert index.queries[-1][0] == TITLES_INDEX


def test_query_embedding_is_cached(repo: StubRepo) -> None:
    service, embedder = make_service(make_index([], []), repo)
    user = make_user("finance")
    service.search(user, "Annual  Leave")
    service.search(user, "annual leave ")
    assert len(embedder.calls) == 1


def test_retrieve_includes_summary_nodes_and_limits_k(repo: StubRepo) -> None:
    doc = repo.add_document("finance", "Report")
    hits = [chunk_hit(f"c{i}", doc.id, f"text {i}", level=1 if i == 0 else 0, page_from=i) for i in range(12)]
    index = make_index(hits, hits)
    service, _ = make_service(index, repo)
    retrieved = service.retrieve(make_user("finance"), "report", k=8)
    assert len(retrieved) == 8
    assert retrieved[0].level == 1
    for _, body in index.queries:
        assert {"term": {"level": 0}} not in body["query"]["bool"]["filter"]


def test_suggest_documents_and_tags(repo: StubRepo) -> None:
    doc = repo.add_document("hr", "Annual leave policy")
    repo.tags = [
        TagRow(id=1, name="Leave", department_id="hr"),
        TagRow(id=2, name="Benefits", department_id="hr"),
        TagRow(id=3, name="leave-secret", department_id="finance"),
    ]

    def responder(index: str, body: dict[str, Any]) -> dict[str, Any]:
        source = {"document_id": str(doc.id), "title": doc.title, "doctype": "policy", "department_id": "hr", "allowed_groups": ["hr"]}
        return {"hits": {"hits": [{"_id": str(doc.id), "_source": source}]}, "aggregations": {"tags": {"buckets": [{"key": "Benefits", "doc_count": 1}]}}}

    index = FakeSearchIndex(responder)
    service, _ = make_service(index, repo)
    user = make_user("hr")
    result = service.suggest(user, "  leave ")
    assert [d.id for d in result.documents] == [doc.id]
    assert [t.name for t in result.tags] == ["Leave", "Benefits"]
    assert index.queries[0][0] == TITLES_INDEX
    empty = service.suggest(user, " l ")
    assert empty.documents == [] and empty.tags == []
    assert len(index.queries) == 1
