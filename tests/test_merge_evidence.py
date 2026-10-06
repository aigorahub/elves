"""Computed "can it merge?" and "was it tested?" evidence."""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.merge_evidence import (  # noqa: E402
    compute_merge_evidence,
    evaluate_merge_evidence,
    fetch_pr_snapshot,
    landing_path,
    local_test_record_head,
    local_test_record_heads,
    parse_suite_inventory,
)


HEAD = "a" * 40
OTHER = "b" * 40
SOCKET = [
    {"name": "Socket Security: Pull Request Alerts", "bucket": "pass", "workflow": ""},
    {"name": "Socket Security: Project Report", "bucket": "pass", "workflow": ""},
    {"name": "Vercel", "bucket": "pass", "workflow": ""},
]
RELEASE_JOBS = [
    {"name": "release-gate", "bucket": "pass", "workflow": "Release"},
    {"name": "full-tests", "bucket": "pass", "workflow": "Release"},
]


def record(head=HEAD, association="MEMBER", gates="- `make test`: passed"):
    return {
        "body": f"Local tests passed on {head}\n{gates}",
        "author_association": association,
    }


def ordinary(**overrides):
    snapshot = {
        "head": HEAD,
        "base": "main",
        "default_branch": "main",
        "state": "OPEN",
        "is_draft": False,
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "labels": [],
        "required_checks": [],
        "checks": list(SOCKET),
        "comments": [record()],
        "behind_by": None,
    }
    snapshot.update(overrides)
    return snapshot


def release(**overrides):
    snapshot = ordinary(
        base="main",
        default_branch="dev",
        labels=["release"],
        required_checks=[
            {"name": "release-gate", "bucket": "pass"},
            {"name": "full-tests", "bucket": "pass"},
        ],
        checks=SOCKET + RELEASE_JOBS,
        comments=[],
        behind_by=0,
    )
    snapshot.update(overrides)
    return snapshot


class LandingPathTests(unittest.TestCase):
    def test_paths(self) -> None:
        self.assertEqual(landing_path("main", "main"), "ordinary")
        self.assertEqual(landing_path("dev", "dev"), "ordinary")
        self.assertEqual(landing_path("main", "dev"), "release")
        self.assertEqual(landing_path("staging", "dev"), "unsupported")
        self.assertEqual(landing_path(None, "main"), "unsupported")

    def test_record_grammar(self) -> None:
        self.assertEqual(
            local_test_record_head(f"Local tests passed on {HEAD.upper()}\n- `x`: passed"), HEAD
        )
        self.assertEqual(
            local_test_record_head(f"  Local tests passed on {OTHER}  \n* `x`: passed."), OTHER
        )
        self.assertIsNone(local_test_record_head(f"Local tests passed on {OTHER}\n* `x`: passed (12)"))
        self.assertIsNone(local_test_record_head(f"Notes\nLocal tests passed on {OTHER}"))
        self.assertIsNone(local_test_record_head("Local tests passed on abc123\n- `x`: passed"))
        self.assertIsNone(local_test_record_head(f"Local tests passed on {HEAD}"))
        self.assertIsNone(
            local_test_record_head(f"Local tests passed on {HEAD}\n- `a`: passed\n- `b`: failed")
        )
        self.assertIsNone(
            local_test_record_head(f"Local tests passed on {HEAD}\n- `a`: 156 of 157 passed")
        )
        self.assertIsNone(local_test_record_head(None))

    def test_record_holds_only_gate_lines(self) -> None:
        first = f"Local tests passed on {HEAD}\n- `npm run lint`: passed\n"
        self.assertEqual(local_test_record_head(first + "\n* `npm test`: PASSED.\n\n"), HEAD)
        for rest in (
            # failures and qualified passes
            "- `npm test`: 812 passed, 1 failed",
            "- `npm test`: failed",
            "- `npm test`: passed (812 of 813; 1 failed)",
            "- `npm test`: passed, except one failed",
            "- `npm test`: passed; build skipped",
            # empty, wrapped, indented, or malformed gate lines
            "- `npm test`:",
            "- `npm test`:   ",
            "- `npm test`:\n    failed",
            "- `npm test`: passed\n    except one test failed",
            "    - `npm test`: failed",
            "- `npm test` : failed",
            "- ` `: passed",
            "- ``: passed",
            "- npm run test:e2e: skipped",
            "- npm run build: skipped",
            # notes, anywhere
            "\nNotes:\n- `npm test`: failed",
            "\nNotes:\n- `GEMINI_API_KEY` was set to a placeholder, not a real key.",
            "\nThe installer ran against an empty temporary home.",
        ):
            self.assertIsNone(local_test_record_head(first + rest), rest)
        self.assertIsNone(local_test_record_head(f"Local tests passed on {HEAD}\n- just a note"))

    def test_record_author_must_be_owner_member_or_collaborator(self) -> None:
        heads = local_test_record_heads(
            [
                record(HEAD, "CONTRIBUTOR"),
                record(OTHER, "COLLABORATOR"),
                {"body": record(HEAD)["body"]},
                "not a comment",
            ]
        )
        self.assertEqual(heads, frozenset({OTHER}))


