"""Live Codex model catalog: the routes the installed host actually offers.

Elves never hardcodes provider model names.  `codex debug models` renders the
catalog the installed binary holds for the authenticated account, including the
reasoning levels each model accepts.  Reading it keeps route validation honest
across model launches, renames, retirements, and account tiers.  When the
catalog cannot be read, callers keep their conservative offline vocabulary
instead of guessing: an unreadable catalog never widens a route.

The probe reads local state only.  It launches no inference turn, spends no
tokens, and is bounded in both wall time and bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


CODEX_CATALOG_ENV = "ELVES_CODEX_MODEL_CATALOG"
CODEX_CATALOG_MAX_BYTES = 4 * 1024 * 1024
CODEX_CATALOG_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class CodexModelCatalog:
    """One bounded read of the installed Codex model catalog."""

    available: bool = False
    source: str = "not_probed"
    reason: str | None = None
    client_version: str | None = None
    # (model, (effort, ...)) pairs keep the dataclass hashable and ordered.
    routes: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(model for model, _ in self.routes)

    def efforts_for(self, model: str | None) -> frozenset[str]:
        """Return the reasoning levels the catalog binds to one model."""
        if not model:
            return frozenset()
        wanted = model.strip().lower()
        for slug, efforts in self.routes:
            if slug == wanted:
                return frozenset(efforts)
        return frozenset()

    def supports(self, model: str | None) -> bool:
        return bool(self.efforts_for(model))

    def route_supported(self, model: str | None, effort: str | None) -> bool:
        if not effort:
            return False
        return effort.strip().lower() in self.efforts_for(model)

    def efforts_union(self) -> frozenset[str]:
        """Return every reasoning level any catalog model accepts."""
        union: set[str] = set()
        for _, efforts in self.routes:
            union.update(efforts)
        return frozenset(union)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "source": self.source,
            "reason": self.reason,
            "client_version": self.client_version,
            "models": {model: list(efforts) for model, efforts in self.routes},
        }


def _parse_catalog_payload(text: str) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    """Parse only anchored catalog rows, never diagnostic prose."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    if not isinstance(models, list):
        return None
    routes: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for entry in models:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug") or entry.get("id")
        if not isinstance(slug, str) or not slug.strip():
            continue
        slug = slug.strip().lower()
        if slug in seen:
            continue
        levels = entry.get("supported_reasoning_levels")
        efforts: list[str] = []
        if isinstance(levels, list):
            for level in levels:
                effort = level.get("effort") if isinstance(level, dict) else level
                if isinstance(effort, str) and effort.strip():
                    token = effort.strip().lower()
                    if token not in efforts:
                        efforts.append(token)
        if not efforts:
            # A model with no advertised levels binds no route: skip it rather
            # than invent one.
            continue
        seen.add(slug)
        routes.append((slug, tuple(efforts)))
    return tuple(routes)


def _catalog_from_text(text: str, *, source: str) -> CodexModelCatalog:
    routes = _parse_catalog_payload(text)
    if routes is None:
        return CodexModelCatalog(source=source, reason="catalog_unparsable")
    if not routes:
        return CodexModelCatalog(source=source, reason="catalog_empty")
    client_version = None
    try:
        payload = json.loads(text)
        raw_version = payload.get("client_version") if isinstance(payload, dict) else None
        if isinstance(raw_version, str) and raw_version.strip():
            client_version = raw_version.strip()
    except (json.JSONDecodeError, ValueError):
        client_version = None
    return CodexModelCatalog(
        available=True,
        source=source,
        client_version=client_version,
        routes=routes,
    )


def probe_codex_model_catalog(
    executable: str = "codex",
    *,
    runner: Any = subprocess.run,
    env: dict[str, str] | None = None,
) -> CodexModelCatalog:
    """Read the installed catalog once, failing closed with a stable reason."""
    environ = os.environ if env is None else env
    override = (environ.get(CODEX_CATALOG_ENV) or "").strip()
    if override:
        path = Path(override)
        try:
            if not path.is_file():
                return CodexModelCatalog(
                    source="catalog_override", reason="override_not_a_file"
                )
            if path.stat().st_size > CODEX_CATALOG_MAX_BYTES:
                return CodexModelCatalog(
                    source="catalog_override", reason="override_too_large"
                )
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return CodexModelCatalog(
                source="catalog_override", reason="override_unreadable"
            )
        return _catalog_from_text(text, source="catalog_override")

    located = shutil.which(executable)
    if not located:
        return CodexModelCatalog(
            source="installed_binary", reason="executable_not_found"
        )
    try:
        result = runner(
            [located, "debug", "models"],
            check=False,
            capture_output=True,
            text=True,
            timeout=CODEX_CATALOG_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return CodexModelCatalog(
            source="installed_binary:debug_models", reason="catalog_command_failed"
        )
    if getattr(result, "returncode", 1) != 0:
        return CodexModelCatalog(
            source="installed_binary:debug_models",
            reason=f"catalog_command_exit_{getattr(result, 'returncode', 'unknown')}",
        )
    stdout = result.stdout or ""
    if len(stdout) > CODEX_CATALOG_MAX_BYTES:
        return CodexModelCatalog(
            source="installed_binary:debug_models", reason="catalog_too_large"
        )
    return _catalog_from_text(stdout, source="installed_binary:debug_models")


_CACHE: dict[tuple[str, str], CodexModelCatalog] = {}


def codex_model_catalog(executable: str = "codex") -> CodexModelCatalog:
    """Return the process-cached catalog for one installed Codex binary."""
    key = (executable, (os.environ.get(CODEX_CATALOG_ENV) or "").strip())
    cached = _CACHE.get(key)
    if cached is None:
        cached = probe_codex_model_catalog(executable)
        _CACHE[key] = cached
    return cached


def reset_codex_model_catalog_cache() -> None:
    """Drop the process cache; tests and long-lived supervisors re-probe."""
    _CACHE.clear()
