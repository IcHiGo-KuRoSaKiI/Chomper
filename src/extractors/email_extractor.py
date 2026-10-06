"""
Extractors for email formats: EML and MSG.

Output layout (both formats)::

    # <subject>

    **From:** ...
    **To:** ...
    **CC:** ...
    **Date:** ...

    <body>

    ## Attachments

    - report.pdf (application/pdf, 12.3 KB)

The body is the ``text/plain`` part when there is one (the sender's own plain
version, free of HTML layout tables); otherwise the HTML part is converted to
Markdown with the shared HTML walker, so an HTML-only message never shows raw
tags. Inline images referenced as ``cid:`` become lazy image records
(``img-<n>``) with markers where they sit. The body is never truncated.
``metadata["body_source"]`` says which part was used.
"""

from __future__ import annotations

import logging
from email import policy
from email.message import EmailMessage, MIMEPart
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor
from .encoding_utils import decode_bytes

try:
    from bs4 import BeautifulSoup

    from .html_markdown import HTMLToMarkdown, body_of, strip_boilerplate

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# Optional import for MSG files
try:
    import extract_msg

    MSG_AVAILABLE = True
except ImportError:
    extract_msg = None
    MSG_AVAILABLE = False

logger = logging.getLogger(__name__)


def human_size(size: int) -> str:
    """``1536`` -> ``1.5 KB``."""
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def html_body_to_markdown(
    html: str | bytes, inline_images: dict[str, bytes]
) -> tuple[str, list[dict[str, Any]]]:
    """Convert an HTML email body; ``cid:`` images resolve through ``inline_images``."""
    if not BS4_AVAILABLE:
        raise ImportError("beautifulsoup4 is required to convert HTML email bodies")

    def load(src: str) -> bytes | None:
        key = src[4:] if src.lower().startswith("cid:") else src
        return inline_images.get(key.strip("<>"))

    soup = BeautifulSoup(html, "lxml")
    strip_boilerplate(soup, chrome=False)
    converter = HTMLToMarkdown(image_loader=load)
    return converter.convert(body_of(soup)), converter.images


def render_email(
    headers: dict[str, str],
    body: str,
    attachments: list[dict[str, Any]],
    include_headers: bool = True,
) -> str:
    """Assemble the Markdown layout shared by EML and MSG."""
    parts: list[str] = []
    if include_headers:
        subject = " ".join((headers.get("subject") or "").split())
        parts.append(f"# {subject}" if subject else "# (no subject)")
        lines = [
            f"**{label}:** {headers[key]}"
            for key, label in (("from", "From"), ("to", "To"), ("cc", "CC"), ("date", "Date"))
            if headers.get(key)
        ]
        if lines:
            parts.append("\n".join(lines))
    parts.append(body.strip() if body.strip() else "*(no body)*")
    if attachments:
        items = [
            f"- {att['filename']} ({att.get('content_type') or 'unknown type'}, {human_size(att.get('size') or 0)})"
            for att in attachments
        ]
        parts.append("## Attachments\n\n" + "\n".join(items))
    return "\n\n".join(parts)


