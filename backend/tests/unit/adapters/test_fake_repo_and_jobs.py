import inspect
from uuid import uuid4

import pytest

from dms_adapters.container import build_container, build_fake_container, uses_fake_ai
from dms_adapters.fakes.ai import FakeEmbedder
from dms_adapters.fakes.jobs import FakeJobQueue
from dms_adapters.fakes.repo import FakeRepo
from dms_adapters.openrouter.embedder import OpenRouterEmbedder
from dms_adapters.postgres.jobs import PostgresJobQueue
from dms_adapters.postgres.repo import PostgresRepo
from dms_core.config import Settings
from dms_core.models import Block, Chunk, DeltaStats, DocumentMeta, RaptorNode
from dms_core.ports import JobQueue, Repo


def protocol_methods(protocol: type) -> list[str]:
    return [name for name, value in vars(protocol).items() if callable(value) and not name.startswith("_")]


@pytest.mark.parametrize("implementation", [FakeRepo, PostgresRepo])
def test_repo_implements_every_protocol_method(implementation: type) -> None:
    for name in protocol_methods(Repo):
        assert hasattr(implementation, name), name
        expected = list(inspect.signature(getattr(Repo, name)).parameters)
        actual = list(inspect.signature(getattr(implementation, name)).parameters)
        assert actual == expected, name


@pytest.mark.parametrize("implementation", [FakeJobQueue, PostgresJobQueue])
def test_job_queue_implements_protocol(implementation: type) -> None:
    for name in protocol_methods(JobQueue):
        expected = list(inspect.signature(getattr(JobQueue, name)).parameters)
        assert list(inspect.signature(getattr(implementation, name)).parameters) == expected


@pytest.fixture
def repo() -> FakeRepo:
    fake = FakeRepo()
    fake.upsert_department("hr", "Human Resources")
    fake.upsert_department("fin", "Finance")
    fake.upsert_user("u1", "alice", "Alice")
    fake.set_membership("u1", "hr", "contributor")
    fake.set_membership("u1", "fin", "viewer")
    return fake


def test_users_and_departments(repo: FakeRepo) -> None:
    user = repo.get_user("u1")
    assert user is not None
    assert user.department_ids == ["fin", "hr"]
    assert user.role_in("hr") == "contributor"
    assert repo.get_user_by_username("alice").id == "u1"
    assert repo.get_user("nobody") is None
    assert [d.id for d in repo.list_departments(["hr"])] == ["hr"]


def test_versions_numbering_and_current(repo: FakeRepo) -> None:
    doc = repo.create_document(department_id="hr", created_by="u1")
    assert doc.title == "Untitled document"
    v1 = repo.create_version(
        document_id=doc.id, blob_sha256="a", original_filename="a.pdf", mime_type="application/pdf",
        size_bytes=1, uploaded_by="u1",
    )
    v2 = repo.create_version(
        document_id=doc.id, blob_sha256="b", original_filename="b.pdf", mime_type="application/pdf",
        size_bytes=2, uploaded_by="u1",
    )
    assert (v1.version_no, v2.version_no) == (1, 2)
    assert repo.get_document(doc.id).current_version_id == v2.id
    assert repo.get_current_version(doc.id).id == v2.id
    assert repo.get_previous_version(doc.id, 2).id == v1.id
    assert repo.get_previous_version(doc.id, 1) is None
    assert repo.get_version_by_no(doc.id, 1).id == v1.id
    assert repo.find_version_by_sha("b").id == v2.id
    assert [v.version_no for v in repo.list_versions(doc.id)] == [1, 2]
    repo.update_version(v2.id, blocks=[{"type": "paragraph", "text": "x"}], chunk_manifest=["c1"], page_count=3)
    repo.set_delta_stats(v2.id, DeltaStats(added=1, reused=4))
    stored = repo.get_version(v2.id)
    assert isinstance(stored.blocks[0], Block)
    assert stored.chunk_manifest == ["c1"]
    assert stored.delta_stats.reused == 4


