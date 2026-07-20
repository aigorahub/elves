#!/usr/bin/env python3
"""Repo consistency check: generic engine + declarative policy inventory.

Semantic and mutation tests must fail for second-launch wording, host-native
full-run becoming Grok, trusted push globally forbidden, absolute test
immutability, and global rollback names. Preferred phrases never alone certify
behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from consistency_engine import (  # noqa: E402
    REPO_ROOT as _ENGINE_ROOT,
    extract_markdown_section,
    find_forbidden_patterns,
    find_forbidden_phrases,
    find_unscoped_patterns,
    find_missing_phrases,
    find_missing_section_phrases,
    public_wording_texts,
    read_frontmatter_version,
    read_latest_changelog_version,
    read_text,
    validate_config_domain_workflow,
    verify_order,
)
from consistency_policy import *  # noqa: F403, E402

assert _ENGINE_ROOT == REPO_ROOT

def main() -> int:
    errors: list[str] = []

    versions = {label: read_frontmatter_version(path) for label, path in VERSION_FILES.items()}
    changelog_version = read_latest_changelog_version(CHANGELOG_PATH)

    for label, version in versions.items():
        if version is None:
            errors.append(f"{label}: missing frontmatter version")

    if changelog_version is None:
        errors.append("CHANGELOG.md: missing release heading")

    if not errors:
        expected = next(iter(versions.values()))
        for label, version in versions.items():
            if version != expected:
                errors.append(
                    f"{label}: version `{version}` does not match repo skill version `{expected}`"
                )
        if changelog_version != expected:
            errors.append(
                f"CHANGELOG.md: latest release `{changelog_version}` does not match repo skill version `{expected}`"
            )

    for label, path in RECOVERY_ORDER_FILES.items():
        verify_order(label, read_text(path), RECOVERY_ORDER_TOKENS, errors)

    for label, path in PENDING_DOCS_FILES.items():
        if "PENDING-DOCS" not in read_text(path):
            errors.append(f"{label}: missing `PENDING-DOCS` guidance")

    for path in DURABLE_DOCS:
        if not path.exists():
            errors.append(f"missing durable doc: {path.relative_to(REPO_ROOT)}")

    for label, phrases in NONSTOP_GUARDRAIL_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing non-stop guardrail phrase `{phrase}`")

    for label, phrases in EFFORT_GUARDRAIL_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing effort guardrail phrase `{phrase}`")

    for label, phrases in FINAL_READINESS_REVIEW_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing final-readiness-review phrase `{phrase}`")

    single_kickoff_labels = set(SINGLE_KICKOFF_PHRASES) | set(
        SINGLE_KICKOFF_FORBIDDEN_PHRASES
    )
    single_kickoff_texts = {
        label: read_text(REPO_ROOT / label) for label in single_kickoff_labels
    }
    errors.extend(
        find_missing_phrases(
            single_kickoff_texts,
            SINGLE_KICKOFF_PHRASES,
            "single-kickoff E2E",
        )
    )
    errors.extend(
        find_missing_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in GROK_OPEN_SOURCE_WORKER_PHRASES
            },
            GROK_OPEN_SOURCE_WORKER_PHRASES,
            "open-source Grok worker",
        )
    )
    errors.extend(
        find_forbidden_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in GROK_OPEN_SOURCE_WORKER_FORBIDDEN_PHRASES
            },
            GROK_OPEN_SOURCE_WORKER_FORBIDDEN_PHRASES,
            "open-source Grok worker",
        )
    )
    errors.extend(
        find_forbidden_phrases(
            single_kickoff_texts,
            SINGLE_KICKOFF_FORBIDDEN_PHRASES,
            "single-kickoff E2E",
        )
    )
    errors.extend(
        find_missing_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in ADAPTIVE_WORKER_ROUTING_PHRASES
            },
            ADAPTIVE_WORKER_ROUTING_PHRASES,
            "adaptive worker routing",
        )
    )
    errors.extend(
        find_missing_phrases(
            {label: read_text(REPO_ROOT / label) for label in PREWALK_PHRASES},
            PREWALK_PHRASES,
            "exact-session prewalk",
        )
    )
    errors.extend(
        find_missing_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in EXPLICIT_HANDOFF_V1_PHRASES
            },
            EXPLICIT_HANDOFF_V1_PHRASES,
            "explicit handoff v1",
        )
    )
    errors.extend(
        find_missing_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in WORKER_CONFIDENCE_SIGNAL_PHRASES
            },
            WORKER_CONFIDENCE_SIGNAL_PHRASES,
            "worker confidence signal",
        )
    )
    errors.extend(
        find_missing_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in PARALLELVES_CONTRACT_PHRASES
            },
            PARALLELVES_CONTRACT_PHRASES,
            "parallelves contract",
        )
    )
    errors.extend(
        find_unscoped_patterns(
            single_kickoff_texts
            | {
                "references/grok-implementer-launch-prompt.md": read_text(
                    REPO_ROOT / "references/grok-implementer-launch-prompt.md"
                )
            },
            SINGLE_KICKOFF_UNSCOPED_PATTERNS,
            "single-kickoff contradiction",
            scope_word="legacy",
        )
    )
    exact_command_texts = {
        label: read_text(REPO_ROOT / label)
        for label in EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS
    }
    errors.extend(
        find_forbidden_patterns(
            exact_command_texts,
            EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS,
            "full-run command wildcard",
        )
    )

    installed_helper_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(INSTALLED_HELPER_PATH_PHRASES)
        | set(INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS)
    }
    errors.extend(
        find_missing_phrases(
            installed_helper_texts,
            INSTALLED_HELPER_PATH_PHRASES,
            "installed helper path",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            installed_helper_texts,
            INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS,
            "installed repo-only helper",
        )
    )

    for label, phrases in ACCEPTANCE_EVIDENCE_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing acceptance-evidence phrase `{phrase}`")

    landing_check_texts = {
        label: read_text(REPO_ROOT / label) for label in LANDING_CHECK_CONTRACT_PHRASES
    }
    errors.extend(
        find_missing_phrases(
            landing_check_texts,
            LANDING_CHECK_CONTRACT_PHRASES,
            "landing-check contract",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            landing_check_texts,
            LANDING_CHECK_BARE_FORBIDDEN_PATTERNS,
            "bare landing-check path",
        )
    )

    codex_goal_texts = {
        label: read_text(REPO_ROOT / label) for label in CODEX_GOALS_SECTION_HEADINGS
    }
    errors.extend(
        find_missing_section_phrases(
            codex_goal_texts,
            CODEX_GOALS_SECTION_PHRASES,
            CODEX_GOALS_SECTION_HEADINGS,
            "Codex Goals exact-path",
        )
    )
    codex_goal_sections = {
        label: extract_markdown_section(text, CODEX_GOALS_SECTION_HEADINGS[label])
        for label, text in codex_goal_texts.items()
    }
    errors.extend(
        find_forbidden_phrases(
            codex_goal_sections,
            CODEX_GOALS_SECTION_FORBIDDEN_PHRASES,
            "Codex Goals generic-path",
        )
    )

    for label, phrases in REPO_CONSISTENCY_WORKFLOW_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing repo-consistency workflow phrase `{phrase}`")
    errors.extend(
        find_forbidden_phrases(
            {
                label: read_text(REPO_ROOT / label)
                for label in REPO_CONSISTENCY_WORKFLOW_FORBIDDEN_PHRASES
            },
            REPO_CONSISTENCY_WORKFLOW_FORBIDDEN_PHRASES,
            "repo-consistency workflow",
        )
    )

    for label, phrases in MEMORY_HYGIENE_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing memory-hygiene phrase `{phrase}`")

    for label, phrases in ELVES_REPORT_PHRASES.items():
        path = REPO_ROOT / label
        if not path.exists():
            errors.append(f"{label}: missing Elves Report file")
            continue
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing Elves Report phrase `{phrase}`")

    for label, phrases in WORKSPACE_ISOLATION_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing workspace-isolation phrase `{phrase}`")

    for label, phrases in OPERATOR_DOC_PHRASES.items():
        path = REPO_ROOT / label
        if not path.exists():
            errors.append(f"{label}: missing operator-doc file")
            continue
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing operator-doc phrase `{phrase}`")

    for label, phrases in MATH_MODULE_PHRASES.items():
        path = REPO_ROOT / label
        if not path.exists():
            errors.append(f"{label}: missing math-module file")
            continue
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing math-module phrase `{phrase}`")

    domain_workflow_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(DOMAIN_WORKFLOW_PHRASES)
        | set(DOMAIN_WORKFLOW_FORBIDDEN_PHRASES)
        | set(DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS)
    }
    errors.extend(
        find_missing_phrases(
            domain_workflow_texts,
            DOMAIN_WORKFLOW_PHRASES,
            "domain workflow",
        )
    )
    errors.extend(
        find_forbidden_phrases(
            domain_workflow_texts,
            DOMAIN_WORKFLOW_FORBIDDEN_PHRASES,
            "domain workflow",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            domain_workflow_texts,
            DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS,
            "domain workflow",
        )
    )
    errors.extend(validate_config_domain_workflow())

    api_surface_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(PUBLIC_API_SURFACE_SNAPSHOT_PHRASES)
        | set(PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS)
    }
    errors.extend(
        find_missing_phrases(
            api_surface_texts,
            PUBLIC_API_SURFACE_SNAPSHOT_PHRASES,
            "public API surface snapshot",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            api_surface_texts,
            PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS,
            "public API surface snapshot",
        )
    )

    reviewed_pr_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(REVIEWED_PR_LANDING_PHRASES) | set(REVIEWED_PR_LANDING_FORBIDDEN_PHRASES)
    }
    errors.extend(
        find_missing_phrases(
            reviewed_pr_texts,
            REVIEWED_PR_LANDING_PHRASES,
            "reviewed-PR landing",
        )
    )
    errors.extend(
        find_forbidden_phrases(
            reviewed_pr_texts,
            REVIEWED_PR_LANDING_FORBIDDEN_PHRASES,
            "reviewed-PR landing",
        )
    )

    council_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(COUNCIL_MODULE_PHRASES)
        | set(COUNCIL_FORBIDDEN_PHRASES)
        | set(COBBLER_FORBIDDEN_PATTERNS)
        | set(COUNCIL_SECTION_HEADINGS)
    }
    council_section_phrases = {
        label: COUNCIL_MODULE_PHRASES[label] for label in COUNCIL_SECTION_HEADINGS
    }
    council_file_phrases = {
        label: phrases
        for label, phrases in COUNCIL_MODULE_PHRASES.items()
        if label not in COUNCIL_SECTION_HEADINGS
    }
    errors.extend(
        find_missing_section_phrases(
            council_texts,
            council_section_phrases,
            COUNCIL_SECTION_HEADINGS,
            "Cobbler",
        )
    )
    errors.extend(
        find_missing_phrases(
            {"AGENTS.md": read_text(REPO_ROOT / "AGENTS.md")},
            AGENTS_POINTER_PHRASES,  # noqa: F405
            "AGENTS thin pointer",
        )
    )
    errors.extend(
        find_missing_phrases(
            council_texts,
            council_file_phrases,
            "Cobbler",
        )
    )
    codex_install_texts = {label: council_texts[label] for label in CODEX_INSTALL_COBBLER_PHRASES}
    errors.extend(
        find_missing_phrases(
            codex_install_texts,
            CODEX_INSTALL_COBBLER_PHRASES,
            "Codex Cobbler install",
        )
    )
    cobbler_config_texts = {
        label: council_texts[label] for label in COBBLER_CONFIG_PREFERENCE_PHRASES
    }
    errors.extend(
        find_missing_phrases(
            cobbler_config_texts,
            COBBLER_CONFIG_PREFERENCE_PHRASES,
            "Cobbler config preference",
        )
    )
    cobbler_mode_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(COBBLER_MODE_PHRASES) | set(COBBLER_FORBIDDEN_PATTERNS)
    }
    errors.extend(
        find_missing_phrases(
            cobbler_mode_texts,
            COBBLER_MODE_PHRASES,
            "Cobbler Mode",
        )
    )
    errors.extend(
        find_forbidden_phrases(
            council_texts,
            COUNCIL_FORBIDDEN_PHRASES,
            "Cobbler",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            council_texts,
            COBBLER_FORBIDDEN_PATTERNS,
            "Cobbler",
        )
    )
    cobbler_harness_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(COBBLER_HARNESS_LOOP_PHRASES) | set(COBBLER_HARNESS_DRIFT_PATTERNS)
    }
    errors.extend(
        find_missing_phrases(
            cobbler_harness_texts,
            COBBLER_HARNESS_LOOP_PHRASES,
            "Cobbler harness loop",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            cobbler_harness_texts,
            COBBLER_HARNESS_DRIFT_PATTERNS,
            "Cobbler harness loop",
        )
    )

    full_run_routing_texts = {
        label: read_text(REPO_ROOT / label)
        for label in FULL_RUN_MODEL_ROUTING_PHRASES
    }
    errors.extend(
        find_missing_phrases(
            full_run_routing_texts,
            FULL_RUN_MODEL_ROUTING_PHRASES,
            "full-run model routing",
        )
    )
    errors.extend(
        find_forbidden_phrases(
            full_run_routing_texts,
            FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES,
            "full-run model routing",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            full_run_routing_texts,
            FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS,
            "full-run model routing",
        )
    )

    implementation_lanes_texts = {
        label: read_text(REPO_ROOT / label) for label in IMPLEMENTATION_LANES_PHRASES
    }
    errors.extend(
        find_missing_phrases(
            implementation_lanes_texts,
            IMPLEMENTATION_LANES_PHRASES,
            "implementation lanes",
        )
    )

    setup_texts = {label: read_text(REPO_ROOT / label) for label in SETUP_COBBLER_PHRASES}
    errors.extend(
        find_missing_phrases(
            setup_texts,
            SETUP_COBBLER_PHRASES,
            "setup cobbler",
        )
    )

    handoff_texts = {
        label: read_text(REPO_ROOT / label) for label in IMPLEMENTER_HANDOFF_PHRASES
    }
    errors.extend(
        find_missing_phrases(
            handoff_texts,
            IMPLEMENTER_HANDOFF_PHRASES,
            "implementer handoff",
        )
    )
    progress_texts = {
        label: read_text(REPO_ROOT / label)
        for label in set(PROGRESS_COMMIT_PHRASES) | set(PROGRESS_COMMIT_ANTIPATTERN_EXAMPLES)
    }
    errors.extend(
        find_missing_phrases(
            progress_texts,
            PROGRESS_COMMIT_PHRASES,
            "progress commit",
        )
    )
    errors.extend(
        find_missing_phrases(
            progress_texts,
            PROGRESS_COMMIT_ANTIPATTERN_EXAMPLES,
            "progress commit anti-pattern example",
        )
    )
    risk_texts = {
        label: read_text(REPO_ROOT / label) for label in RISK_TIER_PHRASES
    }
    errors.extend(
        find_missing_phrases(
            risk_texts,
            RISK_TIER_PHRASES,
            "risk tier safety kernel",
        )
    )

    public_texts = public_wording_texts()
    errors.extend(
        find_forbidden_phrases(
            public_texts,
            {label: PUBLIC_WORDING_FORBIDDEN_PHRASES for label in public_texts},
            "public wording",
        )
    )
    errors.extend(
        find_forbidden_patterns(
            public_texts,
            {label: PUBLIC_WORDING_FORBIDDEN_PATTERNS for label in public_texts},
            "public persona wording",
        )
    )
    # A one-sided bump of the Grok upstream commit (doc pin vs the runtime
    # constant) fails here instead of shipping silently divergent.
    errors.extend(grok_upstream_commit_pin_errors())

    alias_texts = {label: read_text(REPO_ROOT / label) for label in CLAUDE_ALIAS_SKILL_PHRASES}
    errors.extend(
        find_missing_phrases(
            alias_texts,
            CLAUDE_ALIAS_SKILL_PHRASES,
            "Claude Cobbler alias",
        )
    )

    # Semantic behavior policy: structured scenarios must resolve without relying on
    # literal phrase inventories alone (Batch 6 / v2.1.0).
    try:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from cobbler_runtime.behavior_policy import (  # noqa: PLC0415
            FORBIDDEN_FULL_RUN_WAKE_TRIGGERS,
            resolve_from_signals,
            resolve_scenario,
        )

        full = resolve_scenario("full_run_trusted_grok")
        if full.continuation != "same_session" or full.driver_monitor_mode != "parked_monitor":
            errors.append(
                "behavior_policy: full_run_trusted_grok must use same_session + parked_monitor"
            )
        legacy = resolve_scenario("legacy_two_call")
        if legacy.kickoff_mode == full.kickoff_mode and legacy.continuation == full.continuation:
            errors.append(
                "behavior_policy: single-kickoff and legacy two-call must remain contradictory"
            )
        if "per_push" not in FORBIDDEN_FULL_RUN_WAKE_TRIGGERS:
            errors.append("behavior_policy: per_push must be a forbidden full-run wake trigger")
        if resolve_from_signals({"full_run": True}).work_driver != "host_native":
            errors.append("behavior_policy: full_run alone must remain host_native")
        if resolve_from_signals({"bounded_task": True}).work_driver != "host_native":
            errors.append("behavior_policy: bounded_task alone must remain host_native")
        if resolve_from_signals(
            {"bounded_task": True, "work_driver_grok": True}
        ).work_driver != "grok_build":
            errors.append("behavior_policy: explicit bounded Grok route must remain available")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"behavior_policy: failed to load semantic scenarios: {exc}")

    if errors:
        print("Repo consistency check FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repo consistency check OK")
    print(f"- Version: {next(iter(versions.values()))}")
    print("- Recovery order is aligned across repo docs")
    print("- `PENDING-DOCS` guidance is present where expected")
    print("- Durable docs and learnings surfaces exist")
    print("- Workspace-isolation guidance is present across docs")
    print("- Operator-facing docs are aligned")
    print("- Non-stop guardrails are aligned across runtime and template docs")
    print("- Effort guardrails are aligned across runtime and template docs")
    print("- Final readiness review guardrails are aligned")
    print("- Installed helper paths and generic final-readiness gates are aligned")
    print("- Single-kickoff E2E and legacy handoff guidance are aligned")
    print("- Acceptance-evidence and landing-check guardrails are aligned")
    print("- Repo consistency workflow guardrails are aligned")
    print("- Strategic forgetting and memory hygiene guardrails are aligned")
    print("- Elves Report guardrails are aligned")
    print("- Math research workflow guardrails are aligned")
    print("- Cobbler domain workflow guardrails are aligned")
    print("- Public API surface snapshot guardrails are aligned")
    print("- Reviewed PR landing command guardrails are aligned")
    print("- Cobbler guardrails are aligned")
    print("- Cobbler harness loop drift checks are aligned")
    print("- Full-run model routing guardrails are aligned")
    print("- Public wording guardrails are aligned")
    print("- Claude Cobbler alias guardrails are aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
