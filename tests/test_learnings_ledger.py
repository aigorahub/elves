"""Tests for the learnings ledger (v2.24 B2)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_retire_creates_missing_retired_section(self) -> None:
        """Hand-rolled files without ## Retired Learnings still accept retire."""
        hand_rolled = """# Project Learnings

## Repo Conventions

- [L1] [2026-08-01] A live lesson. (evidence: commit abc)

## Known Traps

- [L3] [2026-08-02] A trap. (evidence: commit def)
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), hand_rolled)
            ll.apply_edits(
                path,
                [{"action": "retire", "id": "L1", "reason": "superseded"}],
            )
            text = path.read_text()
            self.assertIn("## Retired Learnings", text)
            self.assertIn("-> retired because superseded", text)
            self.assertNotIn(
                "- [L1] [2026-08-01] A live lesson. (evidence: commit abc)\n",
                text.split("## Retired Learnings")[0],
            )
            # Sibling managed entry untouched.
            self.assertIn("- [L3] [2026-08-02] A trap. (evidence: commit def)", text)


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


class LedgerDigestPlacementTests(unittest.TestCase):
    def test_digest_without_separator_lands_before_first_section(self) -> None:
        # aigorahub/elves#249 item 2: no `---` in the file — digest goes after
        # the intro block, before the first `##` section, not at EOF.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.md"
            path.write_text(
                "# Project Learnings\n\nIntro prose.\n\n"
                "## Repo Conventions\n\n- [L1] entry (evidence: e)\n",
                encoding="utf-8",
            )
            ll.regenerate_digest_file(path)
            text = path.read_text()
            self.assertLess(text.index(ll.DIGEST_BEGIN), text.index("## Repo Conventions"))
            self.assertIn("- [L1] entry", text)


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

    def test_record_ids_unique_within_same_millisecond(self) -> None:
        # v2.24 B8 regression: consecutive applies in one millisecond must not
        # share a record_id, or rollback provenance dedup conflates the edits
        # (manifested as [learnings_history_empty] on the second rollback).
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), SAMPLE)
            with mock.patch("cobbler_runtime.learnings_ledger.time.time", return_value=1_000_000.0):
                ll.apply_edits(
                    path,
                    [{"action": "update", "id": "L1", "text": "one", "reason": "r"}],
                )
                ll.apply_edits(
                    path,
                    [{"action": "update", "id": "L1", "text": "two", "reason": "r"}],
                )
                ll.rollback_last(path)
                ll.rollback_last(path)
            rows = [
                json.loads(line)
                for line in ll.history_path(path).read_text().splitlines()
            ]
            ids = [row["record_id"] for row in rows]
            self.assertEqual(len(ids), len(set(ids)), ids)
            self.assertIn("[2026-08-01]", path.read_text())

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


MID_SECTION = """# Project Learnings

---

## Digest

<!-- elves:learnings-digest:begin -->
<!-- elves:learnings-digest:end -->

## Repo Conventions

- [L1] [2026-08-01] First entry. (evidence: a)
- [L2] [2026-08-02] Middle entry. (evidence: b)
- [L3] [2026-08-03] Last entry. (evidence: c)

