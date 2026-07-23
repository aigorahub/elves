#!/usr/bin/env python3
"""Fresh installed-bundle smokes for Claude Code and Codex skill copies.

Copies a minimal installed-like skill bundle into a temporary directory and
executes operator CLI entry points from an unrelated CWD with a scrubbed
``PYTHONPATH`` so imports resolve only from the installed artifact — never from
the source checkout.

No live model calls. Network is not required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_CLAUDE_ALIASES = (
    "cobbler",
    "cobbler-mode",
    "council",
    "ec",
    "elves-council",
    "fugu",
    "manus",
    "grok",
    "devin",
    "setup-cobbler",
    "setup-council",
)
CLAUDE_ALIAS_MARKER = "<!-- elves-managed-alias: claude-skill-alias v1 -->"

# This is an independent installed-artifact contract, not a reflection of the
# sync allowlist. If sync drops a required helper, this smoke must still fail.
# Call-site deps (worktree_gc, provider_supervisor) must stay listed here even
# if someone later trims the sync list — smoke is the installed product gate.
REQUIRED_TOP_LEVEL_RUNTIME_PATHS = (
    "scripts/preflight.sh",
    "scripts/preflight_worktree.py",
    "scripts/notify.sh",
    "scripts/install_doctor.py",
    "scripts/validate_survival_guide.py",
    "scripts/acceptance_contract.py",
    "scripts/elves_landing_check.py",
    "scripts/landing_profile.py",
    "scripts/cobbler_agents.py",
    "scripts/openrouter_lens.py",
    "scripts/workspace_guard.py",
    "scripts/worktree_gc.py",
    "scripts/provider_supervisor.py",
    "scripts/run_fugu.sh",
    "scripts/run_manus.sh",
    "scripts/run_grok.sh",
    "scripts/run_devin.sh",
)

# Must never appear under an installed skill root (source-checkout archives).
FORBIDDEN_INSTALLED_ARCHIVE_PATHS = (
    "docs/plans",
    "docs/elves",
)

# These helpers maintain this source repository and must not become mandatory
# installed-skill dependencies. Installed docs may name them conditionally, but
# must never present a directly executable source-relative command for one.
REPO_ONLY_HELPER_PATHS = (
    "scripts/check_repo_consistency.py",
    "scripts/release_checklist.py",
    "scripts/pr_portfolio_report.py",
    "scripts/sync_installed_skills.py",
    "scripts/verify_repo.py",
    "scripts/installed_bundle_smoke.py",
)
REPO_ONLY_COMMAND_RE = re.compile(
    r"python3\s+(?:\./)?scripts/(?:"
    + "|".join(re.escape(Path(path).name) for path in REPO_ONLY_HELPER_PATHS)
    + r")\b"
)
INSTALLED_PATH_CONTRACT_PHRASES = (
    "source-checkout shorthand",
    "active elves skill root",
    "target repository as the working directory",
    "~/.claude/skills/elves",
    "~/.codex/skills/elves",
    "$elves_skill_root/scripts/elves_landing_check.py",
    "installed elves bundle never requires a repo-only helper",
)

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_REFERENCE_DEFINITION_RE = re.compile(
    r"(?m)^\s{0,3}\[([^]]+)\]:\s*(<[^>]+>|\S+)(?:\s+.*)?$"
)
MARKDOWN_REFERENCE_LINK_RE = re.compile(r"!?\[([^]]+)\]\[([^]]*)\]")
EXTERNAL_LINK_SCHEMES = frozenset({"http", "https", "mailto", "tel"})

# Commands run against an installed cobbler_agents.py (cwd is outside the bundle).
SMOKE_COMMANDS: list[tuple[str, list[str]]] = [
    ("help", ["--help"]),
    ("preferences-show", ["preferences", "show", "--json"]),
    (
        "route-worker",
        [
            "route-worker", "--host", "codex", "--execution-reasoning", "medium",
            "--review-risk", "standard", "--json",
        ],
    ),
    (
        "native-worker",
        ["native-worker", "spec", "--host", "codex", "--worktree", ".", "--effort", "low", "--model", "fixture-current-model", "--json"],
    ),
    ("validate-config", ["validate-config", "--json"]),
    ("doctor", ["doctor", "--json"]),
    ("setup-dry-run", ["setup", "--dry-run", "--json"]),
    ("onboard-plan", ["onboard", "plan", "--json"]),
    ("implement-status", ["implement", "status", "--json"]),
]

RUNTIME_HELP_COMMANDS = (
    ("acceptance-contract-help", "scripts/acceptance_contract.py", ["--help"]),
    ("landing-check-help", "scripts/elves_landing_check.py", ["--help"]),
    (
        "landing-profile-check-missing",
        "scripts/landing_profile.py",
        ["check", "--json"],
    ),
    ("openrouter-help", "scripts/openrouter_lens.py", ["--help"]),
    ("workspace-guard-help", "scripts/workspace_guard.py", ["--help"]),
)

RECURSIVE_IMPORT_PROGRAM = r"""
import importlib
import json
import sys

