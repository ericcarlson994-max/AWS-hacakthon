from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from strands import Agent
from strands.models.openai import OpenAIModel

from dms_agent.tools import AgentContext, build_tools
from dms_core.answer.citations import extract_cited_numbers
from dms_core.answer.service import AskService
from dms_core.models import AskEvent, SearchFilters, User
from dms_core.ports import Container
from dms_core.search.service import SearchService

SYSTEM_PROMPT = (
    "You are GovDocs Assistant, a research agent for government officers. "
    "You answer questions about the agency's policies, SOPs, circulars, guidelines, reports and meeting minutes "
    "using ONLY the tools provided; never use outside knowledge. "
    "Plan briefly, then call tools: search_documents for passages (run several focused searches for multi-part "
    "or comparison questions), get_document for metadata, summaries and supersession, get_document_versions for "
    "change history, list_documents to enumerate documents by type. "
    "Do not narrate tool usage; call tools silently, then write one final answer. "
    "Every factual claim in the final answer must cite a source number like [3] taken from tool results. "
    "When a document is superseded, say so and prefer the newer one, naming both. "
    "If the tools return nothing relevant, say you could not find it in the documents the user can access. "
    "Answer in the language of the question. Be concise and use short bullet points for comparisons."
)

ANSWER_MAX_TOKENS = 1500
NARRATION_HOLD_CHARS = 240


def build_model(container: Container) -> OpenAIModel:
    settings = container.settings
    return OpenAIModel(
        client_args={
            "api_key": settings.openrouter_api_key,
            "base_url": settings.openrouter_base_url,
            "default_headers": {"HTTP-Referer": "http://localhost", "X-Title": "GovDocs Search"},
        },
        model_id=settings.agent_model,
        params={"max_tokens": ANSWER_MAX_TOKENS, "temperature": 0.2},
    )


def history_messages(history: Sequence[Any], max_turns: int) -> list[dict[str, Any]]:
    turns = [turn for turn in history if getattr(turn, "content", "").strip()][-max_turns * 2 :]
    messages: list[dict[str, Any]] = []
    for turn in turns:
        role = getattr(turn, "role", "user")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"][0]["text"] += "\n\n" + turn.content
            continue
        messages.append({"role": role, "content": [{"text": turn.content}]})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    while messages and messages[-1]["role"] != "assistant":
        messages.pop()
    return messages


def tool_steps(message: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if message.get("role") != "assistant":
        return steps
    for block in message.get("content") or []:
        use = block.get("toolUse") if isinstance(block, dict) else None
        if use:
            steps.append({"tool": use.get("name"), "input": use.get("input") or {}})
    return steps


class AgentService:
    def __init__(self, container: Container, search: SearchService, fallback: AskService) -> None:
        self.container = container
        self.search = search
        self.fallback = fallback

    @property
    def enabled(self) -> bool:
        settings = self.container.settings
        return bool(settings.openrouter_api_key) and not settings.fake_ai

    async def stream(
        self,
        user: User,
        question: str,
        filters: SearchFilters | None = None,
        history: Sequence[Any] = (),
    ) -> AsyncIterator[AskEvent]:
        if not self.enabled:
            yield AskEvent(event="step", data={"tool": "rag_fallback", "input": {"reason": "agent model unavailable"}})
            async for event in self.fallback.stream(user, question, filters):
                yield event
            return
        settings = self.container.settings
        context = AgentContext(
            user=user,
            container=self.container,
            search=self.search,
            max_tool_calls=settings.agent_max_tool_calls,
            scope=filters,
        )
        agent = Agent(
            model=build_model(self.container),
            tools=build_tools(context),
            system_prompt=SYSTEM_PROMPT,
            messages=history_messages(history, settings.agent_max_history_turns),
            callback_handler=None,
        )
        final_text: list[str] = []
        held: list[str] = []
        releasing = False
        try:
            async for event in agent.stream_async(question.strip()):
                if "data" in event and isinstance(event["data"], str) and event["data"]:
                    if releasing:
                        final_text.append(event["data"])
                        yield AskEvent(event="token", data={"text": event["data"]})
                        continue
                    held.append(event["data"])
                    if sum(len(part) for part in held) >= NARRATION_HOLD_CHARS:
                        releasing = True
                        final_text.extend(held)
                        yield AskEvent(event="token", data={"text": "".join(held)})
                        held.clear()
                elif "message" in event and isinstance(event["message"], dict):
                    steps = tool_steps(event["message"])
                    if steps:
                        held.clear()
                        final_text.clear()
                        releasing = False
                    for step in steps:
                        yield AskEvent(event="step", data=step)
            if held:
                final_text.extend(held)
                yield AskEvent(event="token", data={"text": "".join(held)})
            citations = context.citations(extract_cited_numbers("".join(final_text)))
            yield AskEvent(
                event="citations",
                data={"citations": [citation.model_dump(mode="json") for citation in citations]},
            )
            yield AskEvent(event="done", data={"tool_calls": context.tool_calls, "sources": len(context.sources)})
        except Exception as error:
            yield AskEvent(event="error", data={"message": str(error) or error.__class__.__name__})
