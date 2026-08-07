from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_CONTRACT_SCRIPT = REPO_ROOT / "scripts" / "acceptance_contract.py"
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.acceptance import (  # noqa: E402
    normalize_batch_id,
    parse_markdown_acceptance_rows,
    parse_plan_acceptance_contract,
)


VALID_PLAN = """\
# Acceptance contract test plan

## Batch 0: Staging

**Acceptance criteria:**

- [ ] [B0-A1] Bracketed B0 criterion.
- [ ] B0-A2: Bare B0 criterion.

## Master Acceptance

- [ ] [M-A1] Master criterion.
"""


def session_for_plan(*, first_criterion: str = "Bracketed B0 criterion.") -> dict[str, object]:
    return {
        "plan_path": "plan.md",
        "batches": [
            {
                "id": "B0",
                "status": "pending",
                "acceptance": [
                    {
                        "id": "B0-A1",
                        "criterion": first_criterion,
                        "met": False,
                        "evidence": "",
                    },
                    {
                        "id": "B0-A2",
                        "criterion": "Bare B0 criterion.",
                        "met": False,
                        "evidence": "",
                    },
                ],
            }
        ],
        "master_acceptance": [
            {
                "id": "M-A1",
                "criterion": "Master criterion.",
                "met": False,
                "evidence": "",
            }
        ],
    }


class AcceptanceContractCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.repo = Path(self.tmpdir.name)
        self.plan_path = self.repo / "plan.md"
        self.session_path = self.repo / "session.json"

    def write_plan(self, text: str = VALID_PLAN) -> None:
        self.plan_path.write_text(text, encoding="utf-8")

    def write_session(self, session: dict[str, object]) -> None:
        session.setdefault("run_id", "acceptance-contract-test")
        session.setdefault("start_head", "a" * 40)
        self.session_path.write_text(
            json.dumps(session, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def run_cli(self, action: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ACCEPTANCE_CONTRACT_SCRIPT),
                action,
                "--repo-root",
                str(self.repo),
                *args,
            ],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_validate_accepts_b0_and_bare_and_bracketed_rows(self) -> None:
        self.write_plan()
        self.write_session(session_for_plan())

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issues"], [])

    def test_nested_session_resolves_recorded_plan_from_repo_root(self) -> None:
        plan = self.repo / "docs" / "plans" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(VALID_PLAN, encoding="utf-8")
        session_path = self.repo / ".elves" / "session.json"
        session_path.parent.mkdir(parents=True)
        session = session_for_plan()
        session["plan_path"] = "docs/plans/plan.md"
        session["run_id"] = "nested-session-test"
        session["start_head"] = "a" * 40
        session_path.write_text(
            json.dumps(session, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = self.run_cli(
            "validate",
            "--session",
            str(session_path.relative_to(self.repo)),
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["plan"], str(plan.resolve()))

    def test_shared_parser_accepts_bare_and_bracketed_crlf_rows(self) -> None:
        rows, issues = parse_markdown_acceptance_rows(
            "- [ ] B0-A1: Bare criterion.\r\n"
            "- [ ] [M-A1] Bracketed criterion.\r\n",
            require_checkbox=True,
        )
        self.assertEqual(issues, [])
        self.assertEqual(
            [(row.id, row.criterion) for row in rows],
            [
                ("B0-A1", "Bare criterion."),
                ("M-A1", "Bracketed criterion."),
            ],
        )

    def test_oversized_batch_numbers_return_issues_instead_of_raising(self) -> None:
        leading_zero_id = f"B{'0' * 5000}-A1"
        rows, issues = parse_markdown_acceptance_rows(
            f"- [ ] {leading_zero_id}: criterion\n",
            require_checkbox=True,
        )
        self.assertEqual(rows, [])
        self.assertEqual([issue.code for issue in issues], ["acceptance_id_invalid"])
        self.assertIn("- [ ] B0-A1: <criterion>", issues[0].message)

        huge_batch = "1" * 5000
        contract = parse_plan_acceptance_contract(
            f"### Batch {huge_batch}: Too large\n\n"
            "**Acceptance criteria:**\n\n"
            "- [ ] B0-A1: criterion\n\n"
            "## Master Acceptance\n\n"
            "- [ ] M-A1: master\n"
        )
        self.assertIn("batch_id_invalid", {issue.code for issue in contract.issues})
        self.assertIsNone(normalize_batch_id(f"B{huge_batch}"))
        self.assertIsNone(normalize_batch_id(10**128))

    def test_validate_reports_targeted_malformed_row_syntax(self) -> None:
        self.write_plan(
            VALID_PLAN.replace(
                "- [ ] [B0-A1] Bracketed B0 criterion.",
                "- [ ] B0-A1 Bracketed B0 criterion.",
            )
        )

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        syntax_issues = [
            issue
            for issue in payload["issues"]
            if issue["code"] == "acceptance_row_syntax"
        ]
        self.assertEqual(len(syntax_issues), 1, payload)
        message = syntax_issues[0]["message"]
        self.assertIn("- [ ] B0-A1: <criterion>", message)
        self.assertIn("- [ ] [B0-A1] <criterion>", message)

    def test_validate_leading_zero_id_suggests_canonical_replacements(self) -> None:
        self.write_plan(
            VALID_PLAN.replace(
                "- [ ] [B0-A1] Bracketed B0 criterion.",
                "- [ ] B00-A1: Bracketed B0 criterion.",
            )
        )

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        issue = next(
            item
            for item in payload["issues"]
            if item["code"] == "acceptance_id_invalid"
        )
        self.assertIn("acceptance id B00-A1 is not canonical", issue["message"])
        self.assertIn("- [ ] B0-A1: <criterion>", issue["message"])
        self.assertIn("- [ ] [B0-A1] <criterion>", issue["message"])
        self.assertNotIn("`- [ ] B00-A1", issue["message"])

    def test_validate_reports_plan_session_criterion_mismatch(self) -> None:
        self.write_plan()
        self.write_session(
            session_for_plan(first_criterion="Hand-copied criterion drifted.")
        )

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        mismatch = [
            issue
            for issue in payload["issues"]
            if issue["code"] == "acceptance_criterion_mismatch"
        ]
        self.assertEqual(len(mismatch), 1, payload)
        self.assertIn("B0-A1", mismatch[0]["message"])
        self.assertIn("Bracketed B0 criterion.", mismatch[0]["message"])
        self.assertIn("Hand-copied criterion drifted.", mismatch[0]["message"])

    def test_validate_blocks_id_bearing_session_with_legacy_plan(self) -> None:
        self.write_plan(
            "# Legacy plan\n\n"
            "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
            "- [ ] Legacy staging criterion.\n\n"
            "## Master Acceptance\n\n- [ ] Legacy master criterion.\n"
        )
        session = session_for_plan(first_criterion="Drifted legacy wording.")
        self.write_session(session)

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        issue = next(
            item
            for item in payload["issues"]
            if item["code"] == "acceptance_plan_ids_required"
        )
        self.assertIn("Persist matching B#-A#/M-A# rows", issue["message"])

    def test_validate_rejects_malformed_legacy_session_containers(self) -> None:
        self.write_plan(
            "# Legacy plan\n\n"
            "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
            "- [ ] Legacy staging criterion.\n"
        )
        self.session_path.write_text(
            '{"plan_path":"plan.md","batches":{"bad":true},'
            '"master_acceptance":null}\n',
            encoding="utf-8",
        )

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "session_batches_invalid",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )

        self.write_session(
            {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "acceptance": [
                            {"criterion": "Legacy staging criterion."}
                        ],
                    }
                ],
                "master_acceptance": ["bad"],
            }
        )
        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "session_master_acceptance_invalid",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )

    def test_validate_rejects_invalid_duplicate_and_mismatched_legacy_batches(self) -> None:
        self.write_plan(
            "# Legacy plan\n\n"
            "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
            "- [ ] Legacy staging criterion.\n"
        )

        cases = (
            (
                [{"id": "B00", "acceptance": []}],
                {"batch_id_invalid", "plan_batch_missing_in_session"},
            ),
            (
                [
                    {"id": "B0", "acceptance": []},
                    {"id": 0, "acceptance": []},
                ],
                {"batch_id_duplicate"},
            ),
            ([], {"plan_batch_missing_in_session"}),
            (
                [{"id": "B9", "acceptance": []}],
                {
                    "session_batch_missing_in_plan",
                    "plan_batch_missing_in_session",
                },
            ),
        )
        for batches, expected_codes in cases:
            with self.subTest(batches=batches):
                self.write_session(
                    {
                        "plan_path": "plan.md",
                        "batches": batches,
                        "master_acceptance": [],
                    }
                )
                result = self.run_cli(
                    "validate",
                    "--plan",
                    self.plan_path.name,
                    "--session",
                    self.session_path.name,
                    "--json",
                )
                self.assertEqual(
                    result.returncode,
                    1,
                    result.stdout + result.stderr,
                )
                codes = {
                    issue["code"] for issue in json.loads(result.stdout)["issues"]
                }
                self.assertTrue(expected_codes <= codes, codes)

    def test_validate_rejects_extra_stable_session_batch_before_launch(self) -> None:
        self.write_plan()
        session = session_for_plan()
        session["batches"].append(  # type: ignore[union-attr]
            {"id": "B9", "status": "complete", "acceptance": []}
        )
        self.write_session(session)

        result = self.run_cli(
            "validate",
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "session_batch_missing_in_plan",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )

    def test_validate_rejects_empty_explicit_legacy_acceptance_sections(self) -> None:
        cases = (
            (
                "# Legacy plan\n\n"
                "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
                "## Notes\nNothing yet.\n",
                "acceptance_criteria_required",
            ),
            (
                "# Legacy plan\n\n"
                "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
                "- [ ] Legacy staging criterion.\n\n"
                "## Master Acceptance\n",
                "master_acceptance_criteria_required",
            ),
        )
        for plan, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                self.write_plan(plan)
                result = self.run_cli(
                    "validate",
                    "--plan",
                    self.plan_path.name,
                    "--json",
                )
                self.assertEqual(
                    result.returncode,
                    1,
                    result.stdout + result.stderr,
                )
                self.assertIn(
                    expected_code,
                    {
                        issue["code"]
                        for issue in json.loads(result.stdout)["issues"]
                    },
                )

    def test_validate_rejects_master_only_stable_contract(self) -> None:
        self.write_plan(
            "# Incomplete stable plan\n\n"
            "## Master Acceptance\n\n- [ ] M-A1: Master only.\n"
        )
        self.write_session(
            {
                "plan_path": "plan.md",
                "batches": [],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Master only.",
                        "met": False,
                        "evidence": "",
                    }
                ],
            }
        )

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "plan_batch_required",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )

    def test_plan_batch_required_hints_at_legacy_headings(self) -> None:
        # aigorahub/elves#248: pre-v2.23 plans used `### B0 · Name`; the
        # refusal must say how to migrate instead of only naming the grammar.
        self.write_plan(
            "# Legacy plan\n\n## Batches\n\n"
            "### B0 · Land the thing\n\n"
            "**Acceptance criteria:**\n\n- [ ] [B0-A1] It lands.\n\n"
            "## Master Acceptance\n\n- [ ] [M-A1] Done.\n"
        )
        self.write_session(
            {
                "plan_path": "plan.md",
                "batches": [],
                "master_acceptance": [
                    {"id": "M-A1", "criterion": "Done.", "met": False, "evidence": ""}
                ],
            }
        )
        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        issues = {
            issue["code"]: issue["message"]
            for issue in json.loads(result.stdout)["issues"]
        }
        self.assertIn("plan_batch_required", issues)
        self.assertIn("legacy heading", issues["plan_batch_required"])
        self.assertIn("### Batch 0 [B0]: Name", issues["plan_batch_required"])

    def test_validate_rejects_duplicate_b0_session_aliases(self) -> None:
        self.write_plan()
        session = session_for_plan()
        duplicate = dict(session["batches"][0])  # type: ignore[index]
        duplicate["id"] = 0
        duplicate["acceptance"] = []
        session["batches"].append(duplicate)  # type: ignore[union-attr]
        self.write_session(session)

        result = self.run_cli(
            "validate",
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(
            "batch_id_duplicate",
            {issue["code"] for issue in payload["issues"]},
        )

    def test_sync_session_generates_idempotently_and_preserves_evidence(self) -> None:
        self.write_plan()
        self.write_session(
            {
                "plan_path": "plan.md",
                "run_id": "preserve-me",
                "batches": [],
                "master_acceptance": [],
            }
        )

        generated = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        session = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(session["run_id"], "preserve-me")
        self.assertEqual(session["batches"][0]["id"], "B0")
        self.assertEqual(
            [row["id"] for row in session["batches"][0]["acceptance"]],
            ["B0-A1", "B0-A2"],
        )
        self.assertEqual(session["master_acceptance"][0]["id"], "M-A1")
        for row in [
            *session["batches"][0]["acceptance"],
            *session["master_acceptance"],
        ]:
            self.assertFalse(row["met"])
            self.assertEqual(row["evidence"], "")

        session["batches"][0]["acceptance"][0].update(
            {
                "met": True,
                "evidence": "Focused regression test passed.",
                "reviewer_note": "keep this runtime field",
            }
        )
        session["master_acceptance"][0]["evidence"] = "Landing review passed."
        self.write_session(session)
        before = json.loads(self.session_path.read_text(encoding="utf-8"))

        repeated = self.run_cli(
            "sync-session",
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        after = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(after, before)
        self.assertEqual(
            after["batches"][0]["acceptance"][0]["evidence"],
            "Focused regression test passed.",
        )
        self.assertEqual(
            after["batches"][0]["acceptance"][0]["reviewer_note"],
            "keep this runtime field",
        )
        self.assertEqual(
            after["master_acceptance"][0]["evidence"],
            "Landing review passed.",
        )

        dry_run = self.run_cli(
            "sync-session",
            "--session",
            self.session_path.name,
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertEqual(json.loads(dry_run.stdout), after)

    def test_sync_session_derives_bare_and_bracketed_master_rows_symmetrically(self) -> None:
        self.write_plan(
            "# Plan\n\n"
            "## Batch 0: Staging\n\n"
            "**Acceptance criteria:**\n\n"
            "- [ ] B0-A1: Batch criterion.\n\n"
            "## Master Acceptance\n\n"
            "- [ ] M-A1: Bare master criterion.\n"
            "- [ ] [M-A2] Bracketed master criterion.\n"
        )
        self.write_session(
            {
                "plan_path": "plan.md",
                "batches": [],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Bare master criterion.",
                        "met": True,
                        "evidence": "Existing end-to-end proof.",
                        "reviewer_note": "preserve me",
                    }
                ],
            }
        )

        result = self.run_cli(
            "sync-session",
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        session = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [
                (row["id"], row["criterion"])
                for row in session["master_acceptance"]
            ],
            [
                ("M-A1", "Bare master criterion."),
                ("M-A2", "Bracketed master criterion."),
            ],
        )
        self.assertTrue(session["master_acceptance"][0]["met"])
        self.assertEqual(
            session["master_acceptance"][0]["evidence"],
            "Existing end-to-end proof.",
        )
        self.assertEqual(
            session["master_acceptance"][0]["reviewer_note"],
            "preserve me",
        )
        self.assertFalse(session["master_acceptance"][1]["met"])
        self.assertEqual(session["master_acceptance"][1]["evidence"], "")

    def test_validate_requires_final_landing_identity_during_staging(self) -> None:
        self.write_plan()
        session = session_for_plan()
        self.session_path.write_text(
            json.dumps(session, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = self.run_cli(
            "validate",
            "--session",
            self.session_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("session_run_id_missing", codes)
        self.assertIn("session_start_head_invalid", codes)

    def test_sync_session_derives_start_head_from_exact_collision_tripwire(self) -> None:
        self.write_plan()
        session = session_for_plan()
        session["run_id"] = "run-with-legacy-tripwire"
        session["collision_tripwire"] = "b" * 40
        self.session_path.write_text(
            json.dumps(session, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = self.run_cli(
            "sync-session",
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(after["start_head"], "b" * 40)
        self.assertEqual(after["collision_tripwire"], "b" * 40)

        validated = self.run_cli(
            "validate",
            "--session",
            self.session_path.name,
            "--json",
        )
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_validate_rejects_abbreviated_or_mismatched_collision_tripwire(self) -> None:
        self.write_plan()
        cases = (
            (
                "abbreviated",
                "deadbeef",
                "deadbeef",
                {
                    "session_start_head_invalid",
                    "session_collision_tripwire_invalid",
                },
            ),
            (
                "mismatch",
                "a" * 40,
                "b" * 40,
                {"session_collision_tripwire_mismatch"},
            ),
        )
        for name, start_head, tripwire, expected in cases:
            with self.subTest(name=name):
                session = session_for_plan()
                session.update(
                    {
                        "run_id": "identity-test",
                        "start_head": start_head,
                        "collision_tripwire": tripwire,
                    }
                )
                self.session_path.write_text(
                    json.dumps(session, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                result = self.run_cli(
                    "validate",
                    "--session",
                    self.session_path.name,
                    "--json",
                )

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                codes = {
                    issue["code"] for issue in json.loads(result.stdout)["issues"]
                }
                self.assertTrue(expected <= codes, codes)

    def test_sync_session_refuses_to_rewrite_evidenced_criterion(self) -> None:
        self.write_plan()
        session = session_for_plan(first_criterion="Previously evidenced wording.")
        first = session["batches"][0]["acceptance"][0]  # type: ignore[index]
        first["met"] = True
        first["evidence"] = "Proof tied to the old wording."
        self.write_session(session)
        before = self.session_path.read_bytes()

        result = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(
            "acceptance_sync_would_rewrite_proof",
            {issue["code"] for issue in payload["issues"]},
        )
        self.assertEqual(self.session_path.read_bytes(), before)

    def test_sync_session_refuses_to_attach_missing_criterion_to_proof(self) -> None:
        self.write_plan()
        session = session_for_plan(first_criterion="")
        first = session["batches"][0]["acceptance"][0]  # type: ignore[index]
        first["met"] = True
        first["evidence"] = "Proof with no recorded criterion."
        self.write_session(session)
        before = self.session_path.read_bytes()

        result = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "acceptance_sync_would_rewrite_proof",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )
        self.assertEqual(self.session_path.read_bytes(), before)

    def test_sync_treats_whitespace_padded_complete_status_as_proof(self) -> None:
        self.write_plan()
        session = session_for_plan(first_criterion="Previously completed wording.")
        batch = session["batches"][0]  # type: ignore[index]
        batch["status"] = " complete "
        self.write_session(session)
        before = self.session_path.read_bytes()

        result = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "acceptance_sync_would_rewrite_proof",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )
        self.assertEqual(self.session_path.read_bytes(), before)

    def test_sync_session_rejects_duplicate_json_keys_without_rewrite(self) -> None:
        self.write_plan()
        self.session_path.write_text(
            '{"plan_path":"plan.md",'
            '"batches":[{"id":"B9","status":"complete",'
            '"acceptance":{"evidence":"do not erase"}}],'
            '"batches":[],"master_acceptance":[]}\n',
            encoding="utf-8",
        )
        before = self.session_path.read_bytes()

        result = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["issues"][0]["code"], "acceptance_input_invalid")
        self.assertIn("duplicate JSON object key: batches", payload["issues"][0]["message"])
        self.assertEqual(self.session_path.read_bytes(), before)

    def test_sync_session_refuses_malformed_proof_containers(self) -> None:
        cases = (
            (
                "batches",
                {
                    "plan_path": "plan.md",
                    "batches": {"evidence": "do not erase"},
                    "master_acceptance": [],
                },
                "session_batches_invalid",
            ),
            (
                "active_batch",
                {
                    **session_for_plan(),
                    "batches": [
                        {
                            "id": "B0",
                            "status": "complete",
                            "acceptance": {
                                "met": True,
                                "evidence": "do not erase",
                            },
                        }
                    ],
                },
                "session_acceptance_invalid",
            ),
            (
                "master",
                {
                    **session_for_plan(),
                    "master_acceptance": {
                        "met": True,
                        "evidence": "do not erase",
                    },
                },
                "session_master_acceptance_invalid",
            ),
        )
        for name, session, expected_code in cases:
            with self.subTest(name=name):
                self.write_plan()
                self.write_session(session)
                before = self.session_path.read_bytes()

                result = self.run_cli(
                    "sync-session",
                    "--plan",
                    self.plan_path.name,
                    "--session",
                    self.session_path.name,
                    "--write",
                    "--json",
                )

                self.assertEqual(
                    result.returncode,
                    1,
                    result.stdout + result.stderr,
                )
                self.assertIn(
                    expected_code,
                    {
                        issue["code"]
                        for issue in json.loads(result.stdout)["issues"]
                    },
                )
                self.assertEqual(self.session_path.read_bytes(), before)

    def test_sync_rejects_declared_empty_b0_before_it_can_be_removed(self) -> None:
        self.write_plan(
            "# Plan\n\n"
            "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
            "## Batch 1: Build\n\n**Acceptance criteria:**\n\n"
            "- [ ] B1-A1: Build criterion.\n\n"
            "## Master Acceptance\n\n- [ ] M-A1: Master criterion.\n"
        )
        self.write_session(
            {
                "plan_path": "plan.md",
                "batches": [
                    {"id": "B0", "status": "pending", "acceptance": []},
                    {
                        "id": "B1",
                        "status": "pending",
                        "acceptance": [
                            {
                                "id": "B1-A1",
                                "criterion": "Build criterion.",
                                "met": False,
                                "evidence": "",
                            }
                        ],
                    },
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Master criterion.",
                        "met": False,
                        "evidence": "",
                    }
                ],
            }
        )
        before = self.session_path.read_bytes()

        result = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "acceptance_ids_required",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )
        self.assertEqual(self.session_path.read_bytes(), before)

    def test_validate_rejects_empty_master_acceptance_in_stable_mode(self) -> None:
        self.write_plan(
            "# Plan\n\n"
            "## Batch 0: Staging\n\n**Acceptance criteria:**\n\n"
            "- [ ] B0-A1: Staging criterion.\n\n"
            "## Master Acceptance\n"
        )

        result = self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--json",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "master_acceptance_ids_required",
            {issue["code"] for issue in json.loads(result.stdout)["issues"]},
        )

    def test_sync_session_removes_obsolete_proof_free_batch_idempotently(self) -> None:
        self.write_plan()
        session = session_for_plan()
        session["batches"].append(  # type: ignore[union-attr]
            {
                "id": "B9",
                "status": "pending",
                "acceptance": [
                    {
                        "id": "B9-A1",
                        "criterion": "Superseded staging criterion.",
                        "met": False,
                        "evidence": "",
                    }
                ],
            }
        )
        self.write_session(session)

        first = self.run_cli(
            "sync-session",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        after_first = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual([batch["id"] for batch in after_first["batches"]], ["B0"])

        second = self.run_cli(
            "sync-session",
            "--session",
            self.session_path.name,
            "--write",
            "--json",
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(
            json.loads(self.session_path.read_text(encoding="utf-8")),
            after_first,
        )

        validated = self.run_cli(
            "validate",
            "--session",
            self.session_path.name,
            "--json",
        )
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_sync_session_refuses_to_remove_obsolete_evidenced_batch(self) -> None:
        cases = (
            ("complete", "complete", False, ""),
            ("met", "pending", True, ""),
            ("evidence", "pending", False, "Historical proof."),
        )
        for name, status, met, evidence in cases:
            with self.subTest(name=name):
                self.write_plan()
                session = session_for_plan()
                session["batches"].append(  # type: ignore[union-attr]
                    {
                        "id": "B9",
                        "status": status,
                        "acceptance": [
                            {
                                "id": "B9-A1",
                                "criterion": "Superseded but evidenced criterion.",
                                "met": met,
                                "evidence": evidence,
                            }
                        ],
                    }
                )
                self.write_session(session)
                before = self.session_path.read_bytes()

                result = self.run_cli(
                    "sync-session",
                    "--plan",
                    self.plan_path.name,
                    "--session",
                    self.session_path.name,
                    "--write",
                    "--json",
                )

                self.assertEqual(
                    result.returncode,
                    1,
                    result.stdout + result.stderr,
                )
                self.assertIn(
                    "acceptance_sync_would_erase_proof",
                    {
                        issue["code"]
                        for issue in json.loads(result.stdout)["issues"]
                    },
                )
                self.assertEqual(self.session_path.read_bytes(), before)


class DelegatedHandoffContractTests(unittest.TestCase):
    """Explicit handoff v1 fails closed without breaking undeclared v2.8 sessions."""

    write_plan = AcceptanceContractCliTests.write_plan
    write_session = AcceptanceContractCliTests.write_session
    run_cli = AcceptanceContractCliTests.run_cli

    def setUp(self) -> None:
        AcceptanceContractCliTests.setUp(self)
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "elves-tests@example.com"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Elves Tests"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-qm", "initial"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "branch", "-m", "codex/delegated-test"],
            cwd=self.repo,
            check=True,
        )
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()

    def _session_with_driver(
        self,
        work_driver: str | None,
        *,
        worker_packet_path: str | None = None,
        include_handoff: bool = False,
    ) -> dict[str, object]:
        session = session_for_plan()
        session["branch"] = "codex/delegated-test"
        if work_driver is not None:
            session["work_driver"] = work_driver
        if worker_packet_path is not None:
            session["worker_packet_path"] = worker_packet_path
        if include_handoff:
            session["delegation_scope"] = "full_run"
            session["handoff"] = {
                "schema_version": 1,
                "mode": "fresh_start",
                "active_batch": "B0",
                "product_implementation_started": False,
                "coordinator_completed_slices": [],
                "worker_owned_acceptance_ids": ["B0-A1", "B0-A2"],
                "coordinator_owned_acceptance_ids": ["M-A1"],
                "next_exact_action": "Begin B0-A1 with its focused failing test.",
            }
        return session

    def _write_packet(
        self,
        session: dict[str, object],
        *,
        launch_head: str | None = None,
        handoff: dict[str, object] | None = None,
        criterion: str = "Bracketed B0 criterion.",
        json_packet: bool = False,
        markdown_prefix: str = "",
    ) -> str:
        suffix = ".json" if json_packet else ".md"
        packet_path = self.repo / ".elves" / "runtime" / f"worker-packet{suffix}"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        capsule = {
            "schema_version": 1,
            "run_id": "acceptance-contract-test",
            "branch": session["branch"],
            "launch_head": launch_head or self.head,
            "handoff": handoff or session["handoff"],
        }
        if json_packet:
            packet_path.write_text(
                json.dumps(
                    {
                        "elves_handoff": capsule,
                        "acceptance": [
                            {"id": "B0-A1", "criterion": criterion},
                            {"id": "B0-A2", "criterion": "Bare B0 criterion."},
                            {"id": "M-A1", "criterion": "Master criterion."},
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            packet_path.write_text(
                markdown_prefix
                + "<!-- elves-handoff-v1\n"
                + json.dumps(capsule, indent=2, sort_keys=True)
                + "\n-->\n\n"
                + "# Worker packet\n\n"
                + f"- [ ] B0-A1: {criterion}\n"
                + "- [ ] B0-A2: Bare B0 criterion.\n"
                + "- [ ] M-A1: Master criterion.\n",
                encoding="utf-8",
            )
        return str(packet_path.relative_to(self.repo))

    def _validate(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "validate",
            "--plan",
            self.plan_path.name,
            "--session",
            self.session_path.name,
            *extra,
        )

    def _issue_codes(self, result: subprocess.CompletedProcess[str]) -> set[str]:
        return {issue["code"] for issue in json.loads(result.stdout)["issues"]}

    def test_validate_warns_for_delegated_run_without_explicit_handoff(self) -> None:
        self.write_plan()
        self.write_session(self._session_with_driver("grok-build"))

        result = self._validate("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual([], payload["issues"])
        self.assertEqual(["worker_packet_missing"], [item["code"] for item in payload["warnings"]])

    def test_validate_warns_for_all_delegated_driver_spellings_without_handoff(self) -> None:
        for driver in ("grok_build", "devin-cli", "devin_cli", "untrusted_writer"):
            with self.subTest(driver=driver):
                self.write_plan()
                self.write_session(self._session_with_driver(driver))

                result = self._validate("--json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(
                    ["worker_packet_missing"],
                    [item["code"] for item in payload["warnings"]],
                )

    def test_validate_accepts_complete_fresh_start_handoff(self) -> None:
        self.write_plan()
        session = self._session_with_driver("subscription-native-codex", include_handoff=True)
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_validate_accepts_equivalent_json_packet_handoff(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["worker_packet_path"] = self._write_packet(
            session,
            json_packet=True,
        )
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_declared_handoff_requires_packet(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("worker_packet_missing", self._issue_codes(result))
        self.assertEqual([], json.loads(result.stdout)["warnings"])

    def test_declared_non_object_handoff_blocks(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build")
        session["handoff"] = None
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_invalid", self._issue_codes(result))

    def test_host_native_full_run_scope_remains_silent_without_handoff(self) -> None:
        self.write_plan()
        session = self._session_with_driver("host-native")
        session["delegation_scope"] = "full_run"
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([], json.loads(result.stdout)["warnings"])

    def test_validate_silent_for_host_native_and_absent_driver(self) -> None:
        for driver in ("host-native", "host_native", "n_a", None):
            with self.subTest(driver=driver):
                self.write_plan()
                self.write_session(self._session_with_driver(driver))

                result = self._validate("--json")

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)["ok"])

    def test_validate_blocks_unowned_pending_acceptance(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"]["worker_owned_acceptance_ids"] = ["B0-A1"]
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_ownership_mismatch", self._issue_codes(result))

    def test_validate_blocks_overlapping_acceptance_ownership(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"]["coordinator_owned_acceptance_ids"] = ["B0-A1", "M-A1"]
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_ownership_overlap", self._issue_codes(result))

    def test_validate_blocks_fresh_start_that_claims_implementation_started(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"]["product_implementation_started"] = True
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_started_mismatch", self._issue_codes(result))

    def test_validate_accepts_resume_active_batch_with_evidenced_slice(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"].update(
            {
                "mode": "resume_active_batch",
                "product_implementation_started": True,
                "coordinator_completed_slices": [
                    {
                        "description": "Locked the persistence contract.",
                        "evidence": "Focused contract test passes.",
                        "commit": self.head,
                    }
                ],
                "next_exact_action": "Continue B0-A1 from the service implementation seam.",
            }
        )
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validate_blocks_resume_without_completed_slice(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"].update(
            {
                "mode": "resume_active_batch",
                "product_implementation_started": True,
                "next_exact_action": "Continue B0-A1.",
            }
        )
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_slices_mismatch", self._issue_codes(result))

    def test_validate_blocks_nonancestor_completed_slice(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"].update(
            {
                "mode": "resume_active_batch",
                "product_implementation_started": True,
                "coordinator_completed_slices": [
                    {
                        "description": "Claims an unrelated slice.",
                        "evidence": "Untrusted evidence.",
                        "commit": "b" * 40,
                    }
                ],
                "next_exact_action": "Continue B0-A1.",
            }
        )
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "delegated_handoff_slice_commit_unproven",
            self._issue_codes(result),
        )

    def test_validate_blocks_noncanonical_owned_acceptance_id(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["handoff"]["worker_owned_acceptance_ids"] = ["B00-A1"]
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_ownership_invalid", self._issue_codes(result))

    def test_validate_blocks_packet_state_that_differs_from_session(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        packet_handoff = dict(session["handoff"])
        packet_handoff["next_exact_action"] = "A different action."
        session["worker_packet_path"] = self._write_packet(
            session,
            handoff=packet_handoff,
        )
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("worker_packet_handoff_mismatch", self._issue_codes(result))

    def test_validate_blocks_packet_for_a_different_launch_head(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["worker_packet_path"] = self._write_packet(
            session,
            launch_head="b" * 40,
        )
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("worker_packet_launch_head_mismatch", self._issue_codes(result))

    def test_validate_blocks_session_for_a_different_current_branch(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["branch"] = "codex/other-branch"
        session["worker_packet_path"] = self._write_packet(session)
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("delegated_handoff_branch_mismatch", self._issue_codes(result))

    def test_validate_blocks_markdown_capsule_after_packet_content(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["worker_packet_path"] = self._write_packet(
            session,
            markdown_prefix="# Content before state\n\n",
        )
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "worker_packet_state_capsule_position_invalid",
            self._issue_codes(result),
        )

    def test_validate_blocks_oversized_explicit_packet(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        relative = self._write_packet(session)
        packet_path = self.repo / relative
        packet_path.write_text("x" * ((1024 * 1024) + 1), encoding="utf-8")
        session["worker_packet_path"] = relative
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("worker_packet_invalid", self._issue_codes(result))

    def test_validate_reports_malformed_json_packet_once(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        relative = self._write_packet(session, json_packet=True)
        (self.repo / relative).write_text("{", encoding="utf-8")
        session["worker_packet_path"] = relative
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        issues = json.loads(result.stdout)["issues"]
        self.assertEqual(
            ["worker_packet_invalid_json"],
            [item["code"] for item in issues],
        )

    def test_validate_blocks_packet_criterion_text_drift(self) -> None:
        self.write_plan()
        session = self._session_with_driver("grok-build", include_handoff=True)
        session["worker_packet_path"] = self._write_packet(
            session,
            criterion="Drifted criterion text.",
        )
        self.write_session(session)

        result = self._validate("--json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("worker_packet_acceptance_text_mismatch", self._issue_codes(result))


if __name__ == "__main__":
    unittest.main()
