# Optional open-source Grok Build worker

Grok Build is an optional autonomous worker. Native Codex or Claude Code remains the default, and
Grok receives no protected-ref, PR, merge, or final-acceptance authority.

## Install and authenticate

Install Grok Build from the [official `xai-org/grok-build` source](https://github.com/xai-org/grok-build)
and authenticate once in an ordinary terminal:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
grok
```

The first `grok` launch opens the browser login flow; finish it, then exit the interactive CLI.
Elves trusts the installed executable's observed behavior for launches; upstream source is a
semantic reference, not a substitute for probing the installed build.

Use exactly one noninteractive credential route:

- trusted local OAuth: `--grant-grok-auth` keeps a private per-run `HOME` and `GROK_HOME` and
  exposes only the validated owner-private canonical auth file through `GROK_AUTH_PATH`;
- API key: `--grant-env XAI_API_KEY`, preferred for CI and non-trusted lanes.

Never grant host `HOME`, `GROK_HOME`, SSH state, Git configuration, or both auth strategies.

## Capability-check and choose a route

From the target repository, invoke the helper under the active installed Elves skill root (the
`scripts/...` form below is source-checkout shorthand):

```bash
ELVES_HOST=claude  # Use codex when Codex is the live driver.
python3 scripts/cobbler_agents.py route-worker --json \
  --host "$ELVES_HOST" --execution-reasoning medium --review-risk high \
  --provider grok --allow-grok --probe-grok
```

The safe snapshot contains no credentials or raw OAuth/provider output. It records installed
version/build, supported permission and read-only controls, create/resume session grammar,
streaming JSON, JSON schema, ACP, live model catalog/default, and concrete unavailable reasons.
`--new-session` is unsupported; new launches use a caller-generated UUID with `--session-id`, and
recovery uses exact `--resume`.

Provider qualification does not depend on goal support. The isolated `/goal status` probe uses the
narrow auth projection, but is independent of catalog lookup and model inference. It proves only
command resolution; it never enables goal launch by itself. Headless `/goal <objective>` requires
separately recorded behavioral evidence that the exact authenticated prompt-file canary reached a
terminal state and returned the requested session identity. The installed 0.2.101 canary emitted
work but did not reach terminal state within 120 seconds, so Elves currently records and uses the
one-packet fallback. A core capability, auth, or live-catalog failure selects native fallback with
a concrete reason before spawn.

Goal evidence is a path passed with `--grok-goal-behavioral-evidence <artifact.json>` alongside
`--probe-grok` or during `full-run-prepare`. The artifact must be a regular non-symlink JSON file no
larger than 64 KiB and not writable by group or others. It has exactly these fields:

```json
{
  "artifact_type": "grok_goal_terminal_canary",
  "schema_version": 1,
  "installed_version": "<exact-version>",
  "installed_build_commit": "<exact-build-commit>",
  "session_id": "<canonical-uuid>",
  "prompt": "/goal <packet-backed objective>",
  "prompt_sha256": "<sha256-of-exact-prompt>",
  "exit_code": 0,
  "terminal_event": {"type": "end", "sessionId": "<same-canonical-uuid>"}
}
```

The UTF-8 prompt must begin with `/goal `, contain a nonempty objective, and be no larger than
32 KiB. Version, build, prompt digest, successful exit, and terminal session must all match. Elves
stores only a digest-derived evidence ID in safe state. Missing, unsafe, malformed, mismatched, or
incomplete evidence leaves goal mode disabled and uses the one-packet fallback.

Model selection uses only the authenticated live catalog. Omitting `--model` (or using the CLI's
`auto` preparation value) prefers **`grok-4.5`** when the live catalog returns it, then a
non-retired live default. Composer 2.5 (`grok-composer-2.5-fast`) is retired and is never selected.
An explicit model is accepted only if the catalog returns that exact identifier. Elves passes
`--effort high` by default—the highest Grok Build effort. The operator can still make an explicit
lower-effort tradeoff.

## Qualified prewalk lane (distinct from trusted full-run)

Everything below this section describes the **trusted full-run lane**: yolo-approved
(`--always-approve`), optionally `--grant-github-push`, worker-owned feature-branch progress. The
**prewalk lane** is a separate, narrower authority profile in the host-profile registry:

- non-yolo: `--permission-mode auto` only — this lane never emits `--always-approve`, `--yolo`,
  or `dontAsk`;
- no `--grant-github-push` and no push authority; narrow Git roots and the existing
  protected-ref/no-push checks apply;
- caller-generated UUID via `--session-id` (create-only), exact `--resume`, supervisor `--cwd`
  (sandbox is resume-sticky), streaming JSON without tool-call events;
- the private JSON TODO mirror is authoritative because the installed build's `plan.json`
  persistence is vestigial.

Required mode automatically runs the bounded live canary when matching proof is absent and records
a `grok_prewalk_qualification_canary` (schema version 1) artifact. The canary must prove, on the
exact installed version and build commit: the same session and worktree across both phases, the
route change actually applied on resume, guide-only fact retention after transition, no packet
replay, stream identity, honest `retained_safe` instruction fidelity under the persisted-
instruction transport. The real run separately proves whether the lane can complete task edits and
commits under `--permission-mode auto`. Elves writes only bounded fact evidence and never stores
model output or the random canary values. An artifact reporting `pruned` or `turn_scoped` loads as
recorded, non-activating evidence.

Validate a recorded artifact only against the installed binary:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" route-worker --json \
  --host codex --execution-reasoning medium --review-risk high \
  --provider grok --allow-grok --probe-grok \
  --prewalk auto --grok-prewalk-qualification /path/to/grok-prewalk-canary.json
```

The registry keeps single-phase Grok native-worker launch gated. A valid artifact or explicit
experimental request may enter only the two-phase prewalk supervisor. Provider consent,
`allow_grok=false`, live model catalog, API-key, Git, and landing restrictions remain unchanged.

Verification basis: grok-build 0.2.102 source (commit `98c3b24`) plus the 2026-07 repository audit
(repo-only `docs/reviews/2026-07-repo-audit-grok-prewalk.md` in a source checkout via PR #82;
installed bundles must not depend on that file). Advertised grammar and registry rows follow that
verified source. The cross-family delegation default was rechecked against Grok Build 0.2.103 and
source commit `7cfcb20`: the live/default model is catalog-owned, and `high` is the advertised
highest implementation-quality effort. Qualification claims remain bound to the cached artifact's
exact build and routes.

## Launch, follow, and recover

Create the host-owned rollback ref, prepare one exact session, launch with one auth strategy, and
park on the sanitized stream:

```bash
python3 scripts/cobbler_agents.py implement rollback-ref --json \
  --run-id <run-id> --session-id <uuid> --batch B0 --head <start-head> --push

python3 scripts/cobbler_agents.py implement full-run-prepare --json \
  --session-id <uuid> --branch <feature-branch> --start-head <start-head> \
  --worktree <path> --packet <packet.json> --session .elves-session.json \
  --adapter grok-build --model auto

python3 scripts/cobbler_agents.py implement full-run-launch --json \
  --session-id <uuid> --grant-grok-auth --grant-github-push

python3 scripts/cobbler_agents.py implement full-run-await --json \
  --session-id <uuid>
```

On successful terminal reconciliation, the monitor/await JSON includes the bounded host-neutral
`review_context` (`schema=elves-worker-confidence-review-v1`). Before primary Final Readiness,
Claude Code and Codex attach `review_context.review_prompt_block` verbatim. It preserves baseline
review, deepens attention for low confidence, reservations or conflicts, and exposes only a count
when shared-OAuth safety hides reservation text.

The trusted launcher emits Grok's `--always-approve` flag without also emitting
`--permission-mode auto`. Grok Build 0.2.101 makes the explicit permission mode win over the yolo
flag; combining them disables the intended unattended path and can end the first tool turn as
`Cancelled`. Restricted/non-yolo routes still retain their explicit permission mode. A structural
terminal cancellation, refusal, provider error, or max-turn event is a typed failed run even if
the Grok process itself exits zero.

Add `--grok-goal-behavioral-evidence <artifact.json>` to `full-run-prepare` only when that artifact
meets the contract above. Otherwise the same launch uses the one-packet fallback.

For API-key auth, replace `--grant-grok-auth` with `--grant-env XAI_API_KEY`. The default follower
shows sanitized progress, bounded usage, terminal state, and typed errors; unknown event types are
reported safely. Shared OAuth never exposes raw transcript text.

After an interrupted run, recover the same exact identity. `full-run-prepare` revalidates the
registered session, packet, branch, and worktree before the resumed process starts:

```bash
python3 scripts/cobbler_agents.py implement full-run-prepare --json \
  --session-id <uuid> --branch <feature-branch> --start-head <start-head> \
  --worktree <path> --packet <packet.json> --session .elves-session.json \
  --adapter grok-build --model auto --resume

python3 scripts/cobbler_agents.py implement full-run-launch --json \
  --session-id <uuid> --resume --grant-grok-auth --grant-github-push

python3 scripts/cobbler_agents.py implement full-run-await --json \
  --session-id <uuid>
```

If the process exits cleanly after committing and pushing but omits a valid final report, do not
resume it. Run the affected host tests, then reconstruct only the independently provable report
fields:

```bash
python3 scripts/cobbler_agents.py implement full-run-reconcile --json \
  --session-id <uuid> --host-tests-pass
```

A successful host reconstruction also returns the same `review_context`; attach its prompt block
before Final Readiness just as on the ordinary terminal monitor/await path. Invalid optional
confidence evidence falls back to an explicit no-signal baseline review and cannot make an
otherwise permitted reconstruction fail.

Goal-enhanced recovery uses `/goal resume`; it never resends `/goal <packet>`. Use `full-run-logs`
only for bounded diagnosis and `full-run-stop` only for explicit cancellation or recovery of a
live/wedged process. The host still owns cumulative review, acceptance proof, protected refs, PR
actions, and any user-authorized merge.
