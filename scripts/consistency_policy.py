"""Declarative repo-consistency policy inventory and phrase scenarios.

Extracted from check_repo_consistency.py so the generic engine stays small.
Semantic/mutation tests assert behavior, not preferred marketing phrases alone.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES = {
    "SKILL.md": REPO_ROOT / "SKILL.md",
    "AGENTS.md": REPO_ROOT / "AGENTS.md",
}

CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

RECOVERY_ORDER_FILES = {
    "SKILL.md": REPO_ROOT / "SKILL.md",
    "AGENTS.md": REPO_ROOT / "AGENTS.md",
    "references/kickoff-prompt-template.md": REPO_ROOT / "references" / "kickoff-prompt-template.md",
    "references/survival-guide-template.md": REPO_ROOT / "references" / "survival-guide-template.md",
}

RECOVERY_ORDER_TOKENS = [
    "survival guide",
    ".elves-session.json",
    "learnings",
    "plan",
    "execution log",
    ".ai-docs/manifest.md",
]

PENDING_DOCS_FILES = {
    "SKILL.md": REPO_ROOT / "SKILL.md",
    "AGENTS.md": REPO_ROOT / "AGENTS.md",
    "references/review-subagent.md": REPO_ROOT / "references" / "review-subagent.md",
}

DURABLE_DOCS = [
    REPO_ROOT / "docs" / "elves" / "learnings.md",
    REPO_ROOT / ".ai-docs" / "manifest.md",
    REPO_ROOT / ".ai-docs" / "architecture.md",
    REPO_ROOT / ".ai-docs" / "conventions.md",
    REPO_ROOT / ".ai-docs" / "gotchas.md",
    REPO_ROOT / ".ai-docs" / "context-index.md",
    REPO_ROOT / "references" / "learnings-template.md",
]

NONSTOP_GUARDRAIL_PHRASES = {
    "SKILL.md": [
        "Stop Gate",
        "continuation_guard",
        "After every host-owned commit and push, re-read the survival guide before doing anything else.",
        "Do not wait for user acknowledgment",
    ],
    "references/survival-guide-template.md": [
        "## Stop Gate",
        "## Forbidden Stop Reasons",
        "Stop allowed right now",
        "Every completed batch must end with a commit and push",
        "continue without waiting for user acknowledgment",
    ],
    "references/kickoff-prompt-template.md": [
        "Every completed batch must end with a commit and push before you start anything else.",
        "Immediately after every commit and push, re-read the survival guide before any other action.",
        "Do not send a final response unless the survival guide Stop Gate says stopping is allowed or a true blocker forces it.",
    ],
    "references/open-ended-guide.md": [
        "## Stop Gate Pattern",
        "## Forbidden Stop Reasons",
        "continuation_guard.stop_allowed: false",
    ],
}

EFFORT_GUARDRAIL_PHRASES = {
    "SKILL.md": [
        "## Effort Standard",
        "Do not be lazy.",
        "Work as hard as you can for",
    ],
    "references/survival-guide-template.md": [
        "## Effort Standard",
        "Do not be lazy.",
        "Work as hard as you can for the full run.",
    ],
    "references/kickoff-prompt-template.md": [
        "Do not be lazy. Work as hard as you can for the entire run.",
        "Do not coast after the first success, first green check, or first useful checkpoint.",
    ],
    "references/open-ended-guide.md": [
        "## Sustain Effort",
        "Do not be lazy.",
        "Work as hard as you can for the full",
    ],
}

FINAL_READINESS_REVIEW_PHRASES = {
    "SKILL.md": [
        "Final Readiness Review",
        "git diff <default-branch>...HEAD",
        "review subagent",
    ],
    "references/review-subagent.md": [
        "## Final Readiness Review",
        "git diff [DEFAULT_BRANCH]...HEAD",
    ],
    "references/kickoff-prompt-template.md": [
        "Require a final readiness review",
        "git diff <default-branch>...HEAD",
    ],
}

SINGLE_KICKOFF_PHRASES = {
    "SKILL.md": [
        "Default user path: one kickoff",
        "Trusted full-run delegation keeps that path",
        "chat-to-work",
        "chat-to-land",
        "Legacy two-call handoff",
        "full-run",
        "parked",
    ],
    "references/kickoff-prompt-template.md": [
        "Recommended: one kickoff",
        "trusted full-run / parked-monitor",
        "Chat-to-work (E2E, no merge)",
        "Chat-to-land (E2E through merge)",
        "Use separate calls only for the legacy path",
    ],
    "references/e2e-chat-to-land.md": [
        "recommended default user path",
        "Trusted Grok full-run delegation is the optional parked shape",
        "without waiting for a second human call",
        "Legacy / advanced",
    ],
}

SINGLE_KICKOFF_FORBIDDEN_PHRASES = {
    "README.md": [
        "Use the launch template from the same reference file in a fresh call",
        "**Two-step operator flow**",
    ],
    "AGENTS.md": [
        "do not launch in that same call",
        "Execution starts only from a fresh short launch prompt in the next call",
    ],
    "references/kickoff-prompt-template.md": [
        "**Stage and launch in separate calls**",
        "**If you only send one message, the agent should stage first**",
        "wait for your final launch command",
    ],
}

_SINGLE_KICKOFF_SURFACES = (
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "references/kickoff-prompt-template.md",
    "references/e2e-chat-to-land.md",
    "references/grok-implementer-launch-prompt.md",
)

SINGLE_KICKOFF_UNSCOPED_PATTERNS = {
    label: [
        r"\b(?:wait|stop)\b[^.\n]{0,160}\b(?:second|fresh|separate|another|final)\b[^.\n]{0,100}\b(?:launch|call|message|command)\b",
        r"\b(?:second|fresh|separate|another)\s+(?:human\s+)?(?:launch|call|message|command)\b",
    ]
    for label in _SINGLE_KICKOFF_SURFACES
}

EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS = {
    label: [r"full-run-\*"]
    for label in (
        "SKILL.md",
        "AGENTS.md",
        "README.md",
        "references/grok-implementer-launch-prompt.md",
    )
}

INSTALLED_HELPER_PATH_PHRASES = {
    "SKILL.md": [
        "source-checkout shorthand",
        "active Elves skill root",
        "~/.claude/skills/elves",
        "~/.codex/skills/elves",
        "$ELVES_SKILL_ROOT/scripts/acceptance_contract.py",
        "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py",
        "installed Elves bundle never requires a repo-only helper",
    ],
    "references/runtime-helper-paths.md": [
        "## Source checkout shorthand",
        "## Installed Claude Code or Codex skill",
        "target repository as the working directory",
        "$HOME/.claude/skills/elves",
        "$HOME/.codex/skills/elves",
        "scripts/acceptance_contract.py",
        "scripts/elves_landing_check.py",
        "Never make an ordinary installed Elves run",
        "depend on a repo-only helper",
    ],
    "references/grok-implementer-launch-prompt.md": [
        "runtime-helper-paths.md",
        "source-checkout shorthand",
    ],
}

_INSTALLED_FINAL_READINESS_SURFACES = (
    "SKILL.md",
    "AGENTS.md",
    "references/kickoff-prompt-template.md",
    "references/review-subagent.md",
    "references/survival-guide-template.md",
)
INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS = {
    label: [
        r"python3\s+(?:\./)?scripts/(?:verify_repo|release_checklist|check_repo_consistency|installed_bundle_smoke|pr_portfolio_report|sync_installed_skills)\.py\b"
    ]
    for label in _INSTALLED_FINAL_READINESS_SURFACES
}

REPO_CONSISTENCY_WORKFLOW_PHRASES = {
    ".github/workflows/repo-consistency.yml": [
        '"api-break-approvals.json"',
        '"config.json.example"',
        '".env*"',
        '"openapi.json"',
        '"openapi.yaml"',
        '"swagger.json"',
        '".github/ISSUE_TEMPLATE/**"',
        '".github/workflows/repo-consistency.yml"',
        '".github/workflows/pages.yml"',
        '"aliases/**"',
        '"guide/**"',
        '"PRODUCT.md"',
        '"docs/cobbler.md"',
        '"docs/openapi.json"',
        '"scripts/**"',
        "fetch-depth: 0",
        "Unreleased",
        "Development commits verify Unreleased",
        "scripts/release_checklist.py",
        "read_frontmatter_version",
        'BASE_REF="$(git describe --tags --abbrev=0 --exclude="v${VERIFY_VERSION}" HEAD^)"',
        'python3 scripts/verify_repo.py --ci --version "$VERIFY_VERSION"',
        "--base-ref",
        "actions/checkout@v6",
        "actions/setup-python@v6",
    ],
}

ACCEPTANCE_EVIDENCE_PHRASES = {
    "SKILL.md": [
        "plan Acceptance with proof",
        "acceptance",
        "elves_landing_check.py",
        "God-file",
        "one batch per close commit",
    ],
    "references/survival-guide-template.md": [
        "plan Acceptance with proof",
        "Evidence / SCRATCH Layout",
        "elves_landing_check.py",
    ],
    "references/execution-log-template.md": [
        "**Validate:**",
        "Plan Acceptance proof",
    ],
    "references/plan-template.md": [
        "characterization-only",
        "acceptance: [{criterion, met, evidence}]",
    ],
}

LANDING_CHECK_CONTRACT_PHRASES = {
    label: [
        "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py",
        "--session <session-path> --repo-root .",
        "plan_path",
        "equality assertion",
    ]
    for label in (
        "SKILL.md",
        "AGENTS.md",
        "references/survival-guide-template.md",
    )
}

LANDING_CHECK_BARE_FORBIDDEN_PATTERNS = {
    label: [r"python3\s+(?:\./)?scripts/elves_landing_check\.py\b"]
    for label in LANDING_CHECK_CONTRACT_PHRASES
}

CODEX_GOALS_SECTION_HEADINGS = {}
CODEX_GOALS_SECTION_PHRASES = {
}
CODEX_GOALS_SECTION_FORBIDDEN_PHRASES = {
    "README.md": [
        "docs/elves/survival-guide.md",
        "docs/plans/my-plan.md",
        "docs/elves/execution-log.md",
    ],
}

REPO_CONSISTENCY_WORKFLOW_FORBIDDEN_PHRASES = {
    ".github/workflows/repo-consistency.yml": [
        "actions/checkout@v4",
        "actions/setup-python@v5",
    ],
}

REVIEWED_PR_LANDING_PHRASES = {
    "README.md": [
        "\\land-pr",
        "/land-pr",
    ],
    "SKILL.md": [
        "## Reviewed PR Landing Command",
        "\\land-pr",
        "/land-pr",
        "gh pr merge --merge",
        "default when bots are expected",
    ],
    "references/review-subagent.md": [
        "### Reviewed PR Landing Command",
        "\\land-pr",
        "/land-pr",
        "gh pr merge --merge",
        "one-off merge opt-in",
    ],
    "references/survival-guide-template.md": [
        "reviewed-pr-landing-command",
        "\\land-pr",
        "/land-pr",
        "one-off explicit merge opt-in",
    ],
    "references/kickoff-prompt-template.md": [
        "reviewed-PR landing command",
        "\\land-pr",
        "/land-pr",
        "gh pr merge --merge",
    ],
    "references/plan-template.md": [
        "reviewed-PR landing command",
        "\\land-pr",
        "/land-pr",
    ],
}

REVIEWED_PR_LANDING_FORBIDDEN_PHRASES = {
    "SKILL.md": [
        "Only if the user has set a merge-on-green preference in Run Control do you merge yourself",
        "A merge is requested and the user has not set a merge-on-green preference.",
    ],
    "AGENTS.md": [
        "Only if the user has set a merge-on-green preference in Run Control do you merge yourself",
        "A merge is requested and the user has not set a merge-on-green preference.",
        "that gate stays with the user unless they set a merge-on-green preference.",
    ],
    "references/kickoff-prompt-template.md": [
        "merge policy (default: you never merge; opt-in: merge-commit-on-green)",
        "only if the user explicitly set a merge-on-green preference",
    ],
}

MEMORY_HYGIENE_PHRASES = {
    "SKILL.md": [
        "## Strategic Forgetting",
        "chats are for execution",
        "memory and resource hygiene",
    ],
    "references/survival-guide-template.md": [
        "## Strategic Forgetting",
        "## Memory and Resource Hygiene",
    ],
    "references/autonomy-guide.md": [
        "## Memory Pressure And Strategic Forgetting",
        "Local app maintenance",
    ],
}

ELVES_REPORT_PHRASES = {
    "SKILL.md": [
        "## Elves Report",
        "problems found",
        "lessons learned",
        "/tmp/elves-report-<repo-slug>-<yyyy-mm-dd>.html",
        "references/elves-report-template.html",
        "collapsible `<details>` sections",
        "committed examples and reusable templates non-identifying",
        "Elves Report path",
    ],
    "references/survival-guide-template.md": [
        "## Elves Report",
        "problems found",
        "lessons learned",
        "/tmp/elves-report-<repo-slug>-<yyyy-mm-dd>.html",
        "references/elves-report-template.html",
    ],
    "references/execution-log-template.md": [
        "**Elves Report:**",
        "**Problems found:**",
        "**Lessons learned:**",
    ],
    "references/elves-report-template.html": [
        "Elves Report",
        "Problems Found",
        "Lessons Learned",
        "Batch Ledger",
        "<details class=\"batch\"",
    ],
    "docs/elves-report-proof-of-concept.html": [
        "Elves Report",
        "assets/elves-banner.jpeg",
        "Problems found",
        "Lessons learned",
        "Batch Ledger",
        "<details class=\"batch\"",
    ],
}

WORKSPACE_ISOLATION_PHRASES = {
    "SKILL.md": [
        "One run owns one branch and one checkout",
        "./scripts/preflight.sh --create-worktree <branch> --base origin/main",
        "--dry-run",
        "branch, worktree path, base ref, and collision tripwire",
        "does not reuse, delete, or repair existing worktrees",
        "collision tripwire",
    ],
    "README.md": [
        "One run owns one branch and one checkout",
        "./scripts/preflight.sh --create-worktree <branch> --base origin/main",
        "--dry-run",
        "branch, worktree path, base ref, and collision tripwire",
        "does not reuse, delete, or repair existing worktrees",
        "collision tripwire",
    ],
    "references/survival-guide-template.md": [
        "One run owns one branch and one checkout",
        "./scripts/preflight.sh --create-worktree <branch> --base origin/main",
        "--dry-run",
        "branch, worktree path, base ref, and collision tripwire",
        "does not reuse, delete, or repair existing worktrees",
        "collision tripwire",
    ],
    "references/kickoff-prompt-template.md": [
        "git worktree",
        "./scripts/preflight.sh --create-worktree <branch> --base origin/main",
        "--dry-run",
        "branch, worktree path, base ref, and collision tripwire",
        "does not reuse, delete, or repair existing worktrees",
    ],
    "scripts/preflight.sh": [
        "Workspace Ownership",
        "preflight_worktree.py",
        "--create-worktree",
        "git worktree list --porcelain",
        "Current branch is checked out in one worktree",
        "(current checkout)",
        "Recommended dedicated worktree",
        "Use one owned branch and checkout per Elves run before launching",
    ],
    "scripts/preflight_worktree.py": [
        "DEFAULT_BASE_REF = \"origin/main\"",
        "--create-worktree",
        "--worktree-dir",
        "--base",
        "--dry-run",
        "git worktree add",
        "Default base origin/main does not resolve; pass --base <ref>.",
        "Requested --worktree-dir already exists",
        "Created dedicated worktree",
        "Recommended dedicated worktree",
        "collision tripwire:",
    ],
}

OPERATOR_DOC_PHRASES = {
    ".ai-docs/manifest.md": [
        "curated layer above the run-specific `docs/elves/*` memory surfaces",
        "`<plan_path>` from `.elves-session.json`",
        "`<survival_guide_path>` from `.elves-session.json`",
        "`<execution_log_path>` from `.elves-session.json`",
        "`<learnings_path>` from `.elves-session.json`",
        "Promotion flow: `execution log -> learnings -> .ai-docs`",
    ],
    ".ai-docs/architecture.md": [
        "## Memory layers",
        "live run control, checkpoint semantics, active compute, next exact batch",
        "Live operator state belongs in the survival guide and should be rewritten in place.",
        "changes almost always cross multiple surfaces",
    ],
    ".ai-docs/conventions.md": [
        "Run control is live metadata",
        "survival guide's `Run Control` block",
        "survival guide's `Stop Gate`",
        "Active Compute",
        "Every completed batch must end with `update docs -> commit -> push -> re-read survival guide`",
        "Repo-only maintenance helpers stay in the checkout.",
        "pin it with a `*_PHRASES` map",
    ],
    ".ai-docs/gotchas.md": [
        "Stop Gate",
        "continuation_guard",
        "same working tree on the same branch",
        "dedicated `git worktree` per run",
        "Paid pods, remote jobs, and long-lived local services",
        "Local project installs can quietly shadow global installs.",
    ],
    ".github/ISSUE_TEMPLATE/overnight_run_report.md": [
        "- **Run mode:**",
        "- **Checkpoint semantics:**",
        "- **Active compute:**",
        "Run-control behavior",
        "What you changed in your setup afterward",
    ],
    "references/kickoff-prompt-template.md": [
        "Set `## Run Control` explicitly",
        "checkpoint semantics",
        "may-continue-after-checkpoint",
        "actual stop conditions",
        "`Active Compute` if relevant",
        "collision tripwire",
    ],
}

MATH_MODULE_PHRASES = {
    "SKILL.md": [
        "## Math Research Workflows",
        "Cobbler-managed Elves domain workflow",
        "Discovery Sprint",
        "Native host subagents or direct analysis are the default",
        "useful optional math role preset",
        "Google Cloud AlphaEvolve",
        "math-alphaevolve.md",
        "Never treat model output",
    ],
    "references/survival-guide-template.md": [
        "### Math Configuration (optional)",
        "math-coordination: cobbler-managed-domain-workflow",
        "math-provider-policy: native-first-with-optional-external-routes",
        "math-required-env: []",
        "subfield_scout: native-subagent",
        "math-external-route-examples",
        "record the",
        "fallback in the model-call ledger",
    ],
    "references/tool-config-examples.md": [
        "## Math Research Workflow",
        "math-coordination: cobbler-managed-domain-workflow",
        "math-provider-policy: native-first-with-optional-external-routes",
        "math-required-env: []",
        "OPENROUTER_API_KEY",
        "math-ledger-dir: docs/math",
    ],
    "references/math-workflow.md": [
        "Cobbler-managed Elves domain workflow",
        "Cobbler Harness Mapping",
        "## The Discovery Sprint",
        "## Cross-Pollination",
        "## Claim Lifecycle",
        "math-artifact-ledgers.md",
        "math-alphaevolve.md",
        "Evolutionary example search",
    ],
    "references/math-plan-template.md": [
        "## Batch 1: Discovery Sprint",
        "algebraic/combinatorial analogs",
        "Every `quick_win` item has a plausible proof path",
        "evolutionary_search: alphaevolve",
    ],
    "references/math-provider-config.md": [
        "Cobbler-managed domain-workflow setting",
        "No provider key is required by this template",
        "## Role Slots",
        "native-first-with-optional-external-routes",
        "OPENROUTER_API_KEY",
        "record-before-switching-provider",
        "evolutionary_search",
        "math-alphaevolve.md",
    ],
    "references/math-alphaevolve.md": [
        "Google Cloud **AlphaEvolve**",
        "not a proof engine",
        "evolutionary_search",
        "independent-local-replay-only",
        "gcloud-impersonation",
        "deterministic local evaluator",
    ],
    "references/math-review-prompts.md": [
        "## Subfield Scout",
        "## Proof Critic",
        "## Source Auditor",
        "## Formalization Scout",
        "## Evolutionary Search (AlphaEvolve / similar)",
    ],
    "references/math-artifact-ledgers.md": [
        "domain evidence ledgers",
        "## Claim Ledger",
        "## Source Ledger",
        "## Model-Call Ledger",
        "## Human-Verification Ledger",
        "alphaevolve:<task-id>",
    ],
    "config.json.example": [
        '"math"',
        '"coordination": "cobbler-managed-domain-workflow"',
        '"provider_policy": "native-first-with-optional-external-routes"',
        '"required_env": []',
        '"subfield_scout"',
        '"evolutionary_search"',
        '"alphaevolve"',
        '"fallback_policy": "record-before-switching-provider"',
    ],
}

DOMAIN_WORKFLOW_PHRASES = {
    "SKILL.md": [
        "## Coordination Architecture",
        "**Elves** is the execution system",
        "**Cobbler** is the default coordinator",
        "**Domain workflows** are specialized Cobbler-managed packs",
        "**Math** is the first domain workflow",
        "**Providers** are optional role routes",
        "cobbler.default_for_session",
    ],
    "docs/cobbler.md": [
        "## The coordination hierarchy",
        "**Elves** handles execution",
        "**Cobbler** handles coordination",
        "**Domain workflows** handle specialized work under Cobbler",
        "Math is the first domain workflow",
        "cobbler.default_for_session",
    ],
    "references/council-workflow.md": [
        "Elves executes, Cobbler coordinates, domain workflows specialize, and providers",
        "route optional roles",
        "Math is the first Cobbler-managed domain workflow",
        "domain evidence artifacts",
    ],
    "references/kickoff-prompt-template.md": [
        "Cobbler Session State",
        "cobbler.default_for_session: true",
        "math as a Cobbler-managed domain workflow",
    ],
    "references/survival-guide-template.md": [
        "## Cobbler Session State",
        "Cobbler default",
        "cobbler.default_for_session: true",
        "Math is a Cobbler-managed domain workflow",
    ],
    "references/review-subagent.md": [
        "Cobbler Session State",
        "cobbler.default_for_session",
        "Math Domain Workflow Context",
        "math ledgers are treated as domain evidence artifacts",
    ],
    "references/execution-log-template.md": [
        "Math ledger status",
    ],
    "references/math-workflow.md": [
        "Cobbler-managed Elves domain workflow",
        "Cobbler is the coordinator",
        "Present/record",
        "Reclassify",
    ],
    "references/math-provider-config.md": [
        "Math provider routing is a Cobbler-managed domain-workflow setting",
        "No provider key is required by this template",
        "Missing optional provider access never blocks ordinary Cobbler use or a",
        "math Discovery Sprint",
    ],
    "references/math-plan-template.md": [
        "Math is a Cobbler-managed Elves",
        "math-coordination: cobbler-managed-domain-workflow",
        "math-required-env: []",
    ],
    "references/math-review-prompts.md": [
        "Cobbler role templates for the math domain workflow",
        "Every math role should receive the same context packet",
        "Configured",
        "external providers are optional role routes",
    ],
    "references/math-artifact-ledgers.md": [
        "domain evidence ledgers",
        "not a separate Cobbler, Council, or run-state ledger",
        "native-subagent",
    ],
    "references/tool-config-examples.md": [
        "Math is a Cobbler-managed domain workflow",
        "math-coordination: cobbler-managed-domain-workflow",
        "math-required-env: []",
    ],
    "references/council-provider-config.md": [
        "Math has its own Cobbler-managed domain workflow provider slots",
        "host-native or direct analysis is the fallback",
        "provider becomes required only when the project survival guide says",
        "so explicitly",
    ],
    "config.json.example": [
        '"coordination": "cobbler-managed-domain-workflow"',
        '"provider_policy": "native-first-with-optional-external-routes"',
        '"required_env": []',
        '"external_route_examples"',
    ],
    ".ai-docs/architecture.md": [
        "## Coordination hierarchy",
        "Elves executes",
        "Cobbler coordinates",
        "Domain workflows specialize",
        "Math is the first domain workflow",
    ],
    ".ai-docs/conventions.md": [
        "Cobbler is the default coordinator after an Elves invocation",
        "cobbler.default_for_session",
        "Math is a Cobbler-managed domain workflow",
    ],
    ".ai-docs/gotchas.md": [
        "Normal Cobbler and ordinary Elves must not require OpenRouter",
        "math-required-env: []",
    ],
}

DOMAIN_WORKFLOW_FORBIDDEN_PHRASES = {
    label: [
        "Elves can also run configurable mathematical research workflows",
        "OpenRouter is the baseline provider",
        "OpenRouter is the baseline model provider",
        "OpenRouter is the minimum useful setup",
        "Use OpenRouter first when no richer local setup exists",
        "math-provider-policy: openrouter-first",
        '"provider_policy": "openrouter-first"',
        "math-required-env:\n  - OPENROUTER_API_KEY",
        '"required_env": ["OPENROUTER_API_KEY"]',
    ]
    for label in (
        "SKILL.md",
        "AGENTS.md",
        "README.md",
        "references/survival-guide-template.md",
        "references/tool-config-examples.md",
        "references/math-workflow.md",
        "references/math-provider-config.md",
        "references/math-plan-template.md",
        "references/math-review-prompts.md",
        "references/math-artifact-ledgers.md",
        "references/council-workflow.md",
        "references/council-provider-config.md",
        "config.json.example",
    )
}

DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS = {
    label: [
        r"\bmath\b[^.\n]*(?:peer|separate)\s+(?:coordinator|orchestrator|orchestration\s+layer)\b",
        r"\bmath\b[^.\n]*(?:requires|needs)\s+openrouter\b",
        r"\bopenrouter\b\s+is\s+required\s+for\s+math\b",
        r"\bopenrouter_api_key\b\s+(?:is\s+)?(?:required|must\s+be\s+set)\b",
        r"\bmath-required-env:\s*\n\s*-\s*OPENROUTER_API_KEY\b",
    ]
    for label in DOMAIN_WORKFLOW_FORBIDDEN_PHRASES
}

PUBLIC_API_SURFACE_SNAPSHOT_PHRASES = {
    ".gitignore": [
        ".elves/",
    ],
    "SKILL.md": [
        "Public API surface snapshots are optional regression evidence.",
        "Use existing structured sources before inventing scanners",
        "If no credible source exists, record `unavailable` with the reason instead of fabricating",
        "A missing snapshot source is not blocking unless `required: true` was explicitly set in the survival guide.",
        "`required: true` is valid only when explicitly set by the user or project survival guide.",
        "Do not infer required mode from project type, provider config, framework choice, or the presence of API files.",
        "Snapshot artifacts are run artifacts, not product docs",
        "Temporary snapshot artifacts should not remain in final product PR diffs unless the user explicitly",
        "Record shapes and field names, not secrets, bearer tokens, cookies, customer payloads, or production sample data.",
        "A snapshot proves public surface shape only; it is not a substitute for tests, E2E checks, review, or the human-owned constitution.",
        "public API surface delta when configured",
    ],
    "references/survival-guide-template.md": [
        "api-surface-snapshot:",
        "enabled: auto",
        "required: false",
        "Public API surface snapshots are optional regression evidence",
        "A missing snapshot source is not blocking unless required: true was explicitly set",
        "Snapshot artifacts are run artifacts, not product docs",
    ],
    "references/execution-log-template.md": [
        "Public API surface snapshot:",
        "N/A / unavailable reason / no delta / additive / planned breaking / unexpected breaking",
    ],
    "references/review-subagent.md": [
        "API surface snapshot artifacts when configured",
        "Public API surface snapshots",
        "optional regression evidence",
        "A missing snapshot source is not blocking unless `required: true` was explicitly set",
        "A snapshot proves public surface shape only; it is not a substitute",
    ],
    "references/kickoff-prompt-template.md": [
        "Configure optional public API surface snapshot behavior",
        "api-surface-snapshot.enabled: auto",
        "required: false",
        ".elves/api-surface/",
    ],
    "references/tool-config-examples.md": [
        "## Public API Surface Snapshot",
        "enabled: auto",
        "required: false",
        "Use existing structured sources before inventing scanners",
        "If no credible source exists, record `unavailable` with the reason instead of fabricating a snapshot",
        "A snapshot proves public surface shape only; it is not a substitute",
    ],
    "config.json.example": [
        '"api_surface_snapshot"',
        '"enabled": "auto"',
        '"required": false',
        '".elves/api-surface/baseline.json"',
        '"unexpected_breaking_change": "blocking"',
        "snapshots are regression evidence, not authority",
    ],
    "TODO.md": [
        "public API surfaces",
        "implemented `cobbler_runtime.public_api_snapshot` compatibility gate",
    ],
}

PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS = {
    label: [
        r"\bapi\s+snapshots?\s+(?:are|is)\s+required\b",
        r"\bmust\s+generate\s+an?\s+api\s+snapshot\b",
        r"\brequired:\s*true\s+by\s+default\b",
        r"(?<!do not )(?<!never )(?<!don't )(?<!should not )(?<!must not )\binfer\s+required\s+mode\b",
        r"\bsnapshots?\s+replace\s+(?:tests|the constitution|review)\b",
        r"(?<!do not )(?<!never )(?<!don't )(?<!should not )(?<!must not )\bcommit\s+snapshot\s+artifacts\b",
        r"(?<!do not )(?<!never )(?<!don't )(?<!should not )(?<!must not )\brecord\s+(?:raw\s+)?(?:secrets|bearer tokens|cookies|customer payloads|production sample data)\b",
        r"(?<!do not )(?<!never )(?<!don't )(?<!should not )(?<!must not )\bcapture\s+(?:raw\s+)?(?:secrets|bearer tokens|cookies|customer payloads|production sample data)\b",
        r"(?<!do not )(?<!never )(?<!don't )(?<!should not )(?<!must not )\binclude\s+(?:raw\s+)?(?:secrets|bearer tokens|cookies|customer payloads|production sample data)\b",
    ]
    for label in (
        "SKILL.md",
        "AGENTS.md",
        "README.md",
        "references/survival-guide-template.md",
        "references/execution-log-template.md",
        "references/review-subagent.md",
        "references/kickoff-prompt-template.md",
        "references/tool-config-examples.md",
        "config.json.example",
    )
}

COUNCIL_MODULE_PHRASES = {
    "README.md": [
        "/cobbler",
        "/setup-cobbler",
        "$elves cobbler: <task>",
        "Ask the Cobbler",
        "Codex users should not need or expect a top-level `/cobbler` command",
        "Council is a deprecated alias of Cobbler",
    ],
    "SKILL.md": [
        "## Cobbler",
        "Cobbler",
        "/cobbler",
        "$elves cobbler: <task>",
        "/council",
        "/ec",
        "/elves-council",
        "$elves council: <task>",
        "Host honesty matters",
        "do not assume Codex has a top-level `/cobbler` command",
        "Codex Goals are optional continuation plumbing",
        "not required for a Quick Cobbler answer",
        "default orchestration model",
        "Cobbler-first coordination is the default for Elves runs",
        "worker agents may edit the repo",
        "Quick Cobbler is the default one-off answer mode",
        "read-only",
        "stateless",
        "Codex subagents",
        "Claude Code subagents",
        "read-only lens analysis directly",
        "Optional model routing is role-scoped",
        "provider model such as `openrouter:<model-id>`",
        "resolve dissent by",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Risks",
        "Next move",
        "Confidence",
        "run state",
        "Provider-backed council is optional",
        "must not require",
        "vendor identity",
    ],
    "references/council-workflow.md": [
        "# Cobbler Workflow",
        "Cobbler is the default coordination layer",
        "Council is the compatibility path",
        "Claude Code primary: `/cobbler <task>`",
        "Codex primary: `$elves cobbler: <task>`",
        "Codex compatibility: `$elves council: <task>`",
        "Do not document Codex as having a top-level `/cobbler`",
        "Run Cobbler is the default coordination pattern inside an Elves run",
        "Worker agents may edit",
        "Quick Cobbler is the default one-off answer mode",
        "Quick Cobbler is the default one-off answer mode. It is always read-only and stateless",
        "Role agents do not see each other's reports before synthesis",
        "Run Cobbler reuses existing Elves memory surfaces",
        "Provider-backed council is not a third Cobbler mode",
        "use must not require OpenRouter",
        "Optional model routing is role-scoped",
        "fall back to native subagents",
        "model prestige",
        "Do not make Quick Cobbler require OpenRouter",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Risks",
        "Next move",
        "Confidence",
        "Do not create a separate PR, branch, survival guide, execution log, or ledger",
    ],
    "references/council-prompts.md": [
        "# Cobbler Prompt Templates",
        "Cobbler roles are lenses with obligations, not theatrical personas",
        "Do not read or rely on other role reports",
        "Work scope",
        "worker edit with assigned files",
        "Run Cobbler is the default coordination",
        "Return one fitted answer",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Next move",
        "why_this_fits",
        "strongest_dissent",
        "next_move",
    ],
    "references/council-provider-config.md": [
        "# Cobbler Provider-Backed Council Configuration",
        "Cobbler-first coordination is the default for Elves runs",
        "Normal Cobbler",
        "$elves cobbler: <task>",
        "use must work without",
        "Cobbler-first Elves runs and Quick Cobbler one-off answers need no provider configuration",
        "cobbler-coordination-default: cobbler-first",
        "cobbler-model-routing-policy: native-first",
        "provider:model-id",
        "fall back to native",
        "cobbler-provider-backed-required-env: []",
        "Do not make ordinary Cobbler or Council-compatible use",
        "Do not create a separate Council ledger",
    ],
    "references/codex-goals.md": [
        "Goals keeps Codex moving; Cobbler coordinates the Elves loop",
        "Codex Goals are not required for Quick Cobbler",
        "$elves cobbler: <task>",
        "Ask the Cobbler",
        "$elves council: <task>",
        "You only need a Quick Cobbler answer",
        "`survival_guide_path`",
        "`learnings_path`",
        "`plan_path`",
        "`execution_log_path`",
        "do not substitute generic filenames",
    ],
    "references/tool-config-examples.md": [
        "## Cobbler",
        "Default Cobbler coordination block for Elves runs",
        "Cobbler-first is the default orchestration",
        "Quick Cobbler requires no external provider",
        "cobbler-coordination-default: cobbler-first",
        "cobbler-default-backend: native-subagents",
        "cobbler-model-routing-policy: native-first",
        "cobbler-provider-backed-fallback: native-subagent-and-note",
        "openrouter:<model-id>",
        "low, medium, high, or xhigh",
        "cobbler-run-logging: existing-elves-memory",
        "cobbler-provider-backed-required-env: []",
        "Legacy `council-*` config keys remain compatibility aliases",
    ],
    "references/survival-guide-template.md": [
        "Coordination mode",
        "### Cobbler Coordination Defaults",
        "Cobbler-first coordination is the default for Elves runs",
        "Provider-backed council is optional",
        "cobbler-coordination-default: cobbler-first",
        "cobbler-default-backend: native-subagents",
        "cobbler-model-routing-policy: native-first",
        "cobbler-provider-backed-fallback: native-subagent-and-note",
        "openrouter:<model-id>",
        "low, medium, high, or xhigh",
        "cobbler-run-logging: existing-elves-memory",
        "cobbler-provider-backed-required-env: []",
        "Legacy `council-*` config keys remain compatibility aliases",
    ],
    "config.json.example": [
        '"cobbler"',
        '"council"',
        '"coordination_default": "cobbler-first"',
        '"default_for_elves_runs": true',
        '"primary_invocations"',
        '"default_answer_shape"',
        '"provider_backed_council"',
        '"compatibility_for": "cobbler"',
        '"precedence": "cobbler"',
        '"default_backend": "native-subagents"',
        '"quick_read_only": true',
        '"quick_stateless": true',
        '"run_logging": "existing-elves-memory"',
        '"model_routing_policy": "native-first"',
        '"fallback": "native-subagent-and-note"',
        '"external_route_example": "openrouter:<model-id>"',
        '"required_env": []',
        '"provider_policy": "optional-external-providers"',
    ],
}

COUNCIL_SECTION_HEADINGS = {
    "SKILL.md": "## Cobbler",
    "AGENTS.md": "## Cobbler",
}

CLAUDE_ALIAS_MARKER = "<!-- elves-managed-alias: claude-skill-alias v1 -->"

CLAUDE_ALIAS_SKILL_PHRASES = {
    "aliases/claude/cobbler/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: cobbler",
        "/cobbler",
        "default orchestration model",
        "Use the installed `elves` skill",
        "For one-off Quick Cobbler answers, stay read-only and stateless",
        "worker agents may edit scoped files",
        "Claude Code subagents",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Next move",
        "must not require OpenRouter",
    ],
    "aliases/claude/cobbler-mode/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: cobbler-mode",
        "/cobbler-mode",
        "Cobbler Mode",
        "default orchestration model",
        "current-thread",
        "Cobbler Mode: on",
        "Cobbler Mode: off",
        "not durable run state",
        "For one-off Quick Cobbler answers, stay read-only and stateless",
        "worker agents may edit scoped files",
        "Claude Code subagents",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Next move",
        "must not require OpenRouter",
    ],
    "aliases/claude/setup-cobbler/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: setup-cobbler",
        "/setup-cobbler",
        "onboard plan|show|apply|probe",
        "Never stage",
        ".elves/models.toml",
        "must not require OpenRouter",
    ],
    "aliases/claude/setup-council/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: setup-council",
        "/setup-council",
        "onboard plan|show|apply|probe",
        "compatibility",
        "must not require OpenRouter",
        "Never stage",
    ],
    "aliases/claude/council/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: council",
        "/council",
        "compatibility alias",
        "default orchestration model",
        "installed `elves`",
        "For one-off Quick Cobbler answers, stay read-only and stateless",
        "worker agents may edit scoped files",
        "Claude Code subagents",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Next move",
        "must not require OpenRouter",
    ],
    "aliases/claude/ec/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: ec",
        "/ec",
        "compatibility alias",
        "default orchestration model",
        "installed `elves`",
        "For one-off Quick Cobbler answers, stay read-only and stateless",
        "worker agents may edit scoped files",
        "Claude Code subagents",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Next move",
        "must not require OpenRouter",
    ],
    "aliases/claude/elves-council/SKILL.md": [
        CLAUDE_ALIAS_MARKER,
        "name: elves-council",
        "/elves-council",
        "compatibility alias",
        "default orchestration model",
        "installed `elves`",
        "For one-off Quick Cobbler answers, stay read-only and stateless",
        "worker agents may edit scoped files",
        "Claude Code subagents",
        "Recommendation",
        "Why this fits",
        "Strongest dissent",
        "Next move",
        "must not require OpenRouter",
    ],
}

CODEX_INSTALL_COBBLER_PHRASES = {
    "README.md": [
        "--target codex",
        "Do not invent top-level /cobbler",
        "Codex installs the main skill bundle only",
        "$elves cobbler: <task>",
    ],
}

COBBLER_CONFIG_PREFERENCE_PHRASES = {
    "README.md": [
        "Put new Cobbler preferences",
        "under the top-level `cobbler` block",
        "is for compatibility with older",
        "if both blocks are present, `cobbler` wins",
    ],
    "SKILL.md": [
        "Cobbler preferences belong under the top-level `cobbler` block",
        "if both blocks are present",
        "`cobbler` wins",
    ],
    "config.json.example": [
        '"precedence": "cobbler"',
        "If both blocks are present, cobbler wins",
    ],
}

COUNCIL_FORBIDDEN_PHRASES = {
    "README.md": [
        "ordinary `/council` requires OpenRouter",
        "normal `/council` requires OpenRouter",
        "ordinary Cobbler requires OpenRouter",
        "normal Cobbler requires OpenRouter",
        "Cobbler requires `OPENROUTER_API_KEY`",
        "Council requires `OPENROUTER_API_KEY`",
        "Cobbler is optional for Elves runs",
        "Cobbler only runs when invoked",
        "Run Cobbler is just Quick Cobbler inside a run",
        "Run Cobbler is Quick Cobbler inside an existing Elves run",
        "Use `/cobbler` in Codex",
        "Use `/council` in Codex",
        "Quick Cobbler requires Codex Goals",
        "Cobbler requires `/goal`",
    ],
    "SKILL.md": [
        "ordinary `/council` requires OpenRouter",
        "normal `/council` requires OpenRouter",
        "ordinary Cobbler requires OpenRouter",
        "normal Cobbler requires OpenRouter",
        "Cobbler requires `OPENROUTER_API_KEY`",
        "Council requires `OPENROUTER_API_KEY`",
        "Elves can also run Cobbler",
        "Cobbler is optional for Elves runs",
        "Cobbler only runs when invoked",
        "Run Cobbler is just Quick Cobbler inside a run",
        "Run Cobbler is Quick Cobbler inside an existing Elves run",
        "Use `/cobbler` in Codex",
        "Use `/council` in Codex",
        "Quick Cobbler requires Codex Goals",
        "Cobbler requires `/goal`",
    ],
    "AGENTS.md": [
        "ordinary `/council` requires OpenRouter",
        "normal `/council` requires OpenRouter",
        "ordinary Cobbler requires OpenRouter",
        "normal Cobbler requires OpenRouter",
        "Cobbler requires `OPENROUTER_API_KEY`",
        "Council requires `OPENROUTER_API_KEY`",
        "Elves can also run Cobbler",
        "Cobbler is optional for Elves runs",
        "Cobbler only runs when invoked",
        "Run Cobbler is just Quick Cobbler inside a run",
        "Run Cobbler is Quick Cobbler inside an existing Elves run",
        "Use `/cobbler` in Codex",
        "Use `/council` in Codex",
        "Quick Cobbler requires Codex Goals",
        "Cobbler requires `/goal`",
    ],
    "references/codex-goals.md": [
        "Quick Cobbler requires Codex Goals",
        "Cobbler requires `/goal`",
        "Use `/cobbler` in Codex",
        "Use `/council` in Codex",
        "docs/elves/survival-guide.md",
        "docs/plans/my-plan.md",
        "docs/elves/execution-log.md",
    ],
    "references/council-workflow.md": [
        "ordinary `/council` requires OpenRouter",
        "normal `/council` requires OpenRouter",
        "Council requires `OPENROUTER_API_KEY`",
        "Council can edit files",
        "Council can create branches",
        "Council can open PRs",
        "# Elves Council Workflow",
        "Quick Council is the default",
        "Run Council reuses existing Elves memory surfaces",
        "Deep Council is optional",
        "Do not make Quick Council require OpenRouter",
        "Quick Cobbler is read-only and stateless unless",
        "Quick Cobbler is the default one-off answer mode. It is read-only and stateless unless",
        "### Provider-Backed Council",
    ],
    "references/council-provider-config.md": [
        "ordinary `/council` requires OpenRouter",
        "normal `/council` requires OpenRouter",
        "Council requires `OPENROUTER_API_KEY`",
        "# Council Provider Configuration",
        "Quick Council needs no provider configuration",
        "Deep Council is opt-in",
        "council-deep-required-env",
    ],
    "references/council-prompts.md": [
        "# Elves Council Prompts",
        "Council roles are lenses with obligations",
        "You are synthesizing independent Elves Council reports",
        "Mode: [Quick Cobbler / Run Cobbler / Provider-backed council]",
    ],
    "references/tool-config-examples.md": [
        "## Elves Council",
        "Quick Council requires no external provider key",
        "Optional Deep Council provider diversity",
        "council-deep-required-env",
    ],
    "references/survival-guide-template.md": [
        "### Elves Council Configuration (optional)",
        "External providers are optional Deep Council",
        "Optional Deep Council provider diversity",
        "council-deep-required-env",
    ],
}

COBBLER_FORBIDDEN_PATTERNS = {
    label: [
        r"\bquick\s+cobbler\s+(?:needs|requires)\s+openrouter\b",
        r"\bnormal\s+cobbler\s+requires\s+(?:an\s+)?external\s+provider\s+key\b",
        r"\bcobbler\s+requires\s+openrouter\b",
        r"\bcouncil-compatible\s+use\s+requires\s+openrouter\b",
        r"\bopenrouter_api_key\b\s+is\s+required\s+for\s+cobbler\b",
        r"\bcobbler\s+is\s+optional\s+for\s+elves\s+runs\b",
        r"\bcobbler\s+only\s+runs\s+when\s+invoked\b",
        r"\brun\s+cobbler\s+is\s+(?:just\s+)?quick\s+cobbler\s+inside\s+(?:an?\s+)?(?:active\s+)?(?:elves\s+)?run\b",
        r"\bquick\s+cobbler\b[^.\n]*(?:unless|except)\b[^.\n]*(?:active\s+elves\s+run|implementation|edit|mutate)\b",
        r"\bcobbler\s+mode\s+persists\s+across\s+threads\b",
        r"\bcobbler\s+mode\s+starts\s+an?\s+elves\s+run\b",
        r"\bcobbler\s+mode\s+requires\s+codex\s+goals\b",
        r"\bcobbler\s+mode\s+can\s+edit\s+files\s+by\s+default\b",
        r"\buse\s+`?/cobbler-mode`?\s+in\s+codex\b",
    ]
    for label in (
        "SKILL.md",
        "AGENTS.md",
        "README.md",
        "references/council-workflow.md",
        "references/council-provider-config.md",
        "references/tool-config-examples.md",
        "references/survival-guide-template.md",
        "config.json.example",
        "aliases/claude/cobbler/SKILL.md",
        "aliases/claude/cobbler-mode/SKILL.md",
        "aliases/claude/council/SKILL.md",
        "aliases/claude/ec/SKILL.md",
        "aliases/claude/elves-council/SKILL.md",
    )
}

COBBLER_MODE_PHRASES = {
    "SKILL.md": [
        "Cobbler Mode is the lowest-friction way",
        "/cobbler-mode",
        "$elves cobbler-mode",
        "Cobbler Mode: on",
        "Cobbler Mode: off",
        "current-thread conversation state",
        "not durable run state",
        "daemon",
        "Codex slash command",
    ],
    "references/council-workflow.md": [
        "### Cobbler Mode",
        "not a third Cobbler behavior mode",
        "/cobbler-mode",
        "$elves cobbler-mode",
        "Cobbler Mode: on",
        "Cobbler Mode: off",
        "current-thread conversation state",
        "not durable run state",
        "branch, PR, survival guide, execution log, Codex Goal",
    ],
    "aliases/claude/cobbler-mode/SKILL.md": [
        "name: cobbler-mode",
        "/cobbler-mode",
        "Cobbler Mode",
        "default orchestration model",
        "current-thread",
        "Cobbler Mode: on",
        "Cobbler Mode: off",
        "not durable run state",
        "daemon",
    ],
}

COBBLER_HARNESS_LOOP_PHRASES = {
    "SKILL.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "present/record",
        "reclassify",
    ],
    "docs/cobbler.md": [
        "capability scan",
        "Route and medium selection",
        "Context packet",
        "Execute agents/tools/skills",
        "Collect evidence",
        "Fit answer",
        "Present/record",
        "Reclassify",
        "does not copy Fable's model identity",
    ],
    "references/council-workflow.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "Present/record",
        "Reclassify",
    ],
    "references/council-prompts.md": [
        "Capability scan",
        "Route and medium",
        "Context packet",
        "Evidence",
        "Present/record",
        "Reclassify",
    ],
    "references/tool-config-examples.md": [
        "cobbler-harness-loop",
        "capability-scan",
        "route-and-medium-selection",
        "context-packet",
        "execute-agents-tools-skills",
        "collect-evidence",
        "fit-answer",
        "present-record",
        "reclassify",
    ],
    "references/survival-guide-template.md": [
        "cobbler-harness-loop",
        "capability-scan",
        "route-and-medium-selection",
        "context-packet",
        "execute-agents-tools-skills",
        "collect-evidence",
        "fit-answer",
        "present-record",
        "reclassify",
    ],
    "config.json.example": [
        '"harness_loop"',
        '"capability_scan"',
        '"route_and_medium_selection"',
        '"context_packet"',
        '"execute_agents_tools_skills"',
        '"collect_evidence"',
        '"fit_answer"',
        '"present_record"',
        '"reclassify"',
    ],
    "aliases/claude/cobbler/SKILL.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "present/record",
        "reclassify",
    ],
    "aliases/claude/cobbler-mode/SKILL.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "present/record",
        "reclassify",
    ],
    "aliases/claude/council/SKILL.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "present/record",
        "reclassify",
    ],
    "aliases/claude/ec/SKILL.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "present/record",
        "reclassify",
    ],
    "aliases/claude/elves-council/SKILL.md": [
        "capability scan",
        "route and medium selection",
        "context packet",
        "execute agents/tools/skills",
        "collect evidence",
        "fit answer",
        "present/record",
        "reclassify",
    ],
}

COBBLER_HARNESS_DRIFT_PATTERNS = {
    label: [
        r"\bquick\s+cobbler\b[^.\n]*(?:edits|mutates|commits|pushes|opens\s+prs)\b",
        r"\bcontext\s+packet\b[^.\n]*(?:includes|contains)\s+(?:secrets|tokens|credentials|cookies)\b",
        r"\bprovider-backed\s+council\b[^.\n]*(?:required|default)\b",
        r"\breclassify\b[^.\n]*(?:by\s+changing\s+run\s+state|by\s+creating\s+a\s+new\s+run)\b",
    ]
    for label in COBBLER_HARNESS_LOOP_PHRASES
}

FULL_RUN_MODEL_ROUTING_PHRASES = {
    "SKILL.md": [
        "Full-run model routing is a separate optional staging preference",
        "`model-routing` phase preferences",
        "native-first by default",
        "requested route, actual route, and material fallback reason",
        "`requested_route`, `actual_route`, and `fallback_reason`",
        "Missing optional provider access",
        "`required: true`",
    ],
    "references/survival-guide-template.md": [
        "### Full-Run Model Routing (optional)",
        "policy: native-first",
        "fallback: host-native",
        "implement-model: strongest-host-native",
        "JSON keys: requested_route, actual_route, fallback_reason",
    ],
    "references/execution-log-template.md": [
        "**Phase routing (optional):**",
        "Requested route",
        "Actual route",
        "Fallback reason",
    ],
    "references/review-subagent.md": [
        "## Phase Route Context",
        "requested route, actual route, and fallback reason",
        "required: true",
        "Missing optional provider access is not a",
    ],
    "references/tool-config-examples.md": [
        "## Full-Run Model Routing",
        "model-routing:",
        "native-subagent, host-default",
        "openrouter:<model-id>",
        "Do not treat bare aliases as provider model IDs",
    ],
    "references/council-workflow.md": [
        "Run Cobbler is not the same thing as full-run model routing",
        "requested route, actual route, and material fallback reason",
        "separate council ledger",
    ],
    "references/council-prompts.md": [
        "Full-run model routing belongs to Elves run control",
        "not the Quick Cobbler role selector",
    ],
    "references/council-provider-config.md": [
        "## Full-Run Phase Routes",
        "Provider-backed council slots may satisfy read-only full-run model-routing phases",
        "Do not make implementation provider-backed by default",
        "route, actual route, and fallback reason",
    ],
    "config.json.example": [
        '"model_routing"',
        '"policy": "native-first"',
        '"fallback": "host-native"',
        '"required": false',
        '"provider_backed_allowed": false',
        '"log_material_fallbacks": true',
    ],
}

FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES = {
    label: [
        "ordinary Elves requires OpenRouter",
        "normal Elves requires OpenRouter",
        "model-routing requires OpenRouter",
        "full-run model routing requires OpenRouter",
        "required: true is the default",
        "route mismatch is always blocking",
        "implementation routes to external providers by default",
        "Quick Cobbler uses model-routing",
    ]
    for label in (
        "SKILL.md",
        "AGENTS.md",
        "README.md",
        "references/survival-guide-template.md",
        "references/execution-log-template.md",
        "references/review-subagent.md",
        "references/tool-config-examples.md",
        "references/council-workflow.md",
        "references/council-prompts.md",
        "references/council-provider-config.md",
        "config.json.example",
    )
}

FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS = {
    label: [
        r"\bfull-run\s+model\s+routing\s+requires\s+(?:an\s+)?external\s+provider\s+key\b",
        r"\bmodel-routing\s+requires\s+openrouter\b",
        r"\brequired:\s*true\s+is\s+(?:the\s+)?default\b",
        r"(?<!do not )\bmake\s+implementation\s+provider-backed\s+by\s+default\b",
    ]
    for label in FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES
}

# Who implements: host-native default + optional external implementer / host-import writer.
IMPLEMENTATION_LANES_PHRASES = {
    "SKILL.md": [
        "### Who implements (native default, optional extras)",
        "Default: host-native only",
        "Vanilla Cobbler uses whatever host is running the skill",
        "same pattern as the math module",
        "implementation_lane: fast | untrusted",
        "cobbler_agents.py implement prepare|launch|gate|resume-batch|status",
        "references/grok-implementer-launch-prompt.md",
        "the default overnight path",
        "cobbler_agents.py worker",
        "Do not invent top-level Codex slash commands",
    ],
    "CHANGELOG.md": [
        "### Optional external batch implementer",
        "implementation_lane: fast | untrusted",
        "cobbler_agents.py implement prepare|launch|gate|resume-batch|status",
        "references/grok-implementer-launch-prompt.md",
        "not the default overnight path",
        "### Docs: native-first implement framing",
        "vanilla Cobbler is host-native",
    ],
    "references/grok-implementer-launch-prompt.md": [
        "This is not the Elves default",
        "implementation_lane: fast | untrusted",
        "cobbler_agents.py implement prepare",
        "not** use that lease path as the default",
        "Omit `implementation_lane` entirely for host-native runs",
    ],
    "references/councilelves-launch-prompt.md": [
        "Vanilla path",
        "Claude Code or Codex out of the box",
        "implementation_lane: fast | untrusted",
        "cobbler_agents.py implement prepare|launch|gate|resume-batch|status",
        "not** use the untrusted lease path as the default overnight",
        "cobbler_agents.py worker",
    ],
}

# External-agent setup (v1.20.0 Batch 5).
SETUP_COBBLER_PHRASES = {
    "SKILL.md": [
        "### External-agent setup and model onboarding",
        "Supported main drivers are Claude Code and Codex only",
        "/setup-cobbler",
        "/setup-council",
        "$elves setup-cobbler",
        "$elves setup-council",
        "not a top-level",
        "cobbler_agents.py onboard",
        "cobbler_agents.py setup",
        ".elves/models.toml",
        "references/model-onboarding.md",
        "references/cobbler-setup-recipes.md",
    ],
    "docs/cobbler.md": [
        "/setup-cobbler",
        "/setup-council",
        "$elves setup-cobbler",
        "$elves setup-council",
        "model onboarding",
        "cobbler-setup-recipes.md",
        "model-onboarding.md",
        "Never stage",
    ],
    "references/cobbler-setup-recipes.md": [
        "/setup-cobbler",
        "/setup-council",
        "$elves setup-cobbler",
        "onboard plan",
        "verified",
        "experimental",
        "custom",
        "OPENROUTER_API_KEY",
        "native-only",
        "remaining_quota",
        "Never stage",
    ],
    "references/model-onboarding.md": [
        "Model Onboarding",
        "Claude Code + Codex",
        "Supported hosts (main drivers)",
        "not been our focus",
        "many have not been heavily",
        "Antigravity CLI",
        "Prefer a PR",
        "onboard plan",
        "onboard apply",
        "onboard probe",
        "Never stage",
        "host-native",
    ],
    "aliases/claude/setup-cobbler/SKILL.md": [
        "model onboarding",
        "onboard plan|show|apply|probe",
        "Never stage",
        ".elves/models.toml",
        "must not require OpenRouter",
    ],
}

# Coordinator-to-implementer handoff + git-history-as-operator-UI standards (v1.20.0 Batch 1).
IMPLEMENTER_HANDOFF_PHRASES = {
    "SKILL.md": [
        "## Coordinator-to-Implementer Handoff Standard",
        "intent / why",
        "Build On targets",
        "owned surfaces",
        "forbidden surfaces",
        "acceptance evidence",
        "failure modes / pitfalls",
        "HEAD / run-doc paths / route-session identity / output format",
        "blocking coordinator defect",
    ],
    "references/plan-template.md": [
        "Coordinator-to-implementer handoff",
        "Build On targets",
        "Owned surfaces",
        "Forbidden surfaces",
        "acceptance evidence",
        "Failure modes / pitfalls",
        "HEAD / run-doc paths / route-session identity / output format",
    ],
    "references/survival-guide-template.md": [
        "Coordinator-to-implementer handoff",
        "Build On targets",
        "owned surfaces",
        "forbidden surfaces",
        "acceptance evidence",
    ],
    "references/execution-log-template.md": [
        "Handoff standard",
        "Build On targets",
        "owned surfaces",
        "forbidden surfaces",
        "acceptance evidence",
    ],
    "references/review-subagent.md": [
        "Coordinator-to-implementer handoff obligations",
        "blocking coordinator defect",
        "Build On targets",
        "owned surfaces",
        "forbidden surfaces",
        "acceptance evidence",
    ],
}


RISK_TIER_PHRASES = {
    "SKILL.md": [
        "Thin safety kernel",
        "validate once, verify changes, attest final",
        "low | standard | high",
        "trusted | untrusted",
        "touched surfaces",
        "risk checkpoints",
        "terminal readiness",
        "exact HEAD",
        "impact-selected",
    ],
    "references/joyful-runs-contract.md": [
        "low",
        "standard",
        "high",
        "trusted",
        "untrusted",
        "ready=true never grants merge permission",
    ],
    "references/proof-and-review.md": [
        "validate once, verify changes, attest final",
        "impact path",
        "delta re-review",
    ],
}

PROGRESS_COMMIT_PHRASES = {
    "SKILL.md": [
        "## Git History as Operator UI",
        "[<branch> · Batch N/total · Contract|Implement|Validate|Review|Close] <concrete outcome>",
        "Forbid vague subjects",
        "audited detached handoff commits",
        "never own refs, remotes, push, PRs, or canonical run memory",
        "Reserve the `Close` phase for acceptance-backed batch completion",
        "Protected refs, PR operations, and merge never dispatch model inference",
    ],
    "references/plan-template.md": [
        "Contract|Implement|Validate|Review|Close",
        "Forbid vague subjects",
        "audited detached handoff commits",
        "never own refs/remotes/push/PR/run-memory",
        "Close` requires",
    ],
    "references/survival-guide-template.md": [
        "Contract|Implement|Validate|Review|Close",
        "Forbid vague subjects",
        "audited detached handoff commits",
        "Close` requires acceptance",
        "Git/PR ops never dispatch model inference",
    ],
    "references/execution-log-template.md": [
        "Contract|Implement|Validate|Review|Close",
        "forbid vague subjects",
        "audited detached handoff commits",
        "never own refs/remotes/push/PR/run-memory",
    ],
    "references/review-subagent.md": [
        "Git history as operator UI",
        "Contract|Implement|Validate|Review|Close",
        "audited detached handoff commits",
        "Close` appears only with acceptance evidence",
        "did not dispatch model inference",
    ],
}

# Vague subjects must remain present as anti-pattern examples on skill mirrors.
PROGRESS_COMMIT_ANTIPATTERN_EXAMPLES = {
    "SKILL.md": [
        "[feat/payments · Batch 3/12] Updates",
        "[feat/payments · Batch 3/12 · Implement] progress",
        "[feat/payments · Batch 3/12 · Implement] WIP",
        "[feat/payments · Batch 3/12 · Implement] fixes",
    ],
}

PUBLIC_WORDING_FILES = [
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "config.json.example",
]

PUBLIC_WORDING_FORBIDDEN_PHRASES = [
    # Exact model names are valid in the route-identity contract. Keep
    # prohibiting branding/persona claims that describe Cobbler as Fable-like.
    "Fable-like",
    "Fable-style",
    "inspired by Fable",
    "cobbled together",
    "cobbled-together",
]

# Persona claims that describe Cobbler as *being* Fable, matched
# case-insensitively by the pattern engine. Bare model identifiers
# (`Fable 5`, `claude-fable-5`) remain legitimate route-identity wording and
# never match these patterns.
PUBLIC_WORDING_FORBIDDEN_PATTERNS = [
    r"powered\s+by\s+fable",
    r"built\s+on\s+fable",
    r"backed\s+by\s+fable",
    r"driven\s+by\s+fable",
    r"fable\s+under\s+the\s+hood",
    r"fable\s+persona",
]

# --- Elves 2.3: thin AGENTS adapter + compact SKILL pins ---
_AGENTS_THIN_POINTER = [
    'thin Codex adapter',
    'canonical workflow is',
    'SKILL.md',
    'Codex Goals',
    'Grok Build goal mode',
    'chat-to-work',
    'chat-to-land',
    'plan Acceptance with proof',
    'Stop Gate',
    'continuation_guard',
    '\\land-pr',
    '/land-pr',
    'source-checkout shorthand',
    'active Elves skill root',
    '$ELVES_SKILL_ROOT/scripts/elves_landing_check.py',
    '--session <session-path> --repo-root .',
    'Build On',
    'owned surfaces',
    'forbidden surfaces',
    'acceptance evidence',
    'blocking coordinator defect',
    'Contract|Implement|Validate|Review|Close',
    'Forbid vague subjects',
    '[feat/auth · Batch 3/12] Updates',
    '[feat/auth · Batch 3/12 · Implement] progress',
    'One run owns one branch and one checkout',
    'optional regression evidence',
]

# One whole-file thin-adapter check replaces the per-corpus AGENTS.md shims:
# AGENTS.md is a pointer file, so it carries each contract's NAME exactly once
# and the corpora that own the contracts no longer pin AGENTS.md separately.
AGENTS_POINTER_PHRASES = {"AGENTS.md": list(_AGENTS_THIN_POINTER)}

if isinstance(COUNCIL_MODULE_PHRASES, dict):
    COUNCIL_MODULE_PHRASES = dict(COUNCIL_MODULE_PHRASES)
    COUNCIL_MODULE_PHRASES["AGENTS.md"] = [
        "$elves cobbler: <task>",
        "$elves council: <task>",
        "Ask the Cobbler",
        "Codex Goals",
        "Grok Build goal mode",
        "capability-proven enhancement",
        "one-packet fallback",
        "authenticated live catalog",
    ]

if isinstance(COBBLER_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in COBBLER_FORBIDDEN_PATTERNS:
    COBBLER_FORBIDDEN_PATTERNS = {k: v for k, v in COBBLER_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(COBBLER_HARNESS_DRIFT_PATTERNS, dict) and 'AGENTS.md' in COBBLER_HARNESS_DRIFT_PATTERNS:
    COBBLER_HARNESS_DRIFT_PATTERNS = {k: v for k, v in COBBLER_HARNESS_DRIFT_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS:
    DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS = {k: v for k, v in DOMAIN_WORKFLOW_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS:
    EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS = {k: v for k, v in EXACT_FULL_RUN_COMMAND_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS:
    FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS = {k: v for k, v in FULL_RUN_MODEL_ROUTING_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS:
    INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS = {k: v for k, v in INSTALLED_REPO_ONLY_HELPER_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(LANDING_CHECK_BARE_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in LANDING_CHECK_BARE_FORBIDDEN_PATTERNS:
    LANDING_CHECK_BARE_FORBIDDEN_PATTERNS = {k: v for k, v in LANDING_CHECK_BARE_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS, dict) and 'AGENTS.md' in PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS:
    PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS = {k: v for k, v in PUBLIC_API_SURFACE_SNAPSHOT_FORBIDDEN_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(SINGLE_KICKOFF_UNSCOPED_PATTERNS, dict) and 'AGENTS.md' in SINGLE_KICKOFF_UNSCOPED_PATTERNS:
    SINGLE_KICKOFF_UNSCOPED_PATTERNS = {k: v for k, v in SINGLE_KICKOFF_UNSCOPED_PATTERNS.items() if k != 'AGENTS.md'}
if isinstance(COUNCIL_FORBIDDEN_PHRASES, dict) and 'AGENTS.md' in COUNCIL_FORBIDDEN_PHRASES:
    COUNCIL_FORBIDDEN_PHRASES = {k: v for k, v in COUNCIL_FORBIDDEN_PHRASES.items() if k != 'AGENTS.md'}
if isinstance(DOMAIN_WORKFLOW_FORBIDDEN_PHRASES, dict) and 'AGENTS.md' in DOMAIN_WORKFLOW_FORBIDDEN_PHRASES:
    DOMAIN_WORKFLOW_FORBIDDEN_PHRASES = {k: v for k, v in DOMAIN_WORKFLOW_FORBIDDEN_PHRASES.items() if k != 'AGENTS.md'}
if isinstance(FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES, dict) and 'AGENTS.md' in FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES:
    FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES = {k: v for k, v in FULL_RUN_MODEL_ROUTING_FORBIDDEN_PHRASES.items() if k != 'AGENTS.md'}
if isinstance(REVIEWED_PR_LANDING_FORBIDDEN_PHRASES, dict) and 'AGENTS.md' in REVIEWED_PR_LANDING_FORBIDDEN_PHRASES:
    REVIEWED_PR_LANDING_FORBIDDEN_PHRASES = {k: v for k, v in REVIEWED_PR_LANDING_FORBIDDEN_PHRASES.items() if k != 'AGENTS.md'}
if isinstance(SINGLE_KICKOFF_FORBIDDEN_PHRASES, dict) and 'AGENTS.md' in SINGLE_KICKOFF_FORBIDDEN_PHRASES:
    SINGLE_KICKOFF_FORBIDDEN_PHRASES = {k: v for k, v in SINGLE_KICKOFF_FORBIDDEN_PHRASES.items() if k != 'AGENTS.md'}
if isinstance(ACCEPTANCE_EVIDENCE_PHRASES, dict) and 'SKILL.md' in ACCEPTANCE_EVIDENCE_PHRASES:
    ACCEPTANCE_EVIDENCE_PHRASES = dict(ACCEPTANCE_EVIDENCE_PHRASES)
    ACCEPTANCE_EVIDENCE_PHRASES['SKILL.md'] = ['plan Acceptance with proof', 'acceptance', 'elves_landing_check.py', 'God-file', 'one batch per close commit']
if isinstance(COBBLER_CONFIG_PREFERENCE_PHRASES, dict) and 'SKILL.md' in COBBLER_CONFIG_PREFERENCE_PHRASES:
    COBBLER_CONFIG_PREFERENCE_PHRASES = dict(COBBLER_CONFIG_PREFERENCE_PHRASES)
    COBBLER_CONFIG_PREFERENCE_PHRASES['SKILL.md'] = ['config.json', 'cobbler', 'council']
if isinstance(COBBLER_HARNESS_LOOP_PHRASES, dict) and 'SKILL.md' in COBBLER_HARNESS_LOOP_PHRASES:
    COBBLER_HARNESS_LOOP_PHRASES = dict(COBBLER_HARNESS_LOOP_PHRASES)
    COBBLER_HARNESS_LOOP_PHRASES['SKILL.md'] = ['capability scan', 'context packet', 'Cobbler-first', 'fit answer']
if isinstance(COBBLER_MODE_PHRASES, dict) and 'SKILL.md' in COBBLER_MODE_PHRASES:
    COBBLER_MODE_PHRASES = dict(COBBLER_MODE_PHRASES)
    COBBLER_MODE_PHRASES['SKILL.md'] = ['Cobbler Mode', 'cobbler-mode', 'not durable run state']
if isinstance(COUNCIL_MODULE_PHRASES, dict) and 'SKILL.md' in COUNCIL_MODULE_PHRASES:
    COUNCIL_MODULE_PHRASES = dict(COUNCIL_MODULE_PHRASES)
    COUNCIL_MODULE_PHRASES['SKILL.md'] = ['## Cobbler', '/cobbler', '$elves cobbler', 'Quick Cobbler', 'native-subagent-first', 'Cobbler-first coordination is the default for Elves runs', '$elves council: <task>', 'Host honesty matters', 'do not assume Codex has a top-level `/cobbler` command', 'Codex Goals are optional continuation plumbing', 'not required for a Quick Cobbler answer', 'default orchestration model', 'worker agents may edit the repo', 'Quick Cobbler is the default one-off answer mode', '/council', '/ec', '/elves-council']
if isinstance(DOMAIN_WORKFLOW_PHRASES, dict) and 'SKILL.md' in DOMAIN_WORKFLOW_PHRASES:
    DOMAIN_WORKFLOW_PHRASES = dict(DOMAIN_WORKFLOW_PHRASES)
    DOMAIN_WORKFLOW_PHRASES['SKILL.md'] = ['**Elves** is the execution system', '**Cobbler** is the default coordinator', '**Domain workflows** are specialized Cobbler-managed packs', '**Math** is the first domain workflow', '**Providers** are optional role routes', 'cobbler.default_for_session']
if isinstance(EFFORT_GUARDRAIL_PHRASES, dict) and 'SKILL.md' in EFFORT_GUARDRAIL_PHRASES:
    EFFORT_GUARDRAIL_PHRASES = dict(EFFORT_GUARDRAIL_PHRASES)
    EFFORT_GUARDRAIL_PHRASES['SKILL.md'] = ['## Effort Standard', 'Do not be lazy.', 'Work as hard as you can for']
if isinstance(ELVES_REPORT_PHRASES, dict) and 'SKILL.md' in ELVES_REPORT_PHRASES:
    ELVES_REPORT_PHRASES = dict(ELVES_REPORT_PHRASES)
    ELVES_REPORT_PHRASES['SKILL.md'] = ['## Elves Report', 'problems found', 'lessons learned', '/tmp/elves-report-<repo-slug>-<yyyy-mm-dd>.html', 'references/elves-report-template.html', 'collapsible `<details>` sections', 'committed examples and reusable templates non-identifying', 'Elves Report path']
if isinstance(FINAL_READINESS_REVIEW_PHRASES, dict) and 'SKILL.md' in FINAL_READINESS_REVIEW_PHRASES:
    FINAL_READINESS_REVIEW_PHRASES = dict(FINAL_READINESS_REVIEW_PHRASES)
    FINAL_READINESS_REVIEW_PHRASES['SKILL.md'] = ['Final Readiness Review', 'git diff <default-branch>...HEAD', 'review subagent']
if isinstance(FULL_RUN_MODEL_ROUTING_PHRASES, dict) and 'SKILL.md' in FULL_RUN_MODEL_ROUTING_PHRASES:
    FULL_RUN_MODEL_ROUTING_PHRASES = dict(FULL_RUN_MODEL_ROUTING_PHRASES)
    FULL_RUN_MODEL_ROUTING_PHRASES['SKILL.md'] = ['model routing', 'native-first', 'fallback', 'Missing optional provider access']
if isinstance(IMPLEMENTATION_LANES_PHRASES, dict) and 'SKILL.md' in IMPLEMENTATION_LANES_PHRASES:
    IMPLEMENTATION_LANES_PHRASES = dict(IMPLEMENTATION_LANES_PHRASES)
    IMPLEMENTATION_LANES_PHRASES['SKILL.md'] = ['trusted Grok', 'full-run', 'parked', 'untrusted', 'Do not invent top-level Codex slash commands', 'implementation_lane: fast | untrusted']
if isinstance(IMPLEMENTER_HANDOFF_PHRASES, dict) and 'SKILL.md' in IMPLEMENTER_HANDOFF_PHRASES:
    IMPLEMENTER_HANDOFF_PHRASES = dict(IMPLEMENTER_HANDOFF_PHRASES)
    IMPLEMENTER_HANDOFF_PHRASES['SKILL.md'] = ['Build On', 'owned surfaces', 'forbidden surfaces', 'acceptance evidence', 'blocking coordinator defect', 'HEAD / run-doc paths / route-session identity / output format']
if isinstance(INSTALLED_HELPER_PATH_PHRASES, dict) and 'SKILL.md' in INSTALLED_HELPER_PATH_PHRASES:
    INSTALLED_HELPER_PATH_PHRASES = dict(INSTALLED_HELPER_PATH_PHRASES)
    INSTALLED_HELPER_PATH_PHRASES['SKILL.md'] = ['source-checkout shorthand', 'active Elves skill root', '~/.claude/skills/elves', '~/.codex/skills/elves', '$ELVES_SKILL_ROOT/scripts/acceptance_contract.py', '$ELVES_SKILL_ROOT/scripts/elves_landing_check.py', 'installed Elves bundle never requires a repo-only helper']
if isinstance(LANDING_CHECK_CONTRACT_PHRASES, dict) and 'SKILL.md' in LANDING_CHECK_CONTRACT_PHRASES:
    LANDING_CHECK_CONTRACT_PHRASES = dict(LANDING_CHECK_CONTRACT_PHRASES)
    LANDING_CHECK_CONTRACT_PHRASES['SKILL.md'] = ['$ELVES_SKILL_ROOT/scripts/elves_landing_check.py', '--session <session-path> --repo-root .', 'plan_path', 'equality assertion']
if isinstance(MATH_MODULE_PHRASES, dict) and 'SKILL.md' in MATH_MODULE_PHRASES:
    MATH_MODULE_PHRASES = dict(MATH_MODULE_PHRASES)
    MATH_MODULE_PHRASES['SKILL.md'] = ['Cobbler-managed Elves domain workflow', 'Discovery Sprint', 'Native host subagents or direct analysis are the default', 'useful optional math role preset', 'Google Cloud AlphaEvolve', 'math-alphaevolve.md', 'Never treat model output']
if isinstance(MEMORY_HYGIENE_PHRASES, dict) and 'SKILL.md' in MEMORY_HYGIENE_PHRASES:
    MEMORY_HYGIENE_PHRASES = dict(MEMORY_HYGIENE_PHRASES)
    MEMORY_HYGIENE_PHRASES['SKILL.md'] = ['## Strategic Forgetting', 'chats are for execution', 'memory and resource hygiene']
if isinstance(NONSTOP_GUARDRAIL_PHRASES, dict) and 'SKILL.md' in NONSTOP_GUARDRAIL_PHRASES:
    NONSTOP_GUARDRAIL_PHRASES = dict(NONSTOP_GUARDRAIL_PHRASES)
    NONSTOP_GUARDRAIL_PHRASES['SKILL.md'] = ['Stop Gate', 'continuation_guard', 'After every host-owned commit and push, re-read the survival guide before doing anything else.', 'Do not wait for user acknowledgment']
if isinstance(PROGRESS_COMMIT_PHRASES, dict) and 'SKILL.md' in PROGRESS_COMMIT_PHRASES:
    PROGRESS_COMMIT_PHRASES = dict(PROGRESS_COMMIT_PHRASES)
    PROGRESS_COMMIT_PHRASES['SKILL.md'] = ['## Git History as Operator UI', '[<branch> · Batch N/total · Contract|Implement|Validate|Review|Close] <concrete outcome>', 'Forbid vague subjects', 'audited detached handoff commits', 'never own refs, remotes, push, PRs, or canonical run memory', 'Protected refs, PR operations, and merge never dispatch model inference']
if isinstance(PUBLIC_API_SURFACE_SNAPSHOT_PHRASES, dict) and 'SKILL.md' in PUBLIC_API_SURFACE_SNAPSHOT_PHRASES:
    PUBLIC_API_SURFACE_SNAPSHOT_PHRASES = dict(PUBLIC_API_SURFACE_SNAPSHOT_PHRASES)
    PUBLIC_API_SURFACE_SNAPSHOT_PHRASES['SKILL.md'] = ['Public API surface snapshots are optional regression evidence.', 'Use existing structured sources before inventing scanners', 'If no credible source exists, record `unavailable` with the reason instead of fabricating', 'A missing snapshot source is not blocking unless `required: true` was explicitly set in the survival guide.', '`required: true` is valid only when explicitly set by the user or project survival guide.', 'Do not infer required mode from project type, provider config, framework choice, or the presence of API files.', 'Snapshot artifacts are run artifacts, not product docs', 'Temporary snapshot artifacts should not remain in final product PR diffs unless the user explicitly', 'Record shapes and field names, not secrets, bearer tokens, cookies, customer payloads, or production sample data.', 'A snapshot proves public surface shape only; it is not a substitute for tests, E2E checks, review, or the human-owned constitution.', 'public API surface delta when configured']
if isinstance(REVIEWED_PR_LANDING_PHRASES, dict) and 'SKILL.md' in REVIEWED_PR_LANDING_PHRASES:
    REVIEWED_PR_LANDING_PHRASES = dict(REVIEWED_PR_LANDING_PHRASES)
    REVIEWED_PR_LANDING_PHRASES['SKILL.md'] = ['## Reviewed PR Landing Command', 'gh pr merge --merge', '\\land-pr', '/land-pr', 'default when bots are expected']
if isinstance(RISK_TIER_PHRASES, dict) and 'SKILL.md' in RISK_TIER_PHRASES:
    RISK_TIER_PHRASES = dict(RISK_TIER_PHRASES)
    RISK_TIER_PHRASES['SKILL.md'] = ['Thin safety kernel', 'validate once, verify changes, attest final', 'low | standard | high', 'trusted | untrusted', 'touched surfaces', 'risk checkpoints', 'terminal readiness', 'exact HEAD', 'impact-selected']
if isinstance(SETUP_COBBLER_PHRASES, dict) and 'SKILL.md' in SETUP_COBBLER_PHRASES:
    SETUP_COBBLER_PHRASES = dict(SETUP_COBBLER_PHRASES)
    SETUP_COBBLER_PHRASES['SKILL.md'] = ['setup-cobbler', 'setup-council', 'model-onboarding.md', 'not a top-level', 'cobbler_agents.py setup', 'references/cobbler-setup-recipes.md', 'Supported main drivers are Claude Code and Codex only', '$elves setup-council']
if isinstance(SINGLE_KICKOFF_PHRASES, dict) and 'SKILL.md' in SINGLE_KICKOFF_PHRASES:
    SINGLE_KICKOFF_PHRASES = dict(SINGLE_KICKOFF_PHRASES)
    SINGLE_KICKOFF_PHRASES['SKILL.md'] = ['Default user path: one kickoff', 'Trusted full-run delegation keeps that path', 'chat-to-work', 'chat-to-land', 'Legacy two-call', 'full-run', 'parked']
if isinstance(WORKSPACE_ISOLATION_PHRASES, dict) and 'SKILL.md' in WORKSPACE_ISOLATION_PHRASES:
    WORKSPACE_ISOLATION_PHRASES = dict(WORKSPACE_ISOLATION_PHRASES)
    WORKSPACE_ISOLATION_PHRASES['SKILL.md'] = ['One run owns one branch and one checkout', './scripts/preflight.sh --create-worktree <branch> --base origin/main', '--dry-run', 'branch, worktree path, base ref, and collision tripwire', 'does not reuse, delete, or repair existing worktrees']

ADAPTIVE_WORKER_ROUTING_PHRASES = {
    "SKILL.md": [
        "subscription-native worker",
        "authenticated live",
        "same GPT-5.6 model at `medium`",
        "same Fable 5 model at `low`",
        "`claude-opus-4-8` at `medium`",
        "prefer `grok-4.5` at explicit `high`",
        "Composer 2.5 is retired",
        "${XDG_CONFIG_HOME:-~/.config}/elves/config.json",
        "approval-bypass authority",
    ],
    "AGENTS.md": [
        "exact same-model/lower-effort route map",
        "references/adaptive-worker-routing.md",
    ],
    "README.md": [
        "Native delegation names both model and effort",
        "same GPT-5.6 model at `medium`",
        "same Fable 5 model at `low`",
        "`claude-opus-4-8` at `medium`",
        "`grok-4.5` at explicit `high`",
        "Composer 2.5",
    ],
    "references/adaptive-worker-routing.md": [
        "repository safety veto > explicit run intent > repository defaults > global convenience",
        "authenticated live",
        "exact observed model identity",
        "same observed GPT-5.6 model ID at `medium`",
        "same observed `claude-fable-5` model ID at `low`",
        "`claude-opus-4-8` at `medium`",
        "`grok-4.5` at `high` when present in the live catalog",
        "Composer 2.5 is retired",
        "codex exec resume <thread-id>",
        "a session ID is not such an object",
    ],
    "guide/index.html": [
        "Same model, lower effort",
        "GPT-5.6 <code>medium</code>",
        "Fable 5 <code>low</code>",
        "claude-opus-4-8",
        "<code>grok-4.5</code> at <code>high</code>",
        "Composer 2.5 is retired",
    ],
    "CHANGELOG.md": [
        "Explicit delegation route identity and Grok highest-effort default",
        "same GPT-5.6 identity at `medium`",
        "`claude-opus-4-8` at `medium`",
        "authenticated live-catalog default at explicit",
        "Prefer **`grok-4.5` at `high`**",
        "Adaptive subscription-native workers",
        "authenticated live-catalog models",
        "prompt/KV cache",
    ],
}

PREWALK_PHRASES = {
    "SKILL.md": [
        "Exact-session prewalk",
        "A fresh session",
        "with a copied packet or summary is not prewalk",
        "post-edit cold fallback is forbidden",
        "Static help proves",
        "behavioral evidence never grants launch authority",
        "references/prewalk.md",
    ],
    "AGENTS.md": [
        "Prewalk:",
        "cold packet handoff is not prewalk",
        "references/prewalk.md",
    ],
    "README.md": [
        "Optional exact-session prewalk",
        "same session in the same worktree",
        "Static help probes make no model calls",
        "behavioral qualification never opens",
        "references/prewalk.md",
    ],
    "references/prewalk.md": [
        "Elves **prewalk** is a trajectory property",
        "separately qualified worker session",
        "execution route with only",
        "retained_safe",
        "post-edit cold fallback",
        "normally reports actual mode `off`",
        "External providers remain off unless their trajectory semantics are separately qualified",
        "grok_prewalk_qualification_canary",
        "qualification does not itself open the separate registry launch gate",
        "never fabricates them",
    ],
    "references/host-parity.md": [
        "Exact-session prewalk parity",
        "one redacted logical follow stream",
        "no post-edit cold fallback",
        "prewalk.md",
        "no release may claim Grok prewalk availability or behavioral qualification",
        "grok_prewalk_unqualified",
        "cannot open the separate",
    ],
    "references/adaptive-worker-routing.md": [
        "Optional exact-session prewalk route",
        "requested/actual prewalk mode",
        "help probes always report false",
        "actual mode `off`",
        "prewalk_capability_unavailable:grok_prewalk_unqualified:",
        "does not open the separate registry launch gate",
        "no release may claim Grok prewalk availability or behavioral qualification",
    ],
    "guide/index.html": [
        "Use exact-session prewalk when qualified",
        "same session in the same",
        "no paid canary runs implicitly",
        "cannot open",
        "references/prewalk.md",
    ],
    "CHANGELOG.md": [
        "True exact-session native-worker prewalk",
        "execution-route resume with only",
        "no paid canary ran",
        "remains feature-gated off",
        "Qualification never opens the separate registry launch feature gate",
        "claims Grok prewalk availability or behavioral qualification",
    ],
}

EXPLICIT_HANDOFF_V1_PHRASES = {
    "SKILL.md": [
        "strict explicit",
        "handoff v1",
        "advisory, never",
        "does not turn a cold handoff into exact-session prewalk",
    ],
    "AGENTS.md": [
        "explicitly declared handoff-v1",
        "strict",
        "host-neutral",
    ],
    "README.md": [
        "machine-checked cold handoff",
        "ordinary v2.8 path remains advisory",
        "not prewalk continuity proof",
    ],
    "references/schema-and-acceptance.md": [
        "Optional explicit handoff v1",
        "Presence is the opt-in",
        "Both formats are bounded",
        "It is not trajectory continuity",
    ],
    "references/survival-guide-template.md": [
        "Handoff validation:",
        "explicit-v1",
        "never proof of exact-session prewalk continuity",
    ],
    "CHANGELOG.md": [
        "Explicit handoff v1 staging contract",
        "advisory-only",
        "never proves exact-session prewalk continuity",
    ],
}

GROK_OPEN_SOURCE_WORKER_PHRASES = {
    "SKILL.md": [
        "authenticated live",
        "behaviorally proven headless goal mode",
        "one-packet fallback",
        "Native Claude Code and Codex",
    ],
    "CHANGELOG.md": [
        "authenticated live-catalog models",
        "behaviorally proven headless `/goal`",
        "one-packet fallback",
        "Native Codex and Claude Code routes",
    ],
    "docs/elves/learnings.md": [
        "authenticated live catalog's parsed default",
        "another exact catalog member",
        "`/goal status` command resolution",
        "did not reach terminal state",
        "one-packet prompt fallback",
        "mode-safe terminal-canary JSON artifact",
        "digest ID",
        "full-run-await",
    ],
    "references/adaptive-worker-routing.md": [
        "authenticated live",
        "behaviorally verified headless `/goal`",
        "one-packet prompt fallback",
        "--grok-goal-behavioral-evidence <artifact.json>",
        "exact installed version/build",
        "--host claude",
    ],
    "references/cobbler-setup-recipes.md": [
        "authenticated live catalog",
        "one-packet fallback",
        "full-run-await --json",
        "grok-open-source-worker.md",
    ],
    "references/grok-implementer-launch-prompt.md": [
        "authenticated live-catalog parsed default",
        "one-packet prompt path",
        "full-run-await",
        "Claude Code and Codex remain complete without Grok",
    ],
    "references/grok-open-source-worker.md": [
        "https://github.com/xai-org/grok-build",
        "curl -fsSL https://x.ai/cli/install.sh | bash",
        "--allow-grok --probe-grok",
        "ELVES_HOST=claude",
        "--host \"$ELVES_HOST\"",
        "grok_goal_terminal_canary",
        "prompt_sha256",
        "64 KiB",
        "32 KiB",
        "digest-derived evidence ID",
        "narrow auth projection",
        "command resolution",
        "terminal state",
        "one-packet fallback",
        "full-run-launch --json",
        "full-run-await --json",
        "full-run-reconcile --json",
        "--host-tests-pass",
        "--resume --grant-grok-auth",
        "/goal resume",
        "## Feature-gated prewalk lane (distinct from trusted full-run)",
        "--permission-mode auto",
        "grok_prewalk_qualification_canary",
        "operator-authorized live canary",
        "cannot grant launch authority",
        "commit `98c3b24`",
        "source commit `7cfcb20`",
    ],
    "guide/index.html": [
        "https://github.com/xai-org/grok-build",
        "curl -fsSL https://x.ai/cli/install.sh | bash",
        "--provider grok --allow-grok --probe-grok",
        "ELVES_HOST=claude",
        "--host \"$ELVES_HOST\"",
        "mode-safe JSON canary artifact",
        "prompt digest",
        "narrow OAuth projection",
        "command resolution",
        "terminal",
        "one-packet fallback",
        "implement full-run-await --session-id",
        "implement full-run-launch --session-id",
        "implement full-run-reconcile --json",
        "--host-tests-pass",
        "--grant-grok-auth --grant-github-push",
    ],
    "references/host-parity.md": [
        "narrow auth projection",
        "command resolution",
        "catalog lookup and model inference",
        "validated terminal objective-canary artifact",
        "exact installed version/build",
        "prompt digest",
        "one-packet fallback",
        "catalog qualify",
        "--host claude",
        "--host codex",
        "live driver's transport",
    ],
}

_GROK_UPSTREAM_PIN_RE = None  # lazily compiled in grok_upstream_commit_pin_errors


def grok_upstream_commit_pin_errors(semantic_commit: str | None = None) -> list[str]:
    """Cross-check the doc-pinned Grok upstream short SHA against runtime.

    The reference doc pin ("source commit `<short>`" over
    references/grok-open-source-worker.md) and
    worker_routing.GROK_UPSTREAM_SEMANTIC_COMMIT describe the same upstream
    commit; a one-sided bump of either must fail consistency. Tests may inject
    a semantic_commit to exercise the disagreeing state.
    """
    import re
    import sys

    global _GROK_UPSTREAM_PIN_RE
    if _GROK_UPSTREAM_PIN_RE is None:
        _GROK_UPSTREAM_PIN_RE = re.compile(r"source commit `([0-9a-f]{7,40})`")
    if semantic_commit is None:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from cobbler_runtime.worker_routing import (  # noqa: PLC0415
            GROK_UPSTREAM_SEMANTIC_COMMIT,
        )

        semantic_commit = GROK_UPSTREAM_SEMANTIC_COMMIT
    pins = [
        match
        for phrase in GROK_OPEN_SOURCE_WORKER_PHRASES.get(
            "references/grok-open-source-worker.md", []
        )
        for match in _GROK_UPSTREAM_PIN_RE.findall(phrase)
    ]
    errors: list[str] = []
    if not pins:
        errors.append(
            "consistency policy no longer pins the Grok upstream `source commit` "
            "phrase over references/grok-open-source-worker.md"
        )
    for pin in pins:
        if not str(semantic_commit or "").startswith(pin):
            errors.append(
                f"doc-pinned Grok upstream source commit `{pin}` is not a prefix "
                "of worker_routing.GROK_UPSTREAM_SEMANTIC_COMMIT "
                f"`{semantic_commit}`; bump both sides together"
            )
    return errors


GROK_OPEN_SOURCE_WORKER_FORBIDDEN_PHRASES = {
    "docs/elves/learnings.md": [
        "use permitted Grok Composer 2.5 Fast for regular clear work",
        "resume, `/goal`, streaming JSON",
    ],
}

WORKER_CONFIDENCE_SIGNAL_PHRASES = {
    "SKILL.md": [
        "**Confidence trailer**",
        "`Confidence: <level>` alone when `unsure_about` is empty",
        "never a lazy default",
        "flagged `unsure_about` areas get a deeper pass",
        "it does not skip gates or waive review in either direction",
        "`review_context.review_prompt_block`",
        "**Confidence-Guided Review**",
        "Claude Code and Codex use this identical contract",
    ],
    "references/review-subagent.md": [
        "## Worker confidence triage (read before the diff):",
        "An empty `unsure_about` list is a valid, complete answer",
        "The signal is triage only, never authority",
        "calibration observation to note in the report, not a violation",
        "The coordinator **must attach that",
        "block verbatim** to the primary Final Readiness prompt",
        "### Confidence-Guided Review",
        "Claude Code and Codex follow the same rule and prompt shape",
    ],
    "references/host-parity.md": [
        "`elves-worker-confidence-review-v1`",
        "attach its `review_prompt_block` verbatim",
        "confidence to reduce review or gates",
    ],
    "README.md": [
        "Worker confidence now actively guides the primary review on both Claude Code and Codex",
        "Missing signals fall back to the full baseline review",
        "high confidence never reduces gates or",
        "review scope",
    ],
    "guide/index.html": [
        "Worker confidence actively guides that review on both Claude Code and Codex",
        "Missing signals",
        "high confidence never removes a gate or review step",
    ],
    "scripts/cobbler_agents.py": [
        'review_context.get("review_prompt_block")',
        'print(review_context["review_prompt_block"])',
    ],
    "scripts/cobbler_runtime/full_run.py": [
        '"schema": "elves-worker-confidence-review-v1"',
        '"confidence_can_reduce_scope": False',
        '"flagged_areas_require_deeper_pass": True',
        '"missing_signal_falls_back_to_full_review": True',
    ],
    "references/grok-implementer-launch-prompt.md": [
        "**worker confidence signal**",
        "an empty list means \"I verified everything I touched and have no reservations,\"",
        "review triage only, never authority",
        "include your confidence (high | medium | low) and any areas you were unsure about, if any",
    ],
    "references/survival-guide-template.md": [
        "The packet also carries the confidence-reporting requirement:",
        "empty list is a valid, complete answer; triage signal only, never authority.",
    ],
    "CHANGELOG.md": [
        "Worker confidence signal (audit B5)",
        "never a lazy default",
        "review triage only, never authority",
    ],
}

PARALLELVES_CONTRACT_PHRASES = {
    "references/parallelves.md": [
        "not a runtime scheduler, and not an authority change",
        "exactly one coordination hierarchy: Cobbler routes lanes the way it already routes",
        "Cobbler lenses are read-only responders; Parallelves lanes",
        "is shared; the authority model is not. Lanes never gain merge, PR, or protected-ref authority.",
        "Serial remains the default everywhere.",
        "`auto` may only recommend lanes when every",
        "Nothing auto-launches.",
        "no sentence in this contract claims a runtime lane orchestrator, and none exists",
        "`parallel_declined:<gate>:<detail>` reason, recorded as provenance.",
        "`parallel_declined:worker_dominance:no_recorded_timings`",
        "in a driver-owned order, and produces one PR for the whole run.",
        "composes existing per-session worker runs (native or trusted full-run), one\nper lane, per each host's documented grammar",
        "The cross-lane entropy review is mandatory before the integration PR is review-ready.",
        "Per-lane confidence signals order the",
        "Going parallel is a reversible bet.",
        "most one lane's result lands.",
        "`off` (default) | `auto`. `auto` is recommend-only and",
        "2-3 lanes maximum in v1",
        "activate for no host until",
        "Runtime lane supervision is explicitly future work and ships in no v1 batch.",
    ],
    "references/glossary.md": [
        "default, recommend-only `auto`, no runtime orchestrator, no authority change",
        "feature branch on pairwise-disjoint owned surfaces, under the existing worker authority model.",
        "a serial batch that builds shared foundations before lanes fork",
        "per-lane review structurally cannot see.",
        "budget, risk posture) that must pass before `auto` may recommend lanes",
        "judges, and at most one lane's result lands.",
        "the width test records for every declined gate; parallelism is never silently withheld.",
    ],
    "AGENTS.md": [
        "**Parallel lanes (Parallelves):** serial default; `worker.parallel=auto` is recommend-only and\n  nothing auto-launches",
    ],
    "guide/index.html": [
        "Serial stays the default.",
        "<code>auto</code> only recommends lanes when a deterministic width test passes. Nothing\n          launches lanes automatically",
    ],
    "README.md": [
        "serial default, recommend-only width test, trunk -> lanes -> integration",
        "serial stays the default, and\n`worker.parallel=auto` only recommends lanes when the deterministic width test passes",
    ],
    "SKILL.md": [
        "parallel lanes are an earned\nrouting outcome, never a mode switch",
        "`worker.parallel=auto` may only recommend lanes, every decline records a\nconcrete `parallel_declined:<gate>:<detail>` reason, and nothing auto-launches",
        "mandatory cross-lane entropy review",
    ],
    "references/review-subagent.md": [
        "this cross-lane pass is mandatory\nbefore the integration PR is review-ready",
        "the cumulative integration diff, every\nlane's per-lane review record, and every lane's confidence signals",
        "cross-lane question classes that per-lane review structurally cannot see",
        "**Duplicated helpers across lanes**",
        "**Convention divergence**",
        "**Conflicting approaches to shared concerns**",
        "low-confidence lanes and\nflagged `unsure_about` areas are reviewed first",
        "calibration observation to note in the report, not a violation; the signal remains\ntriage only, never authority",
    ],
    "references/host-parity.md": [
        "identical semantics on Claude Code and\nCodex: serial default, recommend-only `auto`",
        "The lanes tooling is\ndeterministic and host-neutral; both hosts invoke it the same way",
        "Per-lane worker launches introduce no new invocation grammar",
        "same subscription-native default and optional-provider rules as any worker",
        "nothing in\nthis section launches lanes at runtime",
    ],
    "references/schema-and-acceptance.md": [
        "advisory in v1, exactly like the pre-handoff-v1",
        "records lane state for recovery and does not validate it",
        "plus the runtime fields `branch`, `worktree`, `session_id`, and `status`",
        "A session without\n`lanes` is serial (the default).",
        "Declaring `lanes` launches nothing and grants nothing",
    ],
    "CHANGELOG.md": [
        "Serial remains the default everywhere; there is no runtime lane\n  orchestrator in v1 and no sentence claims one.",
        "The test is recommend-only; every declined gate records a concrete\n  `parallel_declined:<gate>:<detail>` reason, and nothing auto-launches.",
    ],
    "references/plan-template.md": [
        "Omitting this section means serial (the default).",
        "`owned_surfaces`, and `batches`, plus a `trunk:` batch list built serially before lanes fork.",
        "Declaring lanes never launches anything: `worker.parallel=auto` may only recommend them when",
        "the width test passes, and every decline records a concrete reason.",
    ],
}
