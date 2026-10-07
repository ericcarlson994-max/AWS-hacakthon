from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from dms_adapters.fakes.ai import FakeEmbedder, FakeLlm
from dms_adapters.fakes.storage import FakeSearchIndex
from dms_core.answer.citations import build_citations, extract_cited_numbers
from dms_core.answer.prompt import build_messages
from dms_core.answer.service import NOT_FOUND_MESSAGE, AskService
from dms_core.config import Settings
from dms_core.models import AskEvent, DepartmentMembership, DocumentRow, SearchHit, User
from dms_core.search.mappings import CHUNKS_INDEX
from dms_core.search.service import SearchService


class AskRepo:
    def __init__(self) -> None:
        self.documents: dict[UUID, DocumentRow] = {}

    def add(self, department_id: str, title: str, **fields: Any) -> DocumentRow:
        now = datetime.now(UTC)
        row = DocumentRow(id=uuid4(), department_id=department_id, title=title, created_at=now, updated_at=now, **fields)
        self.documents[row.id] = row
        return row

    def get_documents(self, ids: list[UUID]) -> list[DocumentRow]:
        return [self.documents[i] for i in ids if i in self.documents]

    def get_document_tags(self, document_id: UUID) -> list[Any]:
        return []

    def list_tags(self, department_ids: list[str] | None = None) -> list[Any]:
        return []


def user_in(*departments: str) -> User:
    return User(
        id="u1",
        username="bob",
        display_name="Bob",
        departments=[DepartmentMembership(id=d, name=d, role="viewer") for d in departments],
    )


def hit(chunk_id: str, document_id: UUID, text: str, page: int | None = None) -> dict[str, Any]:
    return {"_id": chunk_id, "_source": {"chunk_id": chunk_id, "document_id": str(document_id), "text": text, "page_from": page, "level": 0}}


def index_returning(hits: list[dict[str, Any]]) -> FakeSearchIndex:
    def responder(index: str, body: dict[str, Any]) -> dict[str, Any]:
        if index == CHUNKS_INDEX:
            return {"hits": {"hits": hits}, "aggregations": {}}
        return {"hits": {"hits": []}, "suggest": {}}

    return FakeSearchIndex(responder)


def ask_service(index: FakeSearchIndex, repo: AskRepo, llm: Any) -> AskService:
    settings = Settings(fake_ai=True)
    return AskService(SearchService(index, FakeEmbedder(dim=16), repo, settings), llm, repo, settings)


async def collect(stream: AsyncIterator[AskEvent]) -> list[AskEvent]:
    return [event async for event in stream]


async def test_zero_hits_yields_not_found() -> None:
    repo = AskRepo()
    llm = FakeLlm()
    events = await collect(ask_service(index_returning([]), repo, llm).stream(user_in("hr"), "what is leave?"))
    assert [e.event for e in events] == ["token", "citations", "done"]
    assert events[0].data == {"text": NOT_FOUND_MESSAGE}
    assert events[1].data == {"citations": []}
    assert llm.calls == []


async def test_foreign_hits_are_invisible_to_ask() -> None:
    repo = AskRepo()
    foreign = repo.add("finance", "Secret budget")
    events = await collect(ask_service(index_returning([hit("s1", foreign.id, "secret")]), repo, FakeLlm()).stream(user_in("hr"), "budget"))
    assert events[0].data == {"text": NOT_FOUND_MESSAGE}


async def test_citations_map_to_hits() -> None:
    repo = AskRepo()
    first = repo.add("hr", "Leave policy")
    second = repo.add("hr", "Leave SOP")
    hits = [hit("c1", first.id, "Annual leave is 14 days.", page=2), hit("c2", second.id, "Apply via portal.", page=5)]
    llm = FakeLlm()
    events = await collect(ask_service(index_returning(hits), repo, llm).stream(user_in("hr"), "how much leave?"))
    kinds = [e.event for e in events]
    assert kinds[-2:] == ["citations", "done"]
    assert set(kinds[:-2]) == {"token"}
    answer = "".join(e.data["text"] for e in events if e.event == "token")
    assert "[1]" in answer and "[2]" in answer
    citations = events[-2].data["citations"]
    assert [c["n"] for c in citations] == [1, 2]
    assert citations[0]["chunk_id"] == "c1"
    assert citations[0]["document_id"] == str(first.id)
    assert citations[0]["title"] == "Leave policy"
    assert citations[0]["page"] == 2
    assert citations[1]["chunk_id"] == "c2"
    assert llm.calls[0]["model"] == Settings().llm_answer_model


class SilentLlm:
    async def stream(self, messages: list[dict[str, Any]], *, model: str | None = None, max_tokens: int = 1200, temperature: float = 0.2) -> AsyncIterator[str]:
        for token in ["No ", "citations ", "here."]:
            yield token


class BrokenLlm:
    async def stream(self, messages: list[dict[str, Any]], *, model: str | None = None, max_tokens: int = 1200, temperature: float = 0.2) -> AsyncIterator[str]:
        raise RuntimeError("llm down")
        yield ""


async def test_uncited_answer_falls_back_to_top_three() -> None:
    repo = AskRepo()
    docs = [repo.add("hr", f"Doc {i}") for i in range(4)]
    hits = [hit(f"c{i}", d.id, f"text {i}") for i, d in enumerate(docs)]
    events = await collect(ask_service(index_returning(hits), repo, SilentLlm()).stream(user_in("hr"), "q"))
    assert [c["n"] for c in events[-2].data["citations"]] == [1, 2, 3]


async def test_llm_failure_yields_error_event() -> None:
    repo = AskRepo()
    doc = repo.add("hr", "Doc")
    events = await collect(ask_service(index_returning([hit("c1", doc.id, "text")]), repo, BrokenLlm()).stream(user_in("hr"), "q"))
    assert events[-1].event == "error"
    assert "llm down" in events[-1].data["message"]


def test_prompt_numbers_sources_and_marks_superseded() -> None:
    old_id, new_id = uuid4(), uuid4()
    hits = [
        SearchHit(chunk_id="a", document_id=old_id, score=1.0, text="Old rule", page=3, heading_path=["Part 1", "Leave"], title="Policy v1"),
        SearchHit(chunk_id="b", document_id=new_id, score=0.9, text="New rule", title="Policy v2"),
    ]
    messages = build_messages("What is the rule?", hits, {old_id})
    assert messages[0]["role"] == "system"
    assert "Answer only from the sources" in messages[0]["content"]
    assert "superseded" in messages[0]["content"]
    user_content = messages[1]["content"]
    assert "[1] Policy v1 | page 3 | Part 1 > Leave | SUPERSEDED" in user_content
    assert "[2] Policy v2" in user_content
    assert "SUPERSEDED" not in user_content.split("[2]")[1]
    assert "What is the rule?" in user_content


def test_citation_helpers() -> None:
    assert extract_cited_numbers("A [2] and [1, 3] and [2] [x] [9]") == [2, 1, 3, 9]
    doc_id = uuid4()
    hits = [SearchHit(chunk_id="a", document_id=doc_id, score=1.0, text="y" * 400, title="T", page=4)]
    citations = build_citations(hits, [1, 9])
    assert len(citations) == 1
    assert citations[0].quote == "y" * 300
    assert citations[0].page == 4