class EMLExtractor(BaseExtractor):
    """
    Extractor for .eml email files (RFC 822 format).

    Uses Python's built-in email library (no external dependencies).
    """

    SUPPORTED_EXTENSIONS = [".eml"]

    def __init__(self, include_headers: bool = True, include_attachments: bool = True):
        """
        Initialize EML extractor.

        Args:
            include_headers: Include email headers in output
            include_attachments: List attachments in output
        """
        self.include_headers = include_headers
        self.include_attachments = include_attachments

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from an EML file."""
        self.validate_file(file_path)
        with open(Path(file_path), "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)

        headers = self._extract_headers(msg)
        plain_part = msg.get_body(preferencelist=("plain",))
        html_part = msg.get_body(preferencelist=("html",))
        body_parts = {id(p) for p in (plain_part, html_part) if p is not None}
        inline_images, attachments = self._other_parts(msg, body_parts)

        body_text = self._part_text(plain_part) if plain_part is not None else None
        body_html = self._part_text(html_part) if html_part is not None else None
        images: list[dict[str, Any]] = []
        if body_text and body_text.strip():
            body, source = body_text, "plain"
        elif body_html and body_html.strip():
            body, images = html_body_to_markdown(body_html, inline_images)
            source = "html"
        else:
            body, source = "", "none"

        listed = attachments if self.include_attachments else []
        formatted_text = render_email(headers, body, listed, self.include_headers)

        metadata = self._get_basic_metadata(file_path)
        metadata.update(
            {
                "format": "email",
                "email_format": "eml",
                "from": headers.get("from"),
                "to": headers.get("to"),
                "cc": headers.get("cc"),
                "subject": headers.get("subject"),
                "date": headers.get("date"),
                "message_id": headers.get("message-id"),
                "has_attachments": len(attachments) > 0,
                "attachment_count": len(attachments),
                "attachments": attachments,
                "has_html": body_html is not None,
                "has_plain_text": body_text is not None,
                "body_source": source,
            }
        )

        return RawDocument(
            text=formatted_text,
            metadata=metadata,
            structure={
                "type": "email",
                "headers": headers,
                "attachments": attachments,
                "content_types": {"has_plain": body_text is not None, "has_html": body_html is not None},
                "images": images,
            },
        )

    def _extract_headers(self, msg: EmailMessage) -> dict[str, str]:
        """Common email headers as strings."""
        headers = {}
        for name in ("from", "to", "cc", "bcc", "subject", "date", "message-id", "reply-to"):
            value = msg.get(name)
            if value:
                headers[name] = str(value)
        return headers

    @staticmethod
    def _part_text(part: MIMEPart) -> str:
        """Decoded text of a body part, surviving unknown or wrong charsets."""
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError, KeyError) as e:
            logger.warning(f"Email part charset could not be used ({e}); detecting encoding")
            payload = part.get_payload(decode=True) or b""
            return decode_bytes(payload)[0] if isinstance(payload, bytes) else str(payload)
        if isinstance(content, bytes):
            return decode_bytes(content)[0]
        return str(content)

    @staticmethod
    def _other_parts(
        msg: EmailMessage, body_parts: set[int]
    ) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
        """Inline images (by Content-ID/location/filename) and listed attachments."""
        inline: dict[str, bytes] = {}
        attachments: list[dict[str, Any]] = []
        for part in msg.walk():
            if part.is_multipart() or id(part) in body_parts:
                continue
            disposition = part.get_content_disposition()
            filename = part.get_filename()
            content_type = part.get_content_type()
            content_id = (part.get("Content-ID") or "").strip().strip("<>")
            if content_type == "message/rfc822":
                payload = part.get_payload()
                inner = payload[0] if isinstance(payload, list) and payload else payload
                size = len(inner.as_bytes()) if hasattr(inner, "as_bytes") else 0
                attachments.append(
                    {"filename": filename or "attached message.eml", "content_type": content_type, "size": size}
                )
                continue
            data = part.get_payload(decode=True)
            data = data if isinstance(data, bytes) else b""
            if part.get_content_maintype() == "image" and disposition != "attachment" and (content_id or not filename):
                for key in (content_id, part.get("Content-Location") or "", filename or ""):
                    if key:
                        inline[key] = data
                continue
            if disposition in ("attachment", "inline") or filename:
                attachments.append(
                    {"filename": filename or "unnamed_attachment", "content_type": content_type, "size": len(data)}
                )
        return inline, attachments


class MSGExtractor(BaseExtractor):
    """
    Extractor for Outlook .msg email files.

    Requires extract-msg library.
    """

    SUPPORTED_EXTENSIONS = [".msg"]

    def __init__(self, include_headers: bool = True, include_attachments: bool = True):
        """
        Initialize MSG extractor.

        Args:
            include_headers: Include email headers in output
            include_attachments: List attachments in output
        """
        if not MSG_AVAILABLE:
            raise ImportError("extract-msg is required for MSG extraction. Install with: pip install extract-msg")
        self.include_headers = include_headers
        self.include_attachments = include_attachments

    def extract(self, file_path: str) -> RawDocument:
        """Extract content from an MSG file."""
        self.validate_file(file_path)
        msg = extract_msg.Message(file_path)
        try:
            headers = {
                "from": msg.sender or "",
                "to": msg.to or "",
                "cc": msg.cc or "",
                "subject": msg.subject or "",
                "date": str(msg.date) if msg.date else "",
                "message-id": msg.messageId or "",
            }
            body_text = msg.body or ""
            body_html = msg.htmlBody or ""
            if isinstance(body_html, bytes):
                body_html = decode_bytes(body_html)[0]

            inline: dict[str, bytes] = {}
            attachments: list[dict[str, Any]] = []
            for att in msg.attachments:
                data = att.data if isinstance(att.data, bytes) else b""
                name = att.longFilename or att.shortFilename or "unnamed"
                mime = att.mimetype or "application/octet-stream"
                cid = (getattr(att, "cid", None) or getattr(att, "contentId", None) or "").strip("<>")
                if cid and mime.startswith("image/"):
                    inline[cid] = data
                    continue
                attachments.append({"filename": name, "size": len(data), "content_type": mime})

            images: list[dict[str, Any]] = []
            if body_text.strip():
                body, source = body_text, "plain"
            elif body_html.strip():
                body, images = html_body_to_markdown(body_html, inline)
                source = "html"
            else:
                body, source = "", "none"

            listed = attachments if self.include_attachments else []
            formatted_text = render_email(headers, body, listed, self.include_headers)

            metadata = self._get_basic_metadata(file_path)
            metadata.update(
                {
                    "format": "email",
                    "email_format": "msg",
                    "from": headers.get("from"),
                    "to": headers.get("to"),
                    "cc": headers.get("cc"),
                    "subject": headers.get("subject"),
                    "date": headers.get("date"),
                    "message_id": headers.get("message-id"),
                    "has_attachments": len(attachments) > 0,
                    "attachment_count": len(attachments),
                    "attachments": attachments,
                    "has_html": bool(body_html),
                    "has_plain_text": bool(body_text),
                    "body_source": source,
                }
            )
            return RawDocument(
                text=formatted_text,
                metadata=metadata,
                structure={
                    "type": "email",
                    "headers": headers,
                    "attachments": attachments,
                    "content_types": {"has_plain": bool(body_text), "has_html": bool(body_html)},
                    "images": images,
                },
            )
        finally:
            msg.close()
