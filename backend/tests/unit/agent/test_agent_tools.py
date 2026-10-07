from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from dms_adapters.container import build_fake_container
from dms_adapters.fakes.storage import FakeSearchIndex
from dms_agent.service import AgentService, history_messages, tool_steps
from dms_agent.tools import BUDGET_MESSAGE, NOT_FOUND, AgentContext, build_tools
from dms_core.answer.service import AskService
from dms_core.config import Settings
from dms_core.models import DocumentMeta, SearchFilters
from dms_core.search.mappings import CHUNKS_INDEX
from dms_core.search.service import SearchService


def seeded():
    container = build_fake_container(Settings(fake_ai=True, openrouter_api_key=""))
    repo = container.repo
    for dept, name in (("finance", "Finance"), ("hr", "HR"), ("public", "Public")):
        repo.upsert_department(dept, name)
    repo.upsert_user("alice", "alice", "Alice")
    repo.set_membership("alice", "finance", "contributor")
    repo.set_membership("alice", "public", "viewer")
    finance = repo.create_document(department_id="finance", created_by="alice", title="Procurement Policy")
    repo.update_document(finance.id, root_summary="Procurement thresholds and approvals.", doctype="policy")
    hr = repo.create_document(department_id="hr", created_by="alice", title="Remote Work Circular")
    repo.update_document(hr.id, meta=DocumentMeta(reference_no="PKP/HR/2026/03"))
    return container, repo.get_user("alice"), finance, hr


def responder_for(docs):
    def respond(index, body):
        if index != CHUNKS_INDEX:
            return {"hits": {"total": {"value": 0}, "hits": []}}
        hits = [
            {
                "_id": f"{doc.id}:c1",
                "_score": 1.0,
                "_source": {
                    "chunk_id": f"{doc.id}:c1",
                    "document_id": str(doc.id),
                    "level": 0,
                    "title": doc.title,
                    "text": f"Text of {doc.title}",
                    "page_from": 1,
                    "heading_path": ["1. Scope"],
                    "allowed_groups": [doc.department_id],
                },
            }
            for doc in docs
        ]
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}, "aggregations": {}}

    return respond


def make_context(container, user, max_calls=8):
    search = SearchService(container.index, container.embedder, container.repo, container.settings)
    return AgentContext(user=user, container=container, search=search, max_tool_calls=max_calls)


def tool_map(context):
    return {t.tool_name: t for t in build_tools(context)}


def test_search_tool_never_returns_foreign_department_documents():
    container, alice, finance, hr = seeded()
    container.index = FakeSearchIndex(responder_for([finance, hr]))
    context = make_context(container, alice)
    output = tool_map(context)["search_documents"](query="policy")
    assert "Procurement Policy" in output
    assert "Remote Work Circular" not in output
    assert all(hit.document_id == finance.id for hit in context.sources)
    for _, body in container.index.queries:
        assert {"terms": {"allowed_groups": ["finance", "public"]}} in body["query"]["bool"]["filter"]


def test_get_document_hides_foreign_and_registers_summary_source():
    container, alice, finance, hr = seeded()
    tools = tool_map(context := make_context(container, alice))
    assert tools["get_document"](document_id=str(hr.id)) == NOT_FOUND
    assert tools["get_document_versions"](document_id=str(hr.id)) == NOT_FOUND
    assert tools["get_document"](document_id="not-a-uuid") == NOT_FOUND
    info = json.loads(tools["get_document"](document_id=str(finance.id)))
    assert info["title"] == "Procurement Policy"
    assert info["summary_source"].startswith("[1] ")
    assert context.sources[0].chunk_id == f"{finance.id}:summary"


def test_list_documents_scoped_to_user_departments():
    container, alice, finance, hr = seeded()
    for doc in (finance, hr):
        container.repo.set_status(doc.id, "READY")
    tools = tool_map(make_context(container, alice))
    listed = json.loads(tools["list_documents"]())
    assert [d["title"] for d in listed["documents"]] == ["Procurement Policy"]
    forced = json.loads(tools["list_documents"](department_id="hr"))
    assert all(d["department_id"] != "hr" for d in forced["documents"])


def test_tool_budget_is_enforced():
    container, alice, finance, _ = seeded()
    tools = tool_map(make_context(container, alice, max_calls=2))
    tools["get_document"](document_id=str(finance.id))
    tools["get_document"](document_id=str(finance.id))
    assert tools["get_document"](document_id=str(finance.id)) == BUDGET_MESSAGE


def test_citations_are_deduplicated_and_numbered():
    container, alice, finance, _ = seeded()
    container.index = FakeSearchIndex(responder_for([finance]))
    context = make_context(container, alice)
    tools = tool_map(context)
    tools["search_documents"](query="a")
    tools["search_documents"](query="b")
    assert len(context.sources) == 1
    citations = context.citations([1, 7])
    assert [c.n for c in citations] == [1]
    assert citations[0].document_id == finance.id


