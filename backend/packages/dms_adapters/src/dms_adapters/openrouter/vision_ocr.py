from __future__ import annotations

import base64

from dms_adapters.openrouter.client import OpenRouterClient
from dms_adapters.openrouter.llm import strip_code_fences

OCR_PROMPT = (
    "Transcribe all text on this page exactly. Preserve headings as markdown `#`, "
    "keep table rows as `| a | b |`. Do not translate."
)


def build_ocr_prompt(hint_lang: str | None) -> str:
    if hint_lang:
        return f"{OCR_PROMPT} The page is likely written in language: {hint_lang}."
    return OCR_PROMPT


class OpenRouterVisionOcr:
    def __init__(self, client: OpenRouterClient, model: str, max_tokens: int = 4000) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def build_messages(self, png_bytes: bytes, hint_lang: str | None = None) -> list[dict]:
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_ocr_prompt(hint_lang)},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            }
        ]

    def transcribe(self, png_bytes: bytes, hint_lang: str | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": self.build_messages(png_bytes, hint_lang),
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }
        result = self.client.post_json("/chat/completions", payload)
        choices = result.get("choices") or []
        if not choices:
            return ""
        content = (choices[0].get("message") or {}).get("content") or ""
        stripped = strip_code_fences(content) if content.lstrip().startswith("```") else content
        return stripped.strip()
