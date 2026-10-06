"""Computed landing evidence: "can it merge?" and "was it tested?" (Elves 2.39).

The host reads both answers from GitHub and the pull request's local test
record for the exact HEAD instead of trusting a boolean typed into the
session. Bot checks (Socket, Vercel) and skipped test jobs satisfy branch
rules but never prove that tests ran.

Two landing paths:
- ordinary: the pull request base is the repository default branch. Tested
  means a ``Local tests passed on <head>`` pull request comment from the
  repository owner, a member, or a collaborator, listing every gate as passed.
- release: the base is ``main`` and ``main`` is not the default branch
  (releases and hotfixes). Tested means the ``release`` label and the pull
  request's own latest ``release-gate`` and ``full-tests`` results passed on
  the head, with ``main`` up to date.

Dependabot pull requests run the full suite in CI instead of local tests:
their GitHub Actions jobs all passed on the head, none skipped, count as
tested. A failed Actions job is never tested, required or not; a failed app
check (Socket, a Vercel preview) is left to review, not read as a test.

Evaluation is pure. ``fetch_pr_snapshot`` makes bounded ``gh`` reads with
closed stdin and explicit timeouts. Nothing here grants merge authority.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


EXACT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
LOCAL_TEST_RECORD_RE = re.compile(r"^Local tests passed on ([0-9a-fA-F]{40})$")
GATE_LINE_RE = re.compile(r"^[-*]\s")
PASSED_GATE_RE = re.compile(r"^[-*]\s+`[^`]+`:\s+passed\b", re.IGNORECASE)
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
DEPENDABOT_LOGINS = frozenset({"app/dependabot", "dependabot[bot]", "dependabot"})
RELEASE_BRANCH = "main"
RELEASE_LABEL = "release"
RELEASE_CHECKS: tuple[str, ...] = ("release-gate", "full-tests")
REQUIRED_CHECK_OK_BUCKETS = frozenset({"pass", "skipping"})
MERGE_STATE_OK = frozenset({"CLEAN", "HAS_HOOKS", "UNSTABLE"})
NO_REQUIRED_CHECKS_MESSAGE = "no required checks reported"
NO_CHECKS_MESSAGE = "no checks reported"
_BOM = chr(0xFEFF)
GH_TIMEOUT_SECONDS = 60
PR_URL_RE = re.compile(r"^https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)$")

GhRunner = Callable[[Sequence[str], Path], tuple[int, str, str]]


@dataclass(frozen=True)
class MergeEvidence:
    head: str
    path: str  # ordinary | release | unsupported | unavailable
    can_merge: bool
    tested: bool
    merge_reasons: tuple[str, ...] = ()
    test_reasons: tuple[str, ...] = ()

    @property
    def green(self) -> bool:
        return self.can_merge and self.tested

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["green"] = self.green
        return payload


def landing_path(base: Any, default_branch: Any) -> str:
    if not isinstance(base, str) or not isinstance(default_branch, str):
        return "unsupported"
    if not base or not default_branch:
        return "unsupported"
    if base == default_branch:
        return "ordinary"
    if base == RELEASE_BRANCH:
        return "release"
    return "unsupported"


def local_test_record_head(body: Any) -> str | None:
    """Head SHA of a valid record, or ``None``.

    The first line is ``Local tests passed on <sha>``. Every gate line
    (``- `<command>`: passed``) says passed, and there is at least one.
    """

    if not isinstance(body, str) or not body.strip():
        return None
    lines = [line.strip() for line in body.lstrip(_BOM).strip().splitlines()]
    match = LOCAL_TEST_RECORD_RE.fullmatch(lines[0])
    if match is None:
        return None
    gates = [line for line in lines[1:] if GATE_LINE_RE.match(line)]
    if not gates or not all(PASSED_GATE_RE.match(line) for line in gates):
        return None
    return match.group(1).lower()


def local_test_record_heads(comments: Sequence[Any]) -> frozenset[str]:
    """Heads with a valid record from the owner, a member, or a collaborator."""

    heads: set[str] = set()
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        if comment.get("author_association") not in TRUSTED_AUTHOR_ASSOCIATIONS:
            continue
        head = local_test_record_head(comment.get("body"))
        if head is not None:
            heads.add(head)
    return frozenset(heads)


def unavailable(head: str, reason: str) -> MergeEvidence:
    return MergeEvidence(
        head=head,
        path="unavailable",
        can_merge=False,
        tested=False,
        merge_reasons=(reason,),
        test_reasons=(reason,),
    )


def evaluate_merge_evidence(
    snapshot: Mapping[str, Any], *, local_head: str
) -> MergeEvidence:
    """Answer both landing questions for ``local_head`` from a PR snapshot."""

    head = str(snapshot.get("head") or "").lower()
    local = local_head.lower()
    path = landing_path(snapshot.get("base"), snapshot.get("default_branch"))
    merge: list[str] = []
    tested: list[str] = []

    if EXACT_COMMIT_RE.fullmatch(head) is None or head != local:
        merge.append("pr_head_mismatch")
        tested.append("pr_head_mismatch")
    if path == "unsupported":
        merge.append("base_not_default_or_release")
    if snapshot.get("state") != "OPEN":
        merge.append("pr_not_open")
    if snapshot.get("is_draft") is not False:
        merge.append("pr_draft")
    mergeable = str(snapshot.get("mergeable") or "UNKNOWN")
    if mergeable != "MERGEABLE":
        merge.append(f"mergeable:{mergeable.lower()}")
    merge_state = str(snapshot.get("merge_state_status") or "UNKNOWN")
    if merge_state not in MERGE_STATE_OK:
        merge.append(f"merge_state:{merge_state.lower()}")

    required = snapshot.get("required_checks")
    if not isinstance(required, list):
        merge.append("required_checks_unavailable")
    else:
        for check in required:
            name = str(check.get("name") or "?") if isinstance(check, Mapping) else "?"
            bucket = check.get("bucket") if isinstance(check, Mapping) else None
            if bucket in REQUIRED_CHECK_OK_BUCKETS:
                continue
            if bucket == "pending":
                merge.append(f"required_check_pending:{name}")
            else:
                merge.append(f"required_check_failed:{name}")

    checks = snapshot.get("checks")
    if not isinstance(checks, list):
        tested.append("checks_unavailable")
        checks = []
    checks = [check for check in checks if isinstance(check, Mapping)]
    # GitHub Actions jobs carry a workflow name; app checks (Socket, Vercel) do not.
    jobs = [check for check in checks if check.get("workflow")]
    for check in jobs:
        if check.get("bucket") == "fail":
            tested.append(f"check_failed:{check.get('name') or '?'}")

    if path == "ordinary" and snapshot.get("author") in DEPENDABOT_LOGINS:
        if not jobs:
            tested.append("dependabot_suite_missing")
        elif any(check.get("bucket") != "pass" for check in jobs):
            tested.append("dependabot_suite_not_passed")
    elif path == "ordinary":
        comments = snapshot.get("comments")
        if not isinstance(comments, list):
            tested.append("local_test_record_unavailable")
        elif local not in local_test_record_heads(comments):
            tested.append("local_test_record_missing")
    elif path == "release":
        labels = snapshot.get("labels")
        if not isinstance(labels, list) or RELEASE_LABEL not in labels:
            tested.append("release_label_missing")
        for name in RELEASE_CHECKS:
            named = [check for check in checks if check.get("name") == name]
            if not named:
                tested.append(f"release_check_missing:{name}")
            elif any(check.get("bucket") != "pass" for check in named):
                tested.append(f"release_check_not_success:{name}")
        behind = snapshot.get("behind_by")
        if not isinstance(behind, int) or isinstance(behind, bool):
            tested.append("main_up_to_date_unknown")
        elif behind != 0:
            tested.append("main_not_up_to_date")
    else:
        tested.append("landing_path_unsupported")

    return MergeEvidence(
        head=local,
        path=path,
        can_merge=not merge,
        tested=not tested,
        merge_reasons=tuple(dict.fromkeys(merge)),
        test_reasons=tuple(dict.fromkeys(tested)),
    )


def run_gh(args: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["gh", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", f"gh unavailable: {exc.__class__.__name__}"
    return proc.returncode, proc.stdout, proc.stderr


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _pages(raw: Any) -> list[Any]:
    # ``gh api --paginate --slurp`` returns one array of pages.
    return raw if isinstance(raw, list) else []


def _checks(
    run: GhRunner,
    extra: Sequence[str],
    number: str,
    repo: str,
    repo_root: Path,
    empty_message: str,
) -> list[Any] | None:
    """``gh pr checks --json``: a list, ``[]`` when none exist, ``None`` if unread.

    gh exits 1 on failed checks and 8 on pending ones while still printing
    JSON, and exits 1 with a message on stderr when no checks exist.
    """

    _, out, err = run(
        ["pr", "checks", number, "--repo", repo, *extra, "--json", "name,bucket,workflow"],
        repo_root,
    )
    if out.strip():
        parsed = _json(out)
        return parsed if isinstance(parsed, list) else None
    if empty_message in err:
        return []
    return None


def fetch_pr_snapshot(
    repo_root: Path,
    *,
    pr: str | None = None,
    run: GhRunner = run_gh,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read the live pull request state. Returns ``(snapshot, error)``."""

    target = [pr] if pr else []
    code, out, _ = run(
        [
            "pr", "view", *target, "--json",
            "number,url,state,isDraft,baseRefName,headRefOid,labels,"
            "mergeable,mergeStateStatus,author",
        ],
        repo_root,
    )
    view = _json(out) if code == 0 else None
    if not isinstance(view, dict):
        return None, "pull_request_unavailable"
    match = PR_URL_RE.fullmatch(str(view.get("url") or ""))
    if match is None:
        return None, "pull_request_url_invalid"
    repo, number = match.group(1), match.group(2)
    head = str(view.get("headRefOid") or "")

    code, out, _ = run(["repo", "view", repo, "--json", "defaultBranchRef"], repo_root)
    repo_view = _json(out) if code == 0 else None
    default_branch = (
        (repo_view.get("defaultBranchRef") or {}).get("name")
        if isinstance(repo_view, dict)
        else None
    )
    if not isinstance(default_branch, str) or not default_branch:
        return None, "default_branch_unavailable"

    # The latest result per check on the head, as GitHub shows it on the PR.
    # Results belong to the commit, as they do for branch protection.
    required = _checks(run, ["--required"], number, repo, repo_root, NO_REQUIRED_CHECKS_MESSAGE)
    checks = _checks(run, [], number, repo, repo_root, NO_CHECKS_MESSAGE)

    code, out, _ = run(
        [
            "api", "--paginate", "--slurp",
            f"repos/{repo}/issues/{number}/comments?per_page=100",
        ],
        repo_root,
    )
    comments: list[dict[str, Any]] | None = None
    if code == 0:
        comments = [
            {
                "body": item.get("body") or "",
                "author_association": item.get("author_association"),
            }
            for page in _pages(_json(out))
            if isinstance(page, list)
            for item in page
            if isinstance(item, dict)
        ]

    base = view.get("baseRefName")
    behind_by: int | None = None
    if landing_path(base, default_branch) == "release" and EXACT_COMMIT_RE.fullmatch(head):
        code, out, _ = run(
            ["api", f"repos/{repo}/compare/{RELEASE_BRANCH}...{head}", "--jq", ".behind_by"],
            repo_root,
        )
        if code == 0 and out.strip().isdigit():
            behind_by = int(out.strip())

    labels = [
        item.get("name")
        for item in view.get("labels") or ()
        if isinstance(item, dict)
    ]
    return (
        {
            "repo": repo,
            "number": int(number),
            "head": head,
            "base": base,
            "default_branch": default_branch,
            "state": view.get("state"),
            "is_draft": view.get("isDraft"),
            "author": (view.get("author") or {}).get("login")
            if isinstance(view.get("author"), dict)
            else None,
            "mergeable": view.get("mergeable"),
            "merge_state_status": view.get("mergeStateStatus"),
            "labels": labels,
            "required_checks": required,
            "checks": checks,
            "comments": comments,
            "behind_by": behind_by,
        },
        None,
    )


def compute_merge_evidence(
    repo_root: Path,
    *,
    local_head: str,
    pr: str | None = None,
    run: GhRunner = run_gh,
) -> MergeEvidence:
    snapshot, error = fetch_pr_snapshot(repo_root, pr=pr, run=run)
    if snapshot is None:
        return unavailable(local_head.lower(), error or "pull_request_unavailable")
    return evaluate_merge_evidence(snapshot, local_head=local_head)
