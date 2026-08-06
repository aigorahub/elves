"""Tests for the learnings ledger (v2.24 B2)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import learnings_ledger as ll  # noqa: E402

SAMPLE = """# Project Learnings

> Intro blockquote kept verbatim.

---

## Digest

<!-- elves:learnings-digest:begin -->
<!-- elves:learnings-digest:end -->

## Repo Conventions

- [L1] [2026-08-01] Use the atomic-replace idiom for state files. (evidence: commit abc)

## Known Traps

- [2026-07-16] Never read suite verdicts through a pipe.

## Retired Learnings

- [L2] [2026-07-01] Old lesson. -> retired because superseded.
"""

LEGACY = """# Project Learnings

---

## Repo Conventions

- [2026-07-29] Freehand lesson without ids.

## Retired Learnings
"""


def _write(tmp: Path, text: str) -> Path:
    path = tmp / "learnings.md"
    path.write_text(text, encoding="utf-8")
    return path


class LedgerParseValidateTests(unittest.TestCase):
    def test_validate_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            report = ll.validate_file(path)
            self.assertTrue(report["parse_ok"])
            self.assertEqual(report["managed_count"], 2)
            self.assertEqual(report["retired_count"], 1)
            self.assertEqual(report["freehand_count"], 1)
            self.assertFalse(report["legacy_mode"])

    def test_duplicate_ids_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = SAMPLE + "\n- [L1] duplicate\n"
            path = _write(Path(tmp), broken)
            before = path.read_bytes()
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(
                    path,
                    [{"action": "update", "id": "L1", "text": "x", "reason": "r"}],
                )
            self.assertEqual(ctx.exception.code, "learnings_duplicate_id")
            self.assertEqual(path.read_bytes(), before)


class LedgerApplyRollbackTests(unittest.TestCase):
    def test_round_trip_restores_byte_identical_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            ll.regenerate_digest_file(path)
            baseline = path.read_bytes()
            ll.apply_edits(
                path,
                [
                    {
                        "action": "create",
                        "category": "Known Traps",
                        "text": "New trap lesson.",
                        "evidence": "execution-log B2",
                        "expect": "fewer trap repeats",
                        "reason": "recurring",
                    }
                ],
                run_id="test-run",
            )
            self.assertNotEqual(path.read_bytes(), baseline)
            result = ll.rollback_last(path, run_id="test-run")
            self.assertEqual(result["id"], "L3")
            self.assertEqual(path.read_bytes(), baseline)
            rows = [
                json.loads(line)
                for line in ll.history_path(path).read_text().splitlines()
            ]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["rollback_of"], rows[0]["record_id"])
            self.assertIsNone(rows[0]["before"])
            self.assertIn("New trap lesson.", rows[0]["after"]["line"])

    def test_update_and_retire_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            ll.regenerate_digest_file(path)
            baseline = path.read_bytes()
            ll.apply_edits(
                path,
                [{"action": "update", "id": "L1", "text": "[2026-08-01] Refined text.", "reason": "clearer"}],
            )
            self.assertIn("Refined text.", path.read_text())
            ll.rollback_last(path)
            self.assertEqual(path.read_bytes(), baseline)

            ll.apply_edits(
                path,
                [{"action": "retire", "id": "L1", "reason": "obsolete"}],
            )
            text = path.read_text()
            self.assertIn("-> retired because obsolete", text)
            ll.rollback_last(path)
            self.assertEqual(path.read_bytes(), baseline)

    def test_freehand_content_byte_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            ll.apply_edits(
                path,
                [
                    {
                        "action": "create",
                        "category": "Repo Conventions",
                        "text": "Another convention.",
                        "evidence": "commit def",
                        "reason": "new",
                    }
                ],
            )
            text = path.read_text()
            self.assertIn("- [2026-07-16] Never read suite verdicts through a pipe.", text)
            self.assertIn("> Intro blockquote kept verbatim.", text)

    def test_evidence_required_on_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(
                    path,
                    [
                        {
                            "action": "create",
                            "category": "Known Traps",
                            "text": "No evidence.",
                            "reason": "r",
                        }
                    ],
                )
            self.assertEqual(ctx.exception.code, "learnings_evidence_required")


class LedgerDigestTests(unittest.TestCase):
    def test_digest_bounded_and_marker_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            body = SAMPLE
            path = _write(Path(tmp), body)
            edits = [
                {
                    "action": "create",
                    "category": "Repo Conventions",
                    "text": "Lesson " + ("x" * 200),
                    "evidence": f"commit {n}",
                    "reason": "n",
                }
                for n in range(45)
            ]
            ll.apply_edits(path, edits)
            text = path.read_text()
            begin = text.index(ll.DIGEST_BEGIN)
            end = text.index(ll.DIGEST_END)
            digest = text[begin:end].splitlines()[1:]
            content_lines = [line for line in digest if line.startswith("- ")]
            self.assertLessEqual(len(content_lines), ll.DIGEST_MAX_ENTRIES + 1)
            for line in content_lines[:-1]:
                self.assertLessEqual(len(line), ll.DIGEST_MAX_LINE_CHARS)
            self.assertIn("more active learnings", content_lines[-1])

    def test_digest_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            ll.regenerate_digest_file(path)
            first = path.read_bytes()
            ll.regenerate_digest_file(path)
            self.assertEqual(path.read_bytes(), first)


class LedgerLegacyTests(unittest.TestCase):
    def test_legacy_validate_ok_and_edits_refuse_with_migrate_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), LEGACY)
            report = ll.validate_file(path)
            self.assertTrue(report["legacy_mode"])
            before = path.read_bytes()
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(
                    path,
                    [{"action": "update", "id": "L1", "text": "x", "reason": "r"}],
                )
            self.assertEqual(ctx.exception.code, "learnings_legacy_mode")
            self.assertIn("migrate", ctx.exception.message)
            self.assertEqual(path.read_bytes(), before)

    def test_migrate_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), LEGACY)
            first = ll.migrate_file(path)
            self.assertEqual(first["assigned"], 1)
            self.assertIn("- [L1] [2026-07-29] Freehand lesson without ids.", path.read_text())
            second = ll.migrate_file(path)
            self.assertEqual(second["assigned"], 0)


class LedgerSafetyTests(unittest.TestCase):
    def test_stale_reference_refuses_after_concurrent_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            # Simulate a concurrent freehand edit that removed L1 between the
            # caller reading the file and calling apply: apply re-parses under
            # the lock, so the stale id refuses cleanly.
            path.write_text(path.read_text().replace(
                "- [L1] [2026-08-01] Use the atomic-replace idiom for state files. (evidence: commit abc)\n",
                "",
            ), encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(
                    path,
                    [{"action": "update", "id": "L1", "text": "x", "reason": "r"}],
                )
            self.assertEqual(ctx.exception.code, "learnings_unknown_id")
            self.assertEqual(path.read_bytes(), before)

    def test_history_cap_refuses_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            hist = ll.history_path(path)
            rows = "\n".join(
                json.dumps({"record_id": f"r{i}", "action": "update"})
                for i in range(ll.HISTORY_MAX_RECORDS)
            )
            hist.write_text(rows + "\n", encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(
                    path,
                    [
                        {
                            "action": "create",
                            "category": "Known Traps",
                            "text": "over cap",
                            "evidence": "e",
                            "reason": "r",
                        }
                    ],
                )
            self.assertEqual(ctx.exception.code, "learnings_history_full")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
