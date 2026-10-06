"""
Shared image helpers used by every extractor and every entry point.

Images are handled lazily. Extractors only record what is cheap to know -- size,
position, page, a stable ``id`` and a way to load the bytes -- through
``image_record``. Decoding, downscaling and base64 encoding happen in
``collect_images``, and only for the images a caller actually asked for (after
page filtering and ``max_images``). A text-only parse never pays for images.

- ``normalize_image`` / ``prepare_image`` turn whatever bytes a document embedded
  into something an MCP client and vision API can take: PNG, JPEG, GIF or WebP,
  in an RGB-family colour mode, no larger than ``DEFAULT_MAX_DIMENSION`` on the
  long edge and ``MAX_IMAGE_BYTES`` in size. Documents happily embed TIFF, CMYK
  JPEG, JPEG 2000 and 12-megapixel photos; clients reject those replies.

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
import re
from collections.abc import Callable
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# Formats MCP clients (and the Claude/OpenAI vision APIs) accept as-is.
_WEB_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
_WEB_MODES = {"RGB", "RGBA", "L", "LA", "P", "1"}

#: Long-edge cap for returned images. Vision models downscale anything larger
#: (Claude's sweet spot is 1568px), so sending more only burns bytes and tokens.
DEFAULT_MAX_DIMENSION = 1568
#: Raw size cap; base64 adds a third, keeping each item under the common 5 MB limit.
MAX_IMAGE_BYTES = 3_500_000

#: Inline marker extractors write where an image sits in the text.
IMAGE_MARKER = "![{alt}](image:{id})"
IMAGE_MARKER_RE = re.compile(r"!\[([^\]\n]*)\]\(image:([\w.-]+)\)")


def image_marker(image_id: str, alt: str = "") -> str:
    """Text marker for an image, e.g. ``![Figure 1: Revenue](image:p3-1)``."""
    alt = " ".join(alt.replace("[", "(").replace("]", ")").split())
    return IMAGE_MARKER.format(alt=alt, id=image_id)


def _probe(image_bytes: bytes) -> tuple[int, int] | None:
    """Width and height from the image header, without decoding pixels."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return img.size
    except Exception:
        return None


def _encode(img: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    if fmt == "JPEG":
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, "white")
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.getchannel("A"))
            img = background
        img.save(out, "JPEG", quality=85, optimize=True)
    else:
        img.save(out, "PNG", optimize=fmt == "PNG")
    return out.getvalue()


