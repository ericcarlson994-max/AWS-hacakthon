from __future__ import annotations

from dms_core.extract.docx import extract_docx
from dms_core.extract.filetype import DOCX_MIME, JPEG_MIME, PDF_MIME, PNG_MIME, XLSX_MIME, detect_mime
from dms_core.extract.image import extract_image
from dms_core.extract.pdf import extract_pdf
from dms_core.extract.xlsx import extract_xlsx
from dms_core.models import ExtractResult
from dms_core.ports import VisionOcr


def extract(
    data: bytes,
    filename: str,
    ocr: VisionOcr | None,
    *,
    ocr_text_threshold: int = 50,
    render_dpi: int = 200,
) -> ExtractResult:
    mime_type = detect_mime(data, filename)
    if mime_type == PDF_MIME:
        blocks, page_count, title, ocr_pages = extract_pdf(
            data, ocr, ocr_text_threshold=ocr_text_threshold, render_dpi=render_dpi
        )
        return ExtractResult(
            blocks=blocks, page_count=page_count, mime_type=mime_type, embedded_title=title, ocr_pages=ocr_pages
        )
    if mime_type == DOCX_MIME:
        blocks, title = extract_docx(data)
        return ExtractResult(blocks=blocks, page_count=1, mime_type=mime_type, embedded_title=title)
    if mime_type == XLSX_MIME:
        blocks, sheet_count, title = extract_xlsx(data)
        return ExtractResult(blocks=blocks, page_count=sheet_count, mime_type=mime_type, embedded_title=title)
    if mime_type in (PNG_MIME, JPEG_MIME):
        blocks, ocr_pages = extract_image(data, ocr)
        return ExtractResult(blocks=blocks, page_count=1, mime_type=mime_type, ocr_pages=ocr_pages)
    raise AssertionError(mime_type)
