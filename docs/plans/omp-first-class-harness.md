# Plan: Oh My Pi (omp) first-class harness citizen

> Staged plan for Elves. Product CLI spelling is **`omp`** (Oh My Pi), never `opm`.
>
> **Sources:** Fugu ultra planning synthesis (2026-08-09) plus host-native live omp/17.2.12 probe.
> Fugu raw log archived at `docs/elves/fugu-omp-harness-plan-fugu-report.log`.
>
> **Staged workspace (actual):**
> - Branch: `feat/omp-first-class-harness`
> - Worktree: `/Users/john/aigora/dev/elves-omp-first-class-harness`
> - Base tip / collision tripwire: `f53966679751819993dcb271f6343e3a656f0009`
> - Plan path (this file): `docs/plans/omp-first-class-harness.md`

## 1. MVP product shape

### Recommendation

Ship **Phase 1—an optional trusted parked full-run `omp-cli` worker—as the primary integration**.

“Primary” means the recommended Elves integration for Oh My Pi, not an automatic routing default. Subscription-native workers remain the normal default; `omp` is used only through explicit intent or a safe user preference.

| Phase | Product shape | Recommendation |
|---|---|---|
| **Phase 0** | Optional `/omp` and `$elves omp` bounded shortcut | Optional thin slice; independently skippable |
| **Phase 1** | Optional trusted parked full-run worker | **MVP and first-class target** |
| **Phase 2** | Host-profile registration and Elves exact-session prewalk | Defer pending Phase 1 behavioral qualification |
| **Phase 3** | Supported main driver and managed skill installation | Last; separate policy decision |

### Rationale

1. **Current main-driver policy is explicit.** Elves supports Claude Code, Codex, and Grok Build as main drivers. Phase 1 must describe `omp` only as an optional worker; running Elves from inside OMP remains unsupported until Phase 3.
2. **The existing thin safety kernel already has the correct seam.** The Devin integration demonstrates the needed shape:
   - canonical adapter identity;
   - adapter-specific argv;
   - strict transport decoding;
   - host-captured provider session identity;
   - the shared prepare/launch/monitor/await/reconcile lifecycle;
   - host-owned protected-ref, review, readiness, and merge controls.
3. **OMP session creation is Devin-like but simpler to authenticate.** OMP cannot accept a preallocated session ID, so the host captures the UUID from its typed NDJSON stream rather than using latest-session discovery.
4. **Phase 0 alone under-delivers.** A one-shot shortcut is useful but does not provide trusted branch progress, exact-session recovery, parked monitoring, or terminal reconciliation.
5. **Phase 3 would be premature.** Main-driver status expands canonical-memory, staging, stop-control, landing, installation, and host-parity policy. A functioning worker adapter is necessary but not sufficient evidence.
6. **OMP `--prewalk` is not Elves prewalk.** It is a model-role switch. Phase 1 forbids it, while Phase 2 must use Elves’ own two-phase exact-session supervisor.

### Phase 1 public contract

- Canonical adapter: **`omp-cli`**.
- Executable: **`omp`**. Never accept or document `opm`.
- Optional provider: missing executable or authentication never blocks native runs.
- Trusted full-run requires:
  - a dedicated registered worktree;
  - an assigned feature branch;
  - explicit implementation authority;
  - a run-scoped isolated `--profile`;
  - session UUID capture from the typed stream;
  - separately granted push authority when push is required.
- The worker may edit, test, commit, and—only when separately authorized—push its assigned feature branch.
- The host retains planning, canonical run memory, protected refs, PR operations, final review, readiness, and merge authority.

---

## 2. Batch plan B0+

### Batch 0 [B0]: Optional bounded shortcut

**Phase:** Optional Phase 0; independently skippable.

**Intent:** Add a convenience route for one bounded OMP task without staging a trusted full run.

**Owned surfaces:**

- `scripts/run_omp.sh`
- Claude `/omp` alias
- provider-shortcut documentation
- shortcut isolation, timeout, and installation tests

**Forbidden surfaces:**

- trusted full-run state
- worker-routing defaults
- main-driver and prewalk policy
- implicit repository write authority
- PR, merge, tag, release, or protected-ref authority

**Acceptance criteria:**

- [ ] B0-A1: `/omp <instructions>` on Claude Code and `$elves omp <instructions>` or equivalent natural language on Codex/Grok resolve `run_omp.sh` from the active installed Elves skill root.
- [ ] B0-A2: The command is always `omp`; `opm` is neither accepted nor documented.
- [ ] B0-A3: The shortcut uses a policy-admitted disposable snapshot, a finite hard wall limit, closed stdin, and a run-scoped profile.
- [ ] B0-A4: Read-only behavior is the default. Any write form requires independent user implementation authority and the existing qualified writable-snapshot boundary.
- [ ] B0-A5: No host `HOME`, agent configuration, Git credentials, PR authority, or merge authority is inherited.
- [ ] B0-A6: Missing executable or auth, malformed NDJSON, timeout, incomplete terminal output, and cleanup failure return clear nonzero failures without affecting native routes.
- [ ] B0-A7: An unmarked user-owned Claude alias is reported as a conflict before any installed skill files are changed.

