from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "elves_landing_check.py"
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.delegated_git import parse_plan_acceptance  # noqa: E402


def load_module():
    spec = importlib.util.spec_from_file_location("elves_landing_check_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load elves_landing_check module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ElvesLandingCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_module()

    def _write_session(self, tmp: Path, payload: dict) -> Path:
        path = tmp / ".elves-session.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def test_complete_with_acceptance_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "name": "Extract facade",
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "gemini-service.ts under 400 LOC",
                                "met": True,
                                "evidence": "wc -l src/gemini-service.ts => 312",
                            }
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Extract facade\n\n"
                "**Acceptance criteria:**\n"
                "- [x] gemini-service.ts under 400 LOC\n",
                encoding="utf-8",
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 0)

    def test_complete_without_acceptance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {"id": 1, "name": "Almost", "status": "complete"},
                ]
            }
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_acceptance_met_false_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 2,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "facade exists",
                                "met": False,
                                "evidence": "still TODO",
                            }
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_null_criterion_treated_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 4,
                        "status": "complete",
                        "acceptance": [
                            {"criterion": None, "met": True, "evidence": "sha"}
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_batch_heading_accepts_bracketed_numbers(self) -> None:
        text = "## Batch [3] Contract: 2026-07-08\n\n**Validate:**\n"
        matches = list(self.mod.BATCH_HEADING.finditer(text))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].group(1), "3")

    def test_batch_ids_accept_canonical_and_legacy_nonnegative_integers(self) -> None:
        for raw, expected in (
            ("B0", 0),
            (0, 0),
            ("0", 0),
            ("B1", 1),
            ("B42", 42),
            (1, 1),
            (42, 42),
            ("1", 1),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.mod.numeric_batch_id({"id": raw}), expected)

    def test_batch_ids_reject_malformed_or_ambiguous_forms(self) -> None:
        invalid = (
            None,
            True,
            False,
            -1,
            1.0,
            "",
            "00",
            "01",
            "B00",
            "B01",
            "b1",
            " B1",
            "B1 ",
            "B-1",
            "B1x",
            "B1١",
            "+1",
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertIsNone(self.mod.numeric_batch_id({"id": raw}))

    def test_canonical_batch_ids_map_exactly_to_plan_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B1",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "First contract",
                                "met": True,
                                "evidence": "first proof",
                            }
                        ],
                    },
                    {
                        "id": "B2",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B2-A1",
                                "criterion": "Second contract",
                                "met": True,
                                "evidence": "second proof",
                            }
                        ],
                    },
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Master contract",
                        "met": True,
                        "evidence": "cumulative proof",
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: First\n\n**Acceptance criteria:**\n"
                "- [x] B1-A1 — First contract\n\n"
                "### Batch 2: Second\n\n**Acceptance criteria:**\n"
                "- [x] B2-A1 — Second contract\n\n"
                "## Master Acceptance\n\n- [x] M-A1 — Master contract\n",
                encoding="utf-8",
            )

            self.assertEqual(self.mod.main(["--session", str(session_path)]), 0)

    def test_batch_zero_maps_exactly_to_plan_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": "Staging contract",
                                "met": True,
                                "evidence": "staging proof",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Master contract",
                        "met": True,
                        "evidence": "cumulative proof",
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n"
                "- [x] B0-A1: Staging contract\n\n"
                "## Master Acceptance\n\n- [x] M-A1: Master contract\n",
                encoding="utf-8",
            )

            self.assertEqual(self.mod.main(["--session", str(session_path)]), 0)

    def test_canonical_and_legacy_alias_collision_is_duplicate_batch(self) -> None:
        for canonical, legacy in (("B0", 0), ("B1", 1)):
            with self.subTest(canonical=canonical):
                session = {
                    "batches": [
                        {
                            "id": canonical,
                            "status": "complete",
                            "acceptance": [
                                {"criterion": "first", "met": True, "evidence": "proof"}
                            ],
                        },
                        {
                            "id": legacy,
                            "status": "complete",
                            "acceptance": [
                                {"criterion": "duplicate", "met": True, "evidence": "proof"}
                            ],
                        },
                    ]
                }
                report = self.mod.Report()

                self.mod.check_session_batches(session, report)

                self.assertIn(
                    "batch_id_duplicate",
                    {finding.code for finding in report.errors},
                )

    def test_acceptance_missing_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 3,
                        "status": "complete",
                        "acceptance": [
                            {"criterion": "tests green", "met": True, "evidence": ""}
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_incomplete_batch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 1,
                        "status": "in_progress",
                        "acceptance": [
                            {
                                "criterion": "done",
                                "met": True,
                                "evidence": "sha",
                            }
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_god_file_lock_only_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 11,
                        "name": "Split god file",
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "structure already exists regex lock",
                                "met": True,
                                "evidence": "structure-only characterization tests pass",
                            }
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_plan_open_acceptance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "facade cut",
                                "met": True,
                                "evidence": "loc 200",
                            }
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Split\n\n"
                "**Acceptance criteria:**\n"
                "- [ ] gemini-service.ts under 400 LOC\n"
                "- [x] facade exists\n",
                encoding="utf-8",
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_plan_without_batch_headings_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"criterion": "done", "met": True, "evidence": "sha"}
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "# Plan\n\n- [x] Everything is done\n",
                encoding="utf-8",
            )

            code = self.mod.main(["--session", str(session_path)])

            self.assertEqual(code, 1)

    def test_missing_plan_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session_path = self._write_session(
                tmp,
                {
                    "batches": [
                        {
                            "id": 1,
                            "status": "complete",
                            "acceptance": [
                                {"criterion": "done", "met": True, "evidence": "sha"}
                            ],
                        }
                    ]
                },
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_batch_tasks_cannot_substitute_for_acceptance_section(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"criterion": "Edited a file", "met": True, "evidence": "sha"}
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Work\n\n**Tasks:**\n- [x] Edited a file\n",
                encoding="utf-8",
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_unrelated_legacy_evidence_cannot_satisfy_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "tests green",
                                "met": True,
                                "evidence": "unrelated test output",
                            }
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Work\n\n**Acceptance criteria:**\n"
                "- [x] Product behavior works\n",
                encoding="utf-8",
            )
            args = self.mod.parse_args(["--session", str(session_path)])
            report = self.mod.run_checks(args)
            self.assertTrue(
                any(f.code == "acceptance_criterion_missing" for f in report.errors)
            )
            self.assertTrue(
                any(f.code == "acceptance_evidence_unrelated" for f in report.errors)
            )

    def test_legacy_normalized_mapping_includes_master_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "feature works",
                                "met": True,
                                "evidence": "batch proof",
                            },
                            {
                                "criterion": "end-to-end ready",
                                "met": True,
                                "evidence": "cumulative proof",
                            },
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Work\n\n**Acceptance criteria:**\n"
                "- [x] Feature   Works\n\n"
                "## Master Acceptance\n\n"
                "- [x] End-to-end ready\n",
                encoding="utf-8",
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 0)

    def test_unchecked_legacy_master_acceptance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"criterion": "done", "met": True, "evidence": "batch"},
                            {
                                "criterion": "end-to-end ready",
                                "met": True,
                                "evidence": "claimed master",
                            },
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Work\n\n**Acceptance criteria:**\n- [x] done\n\n"
                "## Master Acceptance\n\n- [ ] end-to-end ready\n",
                encoding="utf-8",
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_unparseable_stable_acceptance_ids_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract",
                                "met": True,
                                "evidence": "sha",
                            }
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n"
                "**Acceptance criteria:**\n"
                "- [x] B1-A1 Batch contract\n",
                encoding="utf-8",
            )

            code = self.mod.main(["--session", str(session_path)])

            self.assertEqual(code, 1)

    def test_stable_ids_require_master_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract",
                                "met": True,
                                "evidence": "sha",
                            }
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n"
                "**Acceptance criteria:**\n"
                "- [x] B1-A1 — Batch contract\n",
                encoding="utf-8",
            )

            code = self.mod.main(["--session", str(session_path)])

            self.assertEqual(code, 1)

    def test_stable_ids_with_master_and_exact_evidence_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract",
                                "met": True,
                                "evidence": "batch proof",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Master contract",
                        "met": True,
                        "evidence": "cumulative proof",
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n"
                "**Acceptance criteria:**\n"
                "- [x] B1-A1 — Batch contract\n\n"
                "## Master Acceptance\n\n"
                "- [x] M-A1 — Master contract\n",
                encoding="utf-8",
            )

            code = self.mod.main(["--session", str(session_path)])

            self.assertEqual(code, 0)

    def test_legacy_batch_embedded_master_acceptance_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract",
                                "met": True,
                                "evidence": "batch proof",
                            },
                            {
                                "id": "M-A1",
                                "criterion": "Master contract",
                                "met": True,
                                "evidence": "legacy cumulative proof",
                            },
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n**Acceptance criteria:**\n"
                "- [x] B1-A1 — Batch contract\n\n"
                "## Master Acceptance\n\n- [x] M-A1 — Master contract\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )

            self.assertEqual(report.errors, [])
            self.assertIn(
                "legacy_master_acceptance_location",
                {finding.code for finding in report.warnings},
            )

    def test_duplicate_or_wrong_scope_top_level_acceptance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract",
                                "met": True,
                                "evidence": "batch proof",
                            },
                            {
                                "id": "M-A1",
                                "criterion": "Master contract",
                                "met": True,
                                "evidence": "duplicate legacy proof",
                            },
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Master contract",
                        "met": True,
                        "evidence": "canonical proof",
                    },
                    {
                        "id": "B1-A2",
                        "criterion": "Wrong scope",
                        "met": True,
                        "evidence": "wrong scope proof",
                    },
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n**Acceptance criteria:**\n"
                "- [x] B1-A1 — Batch contract\n\n"
                "## Master Acceptance\n\n- [x] M-A1 — Master contract\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            codes = {finding.code for finding in report.errors}
            self.assertIn("acceptance_id_wrong_scope", codes)
            self.assertIn("acceptance_evidence_duplicate_id", codes)
            self.assertIn("acceptance_evidence_unrelated", codes)

    def test_top_level_master_acceptance_requires_met_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"criterion": "done", "met": True, "evidence": "proof"}
                        ],
                    }
                ],
                "master_acceptance": [
                    {"id": "M-A1", "criterion": "Master", "met": False, "evidence": ""}
                ],
            }
            session_path = self._write_session(tmp, session)

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            codes = {finding.code for finding in report.errors}
            self.assertIn("master_acceptance_not_met", codes)
            self.assertIn("master_acceptance_no_evidence", codes)

    def test_delegated_and_landing_parsers_join_wrapped_criteria_identically(self) -> None:
        expected = [
            {
                "id": "B0-A1",
                "criterion": (
                    "Batch contract continues on the next line with `code` "
                    "and punctuation."
                ),
            },
            {
                "id": "M-A1",
                "criterion": "Master contract continues across a wrapped line.",
            },
        ]
        forms = {
            "bare": (
                "- [ ] B0-A1: Batch contract continues\n",
                "* [x] M-A1: Master contract continues\n",
            ),
            "bracketed": (
                "- [ ] [B0-A1] Batch contract continues\n",
                "* [x] [M-A1] Master contract continues\n",
            ),
        }

        for style, (batch_row, master_row) in forms.items():
            with self.subTest(style=style):
                plan = (
                    "### Batch 0: Contract\n\n**Acceptance criteria:**\n"
                    f"{batch_row}"
                    "  on the next line with `code` and punctuation.\n\n"
                    "## Master Acceptance\n\n"
                    f"{master_row}"
                    "  across a wrapped line.\n"
                )

                delegated = parse_plan_acceptance(plan)
                landing = [
                    {"id": item["id"], "criterion": item["criterion"]}
                    for item in self.mod._parse_stable_checkboxes(plan)
                ]

                self.assertEqual(delegated, landing)
                self.assertEqual(delegated, expected)

    def test_stable_mode_rejects_unidentified_batch_or_master_checkboxes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "First criterion",
                                "met": True,
                                "evidence": "batch proof",
                            },
                            {
                                "id": "M-A1",
                                "criterion": "Master criterion",
                                "met": True,
                                "evidence": "master proof",
                            },
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n**Acceptance criteria:**\n"
                "- [x] B1-A1 — First criterion\n"
                "- [x] Unidentified critical criterion\n\n"
                "## Master Acceptance\n\n"
                "- [x] M-A1 — Master criterion\n"
                "- [x] Unidentified master criterion\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            codes = {finding.code for finding in report.errors}
            self.assertIn("plan_acceptance_id_missing", codes)
            self.assertIn("master_acceptance_id_missing", codes)

    def test_stable_asterisk_rows_and_wrapped_criteria_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract continues on the next line",
                                "met": True,
                                "evidence": "batch proof",
                            },
                            {
                                "id": "M-A1",
                                "criterion": "Master contract",
                                "met": True,
                                "evidence": "master proof",
                            },
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n**Acceptance criteria:**\n"
                "* [x] B1-A1 — Batch contract continues\n"
                "  on the next line\n\n## Master Acceptance\n\n"
                "* [x] M-A1 — Master contract\n",
                encoding="utf-8",
            )

            self.assertEqual(self.mod.main(["--session", str(session_path)]), 0)

    def test_stable_criterion_may_reference_its_own_id_in_prose(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            criterion = "Preserve the literal B0-A1 identifier"
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": criterion,
                                "met": True,
                                "evidence": "parser regression passed",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Landing remains exact",
                        "met": True,
                        "evidence": "landing regression passed",
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n"
                f"- [x] B0-A1: {criterion}\n\n"
                "## Master Acceptance\n\n"
                "- [x] [M-A1] Landing remains exact\n",
                encoding="utf-8",
            )

            self.assertEqual(self.mod.main(["--session", str(session_path)]), 0)

    def test_leading_zero_plan_batch_heading_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": "Staging is explicit",
                                "met": True,
                                "evidence": "proof",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Ready",
                        "met": True,
                        "evidence": "proof",
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 00: Staging\n\n**Acceptance criteria:**\n"
                "- [x] B0-A1: Staging is explicit\n\n"
                "## Master Acceptance\n\n- [x] M-A1: Ready\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            self.assertIn(
                "batch_id_invalid",
                {finding.code for finding in report.errors},
            )

    def test_plan_id_must_match_actual_batch_heading_and_extra_session_batch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"id": "B2-A1", "criterion": "Wrong", "met": True, "evidence": "e"},
                            {"id": "M-A1", "criterion": "Master", "met": True, "evidence": "e"},
                        ],
                    },
                    {
                        "id": 2,
                        "status": "complete",
                        "acceptance": [
                            {"id": "B2-A2", "criterion": "Extra", "met": True, "evidence": "e"}
                        ],
                    },
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Only\n\n**Acceptance criteria:**\n"
                "- [x] B2-A1 — Wrong\n\n## Master Acceptance\n\n"
                "- [x] M-A1 — Master\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            codes = {finding.code for finding in report.errors}
            self.assertIn("plan_acceptance_wrong_batch", codes)
            self.assertIn("session_batch_missing_in_plan", codes)

    def test_fenced_and_commented_acceptance_cannot_satisfy_landing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"id": "B1-A1", "criterion": "hidden", "met": True, "evidence": "e"},
                            {"id": "M-A1", "criterion": "hidden master", "met": True, "evidence": "e"},
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: One\n\n**Acceptance criteria:**\n\n"
                "```md\n- [x] B1-A1 — hidden\n```\n\n"
                "## Master Acceptance\n\n"
                "<!--\n- [x] M-A1 — hidden master\n-->\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            codes = {finding.code for finding in report.errors}
            self.assertIn("plan_acceptance_unparseable", codes)
            self.assertIn("master_acceptance_unparseable", codes)

    def test_indented_code_acceptance_cannot_satisfy_landing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {"id": "B1-A1", "criterion": "hidden", "met": True, "evidence": "e"},
                            {"id": "M-A1", "criterion": "hidden master", "met": True, "evidence": "e"},
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: One\n\n"
                "    **Acceptance criteria:**\n"
                "    - [x] B1-A1 — hidden\n\n"
                "## Master Acceptance\n\n"
                "    - [x] M-A1 — hidden master\n",
                encoding="utf-8",
            )

            report = self.mod.run_checks(
                self.mod.parse_args(["--session", str(session_path)])
            )
            codes = {finding.code for finding in report.errors}
            self.assertIn("plan_acceptance_section_missing", codes)
            self.assertIn("master_acceptance_unparseable", codes)

    def test_strict_provenance_rejects_external_untracked_and_mismatched_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Elves Tests"], cwd=root, check=True)
            plan = root / "plan.md"
            plan.write_text(
                "### Batch 1: One\n\n**Acceptance criteria:**\n- [x] done\n",
                encoding="utf-8",
            )
            (root / "other.md").write_text(plan.read_text(encoding="utf-8"), encoding="utf-8")
            subprocess.run(["git", "add", "plan.md", "other.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "plan"], cwd=root, check=True)
            start = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()
            session = {
                "run_id": "run-1",
                "branch": "feature",
                "start_head": start,
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [{"criterion": "done", "met": True, "evidence": "proof"}],
                    }
                ],
            }
            session_path = self._write_session(root, session)
            subprocess.run(["git", "add", ".elves-session.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "session"], cwd=root, check=True)

            strict = ["--repo-root", str(root), "--session", str(session_path)]
            self.assertEqual(self.mod.main(strict), 0)
            root_link = root.parent / "repo-link"
            root_link.symlink_to(root, target_is_directory=True)
            self.assertEqual(
                self.mod.main(
                    [
                        "--repo-root",
                        str(root),
                        "--session",
                        str(root_link / ".elves-session.json"),
                    ]
                ),
                1,
            )
            self.assertEqual(self.mod.main([*strict, "--plan", "other.md"]), 1)

            outside = root.parent / "outside.md"
            outside.write_text(plan.read_text(encoding="utf-8"), encoding="utf-8")
            session["plan_path"] = str(outside)
            session_path.write_text(json.dumps(session), encoding="utf-8")
            subprocess.run(["git", "add", ".elves-session.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "external plan"], cwd=root, check=True)
            self.assertEqual(self.mod.main(strict), 1)

    def test_strict_nested_session_resolves_plan_from_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Elves Tests"], cwd=root, check=True)
            plan = root / "docs" / "plans" / "plan.md"
            plan.parent.mkdir(parents=True)
            plan.write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n"
                "- [x] B0-A1: Done\n\n"
                "## Master Acceptance\n\n- [x] M-A1: Ready\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "docs/plans/plan.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "plan"], cwd=root, check=True)
            start = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            session_path = root / ".elves" / "session.json"
            session_path.parent.mkdir(parents=True)
            session_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-nested",
                        "branch": "feature",
                        "start_head": start,
                        "plan_path": "docs/plans/plan.md",
                        "batches": [
                            {
                                "id": "B0",
                                "status": "complete",
                                "acceptance": [
                                    {
                                        "id": "B0-A1",
                                        "criterion": "Done",
                                        "met": True,
                                        "evidence": "proof",
                                    }
                                ],
                            }
                        ],
                        "master_acceptance": [
                            {
                                "id": "M-A1",
                                "criterion": "Ready",
                                "met": True,
                                "evidence": "proof",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", ".elves/session.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "session"], cwd=root, check=True)

            report = self.mod.run_checks(
                self.mod.parse_args(
                    [
                        "--repo-root",
                        str(root),
                        "--session",
                        str(session_path),
                    ]
                )
            )

            self.assertEqual(report.errors, [])

    def test_land_pr_grant_preserves_active_run_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            readiness = {
                "head": "a" * 40,
                "inputs_digest": "d" * 64,
                "acceptance_complete": True,
                "blockers_resolved": True,
                "exact_tip_review_clean": True,
                "required_checks_green": True,
                "worktree_clean": True,
            }
            session_path = self._write_session(
                tmp,
                {
                    "landing": {
                        "outcome": "landable_pr",
                        "driver_authorized": False,
                        "worker_merge_authority": False,
                        "readiness": readiness,
                    }
                },
            )

            self.assertEqual(
                self.mod.main(
                    [
                        "--session",
                        str(session_path),
                        "--grant-driver-authorization",
                        "land-pr",
                        "--json",
                    ]
                ),
                0,
            )
            updated = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["landing"]["readiness"], readiness)
            self.assertEqual(updated["landing"]["outcome"], "complete_and_merge")
            self.assertTrue(updated["landing"]["driver_authorized"])
            self.assertFalse(updated["landing"]["worker_merge_authority"])

    def test_strict_landing_attestation_is_bound_to_exact_current_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Elves Tests"], cwd=root, check=True)
            (root / "plan.md").write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n- [x] B0-A1: Done\n\n"
                "## Master Acceptance\n\n- [x] M-A1: Ready\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "plan.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "plan"], cwd=root, check=True)
            start = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()
            session = {
                "run_id": "run-authority",
                "branch": "feature",
                "start_head": start,
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {"id": "B0-A1", "criterion": "Done", "met": True, "evidence": "proof"}
                        ],
                    }
                ],
                "master_acceptance": [
                    {"id": "M-A1", "criterion": "Ready", "met": True, "evidence": "proof"}
                ],
                "landing": {
                    "outcome": "landable_pr",
                    "driver_authorized": False,
                    "worker_merge_authority": False,
                },
            }
            session_path = self._write_session(root, session)
            subprocess.run(["git", "add", ".elves-session.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "session"], cwd=root, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
            ).stdout.strip()

            args = self.mod.parse_args(
                ["--repo-root", str(root), "--session", str(session_path)]
            )
            missing_landable = self.mod.run_checks(args)
            self.assertIn(
                "readiness_missing", {item.code for item in missing_landable.errors}
            )
            self.assertFalse(missing_landable.landing["ready"])
            self.assertEqual(missing_landable.landing["action"], "landable_pr")

            session["landing"]["outcome"] = "complete_and_merge"
            session["landing"]["driver_authorized"] = True
            session_path.write_text(json.dumps(session), encoding="utf-8")
            missing_merge = self.mod.run_checks(args)
            self.assertIn(
                "readiness_missing", {item.code for item in missing_merge.errors}
            )
            self.assertFalse(missing_merge.landing["ready"])
            self.assertEqual(missing_merge.landing["action"], "hold")
            self.assertFalse(missing_merge.landing["merge"])

            session["landing"]["outcome"] = "landable_pr"
            session["landing"]["driver_authorized"] = False
            session["landing"]["readiness"] = {
                "head": head,
                "inputs_digest": "d" * 64,
                "acceptance_complete": True,
                "blockers_resolved": True,
                "exact_tip_review_clean": True,
                "required_checks_green": True,
                "worktree_clean": True,
            }
            session_path.write_text(json.dumps(session), encoding="utf-8")

            report = self.mod.run_checks(args)
            self.assertEqual(report.errors, [])
            self.assertIsNotNone(report.landing)
            self.assertTrue(report.landing["ready"])
            self.assertEqual(report.landing["action"], "landable_pr")

            self.assertEqual(
                self.mod.main(
                    [
                        "--session",
                        str(session_path),
                        "--grant-driver-authorization",
                        "land-pr",
                    ]
                ),
                0,
            )
            merge_ready = self.mod.run_checks(args)
            self.assertEqual(merge_ready.errors, [])
            self.assertEqual(merge_ready.landing["action"], "complete_and_merge")
            self.assertTrue(merge_ready.landing["merge"])

            subprocess.run(["git", "commit", "--allow-empty", "-qm", "move head"], cwd=root, check=True)
            stale = self.mod.run_checks(args)
            self.assertIn("readiness_head_changed", {item.code for item in stale.errors})

    def test_worker_landing_authority_claim_is_rejected_and_ignored(self) -> None:
        report = self.mod.Report()
        control, _ = self.mod._landing_control_from_session(
            {
                "landing": {
                    "outcome": "landable_pr",
                    "driver_authorized": False,
                    "worker_merge_authority": True,
                },
                "worker_report": {
                    "landing_outcome": "complete_and_merge",
                    "driver_authorized": True,
                    "ready": True,
                },
            },
            report,
        )
        self.assertFalse(control.driver_authorized)
        self.assertEqual(control.landing_outcome, "landable_pr")
        self.assertIn("worker_merge_authority_invalid", {item.code for item in report.errors})
        self.assertIn("worker_authority_claims_ignored", {item.code for item in report.warnings})

    def test_project_landing_profile_is_live_digest_bound_and_host_owned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Elves Tests"], cwd=root, check=True)
            (root / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

            (root / "plan.md").write_text(
                "### Batch 0: Complete\n\n**Acceptance criteria:**\n"
                "- [x] B0-A1: Profile ready\n\n"
                "## Master Acceptance\n\n- [x] M-A1: Landing ready\n",
                encoding="utf-8",
            )
            profile_path = root / ".elves" / "landing-profile.json"
            profile_path.parent.mkdir()
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checks": [
                            {
                                "id": "profile-pass",
                                "kind": "path_touched",
                                "severity": "blocking",
                                "when": {"kind": "always"},
                                "paths": ["plan.md"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            session = {
                "run_id": "project-profile-test",
                "branch": "feature",
                "start_head": base,
                "project_base_ref": base,
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": "Profile ready",
                                "met": True,
                                "evidence": "focused test",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Landing ready",
                        "met": True,
                        "evidence": "focused test",
                    }
                ],
            }
            session_path = root / ".elves-session.json"
            session_path.write_text(json.dumps(session), encoding="utf-8")
            subprocess.run(
                ["git", "add", "plan.md", ".elves/landing-profile.json", ".elves-session.json"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "commit", "-qm", "profile"], cwd=root, check=True)
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            live = self.mod.evaluate_landing_profile(root, base_ref=base)
            self.assertTrue(live.green)
            session["landing"] = {
                "outcome": "landable_pr",
                "driver_authorized": False,
                "worker_merge_authority": False,
                "readiness": {
                    "head": head,
                    "inputs_digest": "d" * 64,
                    "acceptance_complete": True,
                    "blockers_resolved": True,
                    "exact_tip_review_clean": True,
                    "required_checks_green": True,
                    "project_landing_checks_green": True,
                    "project_landing_checks_digest": live.digest,
                    "worktree_clean": True,
                },
            }
            session_path.write_text(json.dumps(session), encoding="utf-8")
            args = self.mod.parse_args(
                ["--repo-root", str(root), "--session", str(session_path)]
            )

            green = self.mod.run_checks(args)
            self.assertEqual(green.errors, [])
            self.assertTrue(green.project_landing["green"])
            self.assertTrue(green.landing["ready"])

            session["landing"]["readiness"]["project_landing_checks_digest"] = "0" * 64
            session_path.write_text(json.dumps(session), encoding="utf-8")
            stale = self.mod.run_checks(args)
            self.assertIn(
                "project_landing_digest_mismatch",
                {finding.code for finding in stale.errors},
            )
            self.assertFalse(stale.landing["ready"])

            session["worker_report"] = {
                "project_landing_checks_green": True,
                "project_landing_checks_digest": live.digest,
            }
            session_path.write_text(json.dumps(session), encoding="utf-8")
            hostile = self.mod.run_checks(args)
            self.assertIn(
                "worker_authority_claims_ignored",
                {finding.code for finding in hostile.warnings},
            )

    def test_failed_project_profile_checks_are_structured_findings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Elves Tests"], cwd=root, check=True
            )
            (root / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

            (root / "plan.md").write_text(
                "### Batch 0: Complete\n\n**Acceptance criteria:**\n"
                "- [x] B0-A1: Profile ready\n\n"
                "## Master Acceptance\n\n- [x] M-A1: Landing ready\n",
                encoding="utf-8",
            )
            profile_path = root / ".elves" / "landing-profile.json"
            profile_path.parent.mkdir()
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checks": [
                            {
                                "id": "blocking-fail",
                                "kind": "path_touched",
                                "severity": "blocking",
                                "when": {"kind": "always"},
                                "paths": ["docs/**"],
                            },
                            {
                                "id": "advisory-fail",
                                "kind": "path_touched",
                                "severity": "advisory",
                                "when": {"kind": "always"},
                                "paths": ["guide/**"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            session = {
                "run_id": "project-profile-failure-test",
                "branch": "feature",
                "start_head": base,
                "project_base_ref": base,
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": "Profile ready",
                                "met": True,
                                "evidence": "focused test",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Landing ready",
                        "met": True,
                        "evidence": "focused test",
                    }
                ],
            }
            session_path = root / ".elves-session.json"
            session_path.write_text(json.dumps(session), encoding="utf-8")
            subprocess.run(
                ["git", "add", "plan.md", ".elves/landing-profile.json", ".elves-session.json"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "commit", "-qm", "profile"], cwd=root, check=True)

            report = self.mod.run_checks(
                self.mod.parse_args(
                    ["--repo-root", str(root), "--session", str(session_path)]
                )
            )

        self.assertIn(
            "project_landing_blocking_failed", {finding.code for finding in report.errors}
        )
        self.assertIn(
            "project_landing_advisory_failed", {finding.code for finding in report.warnings}
        )

    def test_stable_batch_ids_cannot_be_swapped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B2-A1",
                                "criterion": "Criterion two",
                                "met": True,
                                "evidence": "wrong batch",
                            }
                        ],
                    },
                    {
                        "id": 2,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Criterion one",
                                "met": True,
                                "evidence": "wrong batch",
                            },
                            {
                                "id": "M-A1",
                                "criterion": "Master",
                                "met": True,
                                "evidence": "master proof",
                            },
                        ],
                    },
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: One\n\n**Acceptance criteria:**\n"
                "- [x] B1-A1 — Criterion one\n\n"
                "### Batch 2: Two\n\n**Acceptance criteria:**\n"
                "- [x] B2-A1 — Criterion two\n\n"
                "## Master Acceptance\n\n- [x] M-A1 — Master\n",
                encoding="utf-8",
            )
            args = self.mod.parse_args(["--session", str(session_path)])
            report = self.mod.run_checks(args)
            wrong_batch = [
                finding
                for finding in report.errors
                if finding.code == "acceptance_id_wrong_batch"
            ]
            self.assertEqual(len(wrong_batch), 2)

    def test_unchecked_master_acceptance_cannot_be_bypassed_by_green_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Batch contract",
                                "met": True,
                                "evidence": "batch proof",
                            },
                            {
                                "id": "M-A1",
                                "criterion": "Master contract",
                                "met": True,
                                "evidence": "claimed cumulative proof",
                            },
                        ],
                    }
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: Contract\n\n"
                "**Acceptance criteria:**\n"
                "- [x] B1-A1 — Batch contract\n\n"
                "## Master Acceptance\n\n"
                "- [ ] M-A1 — Master contract\n",
                encoding="utf-8",
            )

            code = self.mod.main(["--session", str(session_path)])

            self.assertEqual(code, 1)

    def test_multi_batch_close_without_validate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "execution_log_path": "execution-log.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "a",
                                "met": True,
                                "evidence": "e",
                            }
                        ],
                    },
                    {
                        "id": 2,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "b",
                                "met": True,
                                "evidence": "e",
                            }
                        ],
                    },
                ],
            }
            session_path = self._write_session(tmp, session)
            (tmp / "execution-log.md").write_text(
                "## 2026-07-08\n\n"
                "**Batch:** close remaining batches 1-2\n"
                "Multi-batch close of unfinished work.\n",
                encoding="utf-8",
            )
            code = self.mod.main(["--session", str(session_path)])
            self.assertEqual(code, 1)

    def test_batch_headings_do_not_replace_labeled_validate_sections(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "execution.md"
            log.write_text(
                "Multi-batch close\n\n## Batch 1\nproof\n\n## Batch 2\nproof\n",
                encoding="utf-8",
            )
            report = self.mod.Report()
            self.mod.check_execution_log(
                log,
                report,
                expected_batch_ids={1, 2},
            )
            self.assertTrue(any(f.code == "multi_batch_close" for f in report.errors))

            log.write_text(
                "Multi-batch close\n\n**Validate for batch 1:**\nproof\n\n"
                "**Validate for batch 2:**\nproof\n",
                encoding="utf-8",
            )
            report = self.mod.Report()
            self.mod.check_execution_log(
                log,
                report,
                expected_batch_ids={1, 2},
            )
            self.assertFalse(report.errors)

    def test_evidence_dirs_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "ok",
                                "met": True,
                                "evidence": "e",
                            }
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            evidence = tmp / "scratch"
            evidence.mkdir()
            batch_dir = evidence / "batch-1"
            batch_dir.mkdir()
            (batch_dir / "lint.log").write_text("ok", encoding="utf-8")
            # missing typecheck/test/build
            code = self.mod.main(
                [
                    "--session",
                    str(session_path),
                    "--evidence-root",
                    str(evidence),
                    "--require-evidence-dirs",
                ]
            )
            self.assertEqual(code, 1)

    def test_b0_evidence_uses_numeric_batch_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            evidence = tmp / "scratch"
            batch_dir = evidence / "batch-0"
            batch_dir.mkdir(parents=True)
            for gate in self.mod.GATE_NAMES:
                (batch_dir / f"{gate}.log").write_text("ok\n", encoding="utf-8")
            session = {
                "batches": [
                    {
                        "id": "B0",
                        "status": "complete",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": "Staging evidence exists",
                                "met": True,
                                "evidence": "scratch/batch-0",
                            }
                        ],
                    }
                ]
            }
            report = self.mod.Report()

            self.mod.check_evidence_dirs(
                evidence,
                session,
                report,
                required=True,
            )

            self.assertEqual(report.errors, [])

    def test_advisory_exits_zero_on_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {"batches": [{"id": 1, "status": "complete"}]}
            session_path = self._write_session(tmp, session)
            code = self.mod.main(["--session", str(session_path), "--advisory"])
            self.assertEqual(code, 0)

    def test_missing_session_exits_2(self) -> None:
        code = self.mod.main(["--session", "/tmp/definitely-missing-elves-session.json"])
        self.assertEqual(code, 2)

    def test_malformed_batch_and_acceptance_entries_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            for payload in (
                {"batches": [{"id": 1, "status": "complete"}, "not-an-object"]},
                {
                    "batches": [
                        {
                            "id": 1,
                            "status": "complete",
                            "acceptance": [
                                {"criterion": "done", "met": True, "evidence": "sha"},
                                "not-an-object",
                            ],
                        }
                    ]
                },
            ):
                with self.subTest(payload=payload):
                    session_path = self._write_session(tmp, payload)
                    code = self.mod.main(["--session", str(session_path)])
                    self.assertEqual(code, 2)

    def test_json_output_shape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": 1,
                        "status": "complete",
                        "acceptance": [
                            {
                                "criterion": "ok",
                                "met": True,
                                "evidence": "sha",
                            }
                        ],
                    }
                ]
            }
            session_path = self._write_session(tmp, session)
            (tmp / "plan.md").write_text(
                "### Batch 1: JSON\n\n**Acceptance criteria:**\n- [x] ok\n",
                encoding="utf-8",
            )
            # Capture via run_checks + print_json path
            args = self.mod.parse_args(["--session", str(session_path), "--json"])
            report = self.mod.run_checks(args)
            self.assertFalse(report.errors)


if __name__ == "__main__":
    unittest.main()
