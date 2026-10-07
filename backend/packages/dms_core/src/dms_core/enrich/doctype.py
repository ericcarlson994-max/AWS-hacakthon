import re

DOCTYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("minutes", (r"\bminutes?\b", r"\bminit\b", r"\bmesyuarat\b", r"会议记录", r"会议纪要")),
    ("circular", (r"\bcircular\b", r"\bpekeliling\b", r"通告", r"通函")),
    ("sop", (r"\bsop\b", r"standard operating procedure", r"prosedur operasi standard", r"标准作业程序")),
    ("guideline", (r"\bguidelines?\b", r"garis panduan", r"指南", r"准则")),
    ("policy", (r"\bpolicy\b", r"\bdasar\b", r"政策")),
    ("report", (r"\breport\b", r"\blaporan\b", r"报告")),
)


def infer_doctype(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        lowered = re.sub(r"[_\-.]+", " ", text.lower())
        for doctype, patterns in DOCTYPE_KEYWORDS:
            if any(re.search(pattern, lowered) for pattern in patterns):
                return doctype
    return None


def resolve_doctype(llm_doctype: str | None, title: str | None, filename: str | None, text: str | None) -> str:
    if llm_doctype and llm_doctype != "other":
        return llm_doctype
    return infer_doctype(title, filename, (text or "")[:600]) or "other"
