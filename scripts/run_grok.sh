#!/bin/bash
# Headless Grok Build task with a minimal environment and kernel read boundary.
set -euo pipefail

PROMPT_CONTENT="$*"
if [ -z "$PROMPT_CONTENT" ]; then
  echo "Usage: run_grok.sh <instructions>" >&2
  exit 2
fi
if ! command -v grok >/dev/null 2>&1; then
  echo "Error: Grok Build CLI not found." >&2
  exit 127
fi

exec python3 - "$PROMPT_CONTENT" "$PWD" <<'PY'
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


prompt = sys.argv[1]
repo_root = Path(sys.argv[2]).resolve()
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

with tempfile.TemporaryDirectory(prefix="elves-grok-shortcut-") as raw_root:
    root = Path(raw_root).resolve()
    home = root / "home"
    grok_home = root / "grok-home"
    tmp = root / "tmp"
    xdg_config = root / "xdg-config"
    xdg_cache = root / "xdg-cache"
    for directory in (home, grok_home, tmp, xdg_config, xdg_cache):
        directory.mkdir(mode=0o700)

    model_default = ""
    config_source = source_home / "config.toml"
    try:
        if config_source.is_file() and not config_source.is_symlink():
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
                if isinstance(configured, str) and configured.strip():
                    model_default = configured.strip()
                break
    except (OSError, UnicodeError, SyntaxError, ValueError):
        pass
    if model_default:
        (grok_home / "config.toml").write_text(
            "[models]\n" + f"default = {json.dumps(model_default)}\n",
            encoding="utf-8",
        )
        (grok_home / "config.toml").chmod(0o600)

    # A named custom profile fails closed if the kernel sandbox cannot be
    # applied. `strict` limits reads to CWD/system paths; the deny list also
    # excludes common repository-local credential files from that CWD.
    (grok_home / "sandbox.toml").write_text(
        "[profiles.elves-shortcut]\n"
        'extends = "strict"\n'
        "restrict_network = true\n"
        + "deny = [\n"
        + '  "**/.env", "**/.env.*", "**/.netrc", "**/.npmrc",\n'
        '  "**/.pypirc", "**/.git-credentials", "**/.ssh/**",\n'
        '  "**/.aws/**", "**/.gnupg/**", "**/.credentials*",\n'
        '  "**/credentials", "**/credentials.json",\n'
        '  "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx"\n'
        "]\n",
        encoding="utf-8",
    )
    (grok_home / "sandbox.toml").chmod(0o600)

    child_env = {
        "HOME": str(home),
        "GROK_HOME": str(grok_home),
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_CACHE_HOME": str(xdg_cache),
        "PATH": parent_path,
        "LANG": parent.get("LANG", "C.UTF-8"),
    }
    if xai_key:
        child_env["XAI_API_KEY"] = xai_key
    else:
        child_env["GROK_CODE_XAI_API_KEY"] = legacy_xai_key

    completed = subprocess.run(
        [
            str(Path(grok).resolve()),
            "--no-auto-update",
            "--cwd",
            str(repo_root),
            "--sandbox",
            "elves-shortcut",
            "--permission-mode",
            "dontAsk",
            "--effort",
            "high",
            "--output-format",
            "plain",
            "--check",
            "--single=" + prompt,
        ],
        cwd=repo_root,
        env=child_env,
        check=False,
    )
    raise SystemExit(completed.returncode)
PY