## Retired Learnings
"""


class LedgerPositionalRollbackTests(unittest.TestCase):
    """Adversarial-review BLOCKING-1: byte-identity must hold mid-section."""

    def test_mid_section_update_rollback_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), MID_SECTION)
            ll.regenerate_digest_file(path)
            baseline = path.read_bytes()
            ll.apply_edits(
                path,
                [{"action": "update", "id": "L2", "text": "[2026-08-02] Edited middle.", "reason": "r"}],
            )
            ll.rollback_last(path)
            self.assertEqual(path.read_bytes(), baseline)

    def test_mid_section_retire_rollback_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), MID_SECTION)
            ll.regenerate_digest_file(path)
            baseline = path.read_bytes()
            ll.apply_edits(
                path,
                [{"action": "retire", "id": "L2", "reason": "mid retire"}],
            )
            ll.rollback_last(path)
            self.assertEqual(path.read_bytes(), baseline)


class LedgerDriftGuardTests(unittest.TestCase):
    """Round-3 review W1: positional restore must not drift across sections."""

    def test_digest_block_insertion_between_apply_and_rollback(self) -> None:
        # Pure ledger-verb sequence: apply on a digest-less file, then the
        # digest verb inserts its 5-line block near the top, then rollback.
        # The recorded body coordinate now points above/elsewhere — the guard
        # must fall back to section placement, never mis-section the entry.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.md"
            path.write_text(
                "# Project Learnings\n\n## Alpha Notes\n\n- [L1] alpha (evidence: a)\n\n"
                "## Repo Conventions\n\n- [L2] first (evidence: b)\n- [L3] second (evidence: c)\n\n"
                "## Retired Learnings\n",
                encoding="utf-8",
            )
            ll.apply_edits(
                path,
                [{"action": "update", "id": "L3", "text": "edited", "reason": "r"}],
            )
            ll.regenerate_digest_file(path)
            ll.rollback_last(path)
            doc = ll.parse_text(path.read_text())
            self.assertEqual(doc.entries[3].section, "Repo Conventions")
            self.assertFalse(doc.entries[3].retired)
            self.assertIn("second", doc.entries[3].text)

    def test_freehand_lines_above_cannot_retire_restored_entry(self) -> None:
        # Freehand insertions above the entry's section between apply and
        # rollback previously shifted the restore into the PREVIOUS section —
        # catastrophically, a Retired section directly above silently retired
        # an active learning. The guard must keep it active in its section.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.md"
            path.write_text(
                "# Project Learnings\n\n## Retired Learnings\n\n"
                "- [L9] old -> retired because done\n\n"
                "## Repo Conventions\n\n- [L1] keep me (evidence: a)\n",
                encoding="utf-8",
            )
            ll.apply_edits(
                path,
                [{"action": "update", "id": "L1", "text": "keep me edited", "reason": "r"}],
            )
            text = path.read_text()
            path.write_text(
                text.replace(
                    "## Retired Learnings",
                    "Freehand context line one.\nFreehand context line two.\n\n## Retired Learnings",
                ),
                encoding="utf-8",
            )
            ll.rollback_last(path)
            doc = ll.parse_text(path.read_text())
            self.assertEqual(doc.entries[1].section, "Repo Conventions")
            self.assertFalse(doc.entries[1].retired)
            self.assertIn("keep me", doc.entries[1].text)


class LedgerCapBoundaryTests(unittest.TestCase):
    """Adversarial-review WARNING-1: refuse-don't-destroy exact at the caps."""

    def _fill_history(self, path: Path, rows: int) -> None:
        hist = ll.history_path(path)
        body = "".join(
            json.dumps({"record_id": f"pre{i}", "action": "update"}) + "\n"
            for i in range(rows)
        )
        hist.write_text(body, encoding="utf-8")

    def test_batch_over_cap_refuses_with_no_phantom_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), MID_SECTION)
            self._fill_history(path, ll.HISTORY_MAX_RECORDS - 1)
            before_file = path.read_bytes()
            edits = [
                {"action": "update", "id": "L1", "text": "x1", "reason": "r"},
                {"action": "update", "id": "L2", "text": "x2", "reason": "r"},
            ]
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(path, edits)
            self.assertEqual(ctx.exception.code, "learnings_history_full")
            self.assertEqual(path.read_bytes(), before_file)
            rows = ll.history_path(path).read_text().splitlines()
            self.assertEqual(len(rows), ll.HISTORY_MAX_RECORDS - 1)

    def test_rollback_at_cap_refuses_without_rewriting_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), MID_SECTION)
            ll.apply_edits(
                path,
                [{"action": "update", "id": "L1", "text": "changed", "reason": "r"}],
            )
            after_apply = path.read_bytes()
            hist = ll.history_path(path)
            existing = hist.read_text()
            filler = "".join(
                json.dumps({"record_id": f"fill{i}", "action": "update"}) + "\n"
                for i in range(ll.HISTORY_MAX_RECORDS - 1)
            )
            hist.write_text(filler + existing, encoding="utf-8")
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.rollback_last(path)
            self.assertEqual(ctx.exception.code, "learnings_history_full")
            self.assertEqual(path.read_bytes(), after_apply)


class LedgerContentionTests(unittest.TestCase):
    """B2-A5: real cross-process flock contention on the history append."""

    def test_concurrent_process_applies_keep_history_coherent(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), MID_SECTION)
            script = (
                "import sys; sys.path.insert(0, sys.argv[3]);"
                "from pathlib import Path;"
                "from cobbler_runtime import learnings_ledger as ll;"
                "ll.apply_edits(Path(sys.argv[1]),"
                "[{'action':'create','category':'Repo Conventions',"
                "'text':'from '+sys.argv[2],'evidence':'e'+sys.argv[2],"
                "'reason':'r'}])"
            )
            procs = [
                sp.Popen(
                    [sys.executable, "-c", script, str(path), tag, str(SCRIPTS)],
                    stdin=sp.DEVNULL,
                    stdout=sp.PIPE,
                    stderr=sp.PIPE,
                )
                for tag in ("alpha", "beta")
            ]
            for proc in procs:
                _, err = proc.communicate(timeout=60)
                self.assertEqual(proc.returncode, 0, err.decode())
            text = path.read_text()
            self.assertIn("from alpha", text)
            self.assertIn("from beta", text)
            rows = [
                json.loads(line)
                for line in ll.history_path(path).read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["record_id"] for row in rows}), 2)
            ll.validate_file(path)