class OrdinaryPathTests(unittest.TestCase):
    def test_record_on_exact_head_is_green(self) -> None:
        evidence = evaluate_merge_evidence(ordinary(), local_head=HEAD)
        self.assertEqual(evidence.path, "ordinary")
        self.assertTrue(evidence.can_merge)
        self.assertTrue(evidence.tested)
        self.assertTrue(evidence.green)

    def test_socket_only_green_is_not_tested(self) -> None:
        evidence = evaluate_merge_evidence(ordinary(comments=[]), local_head=HEAD)
        self.assertTrue(evidence.can_merge)
        self.assertFalse(evidence.tested)
        self.assertIn("local_test_record_missing", evidence.test_reasons)

    def test_record_for_another_commit_is_not_tested(self) -> None:
        evidence = evaluate_merge_evidence(
            ordinary(comments=[record(OTHER)]), local_head=HEAD
        )
        self.assertFalse(evidence.tested)

    def test_skipped_required_check_can_merge_but_pending_cannot(self) -> None:
        skipped = evaluate_merge_evidence(
            ordinary(required_checks=[{"name": "check", "bucket": "skipping"}]),
            local_head=HEAD,
        )
        self.assertTrue(skipped.can_merge)
        pending = evaluate_merge_evidence(
            ordinary(required_checks=[{"name": "check", "bucket": "pending"}]),
            local_head=HEAD,
        )
        self.assertFalse(pending.can_merge)
        self.assertIn("required_check_pending:check", pending.merge_reasons)
        failed = evaluate_merge_evidence(
            ordinary(required_checks=[{"name": "check", "bucket": "cancel"}]),
            local_head=HEAD,
        )
        self.assertIn("required_check_failed:check", failed.merge_reasons)

    def test_blocked_and_unknown_cannot_merge(self) -> None:
        blocked = evaluate_merge_evidence(
            ordinary(merge_state_status="BLOCKED"), local_head=HEAD
        )
        self.assertFalse(blocked.can_merge)
        self.assertIn("merge_state:blocked", blocked.merge_reasons)
        unknown = evaluate_merge_evidence(ordinary(mergeable="UNKNOWN"), local_head=HEAD)
        self.assertIn("mergeable:unknown", unknown.merge_reasons)
        unstable = evaluate_merge_evidence(
            ordinary(merge_state_status="UNSTABLE"), local_head=HEAD
        )
        self.assertTrue(unstable.can_merge)

    def test_unavailable_required_checks_cannot_merge(self) -> None:
        evidence = evaluate_merge_evidence(ordinary(required_checks=None), local_head=HEAD)
        self.assertIn("required_checks_unavailable", evidence.merge_reasons)

    def test_failed_actions_job_is_a_failed_test_without_an_inventory(self) -> None:
        checks = SOCKET + [
            {"name": "comment-gemini-review", "bucket": "fail", "workflow": "Gemini"},
        ]
        evidence = evaluate_merge_evidence(ordinary(checks=checks), local_head=HEAD)
        self.assertTrue(evidence.can_merge)
        self.assertFalse(evidence.tested)
        self.assertIn("test_job_failed:comment-gemini-review", evidence.test_reasons)

    def test_failed_app_check_is_listed_for_triage(self) -> None:
        checks = SOCKET + [{"name": "Vercel Preview", "bucket": "fail", "workflow": ""}]
        evidence = evaluate_merge_evidence(ordinary(checks=checks), local_head=HEAD)
        self.assertTrue(evidence.green)
        self.assertEqual(evidence.failed_checks, ("Vercel Preview",))

    def test_failed_required_check_blocks_both_answers(self) -> None:
        evidence = evaluate_merge_evidence(
            ordinary(
                required_checks=[{"name": "test", "bucket": "fail"}],
                checks=SOCKET + [{"name": "test", "bucket": "fail", "workflow": "CI"}],
            ),
            local_head=HEAD,
        )
        self.assertFalse(evidence.can_merge)
        self.assertIn("required_check_failed:test", evidence.merge_reasons)
        self.assertIn("test_job_failed:test", evidence.test_reasons)

    def test_dependabot_suite_is_unverifiable_without_an_inventory(self) -> None:
        suite = SOCKET + [
            {"name": "unit", "bucket": "pass", "workflow": "CI"},
            {"name": "comment", "bucket": "pass", "workflow": "Bot"},
        ]
        for comments in ([], [record()]):
            evidence = evaluate_merge_evidence(
                ordinary(author="app/dependabot", checks=suite, comments=comments),
                local_head=HEAD,
            )
            self.assertFalse(evidence.tested)
            self.assertIn("dependabot_suite_unverifiable", evidence.test_reasons)


