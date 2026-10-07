from __future__ import annotations

import io
import zipfile

PDF_MIME = "application/pdf"
PNG_MIME = "image/png"
JPEG_MIME = "image/jpeg"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SUPPORTED_MIME: frozenset[str] = frozenset({PDF_MIME, PNG_MIME, JPEG_MIME, DOCX_MIME, XLSX_MIME})

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
ZIP_SIGNATURE = b"PK\x03\x04"


class UnsupportedFileType(ValueError):
    pass


def _zip_mime(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None
    if "word/document.xml" in names:
        return DOCX_MIME
    if "xl/workbook.xml" in names:
        return XLSX_MIME
    return None


def detect_mime(data: bytes, filename: str) -> str:
    head = data[:1024]
    if head.startswith(PNG_SIGNATURE):
        return PNG_MIME
    if head.startswith(JPEG_SIGNATURE):
        return JPEG_MIME
    if head.startswith(ZIP_SIGNATURE):
        mime = _zip_mime(data)
        if mime:
            return mime
    if b"%PDF" in head:
        return PDF_MIME
    raise UnsupportedFileType(f"Unsupported file type for {filename!r}")
