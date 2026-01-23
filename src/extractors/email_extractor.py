"""
Extractors for email formats: EML and MSG.

Handles standard .eml files (RFC 822) and Outlook .msg files.
"""
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from ..models.document import RawDocument
from .base import BaseExtractor

# Optional import for MSG files
try:
    import extract_msg
    MSG_AVAILABLE = True
except ImportError:
    extract_msg = None
    MSG_AVAILABLE = False


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
        """Extract content from EML file."""
        self.validate_file(file_path)

        path = Path(file_path)

        # Parse email
        with open(path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)

        # Extract headers
        headers = self._extract_headers(msg)

        # Extract body
        body_text, body_html = self._extract_body(msg)

        # Extract attachment info
        attachments = self._extract_attachments(msg) if self.include_attachments else []

        # Build formatted output
        text_parts = []

        if self.include_headers:
            text_parts.append("## Email Headers\n")
            text_parts.append(f"**From:** {headers.get('from', 'N/A')}")
            text_parts.append(f"**To:** {headers.get('to', 'N/A')}")
            if headers.get('cc'):
                text_parts.append(f"**CC:** {headers.get('cc')}")
            text_parts.append(f"**Subject:** {headers.get('subject', 'N/A')}")
            text_parts.append(f"**Date:** {headers.get('date', 'N/A')}")
            text_parts.append("")

        text_parts.append("## Email Body\n")
        if body_text:
            text_parts.append(body_text)
        elif body_html:
            # If only HTML, note that
            text_parts.append("*[HTML content - plain text not available]*\n")
            text_parts.append(body_html[:5000])  # Truncate HTML
        else:
            text_parts.append("*[No body content]*")

        if attachments:
            text_parts.append("\n## Attachments\n")
            for att in attachments:
                size_str = f" ({att['size']} bytes)" if att.get('size') else ""
                text_parts.append(f"- {att['filename']}{size_str}")

        formatted_text = "\n".join(text_parts)

        metadata = self._get_basic_metadata(file_path)
        metadata.update({
            "format": "email",
            "email_format": "eml",
            "from": headers.get('from'),
            "to": headers.get('to'),
            "cc": headers.get('cc'),
            "subject": headers.get('subject'),
            "date": headers.get('date'),
            "message_id": headers.get('message-id'),
            "has_attachments": len(attachments) > 0,
            "attachment_count": len(attachments),
            "has_html": body_html is not None,
            "has_plain_text": body_text is not None,
        })

        return RawDocument(
            text=formatted_text,
            metadata=metadata,
            structure={
                "type": "email",
                "headers": headers,
                "attachments": attachments,
                "content_types": {
                    "has_plain": body_text is not None,
                    "has_html": body_html is not None
                }
            }
        )

    def _extract_headers(self, msg) -> dict[str, str]:
        """Extract common email headers."""
        headers = {}
        header_names = ['from', 'to', 'cc', 'bcc', 'subject', 'date', 'message-id', 'reply-to']

        for name in header_names:
            value = msg.get(name)
            if value:
                headers[name] = str(value)

        return headers

    def _extract_body(self, msg) -> tuple:
        """Extract plain text and HTML body parts."""
        body_text = None
        body_html = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain" and body_text is None:
                    try:
                        body_text = part.get_content()
                    except Exception:
                        body_text = part.get_payload(decode=True)
                        if body_text:
                            body_text = body_text.decode('utf-8', errors='replace')

                elif content_type == "text/html" and body_html is None:
                    try:
                        body_html = part.get_content()
                    except Exception:
                        body_html = part.get_payload(decode=True)
                        if body_html:
                            body_html = body_html.decode('utf-8', errors='replace')
        else:
            content_type = msg.get_content_type()
            try:
                content = msg.get_content()
            except Exception:
                content = msg.get_payload(decode=True)
                if content:
                    content = content.decode('utf-8', errors='replace')

            if content_type == "text/plain":
                body_text = content
            elif content_type == "text/html":
                body_html = content

        return body_text, body_html

    def _extract_attachments(self, msg) -> list[dict[str, Any]]:
        """Extract attachment information (not content)."""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disposition:
                    filename = part.get_filename() or "unnamed_attachment"
                    content_type = part.get_content_type()
                    payload = part.get_payload(decode=True)
                    size = len(payload) if payload else 0

                    attachments.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size": size
                    })

        return attachments


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
        """Extract content from MSG file."""
        self.validate_file(file_path)

        # Parse MSG file
        msg = extract_msg.Message(file_path)

        try:
            # Extract headers
            headers = {
                'from': msg.sender or '',
                'to': msg.to or '',
                'cc': msg.cc or '',
                'subject': msg.subject or '',
                'date': str(msg.date) if msg.date else '',
                'message-id': msg.messageId or '',
            }

            # Extract body
            body_text = msg.body or ''
            body_html = msg.htmlBody or ''
            if isinstance(body_html, bytes):
                body_html = body_html.decode('utf-8', errors='replace')

            # Extract attachments
            attachments = []
            if self.include_attachments:
                for att in msg.attachments:
                    attachments.append({
                        "filename": att.longFilename or att.shortFilename or "unnamed",
                        "size": len(att.data) if att.data else 0,
                        "content_type": att.mimetype or "application/octet-stream"
                    })

            # Build formatted output
            text_parts = []

            if self.include_headers:
                text_parts.append("## Email Headers\n")
                text_parts.append(f"**From:** {headers.get('from', 'N/A')}")
                text_parts.append(f"**To:** {headers.get('to', 'N/A')}")
                if headers.get('cc'):
                    text_parts.append(f"**CC:** {headers.get('cc')}")
                text_parts.append(f"**Subject:** {headers.get('subject', 'N/A')}")
                text_parts.append(f"**Date:** {headers.get('date', 'N/A')}")
                text_parts.append("")

            text_parts.append("## Email Body\n")
            if body_text:
                text_parts.append(body_text)
            elif body_html:
                text_parts.append("*[HTML content - plain text not available]*\n")
                text_parts.append(body_html[:5000])
            else:
                text_parts.append("*[No body content]*")

            if attachments:
                text_parts.append("\n## Attachments\n")
                for att in attachments:
                    size_str = f" ({att['size']} bytes)" if att.get('size') else ""
                    text_parts.append(f"- {att['filename']}{size_str}")

            formatted_text = "\n".join(text_parts)

            metadata = self._get_basic_metadata(file_path)
            metadata.update({
                "format": "email",
                "email_format": "msg",
                "from": headers.get('from'),
                "to": headers.get('to'),
                "cc": headers.get('cc'),
                "subject": headers.get('subject'),
                "date": headers.get('date'),
                "message_id": headers.get('message-id'),
                "has_attachments": len(attachments) > 0,
                "attachment_count": len(attachments),
                "has_html": bool(body_html),
                "has_plain_text": bool(body_text),
            })

            return RawDocument(
                text=formatted_text,
                metadata=metadata,
                structure={
                    "type": "email",
                    "headers": headers,
                    "attachments": attachments,
                    "content_types": {
                        "has_plain": bool(body_text),
                        "has_html": bool(body_html)
                    }
                }
            )
        finally:
            msg.close()