def test_update_document_and_reference_lookup(repo: FakeRepo) -> None:
    doc = repo.create_document(department_id="hr", created_by="u1", title="Leave")
    updated = repo.update_document(doc.id, meta={"reference_no": "HR/POL/1"}, doctype="policy", title="Leave Policy")
    assert isinstance(updated.meta, DocumentMeta)
    assert updated.updated_at > doc.updated_at
    other = repo.create_document(department_id="hr", created_by="u1")
    repo.update_document(other.id, meta=DocumentMeta(reference_no="HR/POL/1"))
    assert repo.find_document_by_reference("hr", "hr/pol/1", exclude_id=other.id).id == doc.id
    assert repo.find_document_by_reference("fin", "HR/POL/1") is None
    repo.set_status(doc.id, "FAILED", "boom")
    assert repo.get_document(doc.id).status_detail == "boom"
    with pytest.raises(ValueError):
        repo.update_document(doc.id, not_a_column=1)


def test_list_documents_filters_sort_and_paging(repo: FakeRepo) -> None:
    titles = ["Charlie", "alpha", "Bravo"]
    docs = [repo.create_document(department_id="hr", created_by="u1", title=t) for t in titles]
    repo.create_document(department_id="fin", created_by="u1", title="Zulu")
    repo.update_document(docs[0].id, doctype="policy")
    tag = repo.get_or_create_tag("Leave", "hr")
    repo.set_document_tag(docs[1].id, tag.id, "user", "confirmed")
    rows, total = repo.list_documents(department_ids=["hr"], sort="title")
    assert total == 3
    assert [r.title for r in rows] == ["alpha", "Bravo", "Charlie"]
    rows, total = repo.list_documents(department_ids=["hr", "fin"], page=2, page_size=3)
    assert total == 4 and len(rows) == 1
    assert repo.list_documents(department_ids=["hr", "fin"])[0][0].title == "Zulu"
    assert [r.title for r in repo.list_documents(department_ids=["hr"], doctype="policy")[0]] == ["Charlie"]
    assert [r.title for r in repo.list_documents(department_ids=["hr"], tag="leave")[0]] == ["alpha"]
    assert repo.list_documents(department_ids=["hr"], status="READY") == ([], 0)
    assert len(repo.list_all_document_ids()) == 4


def test_chunks_and_document_embedding(repo: FakeRepo) -> None:
    doc = repo.create_document(department_id="hr", created_by=None)
    version = repo.create_version(
        document_id=doc.id, blob_sha256="s", original_filename="f", mime_type="text/plain", size_bytes=1,
        uploaded_by=None,
    )
    assert repo.document_embedding(doc.id) is None
    repo.upsert_chunks([
        Chunk(id="c1", document_id=doc.id, order=1, text="one", embedding=[1.0, 0.0]),
        Chunk(id="c0", document_id=doc.id, order=0, text="zero", embedding=[0.0, 1.0]),
        Chunk(id="c2", document_id=doc.id, order=2, text="two", embedding=[1.0, 1.0]),
    ])
    assert [c.id for c in repo.get_document_chunks(doc.id)] == ["c0", "c1", "c2"]
    assert [c.id for c in repo.get_chunks(["c2", "c0", "missing"])] == ["c2", "c0"]
    assert repo.document_embedding(doc.id) == pytest.approx([2 / 3, 2 / 3])
    repo.update_version(version.id, chunk_manifest=["c0", "c1"])
    assert repo.document_embedding(doc.id) == pytest.approx([0.5, 0.5])
    repo.upsert_chunks([Chunk(id="c1", document_id=doc.id, order=1, text="one changed")])
    assert repo.get_chunks(["c1"])[0].embedding == [1.0, 0.0]
    repo.delete_chunks(["c2"])
    assert len(repo.get_document_chunks(doc.id)) == 2


def test_minhash_candidates_by_shared_band(repo: FakeRepo) -> None:
    a = repo.create_document(department_id="hr", created_by=None)
    b = repo.create_document(department_id="hr", created_by=None)
    c = repo.create_document(department_id="hr", created_by=None)
    repo.save_minhash(a.id, b"sig-a", [(0, "x"), (1, "y")])
    repo.save_minhash(b.id, b"sig-b", [(0, "q"), (1, "y")])
    repo.save_minhash(c.id, b"sig-c", [(0, "z"), (1, "w")])
    assert repo.find_minhash_candidates([(1, "y")], exclude_document_id=a.id) == [(b.id, b"sig-b")]
    assert repo.find_minhash_candidates([(0, "y")], exclude_document_id=a.id) == []
    assert {d for d, _ in repo.find_minhash_candidates([(0, "x"), (0, "z")], uuid4())} == {a.id, c.id}


