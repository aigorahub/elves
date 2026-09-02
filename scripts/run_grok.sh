#!/bin/bash
# Headless Grok Build task in a read-only tracked-source kernel sandbox.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PROMPT_CONTENT="$*"
if [ -z "$PROMPT_CONTENT" ]; then
  echo "Usage: run_grok.sh <instructions>" >&2
  exit 2
fi
if ! command -v grok >/dev/null 2>&1; then
  echo "Error: Grok Build CLI not found." >&2
  exit 127
fi
if ! REPO_ROOT=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null); then
  echo "Error: run_grok.sh must be invoked inside a Git repository." >&2
  exit 2
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "run_grok.sh requires Python >= 3.10 (repo floor); found $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" >&2
  exit 2
fi

# Opt-in review selectors. Empty keeps the historical posture: the authenticated
# live configuration picks the model, and reasoning effort stays `high`.
GROK_MODEL="${ELVES_GROK_MODEL:-}"
GROK_EFFORT="${ELVES_GROK_EFFORT:-}"

exec python3 - "$PROMPT_CONTENT" "$REPO_ROOT" "$SCRIPT_DIR" "$GROK_MODEL" "$GROK_EFFORT" <<'PY'
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


prompt = sys.argv[1]
repo_root = Path(sys.argv[2]).resolve()
script_dir = Path(sys.argv[3]).resolve()
requested_model = sys.argv[4] if len(sys.argv) > 4 else ""
requested_effort = sys.argv[5] if len(sys.argv) > 5 else ""
sys.path.insert(0, str(script_dir))

