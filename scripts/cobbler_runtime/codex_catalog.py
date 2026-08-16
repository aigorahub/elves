"""Live Codex model catalog: the routes the installed host actually offers.

Elves never hardcodes provider model names.  `codex debug models` renders the
catalog the installed binary holds for the authenticated account, including the
reasoning levels each model accepts.  Reading it keeps route validation honest
across model launches, renames, retirements, and account tiers.

The catalog only ever *widens* the offline vocabulary a host profile already
accepts.  An unreadable, oversized, or unparsable catalog reports a stable
reason and widens nothing, so no failure of this reader can authorise a route
the profile floor would refuse.

The probe reads local state only.  It launches no inference turn, spends no
tokens, and is bounded in wall time and in bytes: the command's stdout is read
through a byte-capped pipe rather than buffered whole, and a file override is
read through the shared fd-bound artifact reader (O_NOFOLLOW open, fstat
identity match, size check on the descriptor actually read).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable

from .storage import read_bounded_artifact_bytes


CODEX_CATALOG_ENV = "ELVES_CODEX_MODEL_CATALOG"
CODEX_CATALOG_MAX_BYTES = 4 * 1024 * 1024
CODEX_CATALOG_TIMEOUT_SECONDS = 5
CODEX_CATALOG_MAX_MODELS = 256

# A catalog row becomes route authority, and an effort token is interpolated
# into the host's own config override (`model_reasoning_effort="<effort>"`).
# Accept only conservative identifiers, so a malformed or hostile catalog
# cannot certify an invented route or carry configuration punctuation into
# that override. New provider names remain free to appear; new *grammars* do
# not.
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}\Z")
_EFFORT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")

# Stable reasons a policy failure maps to, mirroring the artifact reader's
# vocabulary so an operator sees why a catalog was refused.
_ARTIFACT_REASONS = {
    "artifact_not_regular": "override_not_a_file",
    "artifact_writable_by_others": "override_writable_by_others",
    "artifact_too_large": "override_too_large",
}


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


def _parse_catalog_rows(payload: Any) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    """Parse only anchored catalog rows, never diagnostic prose."""
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
        if slug in seen or not _SLUG_RE.match(slug):
            continue
        levels = entry.get("supported_reasoning_levels")
        efforts: list[str] = []
        if isinstance(levels, list):
            for level in levels:
                effort = level.get("effort") if isinstance(level, dict) else level
                if isinstance(effort, str) and effort.strip():
                    token = effort.strip().lower()
                    if token not in efforts and _EFFORT_RE.match(token):
                        efforts.append(token)
        if not efforts:
            # A model with no advertised levels binds no route: skip it rather
            # than invent one.
            continue
        seen.add(slug)
        routes.append((slug, tuple(efforts)))
        if len(routes) >= CODEX_CATALOG_MAX_MODELS:
            break
    return tuple(routes)


def _catalog_from_text(text: str, *, source: str) -> CodexModelCatalog:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return CodexModelCatalog(source=source, reason="catalog_unparsable")
    routes = _parse_catalog_rows(payload)
    if routes is None:
        return CodexModelCatalog(source=source, reason="catalog_unparsable")
    if not routes:
        return CodexModelCatalog(source=source, reason="catalog_empty")
    raw_version = payload.get("client_version")
    client_version = (
        raw_version.strip()
        if isinstance(raw_version, str) and raw_version.strip()
        else None
    )
    return CodexModelCatalog(
        available=True,
        source=source,
        client_version=client_version,
        routes=routes,
    )


def read_bounded_command_output(argv: list[str]) -> tuple[int, str]:
    """Run one local command, reading at most the catalog byte bound.

    ``capture_output`` would buffer everything a misbehaving binary prints
    before any limit could apply, so stdout is read through a capped pipe and
    the child is killed as soon as it exceeds the bound.
    """
    limit = CODEX_CATALOG_MAX_BYTES
    with subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as child:
        assert child.stdout is not None
        try:
            raw = child.stdout.read(limit + 1)
        except OSError:
            child.kill()
            raise
        if len(raw) > limit:
            child.kill()
            child.wait(timeout=CODEX_CATALOG_TIMEOUT_SECONDS)
            return 0, ""
        try:
            child.wait(timeout=CODEX_CATALOG_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
            raise
        return child.returncode, raw.decode("utf-8", errors="replace")


def probe_codex_model_catalog(
    executable: str = "codex",
    *,
    reader: Callable[[list[str]], tuple[int, str]] | None = None,
    env: dict[str, str] | None = None,
) -> CodexModelCatalog:
    """Read the installed catalog once, failing closed with a stable reason.

    ``reader`` runs one local command and returns ``(returncode, stdout)``
    bounded to ``CODEX_CATALOG_MAX_BYTES``; tests inject their own.
    """
    environ = os.environ if env is None else env
    override = (environ.get(CODEX_CATALOG_ENV) or "").strip()
    if override:
        try:
            raw = read_bounded_artifact_bytes(
                Path(override), max_bytes=CODEX_CATALOG_MAX_BYTES
            )
        except ValueError as exc:
            return CodexModelCatalog(
                source="catalog_override",
                reason=_ARTIFACT_REASONS.get(str(exc), "override_unreadable"),
            )
        except OSError:
            return CodexModelCatalog(
                source="catalog_override", reason="override_not_a_file"
            )
        return _catalog_from_text(
            raw.decode("utf-8", errors="replace"), source="catalog_override"
        )

    located = shutil.which(executable)
    if not located:
        return CodexModelCatalog(
            source="installed_binary", reason="executable_not_found"
        )
    invoke = reader if reader is not None else read_bounded_command_output
    try:
        returncode, stdout = invoke([located, "debug", "models"])
    except (OSError, subprocess.SubprocessError, ValueError):
        return CodexModelCatalog(
            source="installed_binary:debug_models", reason="catalog_command_failed"
        )
    if returncode != 0:
        return CodexModelCatalog(
            source="installed_binary:debug_models",
            reason=f"catalog_command_exit_{returncode}",
        )
    return _catalog_from_text(stdout, source="installed_binary:debug_models")


def _catalog_cache_identity(executable: str) -> tuple[Any, ...]:
    """Identify the exact catalog source, so a swapped file re-probes.

    The process cache must not outlive the thing it read.  An override is
    keyed by device/inode/size/mtime and the installed probe by the resolved
    executable and its mtime, so replacing either invalidates the entry
    instead of leaving obsolete route authority in memory.
    """
    override = (os.environ.get(CODEX_CATALOG_ENV) or "").strip()
    if override:
        try:
            info = os.stat(override)
        except OSError:
            return ("override", override, None)
        return (
            "override",
            override,
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
        )
    located = shutil.which(executable)
    if not located:
        return ("installed", executable, None)
    try:
        info = os.stat(located)
    except OSError:
        return ("installed", located, None)
    return ("installed", located, info.st_size, info.st_mtime_ns)


_CACHE: dict[tuple[Any, ...], CodexModelCatalog] = {}


def codex_model_catalog(executable: str = "codex") -> CodexModelCatalog:
    """Return the process-cached catalog for one installed Codex binary."""
    key = _catalog_cache_identity(executable)
    cached = _CACHE.get(key)
    if cached is None:
        cached = probe_codex_model_catalog(executable)
        _CACHE[key] = cached
    return cached


def reset_codex_model_catalog_cache() -> None:
    """Drop the process cache; tests and long-lived supervisors re-probe."""
    _CACHE.clear()