def test_tags_lifecycle(repo: FakeRepo) -> None:
    doc = repo.create_document(department_id="hr", created_by=None)
    tag = repo.get_or_create_tag("Annual  Leave", "hr")
    assert repo.get_or_create_tag("annual leave", "hr").id == tag.id
    global_tag = repo.get_or_create_tag("Finance", None)
    fin_tag = repo.get_or_create_tag("Budget", "fin")
    repo.set_document_tag(doc.id, tag.id, "ai", "suggested", 0.7)
    repo.set_document_tag(doc.id, tag.id, "user", "confirmed")
    refs = repo.get_document_tags(doc.id)
    assert refs[0].status == "confirmed" and refs[0].similarity == 0.7
    assert repo.confirmed_tag_document_ids(tag.id) == [doc.id]
    names = {t.name: t for t in repo.list_tags(["hr"])}
    assert set(names) == {"Annual Leave", "Finance"}
    assert names["Annual Leave"].doc_count == 1
    assert fin_tag.id in {t.id for t in repo.list_tags()}
    repo.set_tag_centroid(tag.id, [0.1, 0.2])
    assert repo.get_tag(tag.id).centroid == [0.1, 0.2]
    repo.remove_document_tag(doc.id, tag.id)
    assert repo.get_document_tags(doc.id) == []
    assert repo.get_tag(global_tag.id).doc_count == 0


def test_raptor_nodes_replace(repo: FakeRepo) -> None:
    doc = repo.create_document(department_id="hr", created_by=None)
    nodes = [
        RaptorNode(id="r1", document_id=doc.id, version_no=1, level=1, summary_text="s", children=["c1"]),
        RaptorNode(id="r0", document_id=doc.id, version_no=1, level=2, summary_text="root"),
    ]
    repo.replace_raptor_nodes(doc.id, 1, nodes)
    assert [n.id for n in repo.get_raptor_nodes(doc.id, 1)] == ["r1", "r0"]
    repo.replace_raptor_nodes(doc.id, 1, nodes[:1])
    assert [n.id for n in repo.get_raptor_nodes(doc.id, 1)] == ["r1"]
    assert repo.get_raptor_nodes(doc.id, 2) == []


def test_fake_job_queue_semantics() -> None:
    repo = FakeRepo()
    queue = FakeJobQueue(repo)
    document_id = uuid4()
    first = queue.enqueue(document_id, None, "extract")
    queue.enqueue(document_id, None, "index")
    assert [j.stage for j in repo.list_jobs(document_id)] == ["extract", "index"]
    claimed = queue.claim(["index"])
    assert claimed.stage == "index" and claimed.status == "running" and claimed.attempts == 1
    queue.complete(claimed)
    job = queue.claim()
    assert job.id == first.id
    assert queue.fail(job, "err1", max_attempts=2) is True
    job = queue.claim()
    assert job.attempts == 2
    assert queue.fail(job, "err2", max_attempts=2) is False
    assert queue.claim() is None
    statuses = {j.stage: (j.status, j.last_error) for j in repo.list_jobs(document_id)}
    assert statuses == {"extract": ("failed", "err2"), "index": ("done", None)}


def test_fake_container_uses_fakes() -> None:
    container = build_fake_container()
    assert isinstance(container.repo, FakeRepo)
    assert isinstance(container.embedder, FakeEmbedder)
    assert len(container.embedder.embed(["x"])[0]) == container.settings.embed_dim


def test_real_container_is_lazy_and_selects_ai() -> None:
    offline = Settings(
        openrouter_api_key="",
        database_url="postgresql://x:y@127.0.0.1:1/none",
        opensearch_url="http://127.0.0.1:1",
        s3_endpoint="http://127.0.0.1:1",
    )
    assert uses_fake_ai(offline)
    container = build_container(offline)
    assert isinstance(container.repo, PostgresRepo)
    assert isinstance(container.embedder, FakeEmbedder)
    keyed = offline.model_copy(update={"openrouter_api_key": "sk-x"})
    assert isinstance(build_container(keyed).embedder, OpenRouterEmbedder)
    forced = keyed.model_copy(update={"fake_ai": True})
    assert isinstance(build_container(forced).embedder, FakeEmbedder)