names = json.loads(sys.argv[1])
for name in names:
    importlib.import_module(name)
print(json.dumps(names))
"""


def _copy_managed_bundle(repo_root: Path, dest_root: Path, *, host: str) -> None:
    """Populate dest_root like sync_installed_skills would for host."""
    # Import sync helpers without mutating process PYTHONPATH permanently.
    scripts_dir = str(repo_root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import sync_installed_skills as sync  # noqa: PLC0415

    # Temporarily point REPO_ROOT so managed paths resolve from the real checkout.
    original_root = sync.REPO_ROOT
    original_targets = sync.TARGETS
    try:
        sync.REPO_ROOT = repo_root
        sync.TARGETS = sync.build_targets(repo_root)
        # Redirect install roots into the temporary installed-like tree.
        cfg = dict(sync.TARGETS[host])
        cfg["root"] = dest_root
        if host == "claude":
            cfg["alias_root"] = dest_root.parent
        else:
            cfg.pop("alias_root", None)
            cfg.pop("managed_aliases", None)
        sync.TARGETS = {host: cfg}
        problems = sync.apply_target(host)
        if problems:
            raise RuntimeError(f"failed to stage {host} bundle: {problems}")
        for required in ("SKILL.md", "AGENTS.md"):
            if not (dest_root / required).is_file():
                raise RuntimeError(f"{host.title()} bundle missing {required}")
        if host == "codex":
            if (dest_root / "aliases").exists():
                raise RuntimeError("Codex bundle must not contain Claude aliases")
    finally:
        sync.REPO_ROOT = original_root
        sync.TARGETS = original_targets


def _validate_alias_installation(
    host: str,
    *,
    bundle_root: Path,
) -> tuple[list[str], int]:
    """Validate the host-specific alias shape at the installed skills root."""
    install_root = bundle_root.parent
    found = {
        path.name
        for path in install_root.iterdir()
        if path.is_dir() and path.resolve() != bundle_root.resolve()
    }
    failures: list[str] = []
    if host == "claude":
        expected = set(EXPECTED_CLAUDE_ALIASES)
        if found != expected:
            failures.append(
                "Claude install expected exactly eleven managed aliases "
                f"{sorted(expected)}; found {sorted(found)}"
            )
        for name in EXPECTED_CLAUDE_ALIASES:
            skill = install_root / name / "SKILL.md"
            if not skill.is_file():
                failures.append(f"Claude alias {name} missing SKILL.md")
                continue
            if CLAUDE_ALIAS_MARKER not in skill.read_text(encoding="utf-8"):
                failures.append(f"Claude alias {name} missing managed marker")
    elif found:
        failures.append(
            "Codex install must contain no Claude aliases; "
            f"found sibling skill directories {sorted(found)}"
        )
    return failures, len(found)


def _markdown_target(raw: str) -> str:
    """Extract a link destination while tolerating Markdown titles/angle form."""
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")].strip()
    return target.split(maxsplit=1)[0] if target else ""


def _blank_markdown(value: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in value)


def _active_markdown_text(value: str) -> str:
    """Exclude comment and fenced examples from installed-link validation."""
    value = re.sub(
        r"<!--.*?(?:-->|\Z)",
        lambda match: _blank_markdown(match.group(0)),
        value,
        flags=re.DOTALL,
    )
    rendered: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in value.splitlines(keepends=True):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence_char is None:
            if match is None:
                rendered.append(line)
                continue
            marker = match.group(1)
            fence_char = marker[0]
            fence_length = len(marker)
            rendered.append(_blank_markdown(line))
            continue
        rendered.append(_blank_markdown(line))
        if match is not None:
            marker = match.group(1)
            if marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
    return "".join(rendered)


def _validate_installed_markdown_links(install_root: Path) -> tuple[list[str], int]:
    """Resolve local Markdown links inside the shipped install tree only."""
    root = install_root.resolve()
    failures: list[str] = []
    checked = 0
    for markdown in sorted(root.rglob("*.md")):
        text = _active_markdown_text(markdown.read_text(encoding="utf-8"))
        definitions = {
            re.sub(r"\s+", " ", match.group(1)).strip().casefold(): _markdown_target(
                match.group(2)
            )
            for match in MARKDOWN_REFERENCE_DEFINITION_RE.finditer(text)
        }
        targets = [_markdown_target(match.group(1)) for match in MARKDOWN_LINK_RE.finditer(text)]
        for match in MARKDOWN_REFERENCE_LINK_RE.finditer(text):
            label = match.group(2) or match.group(1)
            key = re.sub(r"\s+", " ", label).strip().casefold()
            target = definitions.get(key)
            if target is None:
                failures.append(
                    f"{markdown.relative_to(root)}: missing reference definition [{label}]"
                )
                continue
            targets.append(target)
        for target in targets:
            if not target or target.startswith("#"):
                continue
            parsed = urlsplit(target)
            if parsed.scheme.lower() in EXTERNAL_LINK_SCHEMES or parsed.netloc:
                continue
            if parsed.scheme:
                failures.append(
                    f"{markdown.relative_to(root)}: unsupported installed link {target}"
                )
                continue
            relative = unquote(parsed.path)
            if not relative:
                continue
            destination = (markdown.parent / relative).resolve()
            checked += 1
            try:
                destination.relative_to(root)
            except ValueError:
                failures.append(
                    f"{markdown.relative_to(root)}: link escapes installed tree: {target}"
                )
                continue
            if not destination.exists():
                failures.append(
                    f"{markdown.relative_to(root)}: unshipped link target {target}"
                )
    return failures, checked


def _validate_installed_document_contract(bundle_root: Path) -> tuple[list[str], int]:
    """Pin installed helper paths and reject executable repo-only commands."""
    failures: list[str] = []
    checked = 0
    for relative in ("SKILL.md", "AGENTS.md"):
        path = bundle_root / relative
        if not path.is_file():
            failures.append(f"installed document contract missing {relative}")
            continue
        checked += 1
        normalized = path.read_text(encoding="utf-8").casefold()
        for phrase in INSTALLED_PATH_CONTRACT_PHRASES:
            if phrase not in normalized:
                failures.append(
                    f"{relative}: missing installed helper-path contract `{phrase}`"
                )

    reference = bundle_root / "references" / "runtime-helper-paths.md"
    checked += 1
    if not reference.is_file():
        failures.append("installed bundle missing references/runtime-helper-paths.md")

    for markdown in sorted(bundle_root.rglob("*.md")):
        checked += 1
        text = markdown.read_text(encoding="utf-8")
        match = REPO_ONLY_COMMAND_RE.search(text)
        if match:
            failures.append(
                f"{markdown.relative_to(bundle_root)}: executable repo-only helper "
                f"command `{match.group(0)}`"
            )
    return failures, checked


def _runtime_module_names(package: Path) -> set[str]:
    """Map every recursively shipped Python file to its import name."""
    names: set[str] = set()
    for path in package.rglob("*.py"):
        relative = path.relative_to(package.parent).with_suffix("")
        if relative.name == "__init__":
            relative = relative.parent
        names.add(".".join(relative.parts))
    return names


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def smoke_host(
    host: str,
    *,
    repo_root: Path | None = None,
    keep: bool = False,
) -> dict[str, object]:
    """Stage and smoke one host. Returns a result dict with ok/failures."""
    root = Path(repo_root or REPO_ROOT).resolve()
    failures: list[str] = []
    notes: list[str] = []
    tmp_parent = Path(tempfile.mkdtemp(prefix=f"elves-install-smoke-{host}-"))
    bundle_root = tmp_parent / "installed" / host / "elves"
    outside_cwd = tmp_parent / "outside-cwd"
    outside_cwd.mkdir(parents=True)
    try:
        bundle_root.mkdir(parents=True)
        _copy_managed_bundle(root, bundle_root, host=host)

        alias_failures, alias_count = _validate_alias_installation(
            host,
            bundle_root=bundle_root,
        )
        failures.extend(alias_failures)

        link_failures, markdown_link_count = _validate_installed_markdown_links(
            bundle_root.parent
        )
        failures.extend(link_failures)

        document_failures, installed_document_count = (
            _validate_installed_document_contract(bundle_root)
        )
        failures.extend(document_failures)

        agents = bundle_root / "scripts" / "cobbler_agents.py"
        openrouter = bundle_root / "scripts" / "openrouter_lens.py"
        workspace_guard = bundle_root / "scripts" / "workspace_guard.py"
        acceptance_contract = bundle_root / "scripts" / "acceptance_contract.py"
        landing_check = bundle_root / "scripts" / "elves_landing_check.py"
        landing_profile = bundle_root / "scripts" / "landing_profile.py"
        package = bundle_root / "scripts" / "cobbler_runtime"
        missing_runtime_paths = [
            relative
            for relative in REQUIRED_TOP_LEVEL_RUNTIME_PATHS
            if not (bundle_root / relative).is_file()
        ]
        for relative in missing_runtime_paths:
            failures.append(f"missing required runtime dependency {relative}")
        for relative in REPO_ONLY_HELPER_PATHS:
            if (bundle_root / relative).exists():
                failures.append(f"repo-only helper leaked into installed bundle {relative}")
        for relative in FORBIDDEN_INSTALLED_ARCHIVE_PATHS:
            if (bundle_root / relative).exists():
                failures.append(
                    f"source-only archive leaked into installed bundle {relative}"
                )
        if not package.is_dir():
            failures.append("missing cobbler_runtime package in installed bundle")
        # Removing any shipped runtime module must be detectable: assert at least
        # one .py file exists under the package (recursive shipment proof).
        py_files = list(package.rglob("*.py")) if package.is_dir() else []
        if not py_files:
            failures.append("cobbler_runtime package has no .py modules")

        # Scrub env so imports cannot fall back to the source checkout.
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_parent / "home"),
            "TMPDIR": str(tmp_parent / "tmp"),
            "TMP": str(tmp_parent / "tmp"),
            "TEMP": str(tmp_parent / "tmp"),
            "PYTHONPATH": str(bundle_root / "scripts"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
        }
        (tmp_parent / "home").mkdir(exist_ok=True)
        (tmp_parent / "tmp").mkdir(exist_ok=True)

        imported_runtime_modules: list[str] = []
        if not failures:
            expected_modules = sorted(_runtime_module_names(package))
            proc = _run(
                [
                    sys.executable,
                    "-c",
                    RECURSIVE_IMPORT_PROGRAM,
                    json.dumps(expected_modules),
                ],
                cwd=outside_cwd,
                env=env,
            )
            if proc.returncode != 0:
                failures.append(
                    "recursive-runtime-imports "
                    f"exit={proc.returncode} stderr={_clip(proc.stderr)}"
                )
            else:
                try:
                    imported_runtime_modules = json.loads(proc.stdout)
                except (json.JSONDecodeError, TypeError) as exc:
                    failures.append(f"recursive-runtime-imports invalid output: {exc}")
                else:
                    if imported_runtime_modules != expected_modules:
                        failures.append(
                            "recursive-runtime-imports mismatch "
                            f"expected={expected_modules} "
                            f"actual={imported_runtime_modules}"
                        )
                    else:
                        notes.append(
                            f"recursive-runtime-imports={len(imported_runtime_modules)}"
                        )

        if not failures:
            for label, args in SMOKE_COMMANDS:
                proc = _run(
                    [sys.executable, str(agents), *args],
                    cwd=outside_cwd,
                    env=env,
                )
                if proc.returncode != 0:
                    failures.append(
                        f"{label} exit={proc.returncode} "
                        f"stderr={_clip(proc.stderr)} stdout={_clip(proc.stdout)}"
                    )
                else:
                    notes.append(f"{label}=ok")
                    if label == "doctor":
                        try:
                            payload = json.loads(proc.stdout)
                        except (json.JSONDecodeError, TypeError) as exc:
                            failures.append(f"doctor invalid JSON output: {exc}")
                        else:
                            observed_root = Path(
                                str(payload.get("repo_root") or "")
                            ).resolve()
                            if observed_root != outside_cwd.resolve():
                                failures.append(
                                    "installed helper did not keep target cwd as repo_root"
                                )
                            else:
                                notes.append("installed-cli-target-cwd=ok")

            # The documented alternative keeps an unrelated command cwd but
            # points runtime state back at the target explicitly.
            proc = _run(
                [
                    sys.executable,
                    str(agents),
                    "doctor",
                    "--repo-root",
                    str(outside_cwd),
                    "--json",
                ],
                cwd=tmp_parent,
                env=env,
            )
            if proc.returncode != 0:
                failures.append(
                    "installed-cli-explicit-repo-root "
                    f"exit={proc.returncode} stderr={_clip(proc.stderr)}"
                )
            else:
                try:
                    payload = json.loads(proc.stdout)
                except (json.JSONDecodeError, TypeError) as exc:
                    failures.append(
                        f"installed-cli-explicit-repo-root invalid JSON: {exc}"
                    )
                else:
                    observed_root = Path(
                        str(payload.get("repo_root") or "")
                    ).resolve()
                    if observed_root != outside_cwd.resolve():
                        failures.append(
                            "installed helper ignored explicit target --repo-root"
                        )
                    else:
                        notes.append("installed-cli-explicit-repo-root=ok")

            # Required standalone helpers must start without credentials/model calls.
            helper_paths = {
                "scripts/acceptance_contract.py": acceptance_contract,
                "scripts/elves_landing_check.py": landing_check,
                "scripts/landing_profile.py": landing_profile,
                "scripts/openrouter_lens.py": openrouter,
                "scripts/workspace_guard.py": workspace_guard,
            }
            for label, relative, args in RUNTIME_HELP_COMMANDS:
                proc = _run(
                    [sys.executable, str(helper_paths[relative]), *args],
                    cwd=outside_cwd,
                    env=env,
                )
                if proc.returncode != 0:
                    failures.append(
                        f"{label} exit={proc.returncode} stderr={_clip(proc.stderr)}"
                    )
                else:
                    notes.append(f"{label}=ok")

            # Negative proof: deleting a required runtime module makes smoke fail.
            victim = package / "schema.py"
            if victim.is_file():
                backup = victim.read_bytes()
                victim.unlink()
                proc = _run(
                    [sys.executable, str(agents), "implement", "status", "--json"],
                    cwd=outside_cwd,
                    env=env,
                )
                victim.write_bytes(backup)
                if proc.returncode == 0:
                    failures.append(
                        "removed cobbler_runtime/schema.py still allowed implement status"
                    )
                else:
                    notes.append("missing-module-fails=ok")

        return {
            "ok": not failures,
            "host": host,
            "bundle_root": str(bundle_root),
            "outside_cwd": str(outside_cwd),
            "failures": failures,
            "notes": notes,
            "py_module_count": len(py_files),
            "imported_runtime_module_count": len(imported_runtime_modules),
            "required_runtime_count": len(REQUIRED_TOP_LEVEL_RUNTIME_PATHS),
            "alias_count": alias_count,
            "markdown_link_count": markdown_link_count,
            "installed_document_count": installed_document_count,
            "skill_present": (bundle_root / "SKILL.md").is_file(),
            "agents_present": (bundle_root / "AGENTS.md").is_file(),
        }
    finally:
        if not keep:
            shutil.rmtree(tmp_parent, ignore_errors=True)


def _clip(text: str, limit: int = 240) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _require_python_floor() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit(
            "installed_bundle_smoke requires Python >= 3.10 (repo floor); "
            f"found {sys.version_info.major}.{sys.version_info.minor}"
        )


def main(argv: list[str] | None = None) -> int:
    _require_python_floor()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        choices=("all", "claude", "codex"),
        default="all",
        help="Which installed-bundle shape to smoke",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Source repository root used to stage the bundle",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep temporary directories (debug)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON results",
    )
    args = parser.parse_args(argv)
    hosts = ["claude", "codex"] if args.host == "all" else [args.host]
    results = [smoke_host(h, repo_root=args.repo_root, keep=args.keep) for h in hosts]
    ok = all(bool(r["ok"]) for r in results)
    if args.json:
        print(json.dumps({"ok": ok, "results": results}, indent=2, sort_keys=True))
    else:
        for r in results:
            status = "OK" if r["ok"] else "FAIL"
            print(f"[{r['host']}] {status} modules={r['py_module_count']}")
            for note in r.get("notes") or []:
                print(f"  - {note}")
            for failure in r.get("failures") or []:
                print(f"  ! {failure}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
