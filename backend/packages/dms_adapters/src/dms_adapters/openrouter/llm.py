from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from dms_adapters.openrouter.client import OpenRouterClient, OpenRouterError, raise_for_status

FENCE_PATTERN = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def strip_code_fences(text: str) -> str:
    match = FENCE_PATTERN.match(text)
    return match.group(1).strip() if match else text.strip()


def parse_sse_line(line: str) -> str | None:
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if "error" in payload:
        raise OpenRouterError(str(payload["error"]))
    choices = payload.get("choices") or []
    if not choices:
        return None
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content or None


class OpenRouterLlm:
    def __init__(self, client: OpenRouterClient, default_model: str) -> None:
        self.client = client
        self.default_model = default_model

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        result = self.client.post_json("/chat/completions", payload)
        choices = result.get("choices") or []
        if not choices:
            raise OpenRouterError(f"no choices in response: {str(result)[:300]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        return strip_code_fences(content) if json_mode else content

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        async for attempt in self.client.async_retrying():
            with attempt:
                async with self.client.async_client.stream("POST", "/chat/completions", json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise_for_status(response, body)
                    async for line in response.aiter_lines():
                        content = parse_sse_line(line.strip())
                        if content:
                            yield content
                return