**Risk:** Standard—shortcut intent could otherwise be confused with trusted implementation authority.

**Focused tests:**

- `tests/test_provider_shortcuts.py`
- `tests/test_sync_installed_skills.py`
- `tests/test_installed_bundle_smoke.py`

**Depends on:** None.

---

### Batch 1 [B1]: Canonical adapter and transport contract

**Phase:** Phase 1 foundation.

**Intent:** Register `omp-cli` and define its strict machine-facing argv and NDJSON contracts without requiring live provider calls in tests.

**Owned surfaces:**

- adapter registry
- reserved control flags
- create/resume builders
- strict NDJSON transport decoder
- capability metadata
- redacted fixtures

**Forbidden surfaces:**

- full-run process lifecycle
- automatic route selection
- host-profile/prewalk registration
- main-driver policy
- behavioral changes to existing adapters

**Acceptance criteria:**

- [ ] B1-A1: `omp-cli` is a canonical built-in adapter with persistent-session and isolated-write capabilities; it never silently degrades to `custom-cli`.
- [ ] B1-A2: Its canonical contract pair is `("none", "omp-jsonl")`: the complete packet is passed as a positional argv token after `--print`, not misrepresented as a prompt file or stdin transport.
- [ ] B1-A3: `omp-jsonl` is a supported output contract with one strict decoder selected by `default_decoder_for_adapter`.
- [ ] B1-A4: Create argv contains `--mode json`, exact worktree `--cwd`, requested model, thinking level, approval mode, isolated `--profile`, `--print`, and the complete redacted packet.
- [ ] B1-A5: Resume argv contains `--resume <exact-uuid>` and never contains `--continue`, `-c`, bare `--resume`, latest/current selectors, or OMP `--prewalk`.
- [ ] B1-A6: Profile `extra_args` cannot override `--mode`, `--cwd`, `--model`, `--thinking`, `--approval-mode`, `--profile`, `--print`, `--resume`, or session-selection controls.
- [ ] B1-A7: The decoder binds session identity, model, usage, messages, and terminal state only from documented typed events.
- [ ] B1-A8: Empty output, malformed rows, malformed or conflicting UUIDs, conflicting model evidence, invalid usage, missing output, missing terminal state, and size-limit violations fail with stable validation codes.
- [ ] B1-A9: Existing Claude, Grok, Codex, Gemini, Antigravity, OpenCode, Devin, custom, and host-native registry and argv tests remain unchanged.

**Risk:** High—a permissive parser could allow model-authored text to forge transport identity or resume the wrong session.

**Focused tests:**

- `tests/test_worker_cli_lifecycle.py`
- `tests/test_installed_bundle_smoke.py`
- new fixtures under `tests/fixtures/omp/`

**Depends on:** None.

---

### Batch 2 [B2]: Trusted parked full-run lifecycle

**Phase:** Phase 1 core.

**Intent:** Run OMP through the existing host-owned prepare, launch, monitor, await, logs, stop, resume, and reconcile lifecycle.

**Owned surfaces:**

- OMP implementation argv construction
- full-run state and adapter dispatch
- streamed session capture
- monitor and terminal normalization
- authenticated interruption/resume handling
- CLI flags for trusted OMP launch

**Forbidden surfaces:**

- an OMP-specific parallel supervisor
- latest-session discovery
- worker mutation of canonical Elves memory
- worker PR/merge/tag authority
- reopening completed or blocked sessions
- automatic worker selection

**Acceptance criteria:**

- [ ] B2-A1: `full-run-prepare --adapter omp-cli` validates the staged packet, acceptance mapping, worktree, branch, protected refs, executable, requested model, thinking level, approval mode, and run profile before launch.
- [ ] B2-A2: `full-run-launch`, `monitor`, `await`, `logs`, `stop`, and `reconcile` return the existing provider-neutral result shapes.
- [ ] B2-A3: Create starts without a provider session ID. The first authoritative `session` event supplies the canonical UUID, which is persisted as `provider_session_id` before resume is permitted.
- [ ] B2-A4: No listing, “current,” latest-session, or report-text fallback is used when the session event is missing.
- [ ] B2-A5: Repeated identical session events are idempotent; zero session identities or conflicting identities block the run.
- [ ] B2-A6: Resume requires the captured UUID, same worktree, same run profile, an authenticated prior host interruption, a closed prior process identity, unchanged packet/acceptance bindings, and a nonterminal event log.
- [ ] B2-A7: Resume argv is inspected before spawn and must contain the exact `--resume <provider_session_id>` pair.
- [ ] B2-A8: EOF or process exit zero without `agent_end` is incomplete rather than successful.
- [ ] B2-A9: Nonzero exit, malformed terminal data, session/model conflict, unsafe branch movement, protected-ref movement, or missing identity produces a bounded blocked/interrupted result.
- [ ] B2-A10: A healthy run may make meaningful commits on the assigned feature branch and wakes the parked driver only on terminal, safety, checkpoint, blocker, or explicit-stop conditions.
- [ ] B2-A11: Reconciliation derives transport/session/model/usage evidence from the host decoder rather than worker report prose; worker `merge_authority` remains false.
- [ ] B2-A12: Existing Grok and Devin full-run fixtures remain green without semantic changes.

