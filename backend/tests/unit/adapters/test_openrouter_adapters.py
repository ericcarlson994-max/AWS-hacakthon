import json

import httpx
import pytest
import respx

from dms_adapters.openrouter.client import OpenRouterClient, OpenRouterError
from dms_adapters.openrouter.embedder import OpenRouterEmbedder
from dms_adapters.openrouter.llm import OpenRouterLlm, parse_sse_line, strip_code_fences
from dms_adapters.openrouter.vision_ocr import OpenRouterVisionOcr
from dms_core.config import Settings

BASE = "https://openrouter.test/api/v1"


@pytest.fixture
def client() -> OpenRouterClient:
    settings = Settings(openrouter_api_key="sk-test", openrouter_base_url=BASE)
    return OpenRouterClient(settings, wait_min=0, wait_max=0)


def embedding_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    data = [{"index": i, "embedding": [float(len(text)), float(i)]} for i, text in enumerate(payload["input"])]
    return httpx.Response(200, json={"data": list(reversed(data))})


@respx.mock
def test_embedder_batches_and_orders_by_index(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/embeddings").mock(side_effect=embedding_response)
    embedder = OpenRouterEmbedder(client, "baai/bge-m3", batch_size=2)
    vectors = embedder.embed(["a", "bb", "ccc", "dddd", "eeeee"])
    assert route.call_count == 3
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    first = json.loads(route.calls[0].request.content)
    assert first == {"model": "baai/bge-m3", "input": ["a", "bb"]}
    headers = route.calls[0].request.headers
    assert headers["authorization"] == "Bearer sk-test"
    assert headers["http-referer"] == "http://localhost"
    assert headers["x-title"] == "GovDocs Search"


@respx.mock
def test_embedder_empty_input_makes_no_calls(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/embeddings").mock(side_effect=embedding_response)
    assert OpenRouterEmbedder(client, "m").embed([]) == []
    assert route.call_count == 0


@respx.mock
def test_retries_on_429_then_succeeds(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/embeddings").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate"}),
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5]}]}),
        ]
    )
    assert OpenRouterEmbedder(client, "m").embed(["x"]) == [[0.5]]
    assert route.call_count == 3


@respx.mock
def test_retries_stop_after_four_attempts(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(OpenRouterError):
        OpenRouterLlm(client, "m").complete([{"role": "user", "content": "hi"}])
    assert route.call_count == 4


@respx.mock
def test_non_retryable_error_is_raised_immediately(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(OpenRouterError):
        OpenRouterLlm(client, "m").complete([{"role": "user", "content": "hi"}])
    assert route.call_count == 1


@respx.mock
def test_complete_json_mode_strips_fences(client: OpenRouterClient) -> None:
    content = '```json\n{"title": "Leave Policy"}\n```'
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )
    llm = OpenRouterLlm(client, "default/model")
    result = llm.complete([{"role": "user", "content": "x"}], json_mode=True, max_tokens=50)
    assert json.loads(result) == {"title": "Leave Policy"}
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["model"] == "default/model"
    assert sent["max_tokens"] == 50


@respx.mock
def test_complete_plain_uses_override_model(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})
    )
    assert OpenRouterLlm(client, "d").complete([{"role": "user", "content": "x"}], model="other") == "hello"
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "other"
    assert "response_format" not in sent


def test_strip_code_fences_variants() -> None:
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'
    assert strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('  ```JSON\n{"a": 1}```  ') == '{"a": 1}'


def test_parse_sse_line() -> None:
    assert parse_sse_line(": OPENROUTER PROCESSING") is None
    assert parse_sse_line("data: [DONE]") is None
    assert parse_sse_line("") is None
    assert parse_sse_line('data: {"choices":[{"delta":{"content":"Hi"}}]}') == "Hi"
    assert parse_sse_line('data: {"choices":[{"delta":{}}]}') is None


@respx.mock
async def test_stream_parses_sse(client: OpenRouterClient) -> None:
    body = (
        ": OPENROUTER PROCESSING\n\n"
        'data: {"choices":[{"delta":{"role":"assistant","content":"Hello"}}]}\n\n'
        ": OPENROUTER PROCESSING\n\n"
        'data: {"choices":[{"delta":{"content":" world [1]"}}]}\n\n'
        'data: {"choices":[{"delta":{}, "finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    llm = OpenRouterLlm(client, "answer/model")
    tokens = [t async for t in llm.stream([{"role": "user", "content": "q"}])]
    assert tokens == ["Hello", " world [1]"]
    sent = json.loads(route.calls[0].request.content)
    assert sent["stream"] is True
    await client.aclose()


@respx.mock
async def test_stream_retries_on_429(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, text="slow down"),
            httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'),
        ]
    )
    tokens = [t async for t in OpenRouterLlm(client, "m").stream([{"role": "user", "content": "q"}])]
    assert tokens == ["ok"]
    assert route.call_count == 2


@respx.mock
def test_vision_payload_shape(client: OpenRouterClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "# Title\n\n| a | b |"}}]})
    )
    ocr = OpenRouterVisionOcr(client, "qwen/vl")
    text = ocr.transcribe(b"\x89PNGdata", hint_lang="ms")
    assert text == "# Title\n\n| a | b |"
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "qwen/vl"
    assert len(sent["messages"]) == 1
    message = sent["messages"][0]
    assert message["role"] == "user"
    text_part, image_part = message["content"]
    assert text_part["type"] == "text"
    assert "Transcribe all text on this page exactly" in text_part["text"]
    assert "Do not translate" in text_part["text"]
    assert "ms" in text_part["text"]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
