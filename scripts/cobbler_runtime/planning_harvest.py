"""Planning / Command Center harvest helpers for Elves runs.

Implements the core, testable machinery for Linear AIG-411–425 without requiring
Command Center as a dependency: plan identity beacons, three-tier discovery,
resolution modes, lean summaries, batch sandboxes, working canvas, mission
prep, conservative goal assessment, JIT next-batch lines, branch auto-plan
signals, review noise filters, and merge-recovery scope locks.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


BEACON_SCHEMA = "elves-plan-beacon-v1"
CANVAS_SCHEMA = "elves-working-canvas-v1"


@dataclass(frozen=True)
class PlanBeacon:
    schema: str
    plan_path: str
    plan_sha256: str
    title: str
    batch_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        body = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        return f"<!-- {BEACON_SCHEMA}\n{body}\n-->\n"


def plan_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_plan_beacon(plan_path: str | Path, text: str) -> PlanBeacon:
    path = Path(plan_path).as_posix()
    title = "Untitled plan"
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip() or title
            break
    batch_ids = tuple(re.findall(r"\bB\d+\b", text))
    # unique preserve order
    seen: list[str] = []
    for bid in batch_ids:
        if bid not in seen:
            seen.append(bid)
    return PlanBeacon(
        schema=BEACON_SCHEMA,
        plan_path=path,
        plan_sha256=plan_sha256(text),
        title=title,
        batch_ids=tuple(seen),
    )


def discover_plans(
    repo_root: Path,
    *,
    session_plan_path: str | None = None,
    pr_body: str | None = None,
    todo_text: str | None = None,
) -> dict[str, list[str]]:
    """Three-tier plan discovery: filesystem, session, PR/TODO beacon."""
    root = Path(repo_root)
    fs_hits: list[str] = []
    for rel in (
        "docs/plans",
        "docs/plan",
        "plans",
        ".ai-docs/plans",
    ):
        d = root / rel
        if d.is_dir():
            for p in sorted(d.rglob("*.md")):
                try:
                    rel_s = p.relative_to(root).as_posix()
                except ValueError:
                    continue
                fs_hits.append(rel_s)
    session_hits = [session_plan_path] if session_plan_path else []
    beacon_hits: list[str] = []
    for blob in (pr_body or "", todo_text or ""):
        for m in re.finditer(
            r"(?:plan|Plan)\s*[:=]\s*[`\"']?([\w./-]+\.md)", blob
        ):
            beacon_hits.append(m.group(1))
        for m in re.finditer(r"docs/plans/[\w./-]+\.md", blob):
            beacon_hits.append(m.group(0))
    return {
        "filesystem": fs_hits,
        "session": session_hits,
        "beacon": list(dict.fromkeys(beacon_hits)),
    }


def resolve_plan_mode(
    mode: str,
    *,
    file_path: str | None = None,
    manual_text: str | None = None,
) -> dict[str, Any]:
    """Plan resolution modes: file | manual | skip."""
    m = (mode or "").strip().lower()
    if m not in {"file", "manual", "skip"}:
        return {"ok": False, "error": f"unknown_plan_mode:{mode}"}
    if m == "skip":
        return {"ok": True, "mode": "skip", "plan_path": None, "plan_text": None}
    if m == "file":
        if not file_path:
            return {"ok": False, "error": "file_mode_requires_path"}
        return {"ok": True, "mode": "file", "plan_path": file_path, "plan_text": None}
    # manual
    if not (manual_text or "").strip():
        return {"ok": False, "error": "manual_mode_requires_text"}
    return {
        "ok": True,
        "mode": "manual",
        "plan_path": None,
        "plan_text": manual_text.strip(),
    }


_BATCH_HEADER = re.compile(
    r"(?im)^###\s+Batch\s+(\d+)\s+\[(B\d+)\]:\s*(.+)$"
)


def lean_plan_summary(text: str, *, max_chars: int = 4000) -> str:
    """Compact mission + batch titles + acceptance id list for packets/review."""
    lines = text.splitlines()
    mission: list[str] = []
    in_mission = False
    for line in lines:
        if line.strip() == "## Mission":
            in_mission = True
            continue
        if in_mission:
            if line.startswith("## "):
                break
            mission.append(line)
    batches = [
        f"{m.group(2)}: {m.group(3).strip()}" for m in _BATCH_HEADER.finditer(text)
    ]
    ids = sorted(set(re.findall(r"\b(?:B\d+-A\d+|M-A\d+)\b", text)))
    parts = [
        "# Lean plan summary",
        "",
        "## Mission",
        "\n".join(mission).strip() or "(missing)",
        "",
        "## Batches",
    ]
    if batches:
        parts.extend(f"- {b}" for b in batches)
    else:
        parts.append("- (none parsed)")
    parts.extend(
        [
            "",
            "## Acceptance IDs",
            ", ".join(ids) if ids else "(none)",
        ]
    )
    out = "\n".join(parts).strip() + "\n"
    if len(out) > max_chars:
        out = out[: max_chars - 20].rstrip() + "\n…[truncated]\n"
    return out


def task_sandbox_packet(
    plan_text: str,
    *,
    batch_id: str,
    extra_context: str = "",
) -> str:
    """Worker packet fragment with current batch only + mission pin."""
    mission = distill_mission_goal(plan_text)
    # extract batch section only (no full-plan acceptance id dump)
    pattern = re.compile(
        rf"(?ims)^###\s+Batch\s+\d+\s+\[{re.escape(batch_id)}\]:.*?(?=^###\s+Batch|\Z)"
    )
    m = pattern.search(plan_text)
    section = m.group(0).strip() if m else f"(batch {batch_id} not found in plan)"
    parts = [
        f"# Task sandbox — {batch_id} only",
        "",
        "Do not implement other batches. Owned surfaces are limited to this batch.",
        "",
        "## Mission (pinned)",
        mission,
        "",
        "## Current batch",
        section,
    ]
    if extra_context.strip():
        parts.extend(["", "## Extra context", extra_context.strip()])
    return "\n".join(parts).strip() + "\n"


@dataclass
class WorkingCanvas:
    schema: str = CANVAS_SCHEMA
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add_batch_close(
        self,
        *,
        batch_id: str,
        summary: str,
        commit: str | None = None,
        acceptance: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        self.entries.append(
            {
                "batch_id": batch_id,
                "summary": summary.strip(),
                "commit": commit,
                "acceptance": list(acceptance or ()),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "entries": list(self.entries)}

    def to_markdown(self) -> str:
        lines = ["# Working canvas", ""]
        if not self.entries:
            lines.append("(empty)")
        for e in self.entries:
            lines.append(f"## {e['batch_id']}")
            lines.append(e.get("summary") or "")
            if e.get("commit"):
                lines.append(f"Commit: `{e['commit']}`")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def distill_mission_goal(plan_text: str, *, max_chars: int = 600) -> str:
    """Pin a short mission goal for implement/review prompts."""
    m = re.search(
        r"(?ims)^## Mission\s*\n(.*?)(?=^## |\n### |\Z)",
        plan_text,
    )
    body = (m.group(1) if m else plan_text).strip()
    # drop blockquotes markers for cleanliness
    body = re.sub(r"(?m)^>\s?", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > max_chars:
        body = body[: max_chars - 1].rstrip() + "…"
    return body


_PHILOSOPHY = re.compile(
    r"(?i)\b(deliberately|tapestry|pivotal moment|testament to|not just .+ but)\b"
)


def mission_prep(text: str) -> str:
    """Strip redundant philosophy lines; keep gotchas and reference paths."""
    kept: list[str] = []
    for line in text.splitlines():
        if _PHILOSOPHY.search(line) and "http" not in line and "`" not in line:
            continue
        kept.append(line)
    return "\n".join(kept).strip() + ("\n" if kept else "")


@dataclass(frozen=True)
class GoalAssessment:
    complete: bool
    confidence: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_goal_completion(
    *,
    open_acceptance_ids: Sequence[str],
    stop_allowed: bool,
    user_stop: bool,
    open_ended: bool,
) -> GoalAssessment:
    """Conservative assessor: complete only with empty acceptance + permission."""
    reasons: list[str] = []
    if open_acceptance_ids:
        reasons.append(f"open_acceptance:{len(open_acceptance_ids)}")
    if open_ended and not user_stop:
        reasons.append("open_ended_requires_explicit_user_stop")
    if not stop_allowed and not user_stop:
        reasons.append("stop_gate_disallows")
    complete = not reasons
    if complete:
        reasons.append("all_acceptance_closed")
        if user_stop:
            reasons.append("user_stop")
        conf = "high"
    else:
        conf = "low" if open_acceptance_ids else "medium"
    return GoalAssessment(complete=complete, confidence=conf, reasons=tuple(reasons))


def jit_next_batch_lines(plan_text: str, *, completed: Sequence[str]) -> list[str]:
    """Extract next incomplete batch headers for open-ended runs."""
    done = set(completed)
    out: list[str] = []
    for m in _BATCH_HEADER.finditer(plan_text):
        bid = m.group(2)
        if bid not in done:
            out.append(f"{bid}: {m.group(3).strip()}")
    return out


def auto_plan_from_branch_signals(
    *,
    branch: str,
    commits: Sequence[str],
    changed_paths: Sequence[str],
) -> str:
    """Optional auto-plan body when no plan file exists."""
    paths = "\n".join(f"- `{p}`" for p in list(changed_paths)[:40]) or "- (none)"
    commits_s = "\n".join(f"- {c}" for c in list(commits)[:20]) or "- (none)"
    return (
        f"# Plan: Auto from branch `{branch}`\n\n"
        f"## Mission\n\n"
        f"Implement and land the work already present on `{branch}` using branch "
        f"signals (commits + changed paths) as the scope envelope.\n\n"
        f"## Scope\n\n### In scope\n{paths}\n\n### Out of scope\n"
        f"- Unrelated paths not listed above\n\n"
        f"## Recent commits\n{commits_s}\n\n"
        f"## Batches\n\n"
        f"### Batch 1 [B1]: Land branch work\n\n"
        f"**Acceptance criteria:**\n"
        f"- [ ] B1-A1: Changed surfaces build/test on the impact path.\n"
        f"- [ ] B1-A2: Docs updated if operator surfaces changed.\n"
        f"- [ ] B1-A3: PR ready for review.\n\n"
        f"## Master Acceptance\n\n"
        f"- [ ] M-A1: Branch intent realized with proof on the tip.\n"
    )


def planning_consistency_check(
    *,
    plan_text: str,
    session_plan_path: str | None,
    docs_touched: Sequence[str],
) -> dict[str, Any]:
    """Optional landing hygiene: plan path + acceptance ids present."""
    issues: list[str] = []
    if not session_plan_path:
        issues.append("missing_session_plan_path")
    if "Master Acceptance" not in plan_text and "M-A1" not in plan_text:
        issues.append("missing_master_acceptance")
    if not re.search(r"\bB\d+-A\d+\b", plan_text):
        issues.append("missing_batch_acceptance_ids")
    return {"ok": not issues, "issues": issues, "docs_touched": list(docs_touched)}


def filter_review_findings(
    findings: Sequence[Mapping[str, Any]],
    *,
    min_confidence_for_medium: str = "medium",
) -> list[dict[str, Any]]:
    """Confidence × severity filter; stale findings dropped when flagged."""
    rank = {"low": 1, "medium": 2, "high": 3}
    need = rank.get(min_confidence_for_medium, 2)
    kept: list[dict[str, Any]] = []
    for raw in findings:
        f = dict(raw)
        if f.get("stale") or f.get("outdated"):
            continue
        sev = str(f.get("severity", "info")).lower()
        conf = str(f.get("confidence", "medium")).lower()
        if sev in {"critical", "high", "p0", "p1", "blocking"}:
            kept.append(f)
            continue
        if sev in {"medium", "p2", "warning"} and rank.get(conf, 2) >= need:
            kept.append(f)
            continue
        if sev in {"low", "p3", "info"} and rank.get(conf, 2) >= 3:
            kept.append(f)
            continue
        # pending-docs split: mark but do not block unless required
        if str(f.get("category", "")).upper() == "PENDING-DOCS":
            f["blocks_merge"] = bool(f.get("blocks_merge", False))
            kept.append(f)
            continue
    return kept


def merge_recovery_scope_lock(
    *,
    allowed_paths: Sequence[str],
    attempted_paths: Sequence[str],
) -> dict[str, Any]:
    """Fail closed when merge-recovery edits leave the declared scope."""
    from posixpath import normpath

    def _norm(path: str) -> str:
        n = normpath(path.replace("\\", "/"))
        if n.startswith("/") or n == ".." or n.startswith("../"):
            return ""  # force violation
        return n.lstrip("./")

    allowed = {_norm(p) for p in allowed_paths}
    allowed.discard("")
    bad = []
    for path in attempted_paths:
        n = _norm(path)
        if not n:
            bad.append(path)
            continue
        ok = any(n == a or n.startswith(a.rstrip("/") + "/") for a in allowed)
        if not ok:
            bad.append(path)
    return {
        "ok": not bad,
        "violations": bad,
        "runaway": len(bad) >= 5,
    }
