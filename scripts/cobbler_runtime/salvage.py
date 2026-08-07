"""Worker-output salvage previews (v2.24).

On abnormal worker termination — worker death, hang kill, or a missing or
malformed completion — the driver harvests a bounded, redacted tail of the
follow log / worker stdout into the wake context, the gap packet, and the
execution log, so a cold re-drive starts oriented even when the worker never
produced a valid report.

Design adapted, with attribution and without vendored code, from the
``completed_without_reply`` terminal notices in prime-agent (MIT), unified
with the existing Fugu partial-salvage markers. Salvage text is **untrusted
observed output**: it is never parsed as a completion report, never satisfies
labor completeness, and never upgrades a malformed completion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .context import redact_text

DEFAULT_MAX_BYTES = 8 * 1024
MAX_ALLOWED_BYTES = 64 * 1024
SALVAGE_HEADER = "--- Worker output salvage (untrusted; never a completion report) ---"
SALVAGE_FOOTER = "--- end worker output salvage ---"


def harvest_tail(
    log_path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    exact_secret_values: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Read a bounded tail of ``log_path``, redacted; absent is not an error."""

    bounded = max(1, min(int(max_bytes), MAX_ALLOWED_BYTES))
    path = Path(log_path)
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            truncated = size > bounded
            if truncated:
                handle.seek(size - bounded)
            raw = handle.read(bounded)
    except OSError as exc:
        return {"present": False, "reason": str(exc), "source": str(path)}
    text = raw.decode("utf-8", "replace")
    redacted = redact_text(text, exact_values=exact_secret_values)
    return {
        "present": True,
        "text": redacted.text,
        "bytes": len(raw),
        "truncated": truncated,
        "source": str(path),
    }


def render_block(
    salvage: dict[str, Any], *, title: str = "Last observed worker output"
) -> str:
    """Render the marker-fenced block for wake context / gap packet / log.

    Returns ``""`` when nothing was salvaged (e.g. clean completion — callers
    only harvest on abnormal-termination wakes).
    """

    if not salvage.get("present"):
        return ""
    suffix = " (truncated tail)" if salvage.get("truncated") else ""
    return (
        f"{title}{suffix}:\n"
        f"{SALVAGE_HEADER}\n"
        f"{salvage.get('text', '')}\n"
        f"{SALVAGE_FOOTER}"
    )
