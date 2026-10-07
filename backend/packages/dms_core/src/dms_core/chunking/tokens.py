import re

_WHITESPACE = re.compile(r"\s+")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def normalize_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().lower()
