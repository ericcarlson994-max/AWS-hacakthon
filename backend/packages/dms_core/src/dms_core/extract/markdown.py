from __future__ import annotations

import re

from dms_core.models import Block

HEADING_PATTERN = re.compile(r"^(#{1,6})\s*(.*)$")
SEPARATOR_CELL_PATTERN = re.compile(r"^:?-{2,}:?$")


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    non_empty = [cell for cell in cells if cell]
    return bool(non_empty) and all(SEPARATOR_CELL_PATTERN.match(cell) for cell in non_empty)


def _table_text(lines: list[str]) -> str:
    rows: list[str] = []
    for line in lines:
        cells = _table_cells(line)
        if _is_separator_row(cells):
            continue
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_ocr_markdown(text: str, page: int, start_order: int = 0) -> list[Block]:
    blocks: list[Block] = []
    order = start_order
    paragraph_lines: list[str] = []
    table_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal order
        if paragraph_lines:
            body = "\n".join(paragraph_lines).strip()
            if body:
                blocks.append(Block(type="paragraph", text=body, page=page, order=order, source="ocr"))
                order += 1
            paragraph_lines.clear()

    def flush_table() -> None:
        nonlocal order
        if table_lines:
            body = _table_text(table_lines)
            if body.strip():
                blocks.append(Block(type="table", text=body, page=page, order=order, source="ocr"))
                order += 1
            table_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_table()
            continue
        if _is_table_line(stripped):
            flush_paragraph()
            table_lines.append(stripped)
            continue
        flush_table()
        heading_match = HEADING_PATTERN.match(stripped)
        if heading_match:
            flush_paragraph()
            heading_text = heading_match.group(2).strip().rstrip("#").strip()
            if heading_text:
                blocks.append(
                    Block(
                        type="heading",
                        text=heading_text,
                        page=page,
                        level=len(heading_match.group(1)),
                        order=order,
                        source="ocr",
                    )
                )
                order += 1
            continue
        paragraph_lines.append(stripped)
    flush_paragraph()
    flush_table()
    return blocks