def test_history_messages_normalized():
    turns = [
        SimpleNamespace(role="assistant", content="stray"),
        SimpleNamespace(role="user", content="q1"),
        SimpleNamespace(role="assistant", content="a1"),
        SimpleNamespace(role="user", content="q2"),
    ]
    messages = history_messages(turns, max_turns=6)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"][0]["text"] == "q1"


def test_tool_steps_extracts_tool_uses():
    message = {"role": "assistant", "content": [{"text": "x"}, {"toolUse": {"name": "search_documents", "input": {"query": "q"}}}]}
    assert tool_steps(message) == [{"tool": "search_documents", "input": {"query": "q"}}]
    assert tool_steps({"role": "user", "content": [{"toolResult": {}}]}) == []


async def test_agent_falls_back_to_rag_without_model():
    container, alice, finance, _ = seeded()
    container.index = FakeSearchIndex(responder_for([finance]))
    search = SearchService(container.index, container.embedder, container.repo, container.settings)
    service = AgentService(container, search, AskService(search, container.llm, container.repo, container.settings))
    assert not service.enabled
    events = [event async for event in service.stream(alice, "procurement?")]
    assert events[0].event == "step" and events[0].data["tool"] == "rag_fallback"
    assert [e.event for e in events][-2:] == ["citations", "done"]
    assert isinstance(events[-2].data["citations"][0]["document_id"], str)
    assert UUID(events[-2].data["citations"][0]["document_id"]) == finance.id


def test_versions_tool_returns_added_and_removed_passages_as_sources():
    from dms_core.models import Chunk

    container, alice, finance, _ = seeded()
    repo = container.repo
    v1 = repo.create_version(document_id=finance.id, blob_sha256="a", original_filename="p.docx", mime_type="x", size_bytes=1, uploaded_by="alice")
    v2 = repo.create_version(document_id=finance.id, blob_sha256="b", original_filename="p2.docx", mime_type="x", size_bytes=1, uploaded_by="alice")
    chunks = [
        Chunk(id="keep", document_id=finance.id, text="Section 1 unchanged", heading_path=["1. Scope"]),
        Chunk(id="old", document_id=finance.id, text="Threshold RM10,000", heading_path=["4. Thresholds"]),
        Chunk(id="new", document_id=finance.id, text="Threshold RM20,000", heading_path=["4. Thresholds"]),
    ]
    repo.upsert_chunks(chunks)
    repo.update_version(v1.id, chunk_manifest=["keep", "old"])
    repo.update_version(v2.id, chunk_manifest=["keep", "new"])
    context = make_context(container, alice)
    result = json.loads(tool_map(context)["get_document_versions"](document_id=str(finance.id)))
    change = result["latest_change"]
    assert change["from_version"] == 1 and change["to_version"] == 2
    assert "RM20,000" in change["added_passages"][0] and change["added_passages"][0].startswith("[1] added in v2")
    assert "RM10,000" in change["removed_passages"][0]
    assert [hit.chunk_id for hit in context.sources] == ["new", "old"]
    assert [c.n for c in context.citations([2, 1, 2])] == [1, 2]


def test_search_tool_respects_scope_document_ids():
    container, alice, finance, hr = seeded()
    container.index = FakeSearchIndex(responder_for([finance]))
    context = make_context(container, alice)
    context.scope = SearchFilters(document_ids=[str(finance.id)], doctype=["policy"])
    tools = tool_map(context)
    tools["search_documents"](query="procurement")
    assert container.index.queries
    for _, body in container.index.queries:
        clauses = body["query"]["bool"]["filter"]
        assert {"terms": {"document_id": [str(finance.id)]}} in clauses
        assert {"terms": {"doctype": ["policy"]}} in clauses
    container.index.queries.clear()
    assert "selected documents" in tools["search_documents"](query="procurement", doctype="circular")
    assert container.index.queries == []


def test_list_documents_tool_respects_scope():
    container, alice, finance, hr = seeded()
    other = container.repo.create_document(department_id="finance", created_by="alice", title="Other Policy")
    for row in (finance, other):
        container.repo.set_status(row.id, "READY")
    context = make_context(container, alice)
    context.scope = SearchFilters(document_ids=[str(finance.id), str(hr.id), "not-a-uuid"])
    listed = json.loads(tool_map(context)["list_documents"]())
    assert [item["document_id"] for item in listed["documents"]] == [str(finance.id)]
    assert listed["total"] == 1
    details = json.loads(tool_map(context)["get_document"](document_id=str(other.id)))
    assert details["title"] == "Other Policy"
