from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

import fitz

from dms_core.extract.markdown import parse_ocr_markdown
from dms_core.models import Block
from dms_core.ports import VisionOcr

HEADING_SIZE_RATIO = 1.3


@dataclass
class _TextBlock:
    text: str
    size: float
    bbox: list[float]


def _page_text_blocks(page: fitz.Page) -> list[_TextBlock]:
    result: list[_TextBlock] = []
    page_dict = page.get_text("dict")
    for raw_block in page_dict.get("blocks", []):
        if raw_block.get("type", 0) != 0:
            continue
        line_texts: list[str] = []
        weighted_sizes: Counter[float] = Counter()
        for line in raw_block.get("lines", []):
            span_texts: list[str] = []
            for span in line.get("spans", []):
                span_text = span.get("text", "")
                span_texts.append(span_text)
                stripped_length = len(span_text.strip())
                if stripped_length:
                    weighted_sizes[round(float(span.get("size", 0.0)), 1)] += stripped_length
            line_text = "".join(span_texts).strip()
            if line_text:
                line_texts.append(line_text)
        text = "\n".join(line_texts).strip()
        if not text or not weighted_sizes:
            continue
        dominant_size = weighted_sizes.most_common(1)[0][0]
        result.append(_TextBlock(text=text, size=dominant_size, bbox=[float(v) for v in raw_block.get("bbox", [])]))
    return result


def _body_size(all_blocks: list[_TextBlock]) -> float:
    sizes: list[float] = []
    for block in all_blocks:
        sizes.extend([block.size] * max(1, len(block.text)))
    return statistics.median(sizes) if sizes else 0.0


def _render_png(page: fitz.Page, dpi: int) -> bytes:
    pixmap = page.get_pixmap(dpi=dpi)
    return pixmap.tobytes("png")


def extract_pdf(
    data: bytes,
    ocr: VisionOcr | None,
    *,
    ocr_text_threshold: int = 50,
    render_dpi: int = 200,
    start_order: int = 0,
) -> tuple[list[Block], int, str | None, list[int]]:
    document = fitz.open(stream=data, filetype="pdf")
    try:
        page_count = document.page_count
        pages_text_blocks: list[list[_TextBlock] | None] = []
        ocr_texts: dict[int, str] = {}
        ocr_pages: list[int] = []
        for page_index in range(page_count):
            page = document[page_index]
            text_blocks = _page_text_blocks(page)
            stripped_length = len(page.get_text("text").strip())
            if stripped_length < ocr_text_threshold:
                pages_text_blocks.append(None)
                if ocr is not None:
                    ocr_texts[page_index + 1] = ocr.transcribe(_render_png(page, render_dpi))
                    ocr_pages.append(page_index + 1)
                elif text_blocks:
                    pages_text_blocks[-1] = text_blocks
            else:
                pages_text_blocks.append(text_blocks)

        flat_blocks = [block for blocks in pages_text_blocks if blocks for block in blocks]
        body_size = _body_size(flat_blocks)
        heading_threshold = body_size * HEADING_SIZE_RATIO
        heading_sizes = sorted({block.size for block in flat_blocks if body_size and block.size >= heading_threshold})
        largest_heading_size = heading_sizes[-1] if heading_sizes else None

        blocks: list[Block] = []
        order = start_order
        for page_index, text_blocks in enumerate(pages_text_blocks):
            page_number = page_index + 1
            if page_number in ocr_texts:
                parsed = parse_ocr_markdown(ocr_texts[page_number], page=page_number, start_order=order)
                blocks.extend(parsed)
                order += len(parsed)
                continue
            for text_block in text_blocks or []:
                is_heading = bool(body_size) and text_block.size >= heading_threshold
                if is_heading:
                    level = 1 if text_block.size == largest_heading_size else 2
                    blocks.append(
                        Block(
                            type="heading",
                            text=" ".join(text_block.text.split()),
                            page=page_number,
                            level=level,
                            bbox=text_block.bbox or None,
                            order=order,
                            source="text_layer",
                            font_size=text_block.size,
                        )
                    )
                else:
                    blocks.append(
                        Block(
                            type="paragraph",
                            text=text_block.text,
                            page=page_number,
                            bbox=text_block.bbox or None,
                            order=order,
                            source="text_layer",
                            font_size=text_block.size,
                        )
                    )
                order += 1
        metadata = document.metadata or {}
        title = (metadata.get("title") or "").strip() or None
    finally:
        document.close()
    return blocks, page_count, title, ocr_pages