from cobbler_runtime.isolation import (  # noqa: E402
    IsolationSpec,
    context_bundle_report,
    isolated_lane,
    wrap_argv_with_sandbox,
)
from cobbler_runtime.grok_launch import (  # noqa: E402
    build_grok_argv,
    isolated_grok_config,
    probe_grok_capabilities,
    probe_grok_catalog,
    require_supported_grok_cli,
    resolve_grok_effort,
    resolve_grok_model,
)
from cobbler_runtime.review_routes import (  # noqa: E402
    classify_review_route_failure,
    route_unavailable_directive,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


def _route_unavailable(status: int, text: str = "") -> None:
    """Grok is an optional review route; tell the host driver to reroute."""
    if status == 0:
        return
    reason = classify_review_route_failure(exit_code=status, text=text) or "provider"
    print(route_unavailable_directive("Grok", reason), file=sys.stderr)


parent = dict(os.environ)
parent_path = parent.get("PATH", "/usr/bin:/bin")
grok = shutil.which("grok", path=parent_path)
if not grok:
    raise SystemExit("Error: Grok Build CLI not found.")

source_home = Path(parent.get("GROK_HOME") or (Path.home() / ".grok")).expanduser()
xai_key = parent.get("XAI_API_KEY", "")
legacy_xai_key = parent.get("GROK_CODE_XAI_API_KEY", "")
if not xai_key and not legacy_xai_key:
    raise SystemExit(
        "Error: run_grok.sh requires an explicit XAI_API_KEY (or legacy "
        "GROK_CODE_XAI_API_KEY). Shared-file OAuth is not exposed to shortcut agents."
    )
credential_name = "XAI_API_KEY" if xai_key else "GROK_CODE_XAI_API_KEY"
credential_value = xai_key or legacy_xai_key

# Read the installed CLI's advertised surface before building the lane, so an
# incompatible Grok Build never costs a snapshot. Flags are not invented: an
# absent safety flag fails closed, and an absent quality flag is dropped.
# `--help` and `--version` never need the provider key, so they run on a minimal
# environment. Only the catalog probe, which must be authenticated to be truthful,
# receives the parent environment.
probe_env = {
    "PATH": parent_path,
    "HOME": parent.get("HOME", ""),
    "LANG": parent.get("LANG", "C.UTF-8"),
}
try:
    capabilities = probe_grok_capabilities(grok, env=probe_env)
    require_supported_grok_cli(capabilities)
    effort = resolve_grok_effort(requested_effort)
    catalog = probe_grok_catalog(grok, env=parent) if requested_model.strip() else None
    model = resolve_grok_model(requested_model, catalog) if catalog else None
except ValidationIssue as exc:
    print(f"Error: Grok launch preflight failed closed [{exc.code}]: {exc}", file=sys.stderr)
    if exc.hint:
        print(f"Hint: {exc.hint}", file=sys.stderr)
    reason = classify_review_route_failure(exit_code=2, text=f"{exc.code}: {exc.message}")
    print(route_unavailable_directive("Grok", reason or "runner"), file=sys.stderr)
    raise SystemExit(2) from exc


def configured_model_default() -> str:
    config_source = source_home / "config.toml"
    try:
        if not config_source.is_file() or config_source.is_symlink():
            return ""
        current_section = ""
        for raw in config_source.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
            if current_section != "models" or "=" not in line or line.startswith("#"):
                continue
            key, raw_value = line.split("=", 1)
            if key.strip() != "default":
                continue
            configured = ast.literal_eval(raw_value.strip())
            return configured.strip() if isinstance(configured, str) else ""
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return ""
    return ""


try:
    with isolated_lane(
        IsolationSpec(
            repo_root=repo_root,
            lane_id=f"grok-shortcut-{os.getpid()}",
            include_instructions_as_data=True,
            credential_grants={credential_name: credential_value},
            base_env={"PATH": parent_path, "LANG": parent.get("LANG", "C.UTF-8")},
            require_fs_sandbox=True,
        )
    ) as lane:
        for line in context_bundle_report(lane, label="Grok"):
            print(line, file=sys.stderr)
        home = lane.home
        grok_home = home / ".grok"
        grok_home.mkdir(mode=0o700)

        claude_home = home / ".claude"
        claude_home.mkdir(mode=0o700)
        (claude_home / "settings.json").write_text(
            json.dumps({"permissions": {"defaultMode": "dontAsk"}}, indent=2) + "\n",
            encoding="utf-8",
        )
        (claude_home / "settings.json").chmod(0o600)
        (grok_home / "requirements.toml").write_text(
            "[ui]\ndisable_bypass_permissions_mode = true\n",
            encoding="utf-8",
        )
        (grok_home / "requirements.toml").chmod(0o600)

        # Auto-update replaced the removed `--no-auto-update` flag with the
        # `[cli] auto_update` config key, which every supported version reads. The
        # outer kernel sandbox stays the authority: it never grants write access to
        # the CLI's own install tree. Only these keys are written; the host's own
        # config (permission mode, plugins, MCP servers) is never copied in.
        (grok_home / "config.toml").write_text(
            isolated_grok_config(model_default=model or configured_model_default()),
            encoding="utf-8",
        )
        (grok_home / "config.toml").chmod(0o600)

        # Grok's built-in strict profile narrows reads and blocks child network
        # on Linux. Do not add a custom deny profile here: Grok implements Linux
        # read-deny with a nested bwrap re-exec that mounts procfs. The outer
        # Elves sandbox already removes credential/config paths, independently
        # vetoes snapshot writes, and deliberately leaves procfs unmounted.

        # Grok itself needs the provider variable, but model-directed terminal
        # commands do not. GROK_SHELL is Grok's documented shell-selection
        # seam; exec creates a fresh environment after both key names are
        # removed, so descendants cannot recover either variable.
        shell_dir = home / "bin"
        shell_dir.mkdir(mode=0o700)
        # Grok resolves its configured terminal by shell basename and currently
        # accepts standard names such as bash/zsh. Keep the credential scrubber
        # on that documented-compatible surface instead of using a custom name
        # that the real CLI would reject before executing it.
        scrub_shell = shell_dir / "bash"
        scrub_shell.write_text(
            "#!/bin/bash\n"
            "unset XAI_API_KEY GROK_CODE_XAI_API_KEY\n"
            "exec /bin/bash \"$@\"\n",
            encoding="utf-8",
        )
        scrub_shell.chmod(0o700)

        lane.env.update(
            {
                "GROK_HOME": str(grok_home),
                "GROK_SHELL": str(scrub_shell),
                "SHELL": str(scrub_shell),
            }
        )
        plan = build_grok_argv(
            str(Path(grok).resolve()),
            snapshot=lane.snapshot,
            prompt=prompt,
            capabilities=capabilities,
            effort=effort,
            model=model,
            auth_route=catalog.auth_route if catalog else None,
        )
        print(
            f"Grok launch: cli={plan.capabilities.version or 'unknown'} "
            f"effort={plan.effort} model={plan.model or 'authenticated-default'} "
            f"auth={plan.auth_route or 'unreported'} "
            f"omitted_flags={','.join(plan.omitted_flags) or 'none'}.",
            file=sys.stderr,
        )
        command = wrap_argv_with_sandbox(
            list(plan.argv),
            lane,
            mount_proc=False,
        )
        completed = subprocess.run(
            command,
            cwd=lane.snapshot,
            env=lane.env,
            check=False,
        )
        _route_unavailable(completed.returncode)
        raise SystemExit(completed.returncode)
except ValidationIssue as exc:
    print(f"Error: Grok isolation failed closed: {exc}", file=sys.stderr)
    _route_unavailable(2, f"{exc.code}: {exc.message}")
    raise SystemExit(2) from exc
PY
