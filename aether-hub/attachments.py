"""Decode, size-guard, and extract content from chat-composer attachments."""
from __future__ import annotations

import base64
import binascii
import io
from typing import Any

import pypdf

MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


class AttachmentError(ValueError):
    """Raised for any malformed or oversize attachment; server.py already
    maps ValueError to HTTP 400 for the /run route, so no new error
    handling is needed at the call site."""


def decode_attachment(attachment: dict[str, Any]) -> bytes:
    name = attachment.get("name") or "attachment"
    data = attachment.get("data") or ""
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentError(f"invalid base64 for attachment {name!r}") from exc
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(f"attachment {name!r} exceeds {MAX_ATTACHMENT_BYTES} byte limit")
    return raw


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise AttachmentError(f"could not read PDF: {exc}") from exc
    return "\n\n".join(page for page in pages if page)


def build_image_content_part(data: bytes, mime: str) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