class ExactTargetTests(unittest.TestCase):
    def test_head_mismatch_fails_both(self) -> None:
        evidence = evaluate_merge_evidence(ordinary(head=OTHER), local_head=HEAD)
        self.assertFalse(evidence.can_merge)
        self.assertFalse(evidence.tested)

    def test_unsupported_base(self) -> None:
        evidence = evaluate_merge_evidence(
            ordinary(base="staging", default_branch="dev"), local_head=HEAD
        )
        self.assertFalse(evidence.can_merge)
        self.assertIn("landing_path_unsupported", evidence.test_reasons)


INVENTORY = {
    "schema_version": 1,
    "local_gates": ["npm run lint", "npm test"],
    "test_jobs": ["unit", "e2e (1)"],
}


class SuiteInventoryTests(unittest.TestCase):
    def test_inventory_validation(self) -> None:
        self.assertEqual(
            parse_suite_inventory(dict(INVENTORY, extra=["ignored"]))["test_jobs"],
            ("unit", "e2e (1)"),
        )
        for bad in (
            {},
            dict(INVENTORY, schema_version=2),
            dict(INVENTORY, local_gates=[]),
            dict(INVENTORY, test_jobs=["unit", ""]),
            dict(INVENTORY, test_jobs="unit"),
        ):
            with self.assertRaises(ValueError):
                parse_suite_inventory(bad)

    def test_record_must_list_every_inventory_gate(self) -> None:
        partial = record(gates="- `npm run lint`: passed")
        incomplete = evaluate_merge_evidence(
            ordinary(comments=[partial], suite_inventory=INVENTORY), local_head=HEAD
        )
        self.assertIn("local_test_record_incomplete", incomplete.test_reasons)
        full = record(gates="- `npm run lint`: passed\n\n- `npm test`: passed\n- `git diff --check`: passed")
        self.assertTrue(
            evaluate_merge_evidence(
                ordinary(comments=[partial, full], suite_inventory=INVENTORY), local_head=HEAD
            ).green
        )

    def test_inventory_separates_test_jobs_from_other_failures(self) -> None:
        checks = SOCKET + [
            {"name": "comment-gemini-review", "bucket": "fail", "workflow": "Gemini"},
            {"name": "unit", "bucket": "pass", "workflow": "CI"},
        ]
        full = record(gates="- `npm run lint`: passed\n- `npm test`: passed")
        triaged = evaluate_merge_evidence(
            ordinary(checks=checks, comments=[full], suite_inventory=INVENTORY), local_head=HEAD
        )
        self.assertTrue(triaged.green)
        self.assertEqual(triaged.failed_checks, ("comment-gemini-review",))
        failing = evaluate_merge_evidence(
            ordinary(
                checks=SOCKET + [{"name": "e2e (1)", "bucket": "fail", "workflow": "CI"}],
                comments=[full],
                suite_inventory=INVENTORY,
            ),
            local_head=HEAD,
        )
        self.assertIn("test_job_failed:e2e (1)", failing.test_reasons)

    def test_dependabot_needs_every_inventory_test_job_passed(self) -> None:
        passing = SOCKET + [
            {"name": "unit", "bucket": "pass", "workflow": "CI"},
            {"name": "e2e (1)", "bucket": "pass", "workflow": "CI"},
        ]
        self.assertTrue(
            evaluate_merge_evidence(
                ordinary(author="app/dependabot", checks=passing, comments=[], suite_inventory=INVENTORY),
                local_head=HEAD,
            ).green
        )
        missing = evaluate_merge_evidence(
            ordinary(
                author="app/dependabot",
                checks=SOCKET + [{"name": "unit", "bucket": "pass", "workflow": "CI"}],
                comments=[record(gates="- `npm run lint`: passed\n- `npm test`: passed")],
                suite_inventory=INVENTORY,
            ),
            local_head=HEAD,
        )
        self.assertIn("test_job_missing:e2e (1)", missing.test_reasons)
        skipped = evaluate_merge_evidence(
            ordinary(
                author="app/dependabot",
                checks=SOCKET
                + [
                    {"name": "unit", "bucket": "pass", "workflow": "CI"},
                    {"name": "e2e (1)", "bucket": "skipping", "workflow": "CI"},
                ],
                suite_inventory=INVENTORY,
            ),
            local_head=HEAD,
        )
        self.assertIn("test_job_not_passed:e2e (1)", skipped.test_reasons)

    def test_invalid_or_unreadable_inventory_fails_closed(self) -> None:
        self.assertIn(
            "suite_inventory_invalid",
            evaluate_merge_evidence(
                ordinary(suite_inventory={"schema_version": 1}), local_head=HEAD
            ).test_reasons,
        )
        self.assertIn(
            "suite_inventory_unavailable",
            evaluate_merge_evidence(
                ordinary(suite_inventory="unavailable"), local_head=HEAD
            ).test_reasons,
        )


