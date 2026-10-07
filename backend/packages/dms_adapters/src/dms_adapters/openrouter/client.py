from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from dms_core.config import Settings

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenRouterError(RuntimeError):
    pass


class RetryableOpenRouterError(OpenRouterError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"OpenRouter returned {status_code}: {body[:500]}")
        self.status_code = status_code


def is_retryable(error: BaseException) -> bool:
    return isinstance(error, (RetryableOpenRouterError, httpx.TimeoutException, httpx.TransportError))


class OpenRouterClient:
    def __init__(
        self,
        settings: Settings,
        *,
        max_attempts: int = 4,
        wait_min: float = 1.0,
        wait_max: float = 20.0,
        timeout: float = 120.0,
    ) -> None:
        self.settings = settings
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.wait_min = wait_min
        self.wait_max = wait_max
        self.timeout = timeout
        self._client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "GovDocs Search",
            "Content-Type": "application/json",
        }

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=self.timeout)
        return self._client

    @property
    def async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=self.timeout)
        return self._async_client

    def _retrying(self) -> Retrying:
        return Retrying(
            retry=retry_if_exception(is_retryable),
            wait=wait_exponential(multiplier=self.wait_min, min=self.wait_min, max=self.wait_max),
            stop=stop_after_attempt(self.max_attempts),
            reraise=True,
        )

    def async_retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception(is_retryable),
            wait=wait_exponential(multiplier=self.wait_min, min=self.wait_min, max=self.wait_max),
            stop=stop_after_attempt(self.max_attempts),
            reraise=True,
        )

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in self._retrying():
            with attempt:
                response = self.client.post(path, json=payload)
                raise_for_status(response)
                return response.json()
        raise OpenRouterError("unreachable")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None


def raise_for_status(response: httpx.Response, body: str | None = None) -> None:
    if response.status_code < 400:
        return
    text = body if body is not None else response.text
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableOpenRouterError(response.status_code, text)
    raise OpenRouterError(f"OpenRouter returned {response.status_code}: {text[:500]}")
