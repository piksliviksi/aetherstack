import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aether-hub"))

import pytest
from pypdf import PdfWriter

from attachments import (
    AttachmentError,
    MAX_ATTACHMENT_BYTES,
    build_image_content_part,
    decode_attachment,
    extract_pdf_text,
)


def _make_pdf_bytes(text: str | None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if text:
        # pypdf's writer has no text-drawing API; a blank page has no
        # extractable text either way, which also covers the "scanned PDF"
        # (no text layer) case used below.
        pass
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_decode_attachment_roundtrip():
    raw = b"hello world"
    encoded = base64.b64encode(raw).decode("ascii")
    assert decode_attachment({"name": "a.txt", "data": encoded}) == raw


def test_decode_attachment_rejects_invalid_base64():
    with pytest.raises(AttachmentError):
        decode_attachment({"name": "a.txt", "data": "not base64!!"})


def test_decode_attachment_rejects_oversize():
    encoded = base64.b64encode(b"x" * (MAX_ATTACHMENT_BYTES + 1)).decode("ascii")
    with pytest.raises(AttachmentError):
        decode_attachment({"name": "big.bin", "data": encoded})


def test_extract_pdf_text_returns_empty_for_blank_page():
    data = _make_pdf_bytes(None)
    assert extract_pdf_text(data) == ""


def test_extract_pdf_text_rejects_malformed_pdf():
    with pytest.raises(AttachmentError):
        extract_pdf_text(b"not a real pdf")


def test_build_image_content_part_shape():
    part = build_image_content_part(b"\x89PNG...", "image/png")
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
