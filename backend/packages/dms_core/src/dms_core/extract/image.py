from __future__ import annotations

import io

from PIL import Image

from dms_core.extract.markdown import parse_ocr_markdown
from dms_core.models import Block
from dms_core.ports import VisionOcr


def normalize_to_png(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        converted = image.convert("RGBA") if image.mode in ("P", "LA") else image
        if converted.mode not in ("RGB", "RGBA", "L"):
            converted = converted.convert("RGB")
        output = io.BytesIO()
        converted.save(output, format="PNG")
        return output.getvalue()


def extract_image(data: bytes, ocr: VisionOcr | None, start_order: int = 0) -> tuple[list[Block], list[int]]:
    if ocr is None:
        return [], []
    png_bytes = normalize_to_png(data)
    text = ocr.transcribe(png_bytes)
    return parse_ocr_markdown(text, page=1, start_order=start_order), [1]