class ReleasePathTests(unittest.TestCase):
    def test_release_checks_success_is_green(self) -> None:
        evidence = evaluate_merge_evidence(release(), local_head=HEAD)
        self.assertEqual(evidence.path, "release")
        self.assertTrue(evidence.green, evidence)

    def test_local_record_does_not_replace_release_checks(self) -> None:
        checks = SOCKET + [
            {"name": "release-gate", "bucket": "pass", "workflow": "Release"},
            {"name": "full-tests", "bucket": "skipping", "workflow": "Release"},
        ]
        evidence = evaluate_merge_evidence(
            release(checks=checks, comments=[record()]),
            local_head=HEAD,
        )
        self.assertFalse(evidence.tested)
        self.assertIn("release_check_not_success:full-tests", evidence.test_reasons)

    def test_missing_label_check_or_stale_main(self) -> None:
        self.assertIn(
            "release_label_missing",
            evaluate_merge_evidence(release(labels=[]), local_head=HEAD).test_reasons,
        )
        self.assertIn(
            "release_check_missing:release-gate",
            evaluate_merge_evidence(release(checks=list(SOCKET)), local_head=HEAD).test_reasons,
        )
        self.assertIn(
            "main_not_up_to_date",
            evaluate_merge_evidence(release(behind_by=2), local_head=HEAD).test_reasons,
        )
        self.assertIn(
            "main_up_to_date_unknown",
            evaluate_merge_evidence(release(behind_by=None), local_head=HEAD).test_reasons,
        )


