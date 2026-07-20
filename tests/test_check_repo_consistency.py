from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_repo_consistency.py"


def load_consistency_module():
    spec = importlib.util.spec_from_file_location("check_repo_consistency_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load check_repo_consistency module for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ConsistencyPhraseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.consistency = load_consistency_module()

    def test_find_missing_phrases_reports_required_reviewed_landing_phrase(self) -> None:
        errors = self.consistency.find_missing_phrases(
            {"SKILL.md": "Reviewed PR Landing Command"},
            {"SKILL.md": ["Reviewed PR Landing Command", "gh pr merge --merge"]},
            "reviewed-PR landing",
        )

        self.assertEqual(
            errors,
            ["SKILL.md: missing reviewed-PR landing phrase `gh pr merge --merge`"],
        )

    def test_find_forbidden_phrases_reports_stale_merge_policy(self) -> None:
        stale = (
            "Only if the user has set a merge-on-green preference in Run Control "
            "do you merge yourself"
        )

        errors = self.consistency.find_forbidden_phrases(
            {"SKILL.md": stale},
            {"SKILL.md": [stale]},
            "reviewed-PR landing",
        )

        self.assertEqual(
            errors,
            [f"SKILL.md: stale reviewed-PR landing phrase `{stale}`"],
        )

    def test_reviewed_pr_forbidden_corpus_catches_kickoff_merge_policy(self) -> None:
        label = "references/kickoff-prompt-template.md"
        stale = "merge policy (default: you never merge; opt-in: merge-commit-on-green)"

        self.assertIn(label, self.consistency.REVIEWED_PR_LANDING_FORBIDDEN_PHRASES)
        self.assertIn(stale, self.consistency.REVIEWED_PR_LANDING_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.REVIEWED_PR_LANDING_FORBIDDEN_PHRASES,
            "reviewed-PR landing",
        )

        self.assertEqual(
            errors,
            [f"{label}: stale reviewed-PR landing phrase `{stale}`"],
        )

    def test_reviewed_pr_forbidden_corpus_catches_kickoff_final_readiness_drift(self) -> None:
        label = "references/kickoff-prompt-template.md"
        stale = "only if the user explicitly set a merge-on-green preference"

        self.assertIn(label, self.consistency.REVIEWED_PR_LANDING_FORBIDDEN_PHRASES)
        self.assertIn(stale, self.consistency.REVIEWED_PR_LANDING_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.REVIEWED_PR_LANDING_FORBIDDEN_PHRASES,
            "reviewed-PR landing",
        )

        self.assertEqual(
            errors,
            [f"{label}: stale reviewed-PR landing phrase `{stale}`"],
        )

    def test_reviewed_pr_landing_aliases_are_required_on_user_facing_surfaces(self) -> None:
        for label in ("SKILL.md", "README.md"):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.REVIEWED_PR_LANDING_PHRASES)
                self.assertIn("\\land-pr", self.consistency.REVIEWED_PR_LANDING_PHRASES[label])
                self.assertIn("/land-pr", self.consistency.REVIEWED_PR_LANDING_PHRASES[label])
        # AGENTS is a thin Codex adapter; pins land-pr aliases via pointer corpus.
        agents = self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"]
        self.assertTrue(any("land-pr" in p for p in agents))

    def test_single_kickoff_corpus_covers_primary_user_and_agent_surfaces(self) -> None:
        # README links to the contracts instead of restating them (plan B5);
        # version narration lives only in CHANGELOG.md.
        for label in (
            "SKILL.md",
            "references/kickoff-prompt-template.md",
            "references/e2e-chat-to-land.md",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.SINGLE_KICKOFF_PHRASES)
                self.assertTrue(self.consistency.SINGLE_KICKOFF_PHRASES[label])

    def test_grok_worker_corpus_covers_every_claimed_public_surface(self) -> None:
        required = {
            "SKILL.md",
            "CHANGELOG.md",
            "docs/elves/learnings.md",
            "references/adaptive-worker-routing.md",
            "references/cobbler-setup-recipes.md",
            "references/grok-implementer-launch-prompt.md",
            "references/grok-open-source-worker.md",
            "guide/index.html",
            "references/host-parity.md",
        }
        self.assertEqual(
            set(self.consistency.GROK_OPEN_SOURCE_WORKER_PHRASES), required
        )
        for label, phrases in self.consistency.GROK_OPEN_SOURCE_WORKER_PHRASES.items():
            with self.subTest(label=label):
                self.assertTrue(any("one-packet" in phrase for phrase in phrases))
        for label in (
            "references/grok-open-source-worker.md",
            "guide/index.html",
            "references/host-parity.md",
        ):
            with self.subTest(terminal_evidence=label):
                self.assertTrue(
                    any(
                        "terminal" in phrase
                        for phrase in self.consistency.GROK_OPEN_SOURCE_WORKER_PHRASES[
                            label
                        ]
                    )
                )

    def test_prewalk_corpus_pins_trajectory_not_cold_handoff_claims(self) -> None:
        required = {
            "SKILL.md",
            "AGENTS.md",
            "README.md",
            "references/prewalk.md",
            "references/host-parity.md",
            "references/adaptive-worker-routing.md",
            "guide/index.html",
            "CHANGELOG.md",
        }
        self.assertEqual(set(self.consistency.PREWALK_PHRASES), required)
        for label, phrases in self.consistency.PREWALK_PHRASES.items():
            with self.subTest(label=label):
                self.assertTrue(phrases)
        joined = " ".join(self.consistency.PREWALK_PHRASES["SKILL.md"])
        self.assertIn("fresh session", joined.casefold())
        self.assertIn("post-edit cold fallback", joined)

    def test_worker_confidence_corpus_pins_runtime_and_host_parity(self) -> None:
        required = {
            "SKILL.md",
            "README.md",
            "guide/index.html",
            "references/review-subagent.md",
            "references/host-parity.md",
            "scripts/cobbler_agents.py",
            "scripts/cobbler_runtime/full_run.py",
        }
        self.assertTrue(
            required.issubset(self.consistency.WORKER_CONFIDENCE_SIGNAL_PHRASES)
        )
        runtime = " ".join(
            self.consistency.WORKER_CONFIDENCE_SIGNAL_PHRASES[
                "scripts/cobbler_runtime/full_run.py"
            ]
        )
        parity = " ".join(
            self.consistency.WORKER_CONFIDENCE_SIGNAL_PHRASES[
                "references/host-parity.md"
            ]
        )
        self.assertIn("confidence_can_reduce_scope", runtime)
        self.assertIn("missing_signal_falls_back_to_full_review", runtime)
        self.assertIn("review_prompt_block", parity)

    def test_parallelves_corpus_pins_serial_default_and_recommend_only(self) -> None:
        required = {
            "references/parallelves.md",
            "references/glossary.md",
            "references/plan-template.md",
        }
        self.assertTrue(
            required.issubset(self.consistency.PARALLELVES_CONTRACT_PHRASES)
        )
        for label, phrases in self.consistency.PARALLELVES_CONTRACT_PHRASES.items():
            with self.subTest(label=label):
                self.assertTrue(phrases)
        contract = " ".join(
            self.consistency.PARALLELVES_CONTRACT_PHRASES[
                "references/parallelves.md"
            ]
        )
        template = " ".join(
            self.consistency.PARALLELVES_CONTRACT_PHRASES[
                "references/plan-template.md"
            ]
        )
        self.assertIn("Serial remains the default everywhere.", contract)
        self.assertIn("Nothing auto-launches.", contract)
        self.assertIn(
            "parallel_declined:worker_dominance:no_recorded_timings", contract
        )
        self.assertIn("Omitting this section means serial (the default).", template)

    def test_prewalk_corpus_rejects_summary_only_approximation(self) -> None:
        errors = self.consistency.find_missing_phrases(
            {"SKILL.md": "Prewalk starts a new worker from a summary."},
            {"SKILL.md": self.consistency.PREWALK_PHRASES["SKILL.md"]},
            "exact-session prewalk",
        )
        self.assertTrue(errors)
        self.assertTrue(any("fresh session" in error for error in errors))

    def test_explicit_handoff_corpus_pins_opt_in_without_prewalk_claim(self) -> None:
        required = {
            "SKILL.md",
            "AGENTS.md",
            "README.md",
            "references/schema-and-acceptance.md",
            "references/survival-guide-template.md",
            "CHANGELOG.md",
        }
        self.assertEqual(
            set(self.consistency.EXPLICIT_HANDOFF_V1_PHRASES),
            required,
        )
        schema = " ".join(
            self.consistency.EXPLICIT_HANDOFF_V1_PHRASES[
                "references/schema-and-acceptance.md"
            ]
        )
        self.assertIn("Presence is the opt-in", schema)
        self.assertIn("not trajectory continuity", schema)

    def test_explicit_handoff_corpus_rejects_mandatory_prewalk_approximation(self) -> None:
        errors = self.consistency.find_missing_phrases(
            {
                "SKILL.md": (
                    "Every delegated run must include a packet capsule; that capsule proves prewalk."
                )
            },
            {
                "SKILL.md": self.consistency.EXPLICIT_HANDOFF_V1_PHRASES[
                    "SKILL.md"
                ]
            },
            "explicit handoff v1",
        )
        self.assertTrue(errors)
        self.assertTrue(any("advisory, never" in error for error in errors))

    def test_grok_worker_consistency_rejects_stale_fixed_model_policy(self) -> None:
        label = "docs/elves/learnings.md"
        stale = "use permitted Grok Composer 2.5 Fast for regular clear work"
        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            {label: self.consistency.GROK_OPEN_SOURCE_WORKER_FORBIDDEN_PHRASES[label]},
            "open-source Grok worker",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn(stale, errors[0])

    def test_grok_worker_consistency_rejects_status_only_goal_claim(self) -> None:
        label = "references/grok-open-source-worker.md"
        phrases = self.consistency.GROK_OPEN_SOURCE_WORKER_PHRASES[label]
        text = "The /goal status probe proves command resolution."
        errors = self.consistency.find_missing_phrases(
            {label: text}, {label: phrases}, "open-source Grok worker"
        )
        self.assertTrue(errors)
        self.assertTrue(any("terminal state" in error for error in errors))
        self.assertTrue(any("one-packet fallback" in error for error in errors))

    def test_public_persona_wording_flags_claims_but_passes_model_identifiers(
        self,
    ) -> None:
        patterns = {
            "README.md": self.consistency.PUBLIC_WORDING_FORBIDDEN_PATTERNS
        }
        for claim in (
            "Cobbler is powered by Fable.",
            "The workflow is Powered By FABLE under new branding.",
            "built on Fable technology",
            "the run is backed by Fable",
            "with Fable under the hood",
            "adopts a Fable persona",
        ):
            with self.subTest(claim=claim):
                errors = self.consistency.find_forbidden_patterns(
                    {"README.md": claim}, patterns, "public persona wording"
                )
                self.assertTrue(errors, claim)
        for legitimate in (
            "Fable 5 at `max`/`ultra` routes to the same Fable 5 model at `low`.",
            "the exact model id is `claude-fable-5`",
            "Claude Fable 5 is the observed route identity",
        ):
            with self.subTest(legitimate=legitimate):
                errors = self.consistency.find_forbidden_patterns(
                    {"README.md": legitimate},
                    patterns,
                    "public persona wording",
                )
                self.assertEqual(errors, [], legitimate)

    def test_grok_upstream_commit_pin_cross_check_agrees_and_disagrees(self) -> None:
        agreeing = self.consistency.grok_upstream_commit_pin_errors()
        self.assertEqual(agreeing, [])
        # A one-sided bump of the runtime constant fails.
        disagreeing = self.consistency.grok_upstream_commit_pin_errors(
            "deadbeef" + "0" * 32
        )
        self.assertTrue(disagreeing)
        self.assertTrue(
            any("not a prefix" in error for error in disagreeing), disagreeing
        )
        # The pinned short SHA is a genuine prefix of the runtime constant, so
        # a one-sided doc-pin bump fails the same cross-check symmetrically.
        pins = [
            phrase
            for phrase in self.consistency.GROK_OPEN_SOURCE_WORKER_PHRASES[
                "references/grok-open-source-worker.md"
            ]
            if "source commit `" in phrase
        ]
        self.assertTrue(pins)

    def test_single_kickoff_forbidden_corpus_catches_legacy_default_drift(self) -> None:
        label = "README.md"
        stale = "**Two-step operator flow**"
        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.SINGLE_KICKOFF_FORBIDDEN_PHRASES,
            "single-kickoff E2E",
        )
        self.assertEqual(
            errors,
            [f"{label}: stale single-kickoff E2E phrase `{stale}`"],
        )

    def test_semantic_single_kickoff_mutation_fails_without_legacy_scope(self) -> None:
        label = "README.md"
        mutation = (
            "Single kickoff is recommended. Stop after staging, then wait for another "
            "launch command."
        )
        errors = self.consistency.find_unscoped_patterns(
            {label: mutation},
            {label: self.consistency.SINGLE_KICKOFF_UNSCOPED_PATTERNS[label]},
            "single-kickoff contradiction",
            scope_word="legacy",
        )
        self.assertTrue(errors)

        scoped = "Legacy two-call only: stop after staging, then wait for another launch command."
        self.assertEqual(
            self.consistency.find_unscoped_patterns(
                {label: scoped},
                {label: self.consistency.SINGLE_KICKOFF_UNSCOPED_PATTERNS[label]},
                "single-kickoff contradiction",
                scope_word="legacy",
            ),
            [],
        )

    def test_full_run_command_wildcard_is_rejected(self) -> None:
        label = "README.md"
        errors = self.consistency.find_forbidden_patterns(
            {label: "run implement full-run-* now"},
            {label: self.consistency.EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS[label]},
            "full-run command wildcard",
        )
        self.assertTrue(errors)

    def test_installed_helper_path_contract_covers_both_hosts_and_readiness(self) -> None:
        for label in ("SKILL.md",):
            with self.subTest(label=label):
                phrases = self.consistency.INSTALLED_HELPER_PATH_PHRASES[label]
                self.assertIn("~/.claude/skills/elves", phrases)
                self.assertIn("~/.codex/skills/elves", phrases)
                self.assertIn(
                    "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py",
                    phrases,
                )
                self.assertIn(
                    "installed Elves bundle never requires a repo-only helper",
                    phrases,
                )
        # AGENTS thin adapter still pins installed helper path identity.
        agents = self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"]
        self.assertTrue(any("ELVES_SKILL_ROOT" in p or "skill root" in p for p in agents))

    def test_installed_surfaces_reject_executable_repo_only_helper(self) -> None:
        label = "SKILL.md"
        errors = self.consistency.find_forbidden_patterns(
            {label: "python3 scripts/verify_repo.py --ci --version 9.9.9"},
            {
                label: self.consistency.INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS[
                    label
                ]
            },
            "installed repo-only helper",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("installed repo-only helper", errors[0])

    def test_main_rejects_repo_only_helper_regression_in_installed_docs(self) -> None:
        skill_path = self.consistency.REPO_ROOT / "SKILL.md"
        original_read_text = self.consistency.read_text

        def fake_read_text(path: Path) -> str:
            text = original_read_text(path)
            if path == skill_path:
                return text + "\npython3 scripts/verify_repo.py --ci --version 9.9.9\n"
            return text

        self.consistency.read_text = fake_read_text
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                exit_code = self.consistency.main()
        finally:
            self.consistency.read_text = original_read_text

        self.assertEqual(exit_code, 1)
        self.assertIn("installed repo-only helper", output.getvalue())

    def test_landing_check_contract_requires_installed_exact_session_form(self) -> None:
        for label, phrases in self.consistency.LANDING_CHECK_CONTRACT_PHRASES.items():
            with self.subTest(label=label):
                self.assertIn(
                    "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py", phrases
                )
                self.assertIn("--session <session-path> --repo-root .", phrases)
                if label == "AGENTS.md":
                    # Thin Codex adapter pins the installed helper path; equality
                    # assertion detail lives in SKILL.md / survival guide.
                    continue
                self.assertIn("equality assertion", phrases)

    def test_normative_surfaces_reject_bare_landing_check_path(self) -> None:
        for label, patterns in self.consistency.LANDING_CHECK_BARE_FORBIDDEN_PATTERNS.items():
            with self.subTest(label=label):
                errors = self.consistency.find_forbidden_patterns(
                    {label: "Run python3 scripts/elves_landing_check.py before landing."},
                    {label: patterns},
                    "bare landing-check path",
                )
                self.assertEqual(len(errors), 1)

    def test_codex_goals_exact_paths_are_section_scoped(self) -> None:
        # Local fixture corpus: the real corpora no longer require a README
        # Codex Goals section (plan B5), but the scoping function must still work.
        label = "README.md"
        fixture_phrases = {label: ["`survival_guide_path`", "do not substitute generic filenames"]}
        fixture_headings = {label: "### Codex Goals"}
        valid_section = """### Codex Goals
Read `.elves-session.json` first and resolve `survival_guide_path`, `learnings_path`,
`plan_path`, and `execution_log_path`; do not substitute generic filenames.
"""
        errors = self.consistency.find_missing_section_phrases(
            {label: valid_section},
            fixture_phrases,
            fixture_headings,
            "Codex Goals exact-path",
        )
        self.assertEqual(errors, [])

        misplaced = """### Codex Goals
Use Goals for continuation.

### Other
Read `.elves-session.json` first and resolve `survival_guide_path`, `learnings_path`,
`plan_path`, and `execution_log_path`; do not substitute generic filenames.
"""
        errors = self.consistency.find_missing_section_phrases(
            {label: misplaced},
            fixture_phrases,
            fixture_headings,
            "Codex Goals exact-path",
        )
        self.assertTrue(errors)

    def test_codex_goals_section_rejects_generic_paths(self) -> None:
        label = "README.md"
        section = "### Codex Goals\nRead docs/elves/survival-guide.md first.\n"
        errors = self.consistency.find_forbidden_phrases(
            {label: section},
            self.consistency.CODEX_GOALS_SECTION_FORBIDDEN_PHRASES,
            "Codex Goals generic-path",
        )
        self.assertEqual(len(errors), 1)

    def test_implementer_handoff_phrases_cover_skill_and_templates(self) -> None:
        for label in (
            "SKILL.md",
                        "references/plan-template.md",
            "references/survival-guide-template.md",
            "references/execution-log-template.md",
            "references/review-subagent.md",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.IMPLEMENTER_HANDOFF_PHRASES)
                self.assertIn(
                    "acceptance evidence",
                    self.consistency.IMPLEMENTER_HANDOFF_PHRASES[label],
                )
        # AGENTS carries the handoff names via the whole-file pointer corpus.
        pointer = self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"]
        for needle in ("Build On", "owned surfaces", "forbidden surfaces", "acceptance evidence"):
            self.assertIn(needle, pointer)


    def test_progress_commit_phrases_forbid_vague_examples_as_positive(self) -> None:
        for label in ("SKILL.md",):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.PROGRESS_COMMIT_PHRASES)
                self.assertIn(
                    "Contract|Implement|Validate|Review|Close",
                    " ".join(self.consistency.PROGRESS_COMMIT_PHRASES[label]),
                )
                self.assertIn(label, self.consistency.PROGRESS_COMMIT_ANTIPATTERN_EXAMPLES)
        # AGENTS thin adapter carries the anti-pattern examples via the pointer corpus.
        agents_pointer = " ".join(self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"])
        self.assertIn("Batch 3/12] Updates", agents_pointer)
        # Anti-pattern corpus must include vague subjects so they stay labeled bad.
        self.assertIn(
            "[feat/payments · Batch 3/12] Updates",
            self.consistency.PROGRESS_COMMIT_ANTIPATTERN_EXAMPLES["SKILL.md"],
        )

    def test_cobbler_and_council_aliases_are_required_on_user_facing_surfaces(self) -> None:
        for label in ("SKILL.md", "README.md"):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.COUNCIL_MODULE_PHRASES)
                joined = " ".join(self.consistency.COUNCIL_MODULE_PHRASES[label])
                self.assertIn("/cobbler", joined)
                self.assertTrue(
                    "$elves cobbler" in joined or "$elves cobbler: <task>" in joined
                )
                if label == "README.md":
                    # README carries user-facing invocations; contracts live in SKILL.
                    continue
                if label == "SKILL.md":
                    self.assertIn("/council", joined)
                    self.assertIn("/ec", joined)
                    self.assertIn("/elves-council", joined)
                    self.assertIn("$elves council: <task>", joined)

    def test_codex_cobbler_guardrails_are_required(self) -> None:
        self.assertIn(
            "Cobbler-first coordination is the default for Elves runs",
            self.consistency.COUNCIL_MODULE_PHRASES["SKILL.md"],
        )
        self.assertIn(
            "Quick Cobbler is the default one-off answer mode",
            self.consistency.COUNCIL_MODULE_PHRASES["SKILL.md"],
        )
        self.assertIn(
            "do not assume Codex has a top-level `/cobbler` command",
            self.consistency.COUNCIL_MODULE_PHRASES["SKILL.md"],
        )
        self.assertIn(
            "Codex users should not need or expect a top-level `/cobbler` command",
            self.consistency.COUNCIL_MODULE_PHRASES["README.md"],
        )
        self.assertIn(
            "Codex Goals are not required for Quick Cobbler",
            self.consistency.COUNCIL_MODULE_PHRASES["references/codex-goals.md"],
        )
        codex_goal_phrases = self.consistency.COUNCIL_MODULE_PHRASES[
            "references/codex-goals.md"
        ]
        for field in (
            "survival_guide_path",
            "learnings_path",
            "plan_path",
            "execution_log_path",
        ):
            with self.subTest(session_field=field):
                self.assertIn(f"`{field}`", codex_goal_phrases)
        self.assertIn("do not substitute generic filenames", codex_goal_phrases)
        for stale_path in (
            "docs/elves/survival-guide.md",
            "docs/plans/my-plan.md",
            "docs/elves/execution-log.md",
        ):
            with self.subTest(stale_path=stale_path):
                self.assertIn(
                    stale_path,
                    self.consistency.COUNCIL_FORBIDDEN_PHRASES[
                        "references/codex-goals.md"
                    ],
                )
        self.assertIn(
            "Do not document Codex as having a top-level `/cobbler`",
            self.consistency.COUNCIL_MODULE_PHRASES["references/council-workflow.md"],
        )

    def test_cobbler_first_run_coordination_is_required(self) -> None:
        expected = {
            "SKILL.md": "Cobbler-first coordination is the default for Elves runs",
            "references/council-workflow.md": (
                "Run Cobbler is the default coordination pattern inside an Elves run"
            ),
            "references/survival-guide-template.md": "Coordination mode",
            "config.json.example": '"coordination_default": "cobbler-first"',
        }

        for label, phrase in expected.items():
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.COUNCIL_MODULE_PHRASES)
                if label == "AGENTS.md":
                    # Thin adapter: pointer corpus, not dual-fork Cobbler prose.
                    self.assertTrue(self.consistency.COUNCIL_MODULE_PHRASES[label])
                    continue
                self.assertIn(phrase, self.consistency.COUNCIL_MODULE_PHRASES[label])

    def test_cobbler_mode_guardrails_are_required(self) -> None:
        expected = {
            "SKILL.md": "cobbler-mode",
            "references/council-workflow.md": "not a third Cobbler behavior mode",
            "aliases/claude/cobbler-mode/SKILL.md": "/cobbler-mode",
        }

        for label, phrase in expected.items():
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.COBBLER_MODE_PHRASES)
                self.assertIn(phrase, self.consistency.COBBLER_MODE_PHRASES[label])

    def test_codex_cobbler_forbidden_phrases_catch_slash_command_drift(self) -> None:
        label = "README.md"
        stale = "Use `/cobbler` in Codex"

        self.assertIn(stale, self.consistency.COUNCIL_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.COUNCIL_FORBIDDEN_PHRASES,
            "Cobbler",
        )

        self.assertEqual(errors, [f"{label}: stale Cobbler phrase `{stale}`"])

    def test_cobbler_mode_forbidden_patterns_catch_sticky_state_drift(self) -> None:
        label = "README.md"
        text = "Cobbler Mode persists across threads. Cobbler Mode starts an Elves run."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.COBBLER_FORBIDDEN_PATTERNS,
            "Cobbler",
        )

        self.assertIn(
            (
                "README.md: stale Cobbler pattern "
                "`\\bcobbler\\s+mode\\s+persists\\s+across\\s+threads\\b`"
            ),
            errors,
        )
        self.assertIn(
            (
                "README.md: stale Cobbler pattern "
                "`\\bcobbler\\s+mode\\s+starts\\s+an?\\s+elves\\s+run\\b`"
            ),
            errors,
        )

    def test_quick_cobbler_forbidden_patterns_catch_read_only_exceptions(self) -> None:
        label = "references/council-workflow.md"
        text = "Quick Cobbler is read-only unless the user wants implementation."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.COBBLER_FORBIDDEN_PATTERNS,
            "Cobbler",
        )

        self.assertEqual(
            errors,
            [
                (
                    "references/council-workflow.md: stale Cobbler pattern "
                    "`\\bquick\\s+cobbler\\b[^.\\n]*(?:unless|except)\\b[^.\\n]*"
                    "(?:active\\s+elves\\s+run|implementation|edit|mutate)\\b`"
                )
            ],
        )

    def test_codex_cobbler_install_guidance_is_required(self) -> None:
        label = "README.md"
        phrase = "Codex installs the main skill bundle only"

        self.assertIn(label, self.consistency.CODEX_INSTALL_COBBLER_PHRASES)
        self.assertIn(phrase, self.consistency.CODEX_INSTALL_COBBLER_PHRASES[label])

        errors = self.consistency.find_missing_phrases(
            {label: "Codex install docs without the Cobbler reminder"},
            {label: [phrase]},
            "Codex Cobbler install",
        )

        self.assertIn(
            f"{label}: missing Codex Cobbler install phrase `{phrase}`",
            errors,
        )

    def test_cobbler_config_precedence_guidance_is_required(self) -> None:
        label = "SKILL.md"
        # Compact 2.3 pins config.json + cobbler precedence without the long 2.2 sentence.
        phrase = "cobbler"

        self.assertIn(label, self.consistency.COBBLER_CONFIG_PREFERENCE_PHRASES)
        self.assertIn(phrase, self.consistency.COBBLER_CONFIG_PREFERENCE_PHRASES[label])
        self.assertIn("config.json", self.consistency.COBBLER_CONFIG_PREFERENCE_PHRASES[label])

        errors = self.consistency.find_missing_phrases(
            {label: "Persistent Preferences without Cobbler precedence"},
            {label: [phrase]},
            "Cobbler config preference",
        )

        self.assertIn(
            f"{label}: missing Cobbler config preference phrase `{phrase}`",
            errors,
        )

    def test_cobbler_reference_docs_require_fitted_answer_shape(self) -> None:
        for label in ("references/council-workflow.md", "references/council-prompts.md"):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.COUNCIL_MODULE_PHRASES)
                self.assertIn("Recommendation", self.consistency.COUNCIL_MODULE_PHRASES[label])
                self.assertIn("Why this fits", self.consistency.COUNCIL_MODULE_PHRASES[label])
                self.assertIn("Strongest dissent", self.consistency.COUNCIL_MODULE_PHRASES[label])
                self.assertIn("Next move", self.consistency.COUNCIL_MODULE_PHRASES[label])

    def test_cobbler_reference_docs_forbid_stale_council_primary_labels(self) -> None:
        label = "references/council-workflow.md"
        stale = "Quick Council is the default"

        self.assertIn(stale, self.consistency.COUNCIL_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.COUNCIL_FORBIDDEN_PHRASES,
            "Cobbler",
        )

        self.assertEqual(errors, [f"{label}: stale Cobbler phrase `{stale}`"])

    def test_cobbler_reference_docs_forbid_provider_backed_council_as_mode(self) -> None:
        label = "references/council-prompts.md"
        stale = "Mode: [Quick Cobbler / Run Cobbler / Provider-backed council]"

        self.assertIn(stale, self.consistency.COUNCIL_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.COUNCIL_FORBIDDEN_PHRASES,
            "Cobbler",
        )

        self.assertEqual(errors, [f"{label}: stale Cobbler phrase `{stale}`"])

    def test_cobbler_forbidden_phrases_catch_optional_run_framing(self) -> None:
        label = "SKILL.md"
        stale = "Cobbler is optional for Elves runs"

        self.assertIn(stale, self.consistency.COUNCIL_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.COUNCIL_FORBIDDEN_PHRASES,
            "Cobbler",
        )

        self.assertEqual(errors, [f"{label}: stale Cobbler phrase `{stale}`"])

    def test_config_example_requires_cobbler_primary_and_council_compatibility(self) -> None:
        phrases = self.consistency.COUNCIL_MODULE_PHRASES["config.json.example"]

        self.assertIn('"cobbler"', phrases)
        self.assertIn('"coordination_default": "cobbler-first"', phrases)
        self.assertIn('"default_for_elves_runs": true', phrases)
        self.assertIn('"default_answer_shape"', phrases)
        self.assertIn('"provider_backed_council"', phrases)
        self.assertIn('"model_routing_policy": "native-first"', phrases)
        self.assertIn('"fallback": "native-subagent-and-note"', phrases)
        self.assertIn('"external_route_example": "openrouter:<model-id>"', phrases)
        self.assertIn('"compatibility_for": "cobbler"', phrases)
        self.assertIn('"precedence": "cobbler"', phrases)

    def test_cobbler_harness_loop_spine_is_required(self) -> None:
        required_labels = (
            "SKILL.md",
            "docs/cobbler.md",
            "references/council-workflow.md",
            "references/council-prompts.md",
            "references/tool-config-examples.md",
            "references/survival-guide-template.md",
            "config.json.example",
            "aliases/claude/cobbler/SKILL.md",
            "aliases/claude/cobbler-mode/SKILL.md",
            "aliases/claude/council/SKILL.md",
            "aliases/claude/ec/SKILL.md",
            "aliases/claude/elves-council/SKILL.md",
        )

        for label in required_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.COBBLER_HARNESS_LOOP_PHRASES)

        # Elves 2.3 compact SKILL pins the spine without full dual-fork ceremony text.
        for phrase in (
            "capability scan",
            "context packet",
            "fit answer",
            "Cobbler-first",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.consistency.COBBLER_HARNESS_LOOP_PHRASES["SKILL.md"])

    def test_cobbler_harness_loop_reports_missing_step(self) -> None:
        label = "docs/cobbler.md"

        errors = self.consistency.find_missing_phrases(
            {label: "capability scan\nfit answer"},
            {label: ["capability scan", "context packet", "fit answer"]},
            "Cobbler harness loop",
        )

        self.assertEqual(
            errors,
            [f"{label}: missing Cobbler harness loop phrase `context packet`"],
        )

    def test_cobbler_harness_loop_detects_secret_context_packets(self) -> None:
        label = "references/council-prompts.md"
        text = "The context packet includes secrets for provider-backed review."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.COBBLER_HARNESS_DRIFT_PATTERNS,
            "Cobbler harness loop",
        )

        self.assertEqual(
            errors,
            [
                (
                    "references/council-prompts.md: stale Cobbler harness loop pattern "
                    "`\\bcontext\\s+packet\\b[^.\\n]*(?:includes|contains)\\s+"
                    "(?:secrets|tokens|credentials|cookies)\\b`"
                )
            ],
        )

    def test_claude_cobbler_alias_skill_files_are_required(self) -> None:
        expected_aliases = {
            "aliases/claude/cobbler/SKILL.md": "/cobbler",
            "aliases/claude/cobbler-mode/SKILL.md": "/cobbler-mode",
            "aliases/claude/council/SKILL.md": "/council",
            "aliases/claude/ec/SKILL.md": "/ec",
            "aliases/claude/elves-council/SKILL.md": "/elves-council",
        }

        for label, alias in expected_aliases.items():
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.CLAUDE_ALIAS_SKILL_PHRASES)
                self.assertIn(
                    self.consistency.CLAUDE_ALIAS_MARKER,
                    self.consistency.CLAUDE_ALIAS_SKILL_PHRASES[label],
                )
                self.assertIn(alias, self.consistency.CLAUDE_ALIAS_SKILL_PHRASES[label])
                self.assertIn(
                    "default orchestration model",
                    self.consistency.CLAUDE_ALIAS_SKILL_PHRASES[label],
                )
                self.assertIn(
                    "worker agents may edit scoped files",
                    self.consistency.CLAUDE_ALIAS_SKILL_PHRASES[label],
                )
                self.assertIn(
                    "For one-off Quick Cobbler answers, stay read-only and stateless",
                    self.consistency.CLAUDE_ALIAS_SKILL_PHRASES[label],
                )

    def test_extract_markdown_section_limits_to_requested_heading_level(self) -> None:
        text = """# Title

## Math Research Workflows
OpenRouter

## Cobbler
Cobbler-first coordination is the default for Elves runs
read-only

### Nested Detail
dissent

## Strategic Forgetting
Cobbler-first coordination is the default for Elves runs outside the section
"""

        section = self.consistency.extract_markdown_section(text, "## Cobbler")

        self.assertIn("Cobbler-first coordination is the default for Elves runs", section)
        self.assertIn("### Nested Detail", section)
        self.assertIn("dissent", section)
        self.assertNotIn("## Strategic Forgetting", section)
        self.assertNotIn("outside the section", section)

    def test_cobbler_section_phrases_do_not_pass_from_other_sections(self) -> None:
        label = "SKILL.md"
        texts = {
            label: """# Elves

## Math Research Workflows
Cobbler-first coordination is the default for Elves runs

## Cobbler
Cobbler
""",
        }
        phrases = {label: ["Cobbler-first coordination is the default for Elves runs"]}
        headings = {label: "## Cobbler"}

        errors = self.consistency.find_missing_section_phrases(
            texts,
            phrases,
            headings,
            "Cobbler",
        )

        self.assertEqual(
            errors,
            [
                (
                    "SKILL.md: missing Cobbler phrase "
                    "`Cobbler-first coordination is the default for Elves runs`"
                )
            ],
        )

    def test_cobbler_forbidden_phrases_catch_provider_requirement(self) -> None:
        label = "references/council-provider-config.md"
        stale = "normal `/council` requires OpenRouter"

        self.assertIn(label, self.consistency.COUNCIL_FORBIDDEN_PHRASES)
        self.assertIn(stale, self.consistency.COUNCIL_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.COUNCIL_FORBIDDEN_PHRASES,
            "Cobbler",
        )

        self.assertEqual(
            errors,
            [f"{label}: stale Cobbler phrase `{stale}`"],
        )

    def test_cobbler_forbidden_patterns_catch_provider_requirement_variants(self) -> None:
        label = "README.md"
        text = "Quick Cobbler needs OpenRouter before it can answer."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.COBBLER_FORBIDDEN_PATTERNS,
            "Cobbler",
        )

        self.assertEqual(
            errors,
            [
                (
                    "README.md: stale Cobbler pattern "
                    "`\\bquick\\s+cobbler\\s+(?:needs|requires)\\s+openrouter\\b`"
                )
            ],
        )

    def test_cobbler_forbidden_patterns_are_case_insensitive(self) -> None:
        label = "SKILL.md"
        text = "OPENROUTER_API_KEY is required for Cobbler."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.COBBLER_FORBIDDEN_PATTERNS,
            "Cobbler",
        )

        self.assertEqual(
            errors,
            [
                (
                    "SKILL.md: stale Cobbler pattern "
                    "`\\bopenrouter_api_key\\b\\s+is\\s+required\\s+for\\s+cobbler\\b`"
                )
            ],
        )

    def test_full_run_model_routing_guardrails_are_required(self) -> None:
        for label in ("SKILL.md", "config.json.example"):
            with self.subTest(label=label):
                self.assertIn(label, self.consistency.FULL_RUN_MODEL_ROUTING_PHRASES)

        phrases = self.consistency.FULL_RUN_MODEL_ROUTING_PHRASES
        # Compact 2.3 SKILL pins native-first model routing without the long 2.2 ceremony line.
        self.assertTrue(
            any("model routing" in p or "native-first" in p for p in phrases["SKILL.md"])
        )
        self.assertIn('"policy": "native-first"', phrases["config.json.example"])

    def test_full_run_model_routing_forbidden_phrases_catch_required_provider_drift(self) -> None:
        label = "references/tool-config-examples.md"
        stale = "model-routing requires OpenRouter"

        self.assertIn(stale, self.consistency.FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES,
            "full-run model routing",
        )

        self.assertEqual(errors, [f"{label}: stale full-run model routing phrase `{stale}`"])

    def test_full_run_model_routing_forbidden_patterns_catch_required_defaults(self) -> None:
        label = "README.md"
        text = "For this feature, required: true is the default."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS,
            "full-run model routing",
        )

        self.assertEqual(
            errors,
            [
                (
                    "README.md: stale full-run model routing pattern "
                    "`\\brequired:\\s*true\\s+is\\s+(?:the\\s+)?default\\b`"
                )
            ],
        )

    def test_full_run_model_routing_forbidden_patterns_allow_negated_provider_default(self) -> None:
        label = "references/council-provider-config.md"
        text = "Do not make implementation provider-backed by default."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS,
            "full-run model routing",
        )

        self.assertEqual(errors, [])

    def test_full_run_model_routing_forbidden_patterns_catch_positive_provider_default(self) -> None:
        label = "references/council-provider-config.md"
        text = "Users can make implementation provider-backed by default."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS,
            "full-run model routing",
        )

        self.assertEqual(
            errors,
            [
                (
                    "references/council-provider-config.md: stale full-run model routing pattern "
                    "`(?<!do not )\\bmake\\s+implementation\\s+provider-backed\\s+by\\s+default\\b`"
                )
            ],
        )

    def test_math_workflow_is_cobbler_managed_and_provider_optional(self) -> None:
        self.assertIn("SKILL.md", self.consistency.DOMAIN_WORKFLOW_PHRASES)
        self.assertIn(
            "**Math** is the first domain workflow",
            self.consistency.DOMAIN_WORKFLOW_PHRASES["SKILL.md"],
        )
        self.assertIn(
            "Cobbler-managed Elves domain workflow",
            self.consistency.MATH_MODULE_PHRASES["references/math-workflow.md"],
        )
        self.assertIn(
            "No provider key is required by this template",
            self.consistency.MATH_MODULE_PHRASES["references/math-provider-config.md"],
        )
        self.assertIn(
            "math-required-env: []",
            self.consistency.MATH_MODULE_PHRASES["references/survival-guide-template.md"],
        )

    def test_math_workflow_forbidden_phrases_catch_openrouter_required_defaults(self) -> None:
        label = "references/math-provider-config.md"
        stale = "OpenRouter is the minimum useful setup"

        self.assertIn(stale, self.consistency.DOMAIN_WORKFLOW_FORBIDDEN_PHRASES[label])

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.DOMAIN_WORKFLOW_FORBIDDEN_PHRASES,
            "domain workflow",
        )

        self.assertEqual(errors, [f"{label}: stale domain workflow phrase `{stale}`"])

    def test_math_workflow_forbidden_patterns_catch_required_openrouter_env(self) -> None:
        label = "references/survival-guide-template.md"
        text = "math-required-env:\n  - OPENROUTER_API_KEY"

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS,
            "domain workflow",
        )

        self.assertIn(
            (
                "references/survival-guide-template.md: stale domain workflow pattern "
                "`\\bmath-required-env:\\s*\\n\\s*-\\s*OPENROUTER_API_KEY\\b`"
            ),
            errors,
        )

    def test_config_example_math_defaults_are_native_first_and_optional(self) -> None:
        config = json.loads((REPO_ROOT / "config.json.example").read_text())
        math_config = config["math"]

        self.assertEqual(math_config["coordination"], "cobbler-managed-domain-workflow")
        self.assertEqual(
            math_config["provider_policy"],
            "native-first-with-optional-external-routes",
        )
        self.assertEqual(math_config["required_env"], [])
        self.assertIn("OPENROUTER_API_KEY", math_config["optional_env"])
        self.assertNotIn("OPENROUTER_API_KEY", math_config["required_env"])
        self.assertTrue(
            all(
                not route.startswith("openrouter:")
                for route in math_config["role_models"].values()
            )
        )
        self.assertTrue(
            any(
                route.startswith("openrouter:")
                for route in math_config["external_route_examples"].values()
            )
        )

    def test_config_domain_workflow_validator_reports_stale_openrouter_defaults(self) -> None:
        # Policy validator lives in consistency_engine; patch its read_text.
        import consistency_engine  # noqa: PLC0415

        original_read_text = consistency_engine.read_text
        stale_config = json.loads((REPO_ROOT / "config.json.example").read_text())
        stale_config["math"]["provider_policy"] = "openrouter-first"
        stale_config["math"]["required_env"] = ["OPENROUTER_API_KEY"]
        stale_config["math"]["role_models"]["proof_critic"] = "openrouter:<model-id>"

        def fake_read_text(path: Path) -> str:
            if path == consistency_engine.REPO_ROOT / "config.json.example":
                return json.dumps(stale_config)
            return original_read_text(path)

        consistency_engine.read_text = fake_read_text
        try:
            errors = consistency_engine.validate_config_domain_workflow()
        finally:
            consistency_engine.read_text = original_read_text

        self.assertIn(
            "config.json.example: `math.provider_policy` must not be `openrouter-first`",
            errors,
        )
        self.assertIn(
            "config.json.example: `math.required_env` must be empty by default",
            errors,
        )
        self.assertIn(
            "config.json.example: math role defaults must be native/direct, not OpenRouter (`proof_critic`)",
            errors,
        )

    def test_repo_consistency_workflow_guards_alias_and_config_paths(self) -> None:
        phrases = self.consistency.REPO_CONSISTENCY_WORKFLOW_PHRASES[
            ".github/workflows/repo-consistency.yml"
        ]

        self.assertIn('"config.json.example"', phrases)
        self.assertIn('"api-break-approvals.json"', phrases)
        self.assertIn('".env*"', phrases)
        self.assertIn('".github/ISSUE_TEMPLATE/**"', phrases)
        self.assertIn('".github/workflows/pages.yml"', phrases)
        self.assertIn('"aliases/**"', phrases)
        self.assertIn('"guide/**"', phrases)
        self.assertIn('"PRODUCT.md"', phrases)
        self.assertIn('"docs/cobbler.md"', phrases)
        self.assertIn('"openapi.json"', phrases)
        self.assertIn('"openapi.yaml"', phrases)
        self.assertIn('"swagger.json"', phrases)
        self.assertIn('"docs/openapi.json"', phrases)
        self.assertIn('"scripts/**"', phrases)
        self.assertIn("fetch-depth: 0", phrases)
        self.assertIn("--base-ref", phrases)
        self.assertIn("Unreleased", phrases)
        self.assertIn("Development commits verify Unreleased", phrases)
        self.assertIn("scripts/release_checklist.py", phrases)
        self.assertIn("read_frontmatter_version", phrases)
        self.assertIn(
            'BASE_REF="$(git describe --tags --abbrev=0 --exclude="v${VERIFY_VERSION}" HEAD^)"',
            phrases,
        )
        self.assertIn(
            'python3 scripts/verify_repo.py --ci --version "$VERIFY_VERSION"',
            phrases,
        )

    def test_repo_consistency_workflow_triggers_for_api_break_approvals(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "repo-consistency.yml"
        ).read_text()
        pull_request_section = workflow.split("  pull_request:\n", 1)[1].split(
            "  push:\n", 1
        )[0]
        push_section = workflow.split("  push:\n", 1)[1].split(
            "\npermissions:\n", 1
        )[0]

        for section_name, section in (
            ("pull_request", pull_request_section),
            ("push", push_section),
        ):
            with self.subTest(section=section_name):
                self.assertIn('- "api-break-approvals.json"', section)

    def test_repo_consistency_workflow_requires_node24_action_majors(self) -> None:
        label = ".github/workflows/repo-consistency.yml"
        phrases = self.consistency.REPO_CONSISTENCY_WORKFLOW_PHRASES[label]
        forbidden = self.consistency.REPO_CONSISTENCY_WORKFLOW_FORBIDDEN_PHRASES[label]

        self.assertIn("actions/checkout@v6", phrases)
        self.assertIn("actions/setup-python@v6", phrases)
        self.assertIn("actions/checkout@v4", forbidden)
        self.assertIn("actions/setup-python@v5", forbidden)

    def test_pages_workflow_uses_current_actions_and_publishes_only_the_guide(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "pages.yml").read_text()

        self.assertIn("actions/checkout@v6", workflow)
        self.assertIn("actions/configure-pages@v6", workflow)
        self.assertIn("actions/upload-pages-artifact@v5", workflow)
        self.assertIn("actions/deploy-pages@v5", workflow)
        self.assertIn("path: guide", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertNotIn("actions/configure-pages@v5", workflow)
        self.assertNotIn("actions/upload-pages-artifact@v4", workflow)
        self.assertNotIn("actions/deploy-pages@v4", workflow)

    def test_repo_consistency_workflow_rejects_stale_node20_action_majors(self) -> None:
        label = ".github/workflows/repo-consistency.yml"
        stale = "actions/setup-python@v5"

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            self.consistency.REPO_CONSISTENCY_WORKFLOW_FORBIDDEN_PHRASES,
            "repo-consistency workflow",
        )

        self.assertEqual(
            errors,
            [f"{label}: stale repo-consistency workflow phrase `{stale}`"],
        )

    def test_main_rejects_stale_repo_consistency_workflow_action_majors(self) -> None:
        label = ".github/workflows/repo-consistency.yml"
        workflow_path = self.consistency.REPO_ROOT / label
        original_read_text = self.consistency.read_text

        def fake_read_text(path: Path) -> str:
            text = original_read_text(path)
            if path == workflow_path:
                return (
                    text
                    + "\n# stale examples for regression coverage\n"
                    + "# actions/checkout@v4\n"
                    + "# actions/setup-python@v5\n"
                )
            return text

        self.consistency.read_text = fake_read_text
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                exit_code = self.consistency.main()
        finally:
            self.consistency.read_text = original_read_text

        self.assertEqual(exit_code, 1)
        self.assertIn(
            f"{label}: stale repo-consistency workflow phrase `actions/checkout@v4`",
            output.getvalue(),
        )
        self.assertIn(
            f"{label}: stale repo-consistency workflow phrase `actions/setup-python@v5`",
            output.getvalue(),
        )

    def test_operator_doc_guardrails_cover_durable_docs_and_run_report_template(self) -> None:
        expected = {
            ".ai-docs/manifest.md",
            ".ai-docs/architecture.md",
            ".ai-docs/conventions.md",
            ".ai-docs/gotchas.md",
            ".github/ISSUE_TEMPLATE/overnight_run_report.md",
            "references/kickoff-prompt-template.md",
        }

        self.assertTrue(expected.issubset(self.consistency.OPERATOR_DOC_PHRASES))
        self.assertIn(
            "- **Run mode:**",
            self.consistency.OPERATOR_DOC_PHRASES[
                ".github/ISSUE_TEMPLATE/overnight_run_report.md"
            ],
        )
        self.assertIn(
            "`Active Compute` if relevant",
            self.consistency.OPERATOR_DOC_PHRASES["references/kickoff-prompt-template.md"],
        )
        manifest_phrases = self.consistency.OPERATOR_DOC_PHRASES[".ai-docs/manifest.md"]
        for field in (
            "plan_path",
            "survival_guide_path",
            "execution_log_path",
            "learnings_path",
        ):
            with self.subTest(session_field=field):
                self.assertIn(
                    f"`<{field}>` from `.elves-session.json`",
                    manifest_phrases,
                )

    def test_operator_doc_guardrails_report_missing_phrase(self) -> None:
        label = ".ai-docs/conventions.md"

        errors = self.consistency.find_missing_phrases(
            {label: "Run control is live metadata"},
            {label: ["Run control is live metadata", "Stop Gate"]},
            "operator-doc",
        )

        self.assertEqual(errors, [f"{label}: missing operator-doc phrase `Stop Gate`"])

    def test_main_reports_missing_operator_doc_phrase(self) -> None:
        label = "README.md"
        target_path = self.consistency.REPO_ROOT / label
        original_phrases = self.consistency.OPERATOR_DOC_PHRASES
        original_read_text = self.consistency.read_text

        def fake_read_text(path: Path) -> str:
            if path == target_path:
                return "present operator phrase"
            return original_read_text(path)

        self.consistency.OPERATOR_DOC_PHRASES = {
            label: ["present operator phrase", "missing operator phrase"]
        }
        self.consistency.read_text = fake_read_text
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                exit_code = self.consistency.main()
        finally:
            self.consistency.OPERATOR_DOC_PHRASES = original_phrases
            self.consistency.read_text = original_read_text

        self.assertEqual(exit_code, 1)
        self.assertIn(
            f"{label}: missing operator-doc phrase `missing operator phrase`",
            output.getvalue(),
        )

    def test_workspace_isolation_guards_preflight_runtime_check(self) -> None:
        phrases = self.consistency.WORKSPACE_ISOLATION_PHRASES["scripts/preflight.sh"]

        self.assertIn("Workspace Ownership", phrases)
        self.assertIn("preflight_worktree.py", phrases)
        self.assertIn("--create-worktree", phrases)
        self.assertIn("git worktree list --porcelain", phrases)
        self.assertIn("Current branch is checked out in one worktree", phrases)
        self.assertIn("(current checkout)", phrases)
        self.assertIn("Recommended dedicated worktree", phrases)

    def test_workspace_isolation_helper_docs_are_phrase_pinned(self) -> None:
        for label in (
            "SKILL.md",
            "README.md",
            "references/survival-guide-template.md",
            "references/kickoff-prompt-template.md",
        ):
            with self.subTest(label=label):
                phrases = self.consistency.WORKSPACE_ISOLATION_PHRASES[label]
                self.assertIn(
                    "./scripts/preflight.sh --create-worktree <branch> --base origin/main",
                    phrases,
                )
                self.assertIn("--dry-run", phrases)
                self.assertIn("branch, worktree path, base ref, and collision tripwire", phrases)
                self.assertIn("does not reuse, delete, or repair existing worktrees", phrases)
        # AGENTS is thin adapter — must still mention workspace isolation via pointer corpus.
        self.assertIn(
            "One run owns one branch and one checkout",
            self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"],
        )
        self.assertTrue(self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"])

    def test_workspace_isolation_helper_runtime_is_phrase_pinned(self) -> None:
        phrases = self.consistency.WORKSPACE_ISOLATION_PHRASES["scripts/preflight_worktree.py"]

        self.assertIn("DEFAULT_BASE_REF = \"origin/main\"", phrases)
        self.assertIn("--create-worktree", phrases)
        self.assertIn("--worktree-dir", phrases)
        self.assertIn("--base", phrases)
        self.assertIn("--dry-run", phrases)
        self.assertIn("git worktree add", phrases)
        self.assertIn("collision tripwire:", phrases)

    def test_public_wording_guardrails_catch_fable_framing(self) -> None:
        label = "README.md"
        stale = "Fable-style"

        self.assertIn(stale, self.consistency.PUBLIC_WORDING_FORBIDDEN_PHRASES)
        self.assertNotIn("Fable", self.consistency.PUBLIC_WORDING_FORBIDDEN_PHRASES)

        errors = self.consistency.find_forbidden_phrases(
            {label: stale},
            {label: self.consistency.PUBLIC_WORDING_FORBIDDEN_PHRASES},
            "public wording",
        )

        self.assertEqual(errors, [f"{label}: stale public wording phrase `{stale}`"])

    def test_public_wording_surfaces_include_references_and_aliases(self) -> None:
        surfaces = self.consistency.public_wording_texts()

        self.assertIn("SKILL.md", surfaces)
        self.assertIn("references/council-workflow.md", surfaces)
        self.assertIn("aliases/claude/cobbler/SKILL.md", surfaces)

    def test_public_wording_surfaces_exclude_live_run_artifacts(self) -> None:
        surfaces = self.consistency.public_wording_texts()

        self.assertNotIn("docs/plans/v1.15.0-cobbler.md", surfaces)
        self.assertNotIn("docs/elves/survival-guide.md", surfaces)
        self.assertNotIn("docs/elves/execution-log.md", surfaces)

    def test_context_index_is_a_required_durable_doc(self) -> None:
        relative_docs = {
            path.relative_to(self.consistency.REPO_ROOT).as_posix()
            for path in self.consistency.DURABLE_DOCS
        }

        self.assertIn(".ai-docs/context-index.md", relative_docs)

    def test_api_surface_snapshot_guardrails_are_required(self) -> None:
        for label in ("SKILL.md",):
            with self.subTest(label=label):
                phrases = self.consistency.PUBLIC_API_SURFACE_SNAPSHOT_PHRASES[label]
                self.assertIn(
                    "Public API surface snapshots are optional regression evidence.",
                    phrases,
                )
                self.assertIn(
                    (
                        "A missing snapshot source is not blocking unless `required: true` "
                        "was explicitly set in the survival guide."
                    ),
                    phrases,
                )
                self.assertIn(
                    (
                        "A snapshot proves public surface shape only; it is not a substitute "
                        "for tests, E2E checks, review, or the human-owned constitution."
                    ),
                    phrases,
                )
        self.assertIn(
            "optional regression evidence",
            self.consistency.AGENTS_POINTER_PHRASES["AGENTS.md"],
        )

    def test_api_surface_snapshot_config_defaults_are_advisory(self) -> None:
        phrases = self.consistency.PUBLIC_API_SURFACE_SNAPSHOT_PHRASES["config.json.example"]

        self.assertIn('"api_surface_snapshot"', phrases)
        self.assertIn('"enabled": "auto"', phrases)
        self.assertIn('"required": false', phrases)
        self.assertIn("snapshots are regression evidence, not authority", phrases)

    def test_api_surface_snapshot_forbidden_patterns_catch_required_by_default(self) -> None:
        label = "README.md"
        text = "API snapshots are required, with required: true by default."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS,
            "public API surface snapshot",
        )

        self.assertEqual(
            errors,
            [
                (
                    "README.md: stale public API surface snapshot pattern "
                    "`\\bapi\\s+snapshots?\\s+(?:are|is)\\s+required\\b`"
                ),
                (
                    "README.md: stale public API surface snapshot pattern "
                    "`\\brequired:\\s*true\\s+by\\s+default\\b`"
                ),
            ],
        )

    def test_api_surface_snapshot_forbidden_patterns_allow_negated_required_inference(
        self,
    ) -> None:
        label = "SKILL.md"
        text = "Never infer required mode from project type, provider config, or API files."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS,
            "public API surface snapshot",
        )

        self.assertEqual(errors, [])

    def test_api_surface_snapshot_forbidden_patterns_allow_negated_artifact_and_secret_rules(
        self,
    ) -> None:
        label = "SKILL.md"
        text = (
            "Do not commit snapshot artifacts. "
            "Do not record secrets. "
            "Never capture bearer tokens. "
            "Must not include customer payloads."
        )

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS,
            "public API surface snapshot",
        )

        self.assertEqual(errors, [])

    def test_api_surface_snapshot_forbidden_patterns_catch_authority_drift(self) -> None:
        # AGENTS is a thin adapter without dual-fork forbidden patterns; exercise SKILL.
        label = "SKILL.md"
        text = "Snapshots replace tests and should include bearer tokens for debugging."

        errors = self.consistency.find_forbidden_patterns(
            {label: text},
            self.consistency.PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS,
            "public API surface snapshot",
        )

        self.assertEqual(
            errors,
            [
                (
                    "SKILL.md: stale public API surface snapshot pattern "
                    "`\\bsnapshots?\\s+replace\\s+(?:tests|the constitution|review)\\b`"
                ),
                (
                    "SKILL.md: stale public API surface snapshot pattern "
                    "`(?<!do not )(?<!never )(?<!don't )(?<!should not )"
                    "(?<!must not )\\binclude\\s+(?:raw\\s+)?(?:secrets|bearer tokens|cookies|customer payloads|production sample data)\\b`"
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