**Risk:** High—session capture, process settlement, terminal recognition, and authenticated recovery directly affect readiness.

**Focused tests:**

- `tests/test_cobbler_agents_implement.py`
- `tests/test_full_run_supervisor.py`
- `tests/test_follow_mode.py`
- `tests/test_usage_ledger.py`
- `tests/test_storage_isolation_git.py`
- `tests/test_worker_cli_lifecycle.py`

**Depends on:** B1.

---

### Batch 3 [B3]: Authentication, profile isolation, capability inventory, and routing

**Phase:** Phase 1 safety closeout.

**Intent:** Report OMP capabilities honestly and provide only the exact credentials and configuration required by a selected provider.

**Owned surfaces:**

- doctor/setup/onboard inventory
- named provider credential grants
- isolated HOME/XDG/profile setup
- optional worker-route eligibility
- native fallback behavior

**Forbidden surfaces:**

- whole-environment copying
- host `HOME` exposure
- shared default OMP profile
- writable `~/.claude/tools` projection
- implicit provider or GitHub grants
- making OMP mandatory or automatically preferred

**Acceptance criteria:**

- [ ] B3-A1: Doctor/setup/onboard separately report executable presence, version, authentication, exact-resume support, NDJSON support, isolated-write support, usage reporting, and qualification.
- [ ] B3-A2: Inventory never invents remaining quota, authentication success, model availability, or qualification.
- [ ] B3-A3: Provider authentication is granted only through the exact selected and allowlisted environment variable or a separately qualified exact source projection.
- [ ] B3-A4: Credentials for unselected providers are absent even if present in the host environment.
- [ ] B3-A5: Every launch receives a private run HOME/XDG tree and a run-scoped `--profile`; the same profile identity is retained across exact resume.
- [ ] B3-A6: Host `~/.claude/tools` is never copied, mounted wholesale, or exposed writable. A tool-name collision fails before launch or is handled using a run-owned exact tool installation.
- [ ] B3-A7: Other agent configuration roots, SSH material, private keys, global Git configuration, and credential stores remain unavailable.
- [ ] B3-A8: OMP provider auth does not imply GitHub push auth. Push remains a separate explicit host grant.
- [ ] B3-A9: Explicit `omp-cli` selection may proceed only when capability and authority checks pass; otherwise routing records an honest native fallback.
- [ ] B3-A10: Existing Grok consent, Devin behavior, and host-native route selection remain unchanged.

**Risk:** High—multi-provider auth and shared configuration paths can silently broaden authority.

**Focused tests:**

- `tests/test_cobbler_agents_setup.py`
- `tests/test_cobbler_agents_onboard.py`
- `tests/test_dispatch_isolation.py`
- `tests/test_adaptive_worker_routing.py`
- `tests/test_cobbler_native_only_fallback.py`
- `tests/test_full_run_supervisor.py`

**Depends on:** B1 and B2.

---

### Batch 4 [B4]: Documentation, installation, and Phase 1 regression gate

**Intent:** Publish an accurate first-class worker contract and prove that installed Elves bundles contain the required runtime.

**Owned surfaces:**

- canonical worker reference
- SKILL/AGENTS pointers
- host-parity and schema documentation
- survival-guide work-driver vocabulary
- installed bundle shipment and smoke tests
- Unreleased changelog

**Forbidden surfaces:**

- claiming OMP main-driver support
- claiming Elves prewalk support
- inventing model defaults
- requiring OMP for native runs
- release, tag, merge, or global-install mutation

**Acceptance criteria:**

- [ ] B4-A1: Documentation presents OMP as an optional trusted worker and retains Claude Code, Codex, and Grok Build as the supported main drivers.
- [ ] B4-A2: Documentation explicitly distinguishes OMP `--prewalk` from Elves exact-session prewalk.
- [ ] B4-A3: Create, session capture, follow, interruption, exact resume, profile isolation, auth grants, and host reconciliation have copy-paste examples.
- [ ] B4-A4: The existing recursive `cobbler_runtime` shipment includes all new runtime code without introducing a new per-module copy list.
- [ ] B4-A5: Existing Claude, Codex, and Grok skill roots receive the OMP worker runtime and reference; Phase 1 does not invent an OMP main-driver install root.
- [ ] B4-A6: Installed-bundle smoke proves `omp-cli` retains its registry identity and that native operation does not require an installed `omp`.
- [ ] B4-A7: If B0 is included, Claude’s managed alias inventory changes atomically from eleven to twelve while Codex and Grok continue to receive no Claude aliases.
- [ ] B4-A8: Repository consistency checks reject `opm` when used as an Oh My Pi executable, adapter, profile, alias, or command.
- [ ] B4-A9: Focused tests and the applicable repository verifier pass without weakening or skipping tests.

**Risk:** Standard—documentation or installation drift could overstate support or authority.

**Focused tests:**

