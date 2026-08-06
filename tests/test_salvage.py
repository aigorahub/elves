"""Tests for worker-output salvage previews (v2.24 B4)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import salvage as sv  # noqa: E402


class HarvestTests(unittest.TestCase):
    def test_bounded_tail_and_truncated_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_bytes(b"A" * 10_000 + b"TAILMARK")
            result = sv.harvest_tail(log, max_bytes=1024)
            self.assertTrue(result["present"])
            self.assertTrue(result["truncated"])
            self.assertEqual(result["bytes"], 1024)
            self.assertTrue(result["text"].endswith("TAILMARK"))

    def test_small_log_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_text("short output\n", encoding="utf-8")
            result = sv.harvest_tail(log)
            self.assertTrue(result["present"])
            self.assertFalse(result["truncated"])
            self.assertIn("short output", result["text"])

    def test_secret_redaction_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_text(
                "progress ok\nkey sk-fakefakefake123456 leaked\n", encoding="utf-8"
            )
            result = sv.harvest_tail(log)
            self.assertNotIn("sk-fakefakefake123456", result["text"])
            self.assertIn("[REDACTED:", result["text"])

    def test_exact_grant_redaction_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_text("token was hunter2-exact-grant\n", encoding="utf-8")
            result = sv.harvest_tail(
                log, exact_secret_values=frozenset({"hunter2-exact-grant"})
            )
            self.assertNotIn("hunter2-exact-grant", result["text"])

    def test_binary_log_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_bytes(b"\x00\xff\xfe binary noise \x80 end")
            result = sv.harvest_tail(log)
            self.assertTrue(result["present"])
            self.assertIn("end", result["text"])

    def test_missing_log_absent_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = sv.harvest_tail(Path(tmp) / "nope.log")
            self.assertFalse(result["present"])
            self.assertIn("reason", result)

    def test_max_bytes_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_bytes(b"B" * (sv.MAX_ALLOWED_BYTES + 500))
            result = sv.harvest_tail(log, max_bytes=10_000_000)
            self.assertEqual(result["bytes"], sv.MAX_ALLOWED_BYTES)


class RenderTests(unittest.TestCase):
    def test_render_marks_untrusted_never_completion_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_text("last words\n", encoding="utf-8")
            block = sv.render_block(sv.harvest_tail(log))
            self.assertIn("untrusted; never a completion report", block)
            self.assertIn("last words", block)
            self.assertIn(sv.SALVAGE_FOOTER, block)

    def test_render_empty_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            block = sv.render_block(sv.harvest_tail(Path(tmp) / "nope.log"))
            self.assertEqual(block, "")

    def test_truncated_title_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "follow.log"
            log.write_bytes(b"C" * 9000)
            block = sv.render_block(sv.harvest_tail(log, max_bytes=1024))
            self.assertIn("(truncated tail)", block)


if __name__ == "__main__":
    unittest.main()
