from __future__ import annotations

import io
import re

import docx as python_docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from dms_core.models import Block

HEADING_STYLE_PATTERN = re.compile(r"^heading\s*(\d+)$", re.IGNORECASE)


def _heading_level(style_name: str) -> int | None:
    if style_name.strip().lower() == "title":
        return 1
    match = HEADING_STYLE_PATTERN.match(style_name.strip())
    if match:
        return max(1, min(6, int(match.group(1))))
    return None


def serialize_rows(rows: list[list[str]]) -> str:
    cleaned = [[cell.strip() for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""
    header = cleaned[0]
    if len(cleaned) == 1:
        return " | ".join(cell for cell in header if cell)
    lines: list[str] = []
    for row in cleaned[1:]:
        pairs: list[str] = []
        for index, value in enumerate(row):
            if not value:
                continue
            column = header[index] if index < len(header) and header[index] else f"col{index + 1}"
            pairs.append(f"{column}: {value}")
        if pairs:
            lines.append(" | ".join(pairs))
    return "\n".join(lines)


def _table_rows(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        previous_cell = None
        for cell in row.cells:
            if previous_cell is not None and cell._tc is previous_cell:
                continue
            previous_cell = cell._tc
            cells.append(cell.text)
        rows.append(cells)
    return rows


def _iter_body(document: DocxDocument) -> list[Paragraph | Table]:
    items: list[Paragraph | Table] = []
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            items.append(Paragraph(element, document))
        elif tag == "tbl":
            items.append(Table(element, document))
    return items


def extract_docx(data: bytes, start_order: int = 0) -> tuple[list[Block], str | None]:
    document = python_docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    order = start_order
    for item in _iter_body(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style_name = item.style.name if item.style is not None else ""
            level = _heading_level(style_name or "")
            if level is not None:
                blocks.append(Block(type="heading", text=text, page=1, level=level, order=order, source="docx"))
            else:
                blocks.append(Block(type="paragraph", text=text, page=1, order=order, source="docx"))
            order += 1
        else:
            text = serialize_rows(_table_rows(item))
            if text:
                blocks.append(Block(type="table", text=text, page=1, order=order, source="docx"))
                order += 1
    title = (document.core_properties.title or "").strip() or None
    return blocks, title