- `tests/test_sync_installed_skills.py`
- `tests/test_installed_bundle_smoke.py`
- `tests/test_check_repo_consistency.py`
- focused B1–B3 suites

**Depends on:** B2 and B3.

---

### Batch 5 [B5]: Deferred host profile and Elves prewalk

**Phase:** Phase 2; not part of the MVP implementation run.

**Intent:** Add OMP to the provider-neutral host-profile table only after a version-bound behavioral qualification proves one continuous guide-to-execution session.

**Owned surfaces:**

- host-profile launch grammar
- native-worker capability qualification
- two-phase prewalk supervisor
- guide/execution model and thinking transitions

**Forbidden surfaces:**

- OMP `--prewalk`
- help-text-only qualification
- cold fallback after edits
- main-driver support
- relaxed session/worktree/profile checks

**Acceptance criteria:**

- [ ] B5-A1: Qualification proves create, stream-derived UUID capture, exact resume, same worktree, same isolated profile, one logical stream, retained guide context, and route change.
- [ ] B5-A2: The host-profile row defines identity events, provider-secret allowlist, worktree binding, usage source, commit mode, executable probes, and launch readiness.
- [ ] B5-A3: `required` prewalk fails before the task launch when evidence is absent, malformed, version-mismatched, or stale.
- [ ] B5-A4: `experimental` retains exact-session, worktree, packet, profile, process, and authority checks.
- [ ] B5-A5: OMP `--prewalk` never appears in Elves prewalk argv or documentation.
- [ ] B5-A6: Compaction de-qualification and post-edit cold-fallback rules remain identical across transports.

**Risk:** High—prewalk is a trajectory guarantee, not a richer cold handoff.

**Focused tests:**

- `tests/test_host_profiles.py`
- `tests/test_native_worker_prewalk.py`
- `tests/test_native_worker_hardening.py`
- `tests/test_adaptive_worker_routing.py`

**Depends on:** Completed Phase 1 and version-bound behavioral qualification.

---

### Batch 6 [B6]: Deferred main-driver policy and managed installation

**Phase:** Phase 3; separately approved.

**Intent:** Consider OMP as a supported main driver only after it demonstrates host-grade staging, canonical memory, continuation, skill loading, final gates, and landing behavior.

**Owned surfaces:**

- supported-host policy
- verified OMP skill discovery and installation
- host-parity contracts
- installer target and smoke coverage

**Forbidden surfaces:**

- guessing an OMP skill path
- deriving main-driver status from worker success
- self-granted merge/protected-ref authority
- regressions to existing host installs

**Acceptance criteria:**

- [ ] B6-A1: A separate policy decision explicitly adds OMP to the supported-main-driver list.
- [ ] B6-A2: The official OMP skill discovery/install path is behaviorally verified; no `~/.omp/skills` or equivalent path is guessed.
- [ ] B6-A3: A new installation target is added only after marker policy, first-install behavior, updates, conflicts, and cleanup are specified and tested.
- [ ] B6-A4: Host parity covers invocation, helper resolution, canonical memory, stop control, prewalk, review, readiness, and landing authority.
- [ ] B6-A5: OMP remains unable to grant itself merge, release, posting, secret, or protected-ref authority.
- [ ] B6-A6: Claude, Codex, and Grok installation and alias behavior remain unchanged.

**Risk:** Critical—this is a workflow and authority-policy expansion.

**Focused tests:**

- `tests/test_sync_installed_skills.py`
- `tests/test_installed_bundle_smoke.py`
- `tests/test_host_profiles.py`
- `tests/test_architecture_evidence.py`
- host-parity consistency checks

**Depends on:** B5 and sustained Phase 1 operational evidence.

## Master Acceptance

- [ ] M-A1: A supported Elves host can stage one acceptance-bound packet and run OMP as an optional trusted parked implementation worker.
- [ ] M-A2: The host captures one exact OMP UUID from typed NDJSON and uses only `--resume <uuid>` for recovery.
- [ ] M-A3: Successful completion requires `agent_end`, process exit zero, valid identity/model evidence, and clean host safety checks.
- [ ] M-A4: Provider credentials, OMP profile state, worktree authority, GitHub push authority, and merge authority remain separate.
- [ ] M-A5: Missing OMP capability falls back honestly to native work and never makes OMP mandatory.
- [ ] M-A6: Existing Grok, Devin, and host-native behavior remains green.
- [ ] M-A7: User-facing documentation and installed bundles describe the supported Phase 1 route without implying Phase 2 or Phase 3 support.

---

## 3. Exact file touch list

### Required Phase 1 runtime and CLI

