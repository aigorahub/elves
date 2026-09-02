"""Fugu is optional: an unavailable review route reroutes, it does not stop the run.

Quota, authentication, catalog, runner, timeout, and provider failures each pick
another available independent reviewer, record requested route, actual route, and
fallback reason, and never claim a review ran. Claude Code, Codex, Grok Build, and
Oh My Pi share one selector.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.review_routes import (  # noqa: E402
    NATIVE_REVIEW_ROUTES,
    OPTIONAL_REVIEW_ROUTES,
    REVIEW_ROUTE_FAILURE_REASONS,
    SUPPORTED_REVIEW_HOSTS,
    ReviewRouteProbe,
    classify_review_route_failure,
    normalize_review_route_reason,
    review_claim,
    review_route_blocks_run,
    route_unavailable_directive,
    select_review_route,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


ALL_OPTIONAL_DOWN = tuple(
    ReviewRouteProbe(name=name, available=False, reason="provider")
    for name in OPTIONAL_REVIEW_ROUTES
)


class FailureClassificationTests(unittest.TestCase):
    def test_named_failure_classes_are_recognized(self) -> None:
        cases = {
            "quota": "Error: subscription limit reached for this account",
            "authentication": "HTTP 401 Unauthorized: check your API key",
            "catalog": "installed catalog does not offer fugu-cyber/xhigh",
            "runner": "codex-fugu: command not found",
            "timeout": "Fugu ended (wall timeout) with no salvageable output",
        }
        for expected, text in cases.items():
            self.assertEqual(classify_review_route_failure(text=text), expected, text)

    def test_catalog_wins_over_runner_for_model_not_found(self) -> None:
        self.assertEqual(
            classify_review_route_failure(text="Error: model not found"), "catalog"
        )

    def test_exit_codes_classify_without_text(self) -> None:
        self.assertEqual(classify_review_route_failure(exit_code=124), "timeout")
        self.assertEqual(classify_review_route_failure(exit_code=127), "runner")
        self.assertEqual(classify_review_route_failure(exit_code=3), "provider")

    def test_success_is_not_a_failure(self) -> None:
        self.assertIsNone(classify_review_route_failure(exit_code=0))
        self.assertIsNone(classify_review_route_failure(text="ordered P0-P3 findings"))

    def test_an_explicit_success_code_outranks_failure_wording(self) -> None:
        # A clean review log may still discuss timeouts, keys, or missing files.
        for text in (
            "P2: the caller should retry on timeout",
            "the api key is never logged",
            "returns 403 when unauthorized",
            "module not found is handled",
        ):
            self.assertIsNone(
                classify_review_route_failure(exit_code=0, text=text), text
            )
            # Without an exit code the text still decides.
            self.assertIsNotNone(classify_review_route_failure(text=text), text)

    def test_reason_vocabulary_is_closed(self) -> None:
        self.assertEqual(normalize_review_route_reason("Quota"), "quota")
        self.assertEqual(normalize_review_route_reason("not-independent"), "not_independent")
        self.assertEqual(normalize_review_route_reason("weird"), "unknown")
        self.assertEqual(normalize_review_route_reason(None), "unknown")
        for reason in ("quota", "authentication", "catalog", "runner", "timeout", "provider"):
            self.assertIn(reason, REVIEW_ROUTE_FAILURE_REASONS)


class RouteSelectionTests(unittest.TestCase):
    def test_working_explicit_route_is_preserved(self) -> None:
        decision = select_review_route(
            host="claude-code",
            requested="fugu",
            probes=(ReviewRouteProbe("fugu", True), ReviewRouteProbe("grok", True)),
        )
        self.assertEqual(decision.actual_route, "fugu")
        self.assertIsNone(decision.fallback_reason)
        self.assertIn("explicit_user_route_preserved", decision.notes)

    def test_each_failure_class_selects_another_available_reviewer(self) -> None:
        for reason in ("quota", "authentication", "catalog", "runner", "timeout", "provider"):
            decision = select_review_route(
                host="claude-code",
                requested="fugu",
                probes=(
                    ReviewRouteProbe("fugu", False, reason),
                    ReviewRouteProbe("grok", True),
                ),
            )
            self.assertEqual(decision.actual_route, "grok", reason)
            self.assertEqual(decision.fallback_reason, f"fugu:{reason}")
            self.assertEqual(decision.status, "selected")
            self.assertFalse(review_route_blocks_run(decision, required=True), reason)

    def test_native_reviewer_is_preferred_when_no_optional_provider_works(self) -> None:
        decision = select_review_route(
            host="grok-build", requested="fugu", probes=ALL_OPTIONAL_DOWN
        )
        self.assertEqual(decision.actual_route, NATIVE_REVIEW_ROUTES["grok-build"])
        self.assertEqual(decision.kind, "native")
        self.assertIn(
            "native_reviewer_preferred_when_no_optional_provider", decision.notes
        )
        self.assertIn("fugu:provider", decision.fallback_reason or "")

    def test_implementer_cannot_review_itself(self) -> None:
        decision = select_review_route(
            host="claude-code",
            requested="grok",
            probes=(ReviewRouteProbe("grok", True), ReviewRouteProbe("omp", True)),
            exclude=("grok",),
        )
        self.assertEqual(decision.actual_route, "omp")
        self.assertIn("grok:not_independent", decision.fallback_reason or "")

    def test_unprobed_optional_route_is_unconfigured_not_selected(self) -> None:
        decision = select_review_route(host="codex", requested="fugu")
        self.assertEqual(decision.actual_route, NATIVE_REVIEW_ROUTES["codex"])
        self.assertIn("fugu:unconfigured", decision.fallback_reason or "")

    def test_no_route_at_all_is_unavailable_and_never_claims_a_review(self) -> None:
        probes = ALL_OPTIONAL_DOWN + (
            ReviewRouteProbe(NATIVE_REVIEW_ROUTES["omp"], False, "runner"),
        )
        decision = select_review_route(host="omp", requested="fugu", probes=probes)
        self.assertIsNone(decision.actual_route)
        self.assertEqual(decision.status, "unavailable")
        self.assertIn("do_not_claim_a_review_ran", decision.notes)
        self.assertTrue(review_route_blocks_run(decision, required=True))
        self.assertFalse(review_route_blocks_run(decision, required=False))

    def test_default_route_records_no_fallback(self) -> None:
        decision = select_review_route(
            host="claude-code", probes=(ReviewRouteProbe("fugu", True),)
        )
        self.assertEqual(decision.actual_route, "fugu")
        self.assertIsNone(decision.fallback_reason)
        self.assertIn("default_route_selected", decision.notes)

    def test_unknown_host_fails_closed(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            select_review_route(host="not-a-host")
        self.assertEqual(ctx.exception.code, "unknown_review_host")

    def test_available_probe_may_not_carry_a_failure_reason(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            ReviewRouteProbe("fugu", True, "quota")
        self.assertEqual(ctx.exception.code, "invalid_review_route_probe")


class ReviewClaimTests(unittest.TestCase):
    def test_a_selected_route_alone_is_not_a_review(self) -> None:
        decision = select_review_route(
            host="claude-code", probes=(ReviewRouteProbe("fugu", True),)
        )
        self.assertFalse(review_claim(decision, report_produced=False)["review_ran"])
        self.assertTrue(review_claim(decision, report_produced=True)["review_ran"])

    def test_an_unavailable_route_can_never_claim_a_review(self) -> None:
        probes = ALL_OPTIONAL_DOWN + (
            ReviewRouteProbe(NATIVE_REVIEW_ROUTES["codex"], False, "runner"),
        )
        decision = select_review_route(host="codex", probes=probes)
        claim = review_claim(decision, report_produced=True)
        self.assertFalse(claim["review_ran"])
        self.assertEqual(claim["claim"], "no review ran on this tip")


    def test_claim_and_decision_expose_the_same_route_keys(self) -> None:
        decision = select_review_route(
            host="claude-code", probes=(ReviewRouteProbe("fugu", True),)
        )
        claim = review_claim(decision, report_produced=False)
        self.assertTrue(set(decision.to_dict()).issubset(set(claim)))
        for key in decision.to_dict():
            self.assertEqual(claim[key], decision.to_dict()[key], key)


class CrossHarnessParityTests(unittest.TestCase):
    def test_every_supported_host_has_a_native_reviewer(self) -> None:
        self.assertEqual(
            set(SUPPORTED_REVIEW_HOSTS),
            {"claude-code", "codex", "grok-build", "omp"},
        )
        for host in SUPPORTED_REVIEW_HOSTS:
            decision = select_review_route(
                host=host, requested="fugu", probes=ALL_OPTIONAL_DOWN
            )
            self.assertEqual(decision.actual_route, NATIVE_REVIEW_ROUTES[host], host)
            self.assertFalse(review_route_blocks_run(decision, required=True), host)

    def test_every_host_records_the_same_ledger_keys(self) -> None:
        for host in SUPPORTED_REVIEW_HOSTS:
            payload = select_review_route(
                host=host,
                requested="fugu",
                probes=(
                    ReviewRouteProbe("fugu", False, "quota"),
                    ReviewRouteProbe("grok", True),
                ),
            ).to_dict()
            self.assertEqual(
                set(payload),
                {
                    "requested_route",
                    "actual_route",
                    "fallback_reason",
                    "status",
                    "host",
                    "kind",
                    "considered",
                    "notes",
                },
                host,
            )

    def test_every_optional_runner_emits_the_reroute_directive(self) -> None:
        for rel in ("scripts/run_grok.sh", "scripts/run_omp.sh"):
            body = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("route_unavailable_directive", body, rel)
            self.assertIn("classify_review_route_failure", body, rel)
        fugu = (REPO_ROOT / "scripts" / "cobbler_runtime" / "fugu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_review_route_helpers", fugu)

    def test_directive_names_the_reroute_and_the_probe_command(self) -> None:
        line = route_unavailable_directive("Fugu", "quota")
        self.assertIn("[quota]", line)
        self.assertIn("select another available", line)
        self.assertIn("review-route", line)
        self.assertIn("--unavailable fugu=quota", line)
        self.assertIn("does not block the run", line)


class ReviewRouteCliTests(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "cobbler_agents.py"), "review-route", *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO_ROOT),
        )
        return proc.returncode, proc.stdout

    def test_cli_reroutes_and_reports_the_fallback(self) -> None:
        code, out = self._run(
            "--host",
            "claude-code",
            "--requested",
            "fugu",
            "--unavailable",
            "fugu=quota",
            "--available",
            "grok",
            "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["requested_route"], "fugu")
        self.assertEqual(payload["actual_route"], "grok")
        self.assertEqual(payload["fallback_reason"], "fugu:quota")
        self.assertFalse(payload["review_ran"])
        self.assertFalse(payload["blocked"])

    def test_cli_blocks_only_when_required_and_no_route_exists(self) -> None:
        args = [
            "--host",
            "omp",
            "--requested",
            "fugu",
            "--json",
        ]
        for name in OPTIONAL_REVIEW_ROUTES:
            args.extend(["--unavailable", f"{name}=provider"])
        args.extend(["--unavailable", f"{NATIVE_REVIEW_ROUTES['omp']}=runner"])

        code, out = self._run(*args)
        payload = json.loads(out)
        self.assertIsNone(payload["actual_route"])
        self.assertFalse(payload["blocked"])
        self.assertEqual(code, 3)

        code, out = self._run(*args, "--required")
        payload = json.loads(out)
        self.assertTrue(payload["blocked"])
        self.assertEqual(code, 1)

    def test_cli_rejects_an_unknown_host(self) -> None:
        code, _ = self._run("--host", "nope", "--json")
        self.assertEqual(code, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