class FakeGh:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        key = " ".join(args)
        for prefix, response in self.responses.items():
            if key.startswith(prefix):
                return response
        if key.startswith("api repos/acme/app/contents/.github/ci-suite.json"):
            return 1, "", "gh: Not Found (HTTP 404)"
        if key == "repo view --json nameWithOwner":
            return 0, json.dumps({"nameWithOwner": "acme/app"}), ""
        return 1, "", "unexpected call"


def view(base="main", labels=()):
    return json.dumps(
        {
            "number": 7,
            "url": "https://github.com/acme/app/pull/7",
            "state": "OPEN",
            "isDraft": False,
            "baseRefName": base,
            "headRefOid": HEAD,
            "labels": [{"name": name} for name in labels],
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "author": {"login": "octocat"},
        }
    )


class FetchTests(unittest.TestCase):
    def test_ordinary_snapshot_with_no_required_checks(self) -> None:
        gh = FakeGh(
            {
                "pr view": (0, view(), ""),
                "repo view acme/app": (0, json.dumps({"defaultBranchRef": {"name": "main"}}), ""),
                "pr checks 7 --repo acme/app --required": (
                    1,
                    "",
                    "no required checks reported on the 'feature' branch\n",
                ),
                "pr checks 7 --repo acme/app --json": (0, json.dumps(SOCKET), ""),
                "api --paginate --slurp repos/acme/app/issues/7/comments": (
                    0,
                    json.dumps(
                        [
                            [{"body": "Looks good", "author_association": "MEMBER"}],
                            [record(association="OWNER")],
                        ]
                    ),
                    "",
                ),
            }
        )
        snapshot, error = fetch_pr_snapshot(Path("."), run=gh)
        self.assertIsNone(error)
        self.assertEqual(snapshot["required_checks"], [])
        self.assertEqual(len(snapshot["checks"]), 3)
        self.assertEqual(snapshot["author"], "octocat")
        self.assertEqual(len(snapshot["comments"]), 2)
        self.assertIsNone(snapshot["behind_by"])
        self.assertFalse(any(call[:2] == ["api", "repos/acme/app/compare/main..." + HEAD] for call in gh.calls))
        self.assertTrue(evaluate_merge_evidence(snapshot, local_head=HEAD).green)

    def test_release_snapshot_reads_compare(self) -> None:
        checks = list(RELEASE_JOBS)
        gh = FakeGh(
            {
                "pr view": (0, view(labels=["release"]), ""),
                "repo view acme/app": (0, json.dumps({"defaultBranchRef": {"name": "dev"}}), ""),
                "pr checks 7 --repo acme/app --required": (0, json.dumps(checks), ""),
                "pr checks 7 --repo acme/app --json": (0, json.dumps(checks), ""),
                "api --paginate --slurp repos/acme/app/issues/7/comments": (0, "[[]]", ""),
                f"api repos/acme/app/compare/main...{HEAD}": (0, "0\n", ""),
            }
        )
        snapshot, error = fetch_pr_snapshot(Path("."), pr="7", run=gh)
        self.assertIsNone(error)
        self.assertEqual(snapshot["behind_by"], 0)
        self.assertEqual(gh.calls[0][:3], ["pr", "view", "7"])
        self.assertTrue(evaluate_merge_evidence(snapshot, local_head=HEAD).green)

    def test_required_call_with_no_checks_at_all_is_empty(self) -> None:
        gh = FakeGh(
            {
                "pr view": (0, view(), ""),
                "repo view acme/app": (0, json.dumps({"defaultBranchRef": {"name": "main"}}), ""),
                "pr checks 7 --repo acme/app --required": (
                    1,
                    "",
                    "no checks reported on the 'feature' branch\n",
                ),
                "pr checks 7 --repo acme/app --json": (
                    1,
                    "",
                    "no checks reported on the 'feature' branch\n",
                ),
                "api --paginate --slurp repos/acme/app/issues/7/comments": (
                    0,
                    json.dumps([[record(association="MEMBER")]]),
                    "",
                ),
            }
        )
        snapshot, error = fetch_pr_snapshot(Path("."), run=gh)
        self.assertIsNone(error)
        self.assertEqual(snapshot["required_checks"], [])
        self.assertEqual(snapshot["checks"], [])
        self.assertTrue(evaluate_merge_evidence(snapshot, local_head=HEAD).green)

    def test_inventory_is_read_from_the_base_branch(self) -> None:
        encoded = base64.b64encode(json.dumps(INVENTORY).encode()).decode()
        wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
        responses = {
            "pr view": (0, view(base="dev"), ""),
            "repo view acme/app": (0, json.dumps({"defaultBranchRef": {"name": "dev"}}), ""),
            "pr checks 7": (1, "", "no checks reported on the 'feature' branch\n"),
            "api --paginate --slurp repos/acme/app/issues/7/comments": (0, "[[]]", ""),
            "api repos/acme/app/contents/.github/ci-suite.json?ref=dev": (0, wrapped + "\n", ""),
        }
        snapshot, _ = fetch_pr_snapshot(Path("."), run=FakeGh(responses))
        self.assertEqual(snapshot["suite_inventory"], INVENTORY)
        responses["api repos/acme/app/contents/.github/ci-suite.json?ref=dev"] = (
            1,
            "",
            "gh: Server Error (HTTP 502)",
        )
        snapshot, _ = fetch_pr_snapshot(Path("."), run=FakeGh(responses))
        self.assertEqual(snapshot["suite_inventory"], "unavailable")
        del responses["api repos/acme/app/contents/.github/ci-suite.json?ref=dev"]
        snapshot, _ = fetch_pr_snapshot(Path("."), run=FakeGh(responses))
        self.assertIsNone(snapshot["suite_inventory"])

    def test_unknown_checks_error_is_unavailable_not_empty(self) -> None:
        gh = FakeGh(
            {
                "pr view": (0, view(), ""),
                "repo view acme/app": (0, json.dumps({"defaultBranchRef": {"name": "main"}}), ""),
                "pr checks 7": (1, "", "HTTP 502\n"),
                "api --paginate --slurp repos/acme/app/issues/7/comments": (1, "", "HTTP 502\n"),
            }
        )
        snapshot, _ = fetch_pr_snapshot(Path("."), run=gh)
        self.assertIsNone(snapshot["required_checks"])
        self.assertIsNone(snapshot["checks"])
        self.assertIsNone(snapshot["comments"])
        evidence = evaluate_merge_evidence(snapshot, local_head=HEAD)
        self.assertFalse(evidence.can_merge)
        self.assertFalse(evidence.tested)

    def test_pull_request_from_another_repository_is_rejected(self) -> None:
        gh = FakeGh(
            {
                "pr view": (0, view(), ""),
                "repo view --json nameWithOwner": (0, json.dumps({"nameWithOwner": "acme/fork"}), ""),
            }
        )
        evidence = compute_merge_evidence(
            Path("."), local_head=HEAD, pr="https://github.com/acme/app/pull/7", run=gh
        )
        self.assertFalse(evidence.green)
        self.assertEqual(evidence.merge_reasons, ("pull_request_repository_mismatch",))
        self.assertFalse(any(call[:2] == ["pr", "checks"] for call in gh.calls))

    def test_no_pull_request_is_unavailable(self) -> None:
        gh = FakeGh({"pr view": (1, "", "no pull requests found")})
        evidence = compute_merge_evidence(Path("."), local_head=HEAD, run=gh)
        self.assertEqual(evidence.path, "unavailable")
        self.assertFalse(evidence.green)
        self.assertEqual(evidence.merge_reasons, ("pull_request_unavailable",))


if __name__ == "__main__":
    unittest.main()
