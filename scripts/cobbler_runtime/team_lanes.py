"""Persistent driver-owned writer lanes. Dispatch remains the launch owner.

Identity fields are assertions made by the trusted driver, not authentication.
This helper grants no merge-to-main authority. It integrates only into the
registered feature branch, and never launches or resumes a worker.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any, Iterator
import uuid

from .parallel_lanes import validate_lane_partition
from .schema import ValidationIssue

SCHEMA_VERSION = 1
TERMINAL = {"integrated", "failed", "cancelled"}
MAX_COMMITS = 256


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ValidationIssue("team_lanes_" + code, message)


def identity(session: str, kind: str, model: str) -> dict[str, str]:
    result = {"session": session, "kind": kind, "model": model}
    _require(all(isinstance(v, str) and v.strip() == v and v for v in result.values()),
             "identity_invalid", "Session, kind, and exact model are required.")
    return result


def _git(path: str | Path, *args: str, codes: tuple[int, ...] = (0,)) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationIssue("team_lanes_git_failed", f"Git failed: {exc}") from exc
    _require(result.returncode in codes, "git_failed",
             result.stderr.decode("utf-8", "replace").strip()[:2000] or "Git failed.")
    _require(len(result.stdout) <= 4 * 1024 * 1024, "git_output_limit", "Git output exceeds the lane limit.")
    return result.stdout.decode("utf-8", "surrogateescape").rstrip("\n")


def _ancestor(path: str | Path, older: str, newer: str) -> bool:
    return _git(path, "merge-base", older, newer) == older


def _checkout(path: str | Path, branch: str, common: str | None = None,
              *, clean: bool = True) -> dict[str, str]:
    root = str(Path(path).resolve())
    _require(_git(root, "rev-parse", "--show-toplevel") == root,
             "worktree_invalid", "Use an exact worktree root.")
    _require(_git(root, "symbolic-ref", "--quiet", "--short", "HEAD") == branch,
             "branch_drift", "The worktree branch differs from the registered branch.")
    actual_common = str(Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve())
    _require(common is None or actual_common == common, "repository_mismatch",
             "The lane worktree belongs to another repository.")
    if clean:
        _require(not _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"),
                 "dirty_worktree", "The worktree has staged, unstaged, or untracked changes.")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        marker_path = _git(root, "rev-parse", "--git-path", marker)
        if not Path(marker_path).is_absolute():
            marker_path = str(Path(root) / marker_path)
        _require(not Path(marker_path).exists(), "git_operation_pending",
                 "Complete or abort the existing Git operation before proceeding.")
    return {"worktree": root, "branch": branch, "common": actual_common,
            "head": _git(root, "rev-parse", "HEAD")}


def _feature_branch(path: str | Path, branch: str) -> None:
    _git(path, "check-ref-format", "--branch", branch)
    protected = {"main", "master", "HEAD"}
    for ref in _git(path, "for-each-ref", "--format=%(symref)", "refs/remotes").splitlines():
        if ref.startswith("refs/remotes/"):
            protected.add(ref.split("/", 3)[-1])
    _require(branch not in protected, "protected_branch",
             "Writer integration requires an assigned feature branch.")


def _owned(path: str, surfaces: list[str]) -> bool:
    path = path.casefold()
    return any(path == s.casefold().rstrip("/") or
               path.startswith(s.casefold().rstrip("/") + "/") for s in surfaces)


class LaneStore:
    """One SQLite ledger per run, with durable integration reservations."""

    def __init__(self, path: str | Path):
        self.path = Path(path).absolute()

    @contextmanager
    def _transaction(self, *, create: bool = False) -> Iterator[tuple[sqlite3.Connection, dict[str, Any] | None]]:
        _require(not self.path.is_symlink(), "state_invalid", "The lane database cannot be a symlink.")
        _require(create or self.path.is_file(), "state_missing", "Initialize the lane database first.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        try:
            os.chmod(self.path, 0o600)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            if create:
                connection.execute("CREATE TABLE IF NOT EXISTS run (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL)")
            row = connection.execute("SELECT payload FROM run WHERE singleton=1").fetchone()
            state = json.loads(row[0]) if row else None
            _require(create or state is not None, "state_invalid", "The lane database has no run record.")
            if state is not None:
                _require(isinstance(state, dict) and state.get("version") == SCHEMA_VERSION,
                         "schema_version", "Unsupported lane database version.")
                _require(isinstance(state.get("driver"), dict) and isinstance(state.get("lanes"), dict)
                         and isinstance(state.get("run_id"), str),
                         "state_invalid", "The lane database has an invalid run record.")
                for record in [state["driver"], *state["lanes"].values()]:
                    _require(isinstance(record, dict) and all(isinstance(record.get(key), str) and record[key]
                             for key in ("worktree", "branch", "common", "head")),
                             "state_invalid", "The lane database has an invalid checkout record.")
                    agent = record.get("identity")
                    _require(isinstance(agent, dict) and set(agent) == {"session", "kind", "model"},
                             "state_invalid", "The lane database has an invalid agent identity.")
                    identity(**agent)
                for lane_id, lane in state["lanes"].items():
                    _require(lane.get("id") == lane_id and lane.get("status") in
                             {"pending", "running", "completed", "failed", "cancelled", "integrating", "integrated"}
                             and isinstance(lane.get("base_head"), str)
                             and isinstance(lane.get("owned_surfaces"), list)
                             and all(isinstance(surface, str) and surface for surface in lane["owned_surfaces"])
                             and isinstance(lane.get("depends_on"), list)
                             and all(isinstance(dep, str) and dep in state["lanes"] for dep in lane["depends_on"])
                             and "result_head" in lane and "integration" in lane,
                             "state_invalid", "The lane database has an invalid lifecycle record.")
                    if lane["status"] in {"integrating", "integrated"}:
                        reservation = lane["integration"]
                        _require(isinstance(reservation, dict) and all(isinstance(reservation.get(key), str)
                                 for key in ("id", "driver_head", "lane_head", "expected_tree")) and
                                 (lane["status"] != "integrated" or isinstance(reservation.get("merged_head"), str)),
                                 "state_invalid", "The lane database has an invalid integration reservation.")
            yield connection, state
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _save(connection: sqlite3.Connection, state: dict[str, Any]) -> None:
        connection.execute("INSERT OR REPLACE INTO run(singleton,payload) VALUES(1,?)",
                           (json.dumps(state, sort_keys=True),))

    def _driver(self, state: dict[str, Any], actor: dict[str, str]) -> None:
        _require(actor == state["driver"]["identity"], "driver_required",
                 "Only the exact registered driver can change lane state.")
        self._session(state)

    def _session(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("session_path"):
            return None
        from .teams import read_json, team_block
        session = read_json(state["session_path"])
        team = team_block(session)
        _require(session.get("run_id") == state["run_id"] and
                 session.get("team_lanes") == {"state_path": str(self.path), "run_id": state["run_id"]},
                 "session_mismatch", "The canonical session does not match this lane ledger.")
        registered = state["driver"]["identity"]
        _require(all(team["driver"].get(key) == value for key, value in
                     {"session_id": registered["session"], "kind": registered["kind"], "model": registered["model"]}.items()),
                 "identity_mismatch", "The canonical driver identity changed.")
        _require(str(Path(session.get("worktree_path", "")).resolve()) == state["driver"]["worktree"],
                 "worktree_invalid", "The canonical session worktree differs from the driver worktree.")
        _check_contributors(session, state)
        return session

    def _contributor(self, state: dict[str, Any], worker: dict[str, str]) -> None:
        session = self._session(state)
        if session is None:
            return
        from .teams import contributor, identity as team_identity
        from .storage import atomic_write_json
        agent = {"session_id": worker["session"], "kind": worker["kind"], "model": worker["model"]}
        for existing in session["team"]["contributors"]:
            if existing.get("session_id") == agent["session_id"]:
                _require(all(existing.get(key) == value for key, value in agent.items()),
                         "identity_mismatch", "The contributor route differs from its registered identity.")
                agent = team_identity(existing)
                break
        contributor(session, agent, "implementer")
        # Persist before the lane enters the ledger. A crash can leave an extra
        # excluded reviewer, but cannot omit the identity of a registered writer.
        atomic_write_json(Path(state["session_path"]), session)

    @staticmethod
    def _lane(state: dict[str, Any], lane_id: str) -> dict[str, Any]:
        _require(lane_id in state["lanes"], "lane_unknown", "The lane is not registered.")
        return state["lanes"][lane_id]

    def initialize(self, *, repo: str | Path, run_id: str,
                   driver: dict[str, str], session_path: str | Path | None = None) -> dict[str, Any]:
        identity(**driver)
        _require(bool(run_id.strip()), "run_id_required", "A run ID is required.")
        branch = _git(repo, "symbolic-ref", "--short", "HEAD")
        _feature_branch(repo, branch)
        checkout = _checkout(repo, branch)
        with self._transaction(create=True) as (db, state):
            _require(state is None, "already_initialized", "A run already owns this lane database.")
            state = {"version": SCHEMA_VERSION, "run_id": run_id,
                     "driver": {**checkout, "identity": driver}, "lanes": {}}
            if session_path is not None:
                from .teams import read_json, team_block
                from .storage import atomic_write_json
                session_path = Path(session_path).absolute()
                session = read_json(session_path)
                team = team_block(session)
                binding = {"state_path": str(self.path), "run_id": run_id}
                _require(session.get("run_id") == run_id and
                         session.get("team_lanes", binding) == binding,
                         "session_mismatch", "The canonical run ID or lane binding differs.")
                _require(all(team["driver"].get(key) == value for key, value in
                             {"session_id": driver["session"], "kind": driver["kind"], "model": driver["model"]}.items()),
                         "identity_mismatch", "Initialize lanes with the canonical team driver identity.")
                _require(str(Path(session.get("worktree_path", "")).resolve()) == checkout["worktree"],
                         "worktree_invalid", "The canonical session worktree differs from the driver worktree.")
                state["session_path"] = str(session_path)
                session["team_lanes"] = binding
                atomic_write_json(session_path, session)
            self._save(db, state)
        return self.status()

    def register(self, *, actor: dict[str, str], lane_id: str, worktree: str | Path,
                 branch: str, worker: dict[str, str], owns: list[str],
                 depends_on: list[str] | None = None) -> dict[str, Any]:
        identity(**worker)
        with self._transaction() as (db, state):
            self._driver(state, actor)
            _require(lane_id not in state["lanes"], "lane_exists", "This lane is already registered.")
            _require(worker != actor and worker["session"] != actor["session"],
                     "recursive_helper", "A driver cannot register itself as a helper.")
            driver = state["driver"]
            _feature_branch(driver["worktree"], branch)
            checkout = _checkout(worktree, branch, driver["common"])
            _require(checkout["worktree"] != driver["worktree"] and branch != driver["branch"],
                     "worktree_shared", "Each writer needs a separate worktree and branch.")
            for lane in state["lanes"].values():
                _require(checkout["worktree"] != lane["worktree"] and branch != lane["branch"] and
                         worker["session"] != lane["identity"]["session"],
                         "identity_reused", "A writer worktree, branch, or session is already assigned.")
            depends_on = list(depends_on or [])
            _require(len(set(depends_on)) == len(depends_on) and
                     all(dep in state["lanes"] for dep in depends_on),
                     "dependency_unknown", "Dependencies must name earlier registered lanes once each.")
            for surface in owns:
                _require(bool(surface) and "\\" not in surface and not re.search(r"[\x00-\x1f*?\[\]]", surface) and
                         all(part.casefold() not in {"", ".", "..", ".git"} for part in surface.rstrip("/").split("/")),
                         "surface_invalid", "Owned surfaces must be literal repository-relative paths.")
            lane = {**checkout, "id": lane_id, "identity": worker, "owned_surfaces": owns,
                    "depends_on": depends_on, "batches": [lane_id], "status": "pending",
                    "base_head": checkout["head"], "result_head": None, "integration": None}
            issues = validate_lane_partition([*state["lanes"].values(), lane])
            if issues:
                raise issues[0]
            current_driver = _checkout(driver["worktree"], driver["branch"], driver["common"])
            _require(checkout["head"] == current_driver["head"], "base_mismatch",
                     "Register the lane at the current driver commit.")
            self._contributor(state, worker)
            state["lanes"][lane_id] = lane
            self._save(db, state)
        return self.status()

    @staticmethod
    def _dependencies(state: dict[str, Any], lane: dict[str, Any], head: str) -> None:
        for dependency in lane["depends_on"]:
            dep = state["lanes"][dependency]
            _require(dep["status"] == "integrated" and
                     _ancestor(lane["worktree"], dep["integration"]["merged_head"], head),
                     "dependency_unmet", f"Lane {dependency} must be integrated in the lane base first.")

    def start(self, *, actor: dict[str, str], lane_id: str,
              worker: dict[str, str]) -> dict[str, Any]:
        with self._transaction() as (db, state):
            self._driver(state, actor)
            lane = self._lane(state, lane_id)
            _require(lane["identity"] == worker, "identity_mismatch", "Resume requires the same session, kind, and model.")
            _require(lane["status"] in {"pending", "running"}, "transition_invalid", "Only pending or running lanes can start.")
            current = _checkout(lane["worktree"], lane["branch"], state["driver"]["common"],
                                clean=lane["status"] == "pending")
            if lane["status"] == "running":
                _require(_ancestor(lane["worktree"], lane["base_head"], current["head"]),
                         "branch_drift", "The running lane lost its registered base.")
                # This is an identity check, never a request to launch a second worker.
                return {"ok": True, "lane": lane, "resume_only": True, "launch_authorized": False}
            driver = state["driver"]
            driver_now = _checkout(driver["worktree"], driver["branch"], driver["common"])
            self._dependencies(state, lane, current["head"])
            _require(current["head"] == driver_now["head"] and
                     _ancestor(lane["worktree"], lane["base_head"], current["head"]),
                     "base_mismatch", "Bring the pending lane to the current driver commit before launch.")
            lane["base_head"] = current["head"]
            lane["status"] = "running"
            self._save(db, state)
        return self.status()

    @staticmethod
    def _result(lane: dict[str, Any], common: str) -> tuple[str, list[str]]:
        current = _checkout(lane["worktree"], lane["branch"], common)
        base, head = lane["base_head"], current["head"]
        _require(_ancestor(lane["worktree"], base, head), "branch_drift", "The lane lost its registered base.")
        if lane["result_head"] is not None:
            _require(head == lane["result_head"], "branch_drift", "The completed lane commit changed.")
        commits = _git(lane["worktree"], "rev-list", "--reverse", f"{base}..{head}").splitlines()
        _require(0 < len(commits) <= MAX_COMMITS, "result_empty_or_large",
                 f"A writer result requires 1-{MAX_COMMITS} commits.")
        _require(not _git(lane["worktree"], "rev-list", "--merges", f"{base}..{head}"),
                 "result_merge_commit", "Writer results must have linear history from their registered base.")
        touched: set[str] = set()
        for commit in commits:
            touched.update(p for p in _git(lane["worktree"], "diff-tree", "--no-commit-id", "--name-only",
                                          "--no-renames", "-r", "-z", commit).split("\0") if p)
        _require(bool(touched) and all(_owned(p, lane["owned_surfaces"]) for p in touched),
                 "ownership_violation", "Writer history changed a path outside its assigned surfaces, or has no changes.")
        return head, sorted(touched)

    def complete(self, *, actor: dict[str, str], lane_id: str,
                 worker: dict[str, str], result_head: str) -> dict[str, Any]:
        with self._transaction() as (db, state):
            self._driver(state, actor)
            lane = self._lane(state, lane_id)
            _require(lane["identity"] == worker, "identity_mismatch", "Completion requires the exact worker identity.")
            _require(lane["status"] == "running", "transition_invalid", "Only running lanes can complete.")
            head, touched = self._result(lane, state["driver"]["common"])
            _require(head == result_head, "branch_drift", "Report the exact current writer commit.")
            lane.update(status="completed", result_head=head, touched_paths=touched)
            self._save(db, state)
        return self.status()

    def stop(self, *, actor: dict[str, str], lane_id: str, reason: str,
             cancelled: bool = False) -> dict[str, Any]:
        _require(bool(reason.strip()), "reason_required", "A failure or cancellation reason is required.")
        with self._transaction() as (db, state):
            self._driver(state, actor)
            lane = self._lane(state, lane_id)
            _require(lane["status"] in ({"pending", "running", "completed", "failed"} if cancelled else
                                        {"pending", "running", "completed"}),
                     "transition_invalid", "This lane cannot be stopped through a state update.")
            lane.update(status="cancelled" if cancelled else "failed", reason=reason)
            self._save(db, state)
        return self.status()

    def _gate(self, state: dict[str, Any], lane_id: str) -> dict[str, Any]:
        lane = self._lane(state, lane_id)
        _require(lane["status"] == "completed", "integration_state", "Integration requires a completed, unintegrated lane.")
        _require(not any(item["status"] == "integrating" for item in state["lanes"].values()),
                 "integration_pending", "Reconcile the existing integration reservation first.")
        driver = state["driver"]
        _feature_branch(driver["worktree"], driver["branch"])
        current = _checkout(driver["worktree"], driver["branch"], driver["common"])
        head, touched = self._result(lane, driver["common"])
        _require(_ancestor(driver["worktree"], driver["head"], current["head"]),
                 "branch_drift", "The driver lost its registered base.")
        _require(_ancestor(driver["worktree"], lane["base_head"], current["head"]),
                 "branch_drift", "The driver no longer contains the lane base.")
        _require(not _ancestor(driver["worktree"], head, current["head"]),
                 "already_integrated", "The driver already contains this writer result.")
        self._dependencies(state, lane, current["head"])
        driver_paths = [p for p in _git(driver["worktree"], "diff", "--name-only", "--no-renames", "-z",
                                       lane["base_head"], current["head"]).split("\0") if p]
        _require(not any(_owned(p, lane["owned_surfaces"]) for p in driver_paths),
                 "integration_overlap", "The driver changed an owned lane path after the lane base.")
        tree = _git(driver["worktree"], "merge-tree", "--write-tree", current["head"], head).splitlines()[0]
        _require(bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree)),
                 "merge_preview_invalid", "Git did not return a clean merge tree.")
        return {"lane_id": lane_id, "driver_head": current["head"], "lane_head": head,
                "expected_tree": tree, "touched_paths": touched}

    def gate(self, *, actor: dict[str, str], lane_id: str) -> dict[str, Any]:
        with self._transaction() as (_, state):
            self._driver(state, actor)
            return {"ok": True, "preview_only": True, **self._gate(state, lane_id)}

    def integrate(self, *, actor: dict[str, str], lane_id: str) -> dict[str, Any]:
        with self._transaction() as (db, state):
            self._driver(state, actor)
            reservation = {**self._gate(state, lane_id), "id": str(uuid.uuid4())}
            lane = state["lanes"][lane_id]
            lane.update(status="integrating", integration=reservation)
            worktree = state["driver"]["worktree"]
            driver = state["driver"]
            self._save(db, state)
        # Persist before touching Git. Failure or process death leaves a visible
        # reservation. Another invocation must reconcile, never retry blindly.
        current = _checkout(worktree, driver["branch"], driver["common"])
        _require(current["head"] == reservation["driver_head"],
                 "branch_drift", "The driver changed after the integration reservation.")
        self._result(lane, driver["common"])
        _git(worktree, "merge", "--no-ff", "--no-edit", reservation["lane_head"])
        return self.reconcile(actor=actor, lane_id=lane_id, outcome="integrated")

    def reconcile(self, *, actor: dict[str, str], lane_id: str, outcome: str) -> dict[str, Any]:
        _require(outcome in {"integrated", "not-applied"}, "outcome_invalid", "Choose integrated or not-applied.")
        with self._transaction() as (db, state):
            self._driver(state, actor)
            lane = self._lane(state, lane_id)
            _require(lane["status"] == "integrating", "integration_state", "No interrupted integration exists for this lane.")
            driver, reservation = state["driver"], lane["integration"]
            current = _checkout(driver["worktree"], driver["branch"], driver["common"])
            self._result(lane, driver["common"])
            if outcome == "not-applied":
                _require(current["head"] == reservation["driver_head"], "reconcile_ambiguous",
                         "The driver changed. Do not retry this integration.")
                lane.update(status="completed", integration=None)
            else:
                parents = _git(driver["worktree"], "show", "-s", "--format=%P", current["head"]).split()
                tree = _git(driver["worktree"], "rev-parse", f"{current['head']}^{{tree}}")
                _require(parents == [reservation["driver_head"], reservation["lane_head"]] and
                         tree == reservation["expected_tree"], "reconcile_ambiguous",
                         "The integration does not match the reserved parents and tree.")
                lane["status"] = "integrated"
                reservation["merged_head"] = current["head"]
            self._save(db, state)
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._transaction() as (_, state):
            _require(state is not None, "state_missing", "Initialize the lane database first.")
            lanes = state["lanes"]
            groups = {status: [lid for lid, lane in lanes.items() if lane["status"] == status]
                      for status in ("pending", "running", "completed", "failed", "cancelled", "integrating", "integrated")}
            return {"ok": True, "version": state["version"], "run_id": state["run_id"],
                    "driver": state["driver"], "session_path": state.get("session_path"), "lanes": lanes, **groups,
                    "all_terminal": bool(lanes) and all(l["status"] in TERMINAL for l in lanes.values()),
                    "all_integrated": bool(lanes) and all(l["status"] == "integrated" for l in lanes.values()),
                    "ready": bool(lanes) and all(l["status"] in {"integrated", "cancelled"} for l in lanes.values()),
                    "launch_authorized": False, "model_calls_made": False}


def readiness_check(session: dict[str, Any], head: str) -> None:
    """Optional canonical readiness gate; reports alone cannot satisfy it."""
    binding = session.get("team_lanes")
    if binding is None:
        return
    _require(isinstance(binding, dict) and isinstance(binding.get("state_path"), str),
             "session_mismatch", "Invalid canonical lane binding.")
    store = LaneStore(binding["state_path"])
    with store._transaction() as (_, state):
        canonical = store._session(state)
        _require(canonical is not None and canonical.get("team_lanes") == binding and
                 session.get("run_id") == state["run_id"], "session_mismatch",
                 "The canonical session does not match the lane ledger.")
        _check_contributors(session, state)
        driver, lanes = state["driver"], state["lanes"]
        current = _checkout(driver["worktree"], driver["branch"], driver["common"])
        _require(current["head"] == head, "branch_drift", "Readiness must inspect the actual current driver commit.")
        _require(_ancestor(driver["worktree"], driver["head"], head), "branch_drift",
                 "The current driver commit lost its registered base.")
        _require(bool(lanes) and all(lane["status"] in {"integrated", "cancelled"} for lane in lanes.values()),
                 "not_ready", "Integrate completed lanes and resolve pending, active, or failed lanes before readiness.")
        for lane in lanes.values():
            if lane["status"] == "integrated":
                store._result(lane, driver["common"])
                _require(_ancestor(driver["worktree"], lane["integration"]["merged_head"], head) and
                         _ancestor(driver["worktree"], lane["result_head"], head),
                         "branch_drift", "The current driver commit lost an integrated lane result.")


def _check_contributors(session: dict[str, Any], state: dict[str, Any]) -> None:
    from .teams import team_block
    team = team_block(session)
    for writer in [state["driver"]["identity"], *(lane["identity"] for lane in state["lanes"].values())]:
        required = {"session_id": writer["session"], "kind": writer["kind"], "model": writer["model"]}
        _require(any(all(row.get(key) == value for key, value in required.items())
                     for row in team["contributors"]), "contributor_missing",
                 "The canonical contributor ledger must retain each exact writer identity.")


def _command(args: argparse.Namespace) -> int:
    try:
        store = LaneStore(args.state)
        action = args.lane_action
        if action == "status":
            result = store.status()
        else:
            actor = identity(args.actor_session, args.actor_kind, args.actor_model)
            if action == "init":
                result = store.initialize(repo=args.repo, run_id=args.run_id, driver=actor, session_path=args.session)
            elif action == "register":
                result = store.register(actor=actor, lane_id=args.lane, worktree=args.worktree,
                                        branch=args.branch, worker=identity(args.session, args.kind, args.model),
                                        owns=args.owns, depends_on=args.depends_on)
            elif action in {"start", "complete"}:
                kwargs = {"actor": actor, "lane_id": args.lane,
                          "worker": identity(args.session, args.kind, args.model)}
                if action == "complete":
                    kwargs["result_head"] = args.result_head
                result = getattr(store, action)(**kwargs)
            elif action in {"fail", "cancel"}:
                result = store.stop(actor=actor, lane_id=args.lane, reason=args.reason, cancelled=action == "cancel")
            elif action == "reconcile":
                result = store.reconcile(actor=actor, lane_id=args.lane, outcome=args.outcome)
            else:
                result = getattr(store, action)(actor=actor, lane_id=args.lane)
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return 0
    except ValidationIssue as exc:
        print(json.dumps({"ok": False, "issues": [exc.to_dict()]}))
        return 1
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"ok": False, "issues": [{"code": "team_lanes_storage_failed", "message": str(exc)}]}))
        return 1


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("team-lanes", help="Track writer lanes and integrate exact completed results")
    actions = parser.add_subparsers(dest="lane_action", required=True)
    for action in ("init", "register", "start", "complete", "fail", "cancel", "gate", "integrate", "reconcile", "status"):
        command = actions.add_parser(action)
        command.add_argument("--state", required=True, type=Path)
        command.add_argument("--json", action="store_true", help="Output is always JSON")
        command.set_defaults(func=_command)
        if action == "status":
            continue
        for field in ("session", "kind", "model"):
            command.add_argument("--actor-" + field, required=True)
        if action == "init":
            command.add_argument("--repo", required=True, type=Path)
            command.add_argument("--run-id", required=True)
            command.add_argument("--session", type=Path, help="Canonical session with an initialized team")
            continue
        command.add_argument("--lane", required=True)
        if action in {"register", "start", "complete"}:
            for field in ("session", "kind", "model"):
                command.add_argument("--" + field, required=True)
        if action == "register":
            command.add_argument("--worktree", required=True, type=Path)
            command.add_argument("--branch", required=True)
            command.add_argument("--owns", required=True, action="append")
            command.add_argument("--depends-on", action="append", default=[])
        elif action == "complete":
            command.add_argument("--result-head", required=True)
        elif action in {"fail", "cancel"}:
            command.add_argument("--reason", required=True)
        elif action == "reconcile":
            command.add_argument("--outcome", required=True, choices=("integrated", "not-applied"))
