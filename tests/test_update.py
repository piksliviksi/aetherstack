from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


HUB = Path(__file__).resolve().parents[1] / "aether-hub"
sys.path.insert(0, str(HUB))

import update  # noqa: E402


class UpdateSafetyTests(unittest.TestCase):
    def test_semantic_version_comparison_input_is_bounded(self) -> None:
        self.assertEqual(update._version_tuple("v0.3.1\n"), (0, 3, 1))
        self.assertGreater(update._version_tuple("0.4.0"), update._version_tuple("0.3.9"))
        self.assertEqual(update._version_tuple("development"), ())

    def test_staging_writes_archive_and_checksum_without_applying(self) -> None:
        class Response:
            def __init__(self, data: bytes):
                self.data = data
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size: int = -1) -> bytes:
                if size < 0:
                    size = len(self.data) - self.offset
                value = self.data[self.offset : self.offset + size]
                self.offset += len(value)
                return value

        old_urlopen = update.urllib.request.urlopen
        old_dir = update.UPDATE_DIR
        archive = b"PK\x03\x04safe-test-archive"

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url == update.API_URL:
                return Response(b'{"sha":"abcdef1234567890","commit":{"committer":{"date":"2026-01-01"},"message":"test"}}')
            if url == update.VERSION_URL:
                return Response(b"0.3.1\n")
            if url == update.ARCHIVE_URL:
                return Response(archive)
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as td:
            try:
                update.urllib.request.urlopen = fake_urlopen
                update.UPDATE_DIR = Path(td)
                result = update.stage_update()
                self.assertTrue(result["ok"])
                self.assertFalse(result["manifest"]["applied"])
                self.assertEqual(result["manifest"]["bytes"], len(archive))
                self.assertEqual(Path(result["path"]).read_bytes(), archive)
                self.assertTrue((Path(td) / "aetherstack-main-abcdef123456.json").exists())
            finally:
                update.urllib.request.urlopen = old_urlopen
                update.UPDATE_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