| File | Planned change |
|---|---|
| `scripts/cobbler_runtime/schema.py` | Add `omp-cli` to the canonical built-in adapter names. |
| `scripts/cobbler_runtime/adapters.py` | Add registry metadata, reserved flags, `("none", "omp-jsonl")` contract, default profile/decoder, strict NDJSON decoder, and exact create/resume builders. |
| `scripts/cobbler_runtime/capabilities.py` | Add OMP capability inventory with advertised/unknown/qualified distinctions. |
| `scripts/cobbler_runtime/implement.py` | Add OMP model, thinking, approval-mode normalization and direct argv construction. |
| `scripts/cobbler_runtime/full_run.py` | Add OMP adapter dispatch, stream-derived `provider_session_id`, create/resume validation, monitor normalization, and reconciliation support. |
| `scripts/cobbler_runtime/provider_auth.py` | Add exact named-provider grants and optional future source-projection validation without storing raw credentials. |
| `scripts/cobbler_runtime/isolation.py` | Build the private run HOME/XDG/profile environment and deny shared agent configuration/tool roots. |
| `scripts/cobbler_runtime/setup.py` | Add the `omp-cli` profile recipe, executable inventory, and operator guidance. |
| `scripts/cobbler_runtime/onboard.py` | Report OMP availability and capabilities without a required paid call. |
| `scripts/cobbler_runtime/worker_routing.py` | Add explicit optional OMP eligibility and honest native fallback; do not change native defaults. |
| `scripts/cobbler_agents.py` | Accept `omp-cli` on implement/full-run commands and add OMP auth/profile/thinking controls. |

No Phase 1 change is required in `host_profiles.py`, `native_worker.py`, or `prewalk.py`; those belong to B5.

### Required Phase 1 tests and fixtures

New fixtures:

- `tests/fixtures/omp/create-success.jsonl`
- `tests/fixtures/omp/resume-success.jsonl`
- `tests/fixtures/omp/malformed.jsonl`
- `tests/fixtures/omp/conflicting-session.jsonl`
- `tests/fixtures/omp/conflicting-model.jsonl`
- `tests/fixtures/omp/missing-agent-end.jsonl`
- `tests/fixtures/omp/invalid-usage.jsonl`
- `tests/fixtures/omp/terminal-replay-conflict.jsonl`

Tests to update:

- `tests/test_worker_cli_lifecycle.py`
- `tests/test_cobbler_agents_implement.py`
- `tests/test_full_run_supervisor.py`
- `tests/test_follow_mode.py`
- `tests/test_usage_ledger.py`
- `tests/test_dispatch_isolation.py`
- `tests/test_cobbler_agents_setup.py`
- `tests/test_cobbler_agents_onboard.py`
- `tests/test_adaptive_worker_routing.py`
- `tests/test_cobbler_native_only_fallback.py`
- `tests/test_storage_isolation_git.py`
- `tests/test_installed_bundle_smoke.py`
- `tests/test_sync_installed_skills.py`
- `tests/test_check_repo_consistency.py`

### Required Phase 1 references and canonical guidance

New:

- `references/oh-my-pi-worker.md`

Update:

