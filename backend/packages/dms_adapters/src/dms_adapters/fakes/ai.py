from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

_TOKEN = re.compile(r"[\w一-鿿]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        if re.search(r"[一-鿿]", tok):
            out.extend(tok)
        else:
            out.append(tok)
    return out


class FakeEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = _tokens(text)
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
        for g in grams:
            h = int(hashlib.md5(g.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 64) & 1 else -1.0
        if not grams:
            h = int(hashlib.md5(text.encode()).hexdigest(), 16)
            v[h % self.dim] = 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


_DOCTYPE_WORDS = [
    ("minutes", ("minutes", "minit", "mesyuarat", "meeting")),
    ("circular", ("circular", "pekeliling")),
    ("sop", ("standard operating procedure", "sop", "procedure")),
    ("guideline", ("guideline", "garis panduan", "指南", "guidelines")),
    ("policy", ("policy", "dasar")),
    ("report", ("report", "laporan")),
]


class FakeLlm:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _user_text(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for m in messages:
            if m.get("role") == "system":
                continue
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                parts.extend(p.get("text", "") for p in c if isinstance(p, dict))
        return "\n".join(parts)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append({"messages": messages, "model": model, "json_mode": json_mode})
        text = self._user_text(messages)
        if json_mode:
            return json.dumps(self._enrich(text))
        body = " ".join(text.split())
        return "Summary: " + body[-400:]

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "model": model, "stream": True})
        text = self._user_text(messages)
        cites = sorted(set(re.findall(r"\[(\d+)\]", text)), key=int)[:2]
        answer = "Based on the sources " + " ".join(f"[{c}]" for c in cites) if cites else "I couldn't find this in the documents you can access."
        for word in answer.split(" "):
            yield word + " "

    @staticmethod
    def _doctype_of(text: str) -> str | None:
        low = text.lower()
        best: tuple[int, str] | None = None
        for name, words in _DOCTYPE_WORDS:
            for w in words:
                pattern = re.escape(w) if re.search(r"[一-鿿]", w) else rf"(?<![a-z]){re.escape(w)}(?![a-z])"
                found = re.search(pattern, low)
                if found and (best is None or found.start() < best[0]):
                    best = (found.start(), name)
        return best[1] if best else None

    def _enrich(self, text: str) -> dict[str, Any]:
        filename_match = re.search(r"^Filename:\s*(.*)$", text, re.M)
        filename = filename_match.group(1) if filename_match else ""
        excerpt_at = text.find("Document excerpt:")
        if excerpt_at >= 0:
            text = text[excerpt_at + len("Document excerpt:"):]
        stem = re.sub(r"[_\-.]+", " ", filename)
        doctype = self._doctype_of(stem) or self._doctype_of(text) or "other"
        ref = re.search(r"\b([A-Z]{2,}(?:/[A-Z0-9]+){2,})\b", text)
        sup = re.search(r"(?:supersedes|menggantikan|replaces)\W+([A-Z]{2,}(?:/[A-Z0-9]+){2,})", text, re.I)
        date = re.search(r"\b(20\d\d-\d\d-\d\d)\b", text)
        lines = [ln.strip("# ").strip() for ln in text.splitlines() if 3 <= len(ln.strip("# ").strip()) <= 120]
        title = lines[0] if lines else None
        for ln in lines:
            if any(w in ln.lower() for _, ws in _DOCTYPE_WORDS for w in ws):
                title = ln
                break
        return {
            "title": title,
            "doctype": doctype,
            "agency": None,
            "reference_no": ref.group(1) if ref and (not sup or ref.group(1) != sup.group(1)) else None,
            "effective_date": date.group(1) if date else None,
            "supersedes_ref": sup.group(1) if sup else None,
            "language": "zh" if re.search(r"[一-鿿]", text) else "en",
            "tags": [],
        }


class FakeVisionOcr:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.calls: list[int] = []

    def transcribe(self, png_bytes: bytes, hint_lang: str | None = None) -> str:
        self.calls.append(len(png_bytes))
        if self.text is not None:
            return self.text
        return f"# Scanned page\n\nOCR transcribed text block {len(self.calls)}."
