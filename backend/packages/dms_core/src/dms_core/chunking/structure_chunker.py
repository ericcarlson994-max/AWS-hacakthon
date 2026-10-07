import re
from dataclasses import dataclass, field
from uuid import UUID

from dms_core.chunking.chunk_id import make_chunk_id
from dms_core.chunking.tokens import estimate_tokens
from dms_core.models import Block, Chunk

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_TABLE_ROW_BOUNDARY = re.compile(r"\n+|\s\|\s")


@dataclass
class _Piece:
    text: str
    page: int


@dataclass
class _Section:
    heading_path: list[str]
    heading: _Piece | None = None
    pieces: list[_Piece] = field(default_factory=list)


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]


def _hard_split_words(text: str, max_tokens: int) -> list[str]:
    words = text.split()
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and estimate_tokens(candidate) > max_tokens:
            parts.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(" ".join(current))
    return parts


def _group_units(units: list[str], separator: str, max_tokens: int) -> list[str]:
    groups: list[str] = []
    current: list[str] = []
    for unit in units:
        candidate = separator.join([*current, unit])
        if current and estimate_tokens(candidate) > max_tokens:
            groups.append(separator.join(current))
            current = [unit]
        else:
            current.append(unit)
    if current:
        groups.append(separator.join(current))
    return groups


def _split_paragraph(text: str, max_tokens: int) -> list[str]:
    sentences: list[str] = []
    for sentence in split_sentences(text):
        if estimate_tokens(sentence) > max_tokens:
            sentences.extend(_hard_split_words(sentence, max_tokens))
        else:
            sentences.append(sentence)
    return _group_units(sentences, " ", max_tokens)


def _split_table(text: str, max_tokens: int) -> list[str]:
    if "\n" in text:
        rows = [row for row in text.split("\n") if row.strip()]
        return _group_units(rows, "\n", max_tokens)
    cells = [cell for cell in _TABLE_ROW_BOUNDARY.split(text) if cell.strip()]
    return _group_units(cells, " | ", max_tokens)


def _block_pieces(block: Block, max_tokens: int) -> list[_Piece]:
    text = block.text.strip()
    if not text:
        return []
    if estimate_tokens(text) <= max_tokens:
        return [_Piece(text, block.page)]
    if block.type in ("table", "cell"):
        parts = _split_table(text, max_tokens)
    else:
        parts = _split_paragraph(text, max_tokens)
    return [_Piece(part, block.page) for part in parts]


def _build_sections(blocks: list[Block], max_tokens: int) -> list[_Section]:
    sections: list[_Section] = []
    heading_stack: list[tuple[int, str]] = []
    current = _Section(heading_path=[])
    for block in blocks:
        if block.type == "heading" and block.text.strip():
            if current.heading is not None or current.pieces:
                sections.append(current)
            level = block.level or 1
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_text = block.text.strip()
            heading_stack.append((level, heading_text))
            current = _Section(
                heading_path=[text for _, text in heading_stack],
                heading=_Piece(heading_text, block.page),
            )
            continue
        current.pieces.extend(_block_pieces(block, max_tokens))
    if current.heading is not None or current.pieces:
        sections.append(current)
    return sections


def _overlap_tail(text: str, budget_tokens: int) -> str:
    if budget_tokens <= 0:
        return ""
    sentences = split_sentences(text)
    tail: list[str] = []
    for sentence in reversed(sentences):
        candidate = " ".join([sentence, *tail])
        if estimate_tokens(candidate) > budget_tokens:
            break
        tail.insert(0, sentence)
    return " ".join(tail)


@dataclass
class _Draft:
    heading_path: list[str]
    overlap: str
    pieces: list[_Piece]

    def body(self) -> str:
        return "\n\n".join(piece.text for piece in self.pieces)

    def text(self) -> str:
        body = self.body()
        return f"{self.overlap}\n\n{body}" if self.overlap else body


def _section_drafts(section: _Section, target_tokens: int, overlap_ratio: float) -> list[_Draft]:
    drafts: list[_Draft] = []
    initial = [section.heading] if section.heading is not None else []
    current = _Draft(section.heading_path, "", list(initial))
    has_body = False
    for piece in section.pieces:
        if has_body and estimate_tokens(
            current.text() + "\n\n" + piece.text
        ) > target_tokens:
            drafts.append(current)
            previous_body = current.body()
            overlap = _overlap_tail(previous_body, int(estimate_tokens(previous_body) * overlap_ratio))
            if overlap and estimate_tokens(overlap + "\n\n" + piece.text) > target_tokens:
                overlap = ""
            current = _Draft(section.heading_path, overlap, [])
        current.pieces.append(piece)
        has_body = True
    if current.pieces:
        drafts.append(current)
    return drafts


def chunk_blocks(
    document_id: UUID,
    blocks: list[Block],
    *,
    target_tokens: int = 450,
    max_tokens: int = 500,
    overlap_ratio: float = 0.12,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    seen_ids: dict[str, int] = {}
    for section in _build_sections(blocks, max_tokens):
        for draft in _section_drafts(section, target_tokens, overlap_ratio):
            text = draft.text()
            base_id = make_chunk_id(document_id, text)
            occurrences = seen_ids.get(base_id, 0) + 1
            seen_ids[base_id] = occurrences
            chunk_id = base_id if occurrences == 1 else f"{base_id}:{occurrences}"
            pages = [piece.page for piece in draft.pieces]
            chunks.append(
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    order=len(chunks),
                    text=text,
                    heading_path=list(draft.heading_path),
                    page_from=min(pages),
                    page_to=max(pages),
                    token_count=estimate_tokens(text),
                )
            )
    return chunks