if __name__ == "__main__":
    unittest.main()


class LedgerDigestInteriorSectionTests(unittest.TestCase):
    """aigorahub/elves#249: generated digest interiors are not real sections."""

    def test_section_at_ignores_headings_inside_the_digest_block(self) -> None:
        lines = [
            "# Project Learnings",
            "",
            "## Repo Conventions",
            "",
            ll.DIGEST_BEGIN,
            "## Retired Learnings",
            ll.DIGEST_END,
            "",
            "- [L1] entry (evidence: a)",
        ]
        self.assertEqual(ll._section_at(lines, len(lines) - 1), "Repo Conventions")
        # A real heading after the block still wins.
        lines.insert(7, "## Known Traps")
        self.assertEqual(ll._section_at(lines, len(lines) - 1), "Known Traps")

    def test_in_digest_heading_cannot_retire_a_restored_entry(self) -> None:
        # The drift guard trusts a positional restore only when the candidate still
        # lands in the recorded section. An out-of-contract heading written inside
        # the generated digest markers used to satisfy that check while the entry
        # actually landed under Retired Learnings — silently retiring it.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.md"
            path.write_text(
                "# Project Learnings\n\n> Intro blockquote kept verbatim.\n\n"
                "## Repo Conventions\n\n- [L1] keep me (evidence: a)\n\n"
                "## Retired Learnings\n\n- [L9] old -> retired because done\n",
                encoding="utf-8",
            )
            ll.apply_edits(
                path,
                [{"action": "update", "id": "L1", "text": "keep me edited", "reason": "r"}],
            )
            # Cooperating drift: the recorded body coordinate now lands under
            # Retired Learnings, immediately below a forged in-digest heading
            # naming the entry's recorded section.
            path.write_text(
                "# Project Learnings\n\n## Retired Learnings\n\n"
                f"{ll.DIGEST_BEGIN}\n## Repo Conventions\n{ll.DIGEST_END}\n\n"
                "- [L9] old -> retired because done\n\n"
                "## Repo Conventions\n\n- [L1] keep me edited\n",
                encoding="utf-8",
            )
            ll.rollback_last(path)
            doc = ll.parse_text(path.read_text(encoding="utf-8"))
            restored = doc.entries[1]
            self.assertEqual(restored.section, "Repo Conventions")
            self.assertFalse(restored.retired, path.read_text(encoding="utf-8"))


class LedgerDigestMarkerValidationTests(unittest.TestCase):
    """aigorahub/elves#262: refuse nested or unterminated digest markers."""

    def test_parse_accepts_no_markers_or_one_ordered_pair(self) -> None:
        ll.parse_text("# Project Learnings\n\n## Repo Conventions\n\n- [L1] x (evidence: a)\n")
        ll.parse_text(SAMPLE)

    def test_parse_refuses_unterminated_and_nested_markers(self) -> None:
        unterminated = (
            "# Project Learnings\n\n## Repo Conventions\n\n"
            f"{ll.DIGEST_BEGIN}\n- [L1] x (evidence: a)\n"
        )
        nested = (
            "# Project Learnings\n\n"
            f"{ll.DIGEST_BEGIN}\n{ll.DIGEST_BEGIN}\n{ll.DIGEST_END}\n\n"
            "## Repo Conventions\n\n- [L1] x (evidence: a)\n"
        )
        reversed_pair = (
            "# Project Learnings\n\n"
            f"{ll.DIGEST_END}\n{ll.DIGEST_BEGIN}\n\n"
            "## Repo Conventions\n\n- [L1] x (evidence: a)\n"
        )
        for text in (unterminated, nested, reversed_pair):
            with self.subTest(text=text[:40]):
                with self.assertRaises(ll.LedgerError) as ctx:
                    ll.parse_text(text)
                self.assertEqual(ctx.exception.code, "learnings_digest_markers_invalid")

    def test_unterminated_markers_refuse_create_before_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learnings.md"
            path.write_text(
                "# Project Learnings\n\n## Repo Conventions\n\n"
                f"{ll.DIGEST_BEGIN}\n- [L1] existing (evidence: a)\n",
                encoding="utf-8",
            )
            before = path.read_bytes()
            with self.assertRaises(ll.LedgerError) as ctx:
                ll.apply_edits(
                    path,
                    [
                        {
                            "action": "create",
                            "category": "Repo Conventions",
                            "text": "new lesson",
                            "evidence": "commit abc",
                            "reason": "r",
                        }
                    ],
                )
            self.assertEqual(ctx.exception.code, "learnings_digest_markers_invalid")
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(ll.history_path(path).exists())