- `references/adaptive-worker-routing.md`
- `references/host-parity.md`
- `references/runtime-helper-paths.md`
- `references/survival-guide-template.md`
- `references/schema-and-acceptance.md`
- `SKILL.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `scripts/sync_installed_skills.py`
- `scripts/installed_bundle_smoke.py`
- `scripts/check_repo_consistency.py`

### Optional B0 shortcut surfaces

- `scripts/run_omp.sh`
- `aliases/claude/omp/SKILL.md`
- `references/provider-shortcuts.md`
- `scripts/sync_installed_skills.py`
- `scripts/installed_bundle_smoke.py`
- `tests/test_provider_shortcuts.py`
- `tests/test_sync_installed_skills.py`
- `tests/test_installed_bundle_smoke.py`

If B0 is included, update the alias inventory together in:

1. `scripts/sync_installed_skills.py` — `CLAUDE_ALIAS_NAMES`
2. `scripts/installed_bundle_smoke.py` — `EXPECTED_CLAUDE_ALIASES` and eleven-to-twelve diagnostics
3. corresponding exact-count tests

Codex and Grok installs must continue to contain no Claude alias tree.

### Deferred B5 surfaces

- `scripts/cobbler_runtime/host_profiles.py`
- `scripts/cobbler_runtime/native_worker.py`
- `scripts/cobbler_runtime/prewalk.py`
- `scripts/cobbler_runtime/worker_routing.py`
- `tests/test_host_profiles.py`
- `tests/test_native_worker_prewalk.py`
- `tests/test_native_worker_hardening.py`
- `references/prewalk.md`
- `references/host-parity.md`

### Deferred B6 surfaces

- `SKILL.md`
- `AGENTS.md`
- `scripts/sync_installed_skills.py`
- `scripts/installed_bundle_smoke.py`
- `tests/test_sync_installed_skills.py`
- `tests/test_installed_bundle_smoke.py`
- `references/host-parity.md`
- `references/runtime-helper-paths.md`

No new main-driver install target belongs in the Phase 1 diff.

---

## 4. Launch argv create/resume for trusted full-run

### Create argv

Use a direct token vector, never a shell-constructed command:

```python
[
    "omp",
    "--mode", "json",
    "--cwd", registered_worktree,
    "--model", requested_model,
    "--thinking", thinking_level,
    "--approval-mode", "yolo",
    "--profile", run_profile,
    "--print",
    packet_text,
]
```

Requirements:

- `registered_worktree` is absolute, canonical, and equal to the supervisor’s OS working directory.
- `requested_model` is explicit or provider-authoritative; Elves does not invent a prestige default.
- `thinking_level` is validated against the supported OMP vocabulary.
- `yolo` is allowed only on the explicitly trusted full-run path after worktree, branch, protected-ref, packet, and authority checks pass.
- `run_profile` is random and run-scoped.
- `packet_text` is complete, non-empty, size-bounded, redacted, and acceptance-bound.
- Create contains no `--resume` and no caller-generated OMP session ID.
- Create never contains `--continue`, `-c`, or `--prewalk`.

For a read-only probe or B0 shortcut, use `--approval-mode always-ask`, closed stdin, and a finite timeout. Any attempted interactive approval must fail rather than hang. `write` may be offered only as an explicit bounded posture, never as a silent replacement.

### Session capture

OMP has no `--session-id`. During create:

1. Start with `provider_session_id = null`.
2. Parse NDJSON incrementally.
3. Accept identity only from the first valid typed `session` event.
4. Validate the event ID as a canonical exact UUID.
5. Persist it atomically in private full-run state.
6. Bind it to:
   - run and attempt;
   - worktree;
   - run profile;
   - process identity;
   - event-log offset and digest.
7. Treat repeated identical identity events as idempotent.
8. Block on missing or conflicting identity.

There is no session-listing, current-session, latest-session, or report-text fallback.

### Resume argv

```python
[
    "omp",
    "--mode", "json",
    "--cwd", registered_worktree,
    "--model", requested_model,
    "--thinking", thinking_level,
    "--approval-mode", "yolo",
    "--profile", original_run_profile,
    "--resume", provider_session_id,
    "--print",
    resume_instruction,
]
```

Resume fails before spawn when:

- no transport-derived UUID is recorded;
- the ID is empty, noncanonical, dash-leading, or an ambiguous selector;
- worktree or run profile changed;
- the previous process is live or unverifiable;
- the previous interruption was not authenticated as host-owned;
- packet or acceptance bindings changed;
- the branch or protected refs moved unexpectedly;
- the event log is already terminal;
- argv does not contain the exact recorded UUID.

`--continue`, `-c`, latest/current discovery, cross-worktree selection, and fallback to a different session are always forbidden.

---

## 5. JSON transport decoder

Add the canonical **`omp-jsonl`** output contract.

The first committed redacted fixture must freeze the exact current key spelling and nesting. The decoder then accepts that schema, rather than accumulating speculative aliases.

### Event and key contract

| Event type | Authoritative keys | Handling |
|---|---|---|
| `session` | `id`; optional `model` | `id` is the sole create-time session identity source. Validate as a canonical UUID. |
| `turn` | optional `model`; optional `usage` | Supplies typed transport model and turn-level observed usage. |
| `message` | `message.role`, `message.content`; optional `message.model`, `message.usage` | Supplies agent output and typed usage. Message content never supplies transport authority. |
| `agent_end` | terminal message/result collection; optional `model`, `usage` | Sole successful terminal event, subject to process and safety checks. |

### Session identity rules

- Exactly one canonical identity is required for success.
- Identical repeated identity is idempotent.
- Conflicting identity blocks immediately.
- A UUID in message text, report JSON, stderr, or an unknown event is ignored as identity.
- No resume state is produced until identity is durably stored.

### Model rules

- Record model only from typed event fields.
- Repeated identical model evidence is idempotent.
- Conflicting non-empty model evidence blocks reconciliation.
- When `--model` was explicitly requested, authoritative actual-model evidence must be present and must match.
- Model names inside agent messages or reports are not evidence.

### Usage rules

- Preserve provider-emitted nonnegative numeric usage keys.
- Do not estimate missing usage.
- Missing usage means `unobserved`, never zero.
- Sum usage only after replay de-duplication.
- Reject booleans, strings, negative values, invalid nesting, and non-finite values.
- Usage remains advisory and cannot affect landing or merge authority.

### Terminal rules

Successful transport requires all of:

1. valid captured session UUID;
2. exactly one accepted `agent_end`;
3. no identity or model conflict;
4. process exit zero;
5. no host safety blocker;
6. valid host-derived reconciliation.

The following are not success:

- EOF alone;
- exit zero without `agent_end`;
- a final `message`;
- usage-only output;
- worker text claiming completion;
- an unknown event;
- a second distinct terminal event.

### Ordering and replay de-duplication

- Preserve provider event order.
- Assign a host sequence number.
- Retain attempt number, byte offset, and line digest.
- De-duplicate only an identical attempt/offset/digest record.
- Do not content-deduplicate legitimate repeated messages.
- Buffer a partial final line until completed.
- Incomplete JSON at EOF is malformed output.
- Terminal output followed by new non-replay provider output blocks the run.
- Enforce bounded line size, event count, and total stream size.
- Unknown typed events may be retained as sanitized diagnostics but cannot bind identity, model, usage, or terminal state.

### Stable error paths

Cover at minimum:

- empty or whitespace-only stream;
- malformed UTF-8;
- malformed JSON;
- non-object row;
- missing or non-string `type`;
- missing session `id`;
- malformed UUID;
- conflicting UUID;
- missing or conflicting model evidence;
- invalid usage;
- no agent output;
- no `agent_end`;
- multiple distinct terminal events;
- output after terminal;
- oversized line, event count, or stream;
- terminal replay inconsistency.

---

## 6. Auth/isolation grants matrix

| Surface | Phase 1 policy | Required behavior |
|---|---|---|
| Selected provider API key | Explicit named grant only | Project only the exact key required by the selected provider. |
| Unselected provider keys | Denied | Do not expose all supported provider credentials merely because OMP is multi-provider. |
| Stored OMP/provider auth | Disabled by default | Future support requires an exact owner-private, non-link, bounded source projection with identity revalidation. |
| OMP profile | Required run-scoped isolation | Launch with `--profile <run-profile>` and preserve it across resume. |
| Host `HOME` | Denied | Supply a private run HOME/XDG tree containing only staged configuration. |
| `~/.claude/tools` | Denied | Never mount, copy wholesale, or expose it writable; OMP and Claude tooling may collide there. |
| Other agent configuration roots | Denied | No host `.claude`, `.codex`, `.grok`, `.gemini`, `.agent`, or equivalent projection. |
| Registered worktree | Read/write | Exact dedicated worktree only; bind both OS cwd and `--cwd`. |
| Assigned feature branch | Commit allowed | Worker may commit only on its assigned branch. |
| GitHub push auth | Separate explicit grant | Provider auth never implies push authority. |
| `.elves-session.json` and canonical run docs | Host-owned | Worker receives acceptance context but does not mutate canonical memory. |
| SSH agent/private keys/global Git config | Denied | Use only existing separately qualified local/file-remote behavior. |
| PR, merge, tag, release, protected refs | Denied | Approval mode does not grant these authorities. |
| Network | Provider-required only | Network access grants no posting, connector, secret, or merge authority. |
| OMP `--prewalk` | Forbidden | It is neither isolation nor Elves exact-session prewalk. |

Additional rules:

- Derive the profile name from a random run identifier, not repository, branch, or user path text.
- Persist only a normalized profile identifier or digest, never credentials.
- Record credential names and keyed digests for redaction/audit, not raw credential values.
- Revalidate profile, worktree, executable, and credential-source identities before each resume.

---

## 7. Non-goals and regression guards

### Non-goals

- Do not require OMP for native runs.
- Do not make OMP the automatic default worker.
- Do not support OMP as a main driver in Phase 1.
- Do not infer main-driver readiness from worker success.
- Do not pass or reinterpret OMP `--prewalk`.
- Do not add latest/current/continue session recovery.
- Do not trust report or message text for identity, model, usage, completion, or authority.
- Do not expose host HOME, credential stores, agent configuration, or `~/.claude/tools`.
- Do not create a second full-run supervisor or generic remote-agent framework.
- Do not require live paid calls in ordinary unit tests.
- Do not invent a model default when provider configuration is authoritative.
- Do not grant worker PR, merge, tag, release, posting, or protected-ref authority.
- Do not add an `opm` compatibility spelling.

### Grok regression guards

- Preserve caller-assigned UUID creation.
- Preserve authenticated live-catalog model selection.
- Preserve API-key and qualified shared-OAuth behavior.
- Preserve goal-mode qualification and one-packet fallback.
- Preserve Grok streaming decoding and redaction.
- Preserve the distinction between trusted full-run and Grok prewalk.

### Devin regression guards

- Preserve list/ATIF session discovery.
- Preserve exact `--resume <id>` and the prohibition on `--continue`.
- Preserve Devin auth/config projection.
- Preserve SWE-1.7 Lightning default behavior.
- Preserve existing terminal and reconciliation semantics.

### Host-native regression guards

- Missing OMP executable or auth selects an honest native fallback rather than a blocker.
- Native route identity and effort selection remain unchanged.
- No OMP profile, credential, executable, or decoder becomes a native staging requirement.
- Native exact-session prewalk remains provider-neutral.
- Host-native runs require no external provider credentials.

### Installation and alias guards

- Claude receives exactly the managed Claude aliases.
- Codex and Grok receive no Claude aliases.
- Source-only plan archives remain absent from installed bundles.
- The recursive `cobbler_runtime` package and required top-level helpers continue to ship.
- Installed documentation contains no dependency on repository-only helpers.
- Adding B0 updates all exact alias inventories and counts atomically.

---

## 8. Staging checklist

### Branch and worktree

1. Persist this plan at `docs/plans/omp-first-class-harness.md`.
2. Create `feat/omp-first-class-harness` from the verified default-branch tip.
3. Use a dedicated worktree and record its canonical absolute path.
4. Record `START_TIP` as the collision tripwire.
5. Implement with a host-native worker; do not dogfood OMP while building its authority and recovery path.
6. Keep B5 and B6 outside the implementation worker’s scope.

Suggested commands:

```bash
git fetch origin
./scripts/preflight.sh \
  --create-worktree feat/omp-first-class-harness \
  --base origin/main \
  --dry-run

