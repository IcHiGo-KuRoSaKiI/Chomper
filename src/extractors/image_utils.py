"""
Shared image helpers used by every extractor and every entry point.

Two jobs:

- ``normalize_image`` turns whatever bytes a document embedded into something an
  MCP client can display: PNG, JPEG, GIF or WebP, in an RGB-family colour mode.
  Documents happily embed TIFF, BMP, CMYK JPEG, JPEG 2000 and friends; clients
  do not render those, and a wrong MIME type makes them reject the whole reply.

- ``collect_images`` finds image records in a document structure however the
  extractor nested them (top-level ``images``, per-page, per-slide, per-section,
  or deeper). Extractors disagree on shape, and every caller reading its own
  favourite key is how PPTX images went missing. One walker, used everywhere.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# Formats MCP clients (and the Claude/OpenAI vision APIs) accept as-is.
_WEB_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
_WEB_MODES = {"RGB", "RGBA", "L", "LA", "P", "1"}


def normalize_image(image_bytes: bytes) -> tuple[bytes, int, int, str] | None:
    """
    Return ``(bytes, width, height, mime_type)`` in a client-safe format.

    Bytes already in a web format and colour mode pass through untouched.
    Anything else is re-encoded as PNG. Returns ``None`` when Pillow cannot
    decode the data at all (for example EMF/WMF vector art off Windows).
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
            if fmt in _WEB_FORMATS and img.mode in _WEB_MODES:
                return image_bytes, width, height, _WEB_FORMATS[fmt]

            img.load()
            if img.mode not in _WEB_MODES:
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            out = io.BytesIO()
            img.save(out, "PNG")
            return out.getvalue(), width, height, "image/png"
    except Exception as e:
        logger.warning(f"Skipping undecodable image ({len(image_bytes)} bytes): {e}")
        return None


def image_record(
    image_bytes: bytes,
    min_width: int = 0,
    min_height: int = 0,
    **extra: Any,
) -> dict[str, Any] | None:
    """
    Build the standard image item every extractor emits.

    Returns ``None`` if the image cannot be decoded or is below the size floor.
    """
    normalized = normalize_image(image_bytes)
    if normalized is None:
        return None
    data, width, height, mime = normalized
    if width < min_width or height < min_height:
        return None
    return {
        "type": "image",
        "content": base64.b64encode(data).decode("utf-8"),
        "mime_type": mime,
        "width": width,
        "height": height,
        **extra,
    }


def _walk(node: Any, page: int | None, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        number = node.get("page_number", node.get("slide_number"))
        if isinstance(number, int):
            page = number
        if node.get("type") == "image" and node.get("content"):
            out.append({**node, "page": node.get("page", page)})
            return
        for value in node.values():
            _walk(value, page, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, page, out)


def collect_images(
    structure: dict[str, Any] | None,
    page_filter: int | None = None,
    max_images: int | None = None,
    dedupe: bool = True,
) -> list[dict[str, Any]]:
    """
    Gather every image item in a document structure, in document order.

    Args:
        structure: ``RawDocument.structure`` from any extractor.
        page_filter: Only images on this page/slide (1-indexed).
        max_images: Stop after this many.
        dedupe: Collapse identical images (a logo on every page) into one
            record whose ``pages`` lists every page it appears on. Skipped when
            ``page_filter`` is set, so a page always shows everything on it.

    Returns:
        Image items: ``content`` (base64), ``mime_type``, ``width``, ``height``,
        ``page`` and, when deduped, ``pages``.
    """
    if not isinstance(structure, dict):
        return []

    found: list[dict[str, Any]] = []
    _walk({k: v for k, v in structure.items() if k != "images"}, None, found)
    if not found:
        # Extractors that only publish a flat top-level list.
        _walk(structure.get("images") or [], None, found)

    if page_filter is not None:
        found = [img for img in found if img.get("page") == page_filter]
    elif dedupe:
        unique: dict[str, dict[str, Any]] = {}
        for img in found:
            key = hashlib.sha1(img["content"].encode("ascii", "ignore")).hexdigest()
            if key in unique:
                if img.get("page") is not None and img["page"] not in unique[key]["pages"]:
                    unique[key]["pages"].append(img["page"])
            else:
                unique[key] = {**img, "pages": [img["page"]] if img.get("page") is not None else []}
        found = list(unique.values())

    for img in found:
        img.setdefault("mime_type", detect_mime_type(img["content"]))

    return found[:max_images] if max_images is not None else found


def detect_mime_type(base64_data: str) -> str:
    """Detect MIME type from the base64 prefix of image data."""
    if base64_data.startswith("/9j/"):
        return "image/jpeg"
    if base64_data.startswith("R0lGOD"):
        return "image/gif"
    if base64_data.startswith("iVBOR"):
        return "image/png"
    if base64_data.startswith("UklGR"):
        return "image/webp"
    return "image/png"
