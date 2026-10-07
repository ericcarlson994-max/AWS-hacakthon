from __future__ import annotations

from collections.abc import AsyncIterator

from dms_core.answer.citations import build_citations, extract_cited_numbers
from dms_core.answer.prompt import build_messages
from dms_core.config import Settings
from dms_core.models import AskEvent, SearchFilters, User
from dms_core.ports import Llm, Repo
from dms_core.search.service import SearchService

NOT_FOUND_MESSAGE = "I couldn't find anything about that in the documents you can access."
FALLBACK_CITATION_COUNT = 3


class AskService:
    def __init__(self, search: SearchService, llm: Llm, repo: Repo, settings: Settings) -> None:
        self.search = search
        self.llm = llm
        self.repo = repo
        self.settings = settings

    async def stream(
        self, user: User, question: str, filters: SearchFilters | None = None
    ) -> AsyncIterator[AskEvent]:
        try:
            hits = self.search.retrieve(user, question, k=self.settings.ask_top_k, filters=filters)
            if not hits:
                yield AskEvent(event="token", data={"text": NOT_FOUND_MESSAGE})
                yield AskEvent(event="citations", data={"citations": []})
                yield AskEvent(event="done", data={})
                return
            document_ids = list(dict.fromkeys(hit.document_id for hit in hits))
            superseded = {row.id for row in self.repo.get_documents(document_ids) if row.superseded_by is not None}
            messages = build_messages(question, hits, superseded)
            answer_parts: list[str] = []
            async for token in self.llm.stream(messages, model=self.settings.llm_answer_model):
                if not token:
                    continue
                answer_parts.append(token)
                yield AskEvent(event="token", data={"text": token})
            numbers = extract_cited_numbers("".join(answer_parts))
            citations = build_citations(hits, numbers)
            if not citations:
                citations = build_citations(hits, list(range(1, min(FALLBACK_CITATION_COUNT, len(hits)) + 1)))
            yield AskEvent(
                event="citations",
                data={"citations": [citation.model_dump(mode="json") for citation in citations]},
            )
            yield AskEvent(event="done", data={})
        except Exception as error:
            yield AskEvent(event="error", data={"message": str(error) or error.__class__.__name__})
