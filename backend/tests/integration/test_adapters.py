import hashlib
import socket
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest

from dms_adapters.opensearch.index import OpenSearchIndex
from dms_adapters.postgres.db import Database
from dms_adapters.postgres.jobs import PostgresJobQueue
from dms_adapters.postgres.repo import PostgresRepo
from dms_adapters.storage.s3_store import S3BlobStore
from dms_core.config import Settings
from dms_core.models import Chunk, DeltaStats, DocumentMeta, RaptorNode
from dms_core.search.mappings import CHUNKS_INDEX

SETTINGS = Settings(fake_ai=True)


def port_open(url: str, default_port: int) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or default_port), timeout=1.5):
            return True
    except OSError:
        return False


def postgres_ready() -> bool:
    try:
        with psycopg.connect(SETTINGS.database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1 FROM jobs LIMIT 1")
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(not postgres_ready(), reason="postgres unavailable")
requires_s3 = pytest.mark.skipif(not port_open(SETTINGS.s3_endpoint, 9000), reason="s3 unavailable")
requires_opensearch = pytest.mark.skipif(
    not OpenSearchIndex(SETTINGS).ping(), reason="opensearch unavailable"
)


def unit_vector(position: int, dim: int = 1024) -> list[float]:
    vector = [0.0] * dim
    vector[position % dim] = 1.0
    return vector


def claim_own(jobs: PostgresJobQueue, database: Database, job_id: int, stage: str):
    foreign: list[int] = []
    try:
        for _ in range(200):
            candidate = jobs.claim([stage])
            if candidate is None or candidate.id == job_id:
                return candidate
            foreign.append(candidate.id)
        return None
    finally:
        if foreign:
            with database.connection() as connection:
                connection.execute(
                    "UPDATE jobs SET status = 'queued', attempts = greatest(attempts - 1, 0) WHERE id = ANY(%s)",
                    (foreign,),
                )


def cleanup(database: Database, document_ids: list, department_ids: list[str], user_ids: list[str], tag_ids: list[int]) -> None:
    with database.connection() as connection:
        connection.execute("DELETE FROM jobs WHERE document_id = ANY(%s)", (document_ids,))
        connection.execute("DELETE FROM document_tags WHERE document_id = ANY(%s) OR tag_id = ANY(%s)", (document_ids, tag_ids))
        connection.execute("DELETE FROM tags WHERE id = ANY(%s)", (tag_ids,))
        connection.execute("DELETE FROM raptor_nodes WHERE document_id = ANY(%s)", (document_ids,))
        connection.execute("DELETE FROM minhash_bands WHERE document_id = ANY(%s)", (document_ids,))
        connection.execute("DELETE FROM chunks WHERE document_id = ANY(%s)", (document_ids,))
        connection.execute("UPDATE documents SET current_version_id = NULL WHERE id = ANY(%s)", (document_ids,))
        connection.execute("DELETE FROM versions WHERE document_id = ANY(%s)", (document_ids,))
        connection.execute(
            "UPDATE documents SET superseded_by = NULL, duplicate_of = NULL WHERE id = ANY(%s)", (document_ids,)
        )
        connection.execute("DELETE FROM documents WHERE id = ANY(%s)", (document_ids,))
        connection.execute("DELETE FROM user_departments WHERE user_id = ANY(%s)", (user_ids,))
        connection.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
        connection.execute("DELETE FROM departments WHERE id = ANY(%s)", (department_ids,))


@requires_postgres
def test_postgres_repo_round_trip() -> None:
    database = Database.from_settings(SETTINGS)
    repo = PostgresRepo(SETTINGS, database)
    jobs = PostgresJobQueue(SETTINGS, database)
    suffix = uuid4().hex[:10]
    department = f"it-dept-{suffix}"
    user_id = f"it-user-{suffix}"
    document_ids: list = []
    tag_ids: list[int] = []
    try:
        assert repo.ping()
        repo.upsert_department(department, "Integration Dept")
        repo.upsert_user(user_id, f"user-{suffix}", "Integration User")
        repo.set_membership(user_id, department, "contributor")
        user = repo.get_user(user_id)
        assert user is not None and user.departments[0].name == "Integration Dept"
        assert user.role_in(department) == "contributor"
        assert repo.get_user_by_username(f"user-{suffix}").id == user_id
        assert [d.id for d in repo.list_departments([department])] == [department]

        doc = repo.create_document(department_id=department, created_by=user_id, title="Leave Policy")
        document_ids.append(doc.id)
        other = repo.create_document(department_id=department, created_by=user_id)
        document_ids.append(other.id)
        assert other.title == "Untitled document"

        updated = repo.update_document(
            doc.id, meta=DocumentMeta(reference_no=f"HR/{suffix}/1"), doctype="policy", title_confidence=0.9
        )
        assert updated.meta.reference_no == f"HR/{suffix}/1"
        assert updated.updated_at >= doc.updated_at
        repo.update_document(other.id, meta={"reference_no": f"HR/{suffix}/1"}, superseded_by=doc.id)
        assert repo.find_document_by_reference(department, f"HR/{suffix}/1", exclude_id=other.id).id == doc.id
        repo.set_status(doc.id, "INDEXED", "ok")
        assert repo.get_document(doc.id).status == "INDEXED"
        assert {d.id for d in repo.get_documents([doc.id, other.id])} == {doc.id, other.id}

        sha = hashlib.sha256(suffix.encode()).hexdigest()
        v1 = repo.create_version(
            document_id=doc.id, blob_sha256=sha, original_filename="a.pdf", mime_type="application/pdf",
            size_bytes=10, uploaded_by=user_id,
        )
        v2 = repo.create_version(
            document_id=doc.id, blob_sha256=sha + "b", original_filename="b.pdf", mime_type="application/pdf",
            size_bytes=11, uploaded_by=user_id,
        )
        assert (v1.version_no, v2.version_no) == (1, 2)
        assert repo.get_document(doc.id).current_version_id == v2.id
        assert repo.get_current_version(doc.id).id == v2.id
        assert repo.get_previous_version(doc.id, 2).id == v1.id
        assert repo.get_version_by_no(doc.id, 1).id == v1.id
        assert repo.find_version_by_sha(sha).id == v1.id
        assert [v.version_no for v in repo.list_versions(doc.id)] == [1, 2]

        chunks = [
            Chunk(id=f"{suffix}-c{i}", document_id=doc.id, order=i, text=f"chunk {i}", heading_path=["H", str(i)],
                  page_from=1, page_to=1, token_count=3, embedding=unit_vector(i))
            for i in range(3)
        ]
        repo.upsert_chunks(chunks)
        repo.update_version(
            v2.id,
            blocks=[{"type": "heading", "text": "H", "level": 1}],
            chunk_manifest=[chunks[0].id, chunks[1].id],
            page_count=1,
            merkle_root="root",
        )
        repo.set_delta_stats(v2.id, DeltaStats(added=2, reused=1))
        stored_version = repo.get_version(v2.id)
        assert stored_version.blocks[0].type == "heading"
        assert stored_version.delta_stats.reused == 1
        fetched = repo.get_chunks([chunks[2].id, chunks[0].id])
        assert [c.id for c in fetched] == [chunks[2].id, chunks[0].id]
        assert len(fetched[0].embedding) == 1024 and fetched[0].embedding[2] == 1.0
        assert fetched[0].heading_path == ["H", "2"]
        assert [c.order for c in repo.get_document_chunks(doc.id)] == [0, 1, 2]
        mean = repo.document_embedding(doc.id)
        assert mean is not None and mean[0] == pytest.approx(0.5) and mean[1] == pytest.approx(0.5)
        assert mean[2] == pytest.approx(0.0)
        repo.delete_chunks([chunks[2].id])
        assert len(repo.get_document_chunks(doc.id)) == 2
        assert repo.document_embedding(other.id) is None

        repo.save_minhash(doc.id, b"sig-doc", [(0, f"x{suffix}"), (1, f"y{suffix}")])
        repo.save_minhash(other.id, b"sig-other", [(0, f"q{suffix}"), (1, f"y{suffix}")])
        assert repo.find_minhash_candidates([(1, f"y{suffix}")], doc.id) == [(other.id, b"sig-other")]
        assert repo.find_minhash_candidates([(0, f"y{suffix}")], doc.id) == []

        tag = repo.get_or_create_tag(f"Leave {suffix}", department)
        tag_ids.append(tag.id)
        assert repo.get_or_create_tag(f"leave {suffix}", department).id == tag.id
        global_tag = repo.get_or_create_tag(f"Global {suffix}", None)
        tag_ids.append(global_tag.id)
        assert repo.get_or_create_tag(f"Global {suffix}", None).id == global_tag.id
        repo.set_document_tag(doc.id, tag.id, "ai", "suggested", 0.66)
        repo.set_document_tag(doc.id, tag.id, "user", "confirmed")
        refs = repo.get_document_tags(doc.id)
        assert refs[0].status == "confirmed" and refs[0].similarity == pytest.approx(0.66)
        assert repo.confirmed_tag_document_ids(tag.id) == [doc.id]
        listed = {t.id: t for t in repo.list_tags([department])}
        assert listed[tag.id].doc_count == 1 and global_tag.id in listed
        repo.set_tag_centroid(tag.id, unit_vector(5))
        assert repo.get_tag(tag.id).centroid[5] == 1.0
        rows, total = repo.list_documents(department_ids=[department], tag=f"leave {suffix}")
        assert total == 1 and rows[0].id == doc.id
        rows, total = repo.list_documents(department_ids=[department], sort="title", page_size=1)
        assert total == 2 and rows[0].title == "Leave Policy"
        assert repo.list_documents(department_ids=[department], doctype="policy")[1] == 1
        repo.remove_document_tag(doc.id, tag.id)
        assert repo.get_document_tags(doc.id) == []

        nodes = [
            RaptorNode(id=f"{suffix}-r1", document_id=doc.id, version_no=2, level=1, summary_text="sum",
                       embedding=unit_vector(9), children=[chunks[0].id]),
            RaptorNode(id=f"{suffix}-r2", document_id=doc.id, version_no=2, level=2, summary_text="root",
                       embedding=None, children=[f"{suffix}-r1"]),
        ]
        repo.replace_raptor_nodes(doc.id, 2, nodes)
        stored_nodes = repo.get_raptor_nodes(doc.id, 2)
        assert [n.id for n in stored_nodes] == [f"{suffix}-r1", f"{suffix}-r2"]
        assert stored_nodes[0].embedding[9] == 1.0 and stored_nodes[1].children == [f"{suffix}-r1"]
        repo.replace_raptor_nodes(doc.id, 2, nodes[:1])
        assert len(repo.get_raptor_nodes(doc.id, 2)) == 1

        assert doc.id in repo.list_all_document_ids()

        enqueued = jobs.enqueue(doc.id, v2.id, "extract")
        assert enqueued.status == "queued"
        claimed = claim_own(jobs, database, enqueued.id, "extract")
        assert claimed is not None and claimed.attempts == 1 and claimed.status == "running"
        assert jobs.fail(claimed, "transient", max_attempts=2) is True
        listed_jobs = repo.list_jobs(doc.id)
        assert listed_jobs[0].status == "queued" and listed_jobs[0].last_error == "transient"
        with database.connection() as connection:
            connection.execute("UPDATE jobs SET run_after = now() WHERE id = %s", (enqueued.id,))
        second = claim_own(jobs, database, enqueued.id, "extract")
        assert second is not None and second.attempts == 2
        assert jobs.fail(second, "fatal", max_attempts=2) is False
        assert repo.list_jobs(doc.id)[0].status == "failed"
        done_job = jobs.enqueue(doc.id, None, "delta")
        finished = claim_own(jobs, database, done_job.id, "delta")
        assert finished is not None
        jobs.complete(finished)
        assert {j.stage: j.status for j in repo.list_jobs(doc.id)} == {"extract": "failed", "delta": "done"}
    finally:
        cleanup(database, document_ids, [department], [user_id], tag_ids)
        database.close()


@requires_s3
def test_s3_blob_store_round_trip() -> None:
    store = S3BlobStore(SETTINGS)
    store.ensure_bucket()
    store.ensure_bucket()
    payload = f"hello {uuid4()}".encode()
    sha = hashlib.sha256(payload).hexdigest()
    assert store.exists(sha) is False
    store.put(sha, payload, "text/plain")
    try:
        assert store.exists(sha) is True
        assert store.get(sha) == payload
    finally:
        store.client.delete_object(Bucket=SETTINGS.s3_bucket, Key=f"blobs/{sha}")
    assert store.exists(sha) is False


@requires_opensearch
def test_opensearch_index_round_trip() -> None:
    index = OpenSearchIndex(SETTINGS)
    index.ensure_indexes()
    index.ensure_indexes()
    document_id = f"it-doc-{uuid4().hex}"
    chunk_id = f"{document_id}-c0"
    vector = unit_vector(123)
    try:
        index.upsert_chunks([
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "version_id": None,
                "level": 0,
                "allowed_groups": [f"dept:{document_id}"],
                "department_id": "it",
                "doctype": "policy",
                "tags": [],
                "title": "Integration policy",
                "text": "annual leave entitlement for integration testing",
                "heading_path": ["Leave"],
                "page_from": 1,
                "effective_date": "2025-01-01",
                "superseded": False,
                "embedding": vector,
            }
        ])
        index.upsert_title({
            "document_id": document_id,
            "title": "Integration policy",
            "filename": "policy.pdf",
            "tags": [],
            "doctype": "policy",
            "department_id": "it",
            "allowed_groups": [f"dept:{document_id}"],
            "superseded": False,
        })
        knn_body = {
            "size": 5,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": vector,
                        "k": 5,
                        "filter": {"term": {"allowed_groups": f"dept:{document_id}"}},
                    }
                }
            },
        }
        result = index.search(CHUNKS_INDEX, knn_body)
        assert result["hits"]["hits"][0]["_id"] == chunk_id
        responses = index.msearch([
            (CHUNKS_INDEX, {"query": {"term": {"document_id": document_id}}}),
            ("dms_titles", {"query": {"term": {"document_id": document_id}}}),
        ])
        assert [r["hits"]["total"]["value"] for r in responses] == [1, 1]
        index.delete_chunks([chunk_id, "missing-chunk"])
        index.refresh()
        assert index.count(CHUNKS_INDEX, {"term": {"document_id": document_id}}) == 0
    finally:
        index.delete_document(document_id)
    index.refresh()
    assert index.count("dms_titles", {"term": {"document_id": document_id}}) == 0
