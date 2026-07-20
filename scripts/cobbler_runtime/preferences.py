"""Safe machine-global Elves preferences.

The file is shared by every supported host at
``${XDG_CONFIG_HOME:-~/.config}/elves/config.json``.  It stores convenience
only: repository policy and explicit run intent are resolved separately and
always outrank it.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .schema import ValidationIssue


PREFERENCE_SCHEMA_VERSION = 1
DEFAULT_PREFERENCES: dict[str, Any] = {
    "version": PREFERENCE_SCHEMA_VERSION,
    "worker": {"provider": "auto", "native_effort": "auto", "prewalk": "auto", "parallel": "off"},
}

SAFE_PATHS: dict[str, tuple[type, set[str] | None]] = {
    "worker.provider": (str, {"auto", "native", "grok"}),
    "worker.native_effort": (str, {"auto", "low", "medium", "high"}),
    "worker.prewalk": (str, {"off", "auto", "required"}),
    "worker.parallel": (str, {"off", "auto"}),
}

_FORBIDDEN_SEGMENTS = frozenset(
    {
        "credential", "credentials", "secret", "token", "apikey", "password",
        "merge", "destructive", "authorization", "auth",
    }
)
_FORBIDDEN_COMPOUNDS = frozenset(
    {
        "api_key", "merge_authority", "force_push", "protected_ref",
        "approval_bypass", "bypass_approval", "permission_bypass",
        "always_approve", "alwaysapprove", "permission_mode", "permissionmode",
        "bypasspermissions",
    }
)
_FORBIDDEN_VALUES = frozenset(
    {"alwaysapprove", "always_approve", "bypasspermissions", "bypass_permissions", "dontask", "dont_ask"}
)


def global_preferences_path(*, env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    xdg = values.get("XDG_CONFIG_HOME", "").strip()
    if xdg and not Path(xdg).expanduser().is_absolute():
        raise ValidationIssue(
            "relative_xdg_config_home",
            "XDG_CONFIG_HOME must be absolute for machine-global Elves preferences",
            path="XDG_CONFIG_HOME",
        )
    root = Path(xdg).expanduser() if xdg else Path(values.get("HOME", "~")).expanduser() / ".config"
    return root / "elves" / "config.json"


def _normalized_token(value: object) -> str:
    return str(value).strip().lower().replace("-", "_")


def _reject_unsafe_keys(value: Any, *, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            token = _normalized_token(key)
            segments = set(token.split("_"))
            if segments & _FORBIDDEN_SEGMENTS or any(
                unsafe in token for unsafe in _FORBIDDEN_COMPOUNDS
            ):
                raise ValidationIssue(
                    "unsafe_global_preference",
                    f"Global preferences cannot store authority or sensitive field `{key_path}`",
                    path=key_path,
                    hint="Keep authority, credentials, and approval policy in the active run/repository policy.",
                )
            _reject_unsafe_keys(child, path=key_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_unsafe_keys(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and _normalized_token(value) in _FORBIDDEN_VALUES:
        raise ValidationIssue(
            "unsafe_global_preference",
            f"Global preferences cannot store approval-bypass value at `{path}`",
            path=path,
            hint="Keep permission and approval policy out of machine-global preferences.",
        )


def _validate_known_fields(data: Mapping[str, Any]) -> None:
    version = data.get("version", PREFERENCE_SCHEMA_VERSION)
    if version != PREFERENCE_SCHEMA_VERSION:
        raise ValidationIssue(
            "unsupported_preference_version",
            f"Unsupported global preference version `{version}`",
            path="version",
        )
    worker = data.get("worker", {})
    if not isinstance(worker, Mapping):
        raise ValidationIssue("invalid_type", "`worker` must be an object", path="worker")
    for dotted, (expected_type, choices) in SAFE_PATHS.items():
        _, name = dotted.split(".", 1)
        if name not in worker:
            continue
        value = worker[name]
        if not isinstance(value, expected_type) or (choices is not None and value not in choices):
            allowed = ", ".join(sorted(choices or ()))
            raise ValidationIssue(
                "invalid_global_preference",
                f"Invalid `{dotted}` value `{value}`",
                path=dotted,
                hint=f"Allowed values: {allowed}",
            )


def validate_preferences(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValidationIssue("invalid_type", "Global preferences must be a JSON object")
    result = dict(data)
    _reject_unsafe_keys(result)
    _validate_known_fields(result)
    return result


def load_preferences(path: Path | None = None, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    target = path or global_preferences_path(env=env)
    if not target.exists():
        return json.loads(json.dumps(DEFAULT_PREFERENCES))
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationIssue(
            "invalid_global_preferences",
            f"Unable to read global preferences at `{target}`: {exc}",
            path=str(target),
        ) from exc
    return validate_preferences(data)


def _atomic_write(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, stat.S_IRWXU)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _set_nested(data: dict[str, Any], dotted: str, value: Any) -> None:
    if dotted not in SAFE_PATHS:
        raise ValidationIssue(
            "unsupported_global_preference",
            f"Unsupported preference `{dotted}`",
            path=dotted,
            hint=f"Supported preferences: {', '.join(sorted(SAFE_PATHS))}",
        )
    expected, choices = SAFE_PATHS[dotted]
    if not isinstance(value, expected) or (choices is not None and value not in choices):
        raise ValidationIssue(
            "invalid_global_preference",
            f"Invalid value `{value}` for `{dotted}`",
            path=dotted,
            hint=f"Allowed values: {', '.join(sorted(choices or ())) }",
        )
    group, name = dotted.split(".", 1)
    current = data.get(group)
    if current is None:
        current = {}
        data[group] = current
    if not isinstance(current, dict):
        raise ValidationIssue("invalid_type", f"`{group}` must be an object", path=group)
    current[name] = value


def set_preference(dotted: str, value: Any, *, path: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    target = path or global_preferences_path(env=env)
    data = load_preferences(target)
    _set_nested(data, dotted, value)
    data["version"] = PREFERENCE_SCHEMA_VERSION
    validate_preferences(data)
    _atomic_write(target, data)
    return data


def reset_preferences(*, path: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    target = path or global_preferences_path(env=env)
    data = json.loads(json.dumps(DEFAULT_PREFERENCES))
    _atomic_write(target, data)
    return data


@dataclass(frozen=True)
class PreferenceSnapshot:
    path: str
    values: dict[str, Any]
    exists: bool
    schema_version: int = PREFERENCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "schema_version": self.schema_version,
            "values": self.values,
            "authority_fields_supported": False,
        }


def preference_snapshot(*, path: Path | None = None, env: Mapping[str, str] | None = None) -> PreferenceSnapshot:
    target = path or global_preferences_path(env=env)
    return PreferenceSnapshot(path=str(target), values=load_preferences(target), exists=target.exists())