./scripts/preflight.sh \
  --create-worktree feat/omp-first-class-harness \
  --base origin/main
```

### Run-document paths

```text
Plan:             docs/plans/omp-first-class-harness.md
Session:          .elves-session.json
Survival guide:   docs/elves/survival-guide-omp-first-class-harness.md
Execution log:    docs/elves/execution-log-omp-first-class-harness.md
Worker packet:    docs/elves/worker-packet-omp-first-class-harness.md
```

### Before implementation launch

- Parse all `B#-A#` and `M-A#` criteria.
- Synchronize exact criterion text into session and worker packet.
- Record worker-owned and forbidden surfaces.
- Record B0 as included or skipped.
- Record B5 and B6 as deferred.
- Capture:
  - branch;
  - worktree;
  - default branch;
  - `START_TIP`;
  - origin identity;
  - protected refs;
  - packet and plan digests.
- Run focused baselines for adapters, full-run, routing, setup, installation, and aliases.
- Confirm tests do not require an installed `omp`.
- Confirm implementation authority but no merge authority.
- Confirm user-owned merge policy.
- Validate staging:

```bash
git remote get-url origin
git push --dry-run 2>&1 | head -3
gh auth status 2>&1 | head -3

python3 "$ELVES_SKILL_ROOT/scripts/acceptance_contract.py" validate \
  --repo-root . \
  --session .elves-session.json
```

