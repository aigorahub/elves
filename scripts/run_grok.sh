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

exec python3 - "$PROMPT_CONTENT" "$REPO_ROOT" "$SCRIPT_DIR" <<'PY'
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
sys.path.insert(0, str(script_dir))

from cobbler_runtime.isolation import (  # noqa: E402
    IsolationSpec,
    isolated_lane,
    wrap_argv_with_sandbox,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


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

        model_default = configured_model_default()
        if model_default:
            (grok_home / "config.toml").write_text(
                "[models]\n" + f"default = {json.dumps(model_default)}\n",
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
        command = wrap_argv_with_sandbox(
            [
                str(Path(grok).resolve()),
                "--no-auto-update",
                "--cwd",
                str(lane.snapshot),
                "--sandbox",
                "strict",
                "--effort",
                "high",
                "--output-format",
                "plain",
                "--check",
                "--single=" + prompt,
            ],
            lane,
            mount_proc=False,
        )
        completed = subprocess.run(
            command,
            cwd=lane.snapshot,
            env=lane.env,
            check=False,
        )
        raise SystemExit(completed.returncode)
except ValidationIssue as exc:
    print(f"Error: Grok isolation failed closed: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc
PY