def prepare_image(
    image_bytes: bytes,
    max_dimension: int | None = DEFAULT_MAX_DIMENSION,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> tuple[bytes, int, int, str] | None:
    """
    Return ``(bytes, width, height, mime_type)`` ready to send to a client.

    Bytes already in a web format and colour mode, within the size limits, pass
    through untouched. Otherwise the image is converted, downscaled so the long
    edge is at most ``max_dimension`` (``None`` or ``0`` keeps full size), and
    re-encoded: PNG to keep line art and text crisp, JPEG when PNG would exceed
    ``max_bytes``. Returns ``None`` when Pillow cannot decode the data at all
    (for example EMF/WMF vector art off Windows).
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
            too_big = bool(max_dimension) and max(width, height) > max_dimension
            if (
                fmt in _WEB_FORMATS
                and img.mode in _WEB_MODES
                and not too_big
                and len(image_bytes) <= max_bytes
            ):
                return image_bytes, width, height, _WEB_FORMATS[fmt]

            img.load()
            if img.mode not in _WEB_MODES or img.mode == "P" and "transparency" in img.info:
                img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
            if too_big and max_dimension:
                img = img.copy()
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            data = _encode(img, "PNG")
            mime = "image/png"
            if len(data) > max_bytes:
                data = _encode(img, "JPEG")
                mime = "image/jpeg"
            if len(data) > max_bytes:
                # Still too big (enormous max_dimension): shrink until it fits.
                while len(data) > max_bytes and max(img.size) > 256:
                    img = img.resize((img.width * 3 // 4, img.height * 3 // 4), Image.Resampling.LANCZOS)
                    data = _encode(img, "JPEG")
            return data, img.width, img.height, mime
    except Exception as e:
        logger.warning(f"Skipping undecodable image ({len(image_bytes)} bytes): {e}")
        return None


def normalize_image(image_bytes: bytes) -> tuple[bytes, int, int, str] | None:
    """Client-safe format conversion at full resolution (see ``prepare_image``)."""
    return prepare_image(image_bytes, max_dimension=None, max_bytes=2**62)


def image_record(
    image_bytes: bytes | None = None,
    min_width: int = 0,
    min_height: int = 0,
    *,
    loader: Callable[[], bytes] | None = None,
    width: int | None = None,
    height: int | None = None,
    key: str | None = None,
    **extra: Any,
) -> dict[str, Any] | None:
    """
    Build the standard (lazy) image item every extractor emits.

    Pass either ``image_bytes`` (size is read from the header) or a ``loader``
    plus ``width``/``height`` when fetching the bytes is itself costly (PDF).
    ``key`` identifies identical images for de-duplication; it defaults to a
    hash of the bytes. ``extra`` usually carries ``id``, ``page``, ``position``
    and ``alt``.

    Returns ``None`` if the image cannot be read or is below the size floor.
    Nothing is decoded or encoded here; see ``collect_images``.
    """
    if image_bytes is not None:
        size = _probe(image_bytes)
        if size is None:
            logger.debug(f"Skipping unreadable image ({len(image_bytes)} bytes)")
            return None
        width, height = size
        data = image_bytes
        loader = lambda: data  # noqa: E731
        key = key or hashlib.sha1(image_bytes).hexdigest()
    elif loader is None or width is None or height is None:
        raise ValueError("image_record needs image_bytes, or a loader with width and height")

    if width < min_width or height < min_height:
        return None
    return {
        "type": "image",
        "width": width,
        "height": height,
        "_load": loader,
        "_key": key,
        **extra,
    }


def _walk(node: Any, page: int | None, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        number = node.get("page_number", node.get("slide_number"))
        if isinstance(number, int):
            page = number
        if node.get("type") == "image" and (node.get("_load") or node.get("content")):
            out.append({**node, "page": node.get("page", page)})
            return
        for value in node.values():
            _walk(value, page, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, page, out)


def _find(structure: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every image record in document order, each with a ``page`` and an ``id``."""
    if not isinstance(structure, dict):
        return []
    found: list[dict[str, Any]] = []
    _walk({k: v for k, v in structure.items() if k != "images"}, None, found)
    if not found:
        # Extractors that only publish a flat top-level list.
        _walk(structure.get("images") or [], None, found)
    for index, img in enumerate(found, start=1):
        img.setdefault("id", f"img-{index}")
    return found


def _dedupe(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for img in found:
        key = img.get("_key") or hashlib.sha1(str(img.get("content", "")).encode()).hexdigest()
        if key in unique:
            first = unique[key]
            if img.get("page") is not None and img["page"] not in first["pages"]:
                first["pages"].append(img["page"])
            first["aliases"].append(img["id"])
        else:
            unique[key] = {
                **img,
                "pages": [img["page"]] if img.get("page") is not None else [],
                "aliases": [],
            }
    return list(unique.values())


def _select(
    structure: dict[str, Any] | None,
    page_filter: int | None,
    dedupe: bool,
    image_id: str | None = None,
) -> list[dict[str, Any]]:
    found = _find(structure)
    if image_id is not None:
        deduped = _dedupe(found)
        return [img for img in deduped if img["id"] == image_id or image_id in img["aliases"]]
    if page_filter is not None:
        return [img for img in found if img.get("page") == page_filter]
    return _dedupe(found) if dedupe else found


def count_images(
    structure: dict[str, Any] | None,
    page_filter: int | None = None,
    dedupe: bool = True,
) -> int:
    """How many images ``collect_images`` would return, without loading any."""
    return len(_select(structure, page_filter, dedupe))


def materialize(
    img: dict[str, Any],
    max_dimension: int | None = DEFAULT_MAX_DIMENSION,
) -> dict[str, Any] | None:
    """Load, convert, downscale and base64-encode one image record."""
    public = {k: v for k, v in img.items() if not k.startswith("_")}
    if img.get("content") and not img.get("_load"):
        public.setdefault("mime_type", detect_mime_type(public["content"]))
        return public
    try:
        raw = img["_load"]()
    except Exception as e:
        logger.warning(f"Could not load image {img.get('id')}: {e}")
        return None
    prepared = prepare_image(raw, max_dimension=max_dimension)
    if prepared is None:
        return None
    data, width, height, mime = prepared
    public.update(
        content=base64.b64encode(data).decode("ascii"),
        mime_type=mime,
        width=width,
        height=height,
        original_width=img["width"],
        original_height=img["height"],
    )
    return public


def collect_images(
    structure: dict[str, Any] | None,
    page_filter: int | None = None,
    max_images: int | None = None,
    dedupe: bool = True,
    max_dimension: int | None = DEFAULT_MAX_DIMENSION,
    image_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Gather image items in a document structure, in document order, ready to send.

    Args:
        structure: ``RawDocument.structure`` from any extractor.
        page_filter: Only images on this page/slide (1-indexed).
        max_images: Stop after this many. Only these are decoded and encoded.
        dedupe: Collapse identical images (a logo on every page) into one
            record whose ``pages`` lists every page it appears on and whose
            ``aliases`` lists the ids of the repeats. Skipped when
            ``page_filter`` is set, so a page always shows everything on it.
        max_dimension: Downscale so the long edge is at most this many pixels;
            ``None`` or ``0`` returns full resolution.
        image_id: Only the image with this id (or alias), as written in the
            text marker ``![...](image:<id>)``.

    Returns:
        Image items: ``id``, ``content`` (base64), ``mime_type``, ``width``,
        ``height``, ``original_width``, ``original_height``, ``page``,
        ``position`` and, when deduped, ``pages`` and ``aliases``.
    """
    selected = _select(structure, page_filter, dedupe, image_id)
    out: list[dict[str, Any]] = []
    for img in selected:
        if max_images is not None and len(out) >= max_images:
            break
        ready = materialize(img, max_dimension=max_dimension)
        if ready is not None:
            out.append(ready)
    return out


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