### Implementation order

1. B1: adapter and decoder.
2. B2: full-run lifecycle.
3. B3: authentication, isolation, inventory, routing.
4. B4: documentation, installation, regression closeout.
5. B0 only if explicitly included as a separate slice.
6. Do not begin B5 or B6.

### Terminal verification

- All focused B1–B4 tests pass.
- Existing Grok and Devin full-run tests pass.
- Host-native fallback tests pass without OMP.
- Installed-bundle and alias tests pass.
- Consistency checks reject accidental `opm` spellings.
- Terminal project verification appropriate to touched surfaces passes.
- One cumulative review covers:
  - session provenance;
  - exact resume;
  - profile isolation;
  - terminal semantics;
  - replay de-duplication;
  - credential projection;
  - protected refs;
  - fallback behavior;
  - documentation truthfulness.
- Produce a landable PR.
- Do not merge without separate user authorization.

## Staging Run Control block

```markdown
## Run Control

- **Run mode:** finite
- **Plan:** `docs/plans/omp-first-class-harness.md`
- **Branch:** `feat/omp-first-class-harness`
- **Worktree path:** `<absolute dedicated worktree path recorded by preflight>`
- **Default branch / base:** `origin/main`
- **Branch tip at start (collision tripwire):** `<START_TIP recorded at staging>`
- **Session:** `.elves-session.json`
- **Survival guide:** `docs/elves/survival-guide-omp-first-class-harness.md`
- **Execution log:** `docs/elves/execution-log-omp-first-class-harness.md`
- **Worker packet:** `docs/elves/worker-packet-omp-first-class-harness.md`
- **Work driver:** host-native
- **Delegation scope:** full_run
- **Implementation lane:** fast
- **Worker prewalk:** off
- **Included batches:** B1, B2, B3, B4
- **Optional batch B0:** skipped unless explicitly enabled before implementation
- **Deferred / out of scope:** B5 (Phase 2 host-profile/prewalk); B6 (Phase 3 main-driver/install policy)
- **Worker owned surfaces:** the exact Phase 1 runtime, CLI, test, fixture, reference, SKILL/AGENTS, installation, and regression files listed in the plan
- **Worker forbidden surfaces:** default branch, protected refs, PR/merge/tag/release operations, host credentials and configuration roots, `~/.claude/tools`, external systems, B5, B6, and unrelated product changes
- **Acceptance identity:** batch criteria use `B#-A#`; Master Acceptance uses `M-A#`
- **Follow mode:** default sanitized stream on full-run-await
- **Re-drive budget:** 1 substantive worker re-drive; transient provider failures retry the same attempt with bounded backoff
- **GitHub push auth route:** host-owned explicit projection only; never implied by provider auth
- **Worker merge authority:** false
- **Driver merge authorized:** no
- **Merge policy:** user-merges (default — never merge)
- **Landing outcome:** landable_pr
- **Non-Negotiables:**
  1. The executable and product spelling is `omp`; never accept or document `opm`.
  2. Phase 1 adds an optional parked full-run worker, not a main driver or automatic default.
  3. Session identity comes only from the typed OMP NDJSON stream.
  4. Resume always uses `--resume <exact-uuid>`.
  5. `--continue`, `-c`, latest/current session selection, and OMP `--prewalk` are forbidden.
  6. Every launch uses an isolated run-scoped `--profile`.
  7. Host `HOME`, agent configuration roots, credential stores, and `~/.claude/tools` are denied.
  8. OMP/provider authentication never grants GitHub push, PR, protected-ref, release, or merge authority.
  9. Existing Grok, Devin, and host-native behavior must remain green.
  10. Do not weaken, skip, or delete tests to obtain green.
- **Stop Gate — Stop allowed right now:** no, until B1–B4 and Master Acceptance are proven at the exact branch tip or a genuine hard blocker is recorded
```
