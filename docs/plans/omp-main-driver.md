# Plan: Oh My Pi (omp) as a supported main driver

> **Status:** plan revised after Fugu Ultra design review (2026-08-09).  
> Fugu log: `docs/elves/fugu-omp-main-driver-plan-review.log`  
> Fugu verdict: **needs changes incorporated before B1–B5** (done below); **B0 may start now**.  
> Do not write installer code, claim public main-driver support, or cut 2.26.0 until B0 freezes paths
> and ordinary launch is proven.

> Builds on Phase 1 (`docs/plans/omp-first-class-harness.md`, shipped **v2.25.0**): optional parked
> `omp-cli` worker + `/omp` shortcut. That work is **not** main-driver support.

---

## Mission

Make **Oh My Pi (`omp`)** a fourth **supported main driver** for Elves. A developer opens `omp`,
loads Elves from a **B0-proven** managed install root, and gets host-grade parity with Claude Code,
Codex, and Grok Build: stage, exact-session prewalk when qualified, separate native worker, parked
full-run follow, terminal review, landable PR. The **user** owns merge authorization; the host
preserves and enforces it and never originates it from model output, qualification evidence, or
skill load success.

**Done when:** docs list omp with the three existing main drivers; `sync --target omp` installs to
the frozen root and a fresh omp process loads Elves; host profile + ordinary launch + prewalk share
the same safety contract; Phase 1 worker/shortcut remain when Claude/Codex/Grok drive;
`launch_ready=True` only after ordinary single-phase launch proof (not prewalk-only).

---

## Context

| User goal | v2.25.0 Phase 1 | This plan |
|-----------|-----------------|-----------|
| Open omp, run Elves end-to-end | No | Yes |
| `host_profiles.py` + routing accept omp | No | B1 |
| Elves prewalk (not omp `--prewalk`) | No | B2 |
| Managed install `--target omp` | No | B3 (after B0 path freeze) |
| Park `omp-cli` under Claude/Codex/Grok | Yes | Keep |

**Candidate skill root (not frozen):** `~/.omp/agent/skills/elves` (oh-my-pi native
`~/.omp/agent/skills/`). Project `.omp/skills/` and Claude/Codex/`.agents` sources may shadow.
**B0 must freeze the root with an installed-binary load probe.** Fixtures alone cannot freeze a path.

**Authoritative launch path:** reconcile `references/omp-worker.md` examples with the real
Phase 1 adapter (`adapters.py` omp-cli builders: `--mode json`, `--append-system-prompt` bare
packet path, stream UUID, never `--continue`). Main-host design **reuses** that transport grammar
where possible; do not invent a second decoder.

---

## Dual-role model

```text
Role A — Main driver (this plan)
  Token: omp (never omp-cli as host)
  User opens: omp
  Skill: B0-frozen managed root
  Host: stages, supervises, reviews, prepares PR, enforces readiness
  User: owns merge authorization

Role B — Optional worker (v2.25.0)
  Adapter: omp-cli
  Launched by Claude / Codex / Grok
  Does not own plan / PR / merge
```

Interactive host session and separate native omp **worker** must not share: session id, default
profile, HOME/XDG, conversation state, or unrelated credentials.

---

## Scope

### In Scope

- B0 installed discovery + transport + isolation + prewalk canary evidence
- Host profile, worker_routing, cobbler_agents host recognition
- Ordinary native launch with run-scoped profile, single selected credential, packet transport
- Elves exact-session prewalk for omp
- Managed install target after path freeze
- Policy/docs (four main drivers), host parity, dual-role clarity
- Cumulative installed-host proof and release (**2.26.0** or next free minor)

### Out of Scope

- Making omp mandatory; replacing other hosts
- Model-originated merge / protected-ref / secret / PR authority
- omp product `--prewalk` as Elves prewalk
- Installer work before B0 path freeze
- Claiming main-driver parity while `launch_ready=False`
- Path `~/.omp/skills` without B0 proof
- Fugu / Sakana as a main driver

### Forbidden surfaces (repository-wide)

- Resolving `omp-cli` as a main host token
- Forwarding all ambient OMP-compatible provider keys
- Sharing interactive host omp profile with its worker
- Claiming discovery from fixtures alone
- Packet replay on execution resume; identity from assistant prose
- Committing raw canary transcripts or credentials
- Qualification evidence granting Git/PR/merge authority
- omp `--prewalk` in any Elves create/resume/prewalk argv, help, or examples

---

## Batches

### Batch 0 [B0]: Discovery and qualification evidence

**Intent:** Prove installed omp discovery and transport **before** any install or main-driver claim.

Split:

#### B0.1 Installed discovery and path freeze

- Executable path + exact version/build (bounded help/version capture)
- Native global skill root, project root, precedence, toggles
- Duplicate-name and shadowing (Claude/Codex/`.agents` vs native)
- Fresh omp process loads an **isolated probe skill** from the selected root
- Loaded skill resolves its own runtime helpers (no Claude install required)
- Freeze root into Appendix B; then fixtures may encode the observed contract for CI

#### B0.2 Transport, isolation, qualification

- Create/resume grammar; packet/prompt delivery; authoritative UUID + conflict rules
- Terminal `agent_end` / incomplete EOF; exact `--resume <uuid>` only
- Same worktree + same run-scoped profile; model/thinking override on resume
- Safe noninteractive approval; **exactly one** selected provider credential
- No ambient HOME/SSH/global Git/other-agent config
- Provider auth does not imply push/merge authority
- Two-turn prewalk canary: packet once, execution input exactly `Continue.`, `retained_safe`
- Stale/version/route mismatch fail-closed
- Explicit **initial** vs **release** `launch_ready` decisions

**Acceptance criteria:**

- [x] B0-A1: Installed version/build + create/resume help recorded (bounded).
- [x] B0-A2: **Installed-binary** load probe freezes skill root in Appendix B (not fixtures-only).
- [x] B0-A3: Transport + isolation items 9–20 in Fugu §5 proven or honestly failed with artifacts.
- [x] B0-A4: Prewalk canary items 21–26 proven or honest gaps; no help-text-only “ready.”
- [x] B0-A5: Appendix B filled; private raw evidence stays uncommitted.

**Risk:** Critical if skipped.  
**Forbidden:** installer code; SKILL main-driver list change.  
**Depends on:** main ≥ v2.25.0.

---

### Batch 1 [B1]: Host recognition and ordinary native launch

**Intent:** Register omp as a host and enable **ordinary single-phase** launch (prewalk-off and
unqualified auto fallback), not only a profile row.

**Owned surfaces (required, not optional):**

- `scripts/cobbler_runtime/host_profiles.py` (extend `HostLaunchRequest` for run-scoped profile /
  approval policy if the current request cannot express them)
- `scripts/cobbler_runtime/native_worker.py`
- `scripts/cobbler_runtime/worker_routing.py` (today rejects non-Claude/Codex/Grok hosts)
- `scripts/cobbler_agents.py` (prewalk-capabilities / host probes)
- Reuse: `adapters.py` omp transport, isolation/auth surfaces from Phase 1
- Tests: `test_host_profiles.py`, `test_adaptive_worker_routing.py`, extend omp adapter tests

**Acceptance criteria:**

- [x] B1-A1: Canonical host token `omp`; optional alias `oh-my-pi` only if B0 needs it; `omp-cli` rejected as host.
- [x] B1-A2: Identity is stream-derived UUID (not caller-only session-id unless B0 proves otherwise).
- [x] B1-A3: Launch argv: `--mode json`, model, thinking, cwd, run-scoped profile, approval policy, packet transport per authoritative Phase 1 adapter; never `--continue` / `-c`.
- [x] B1-A4: Exactly one selected provider credential; not a static full-key allowlist dump.
- [x] B1-A5: Routing and capability probes accept omp; other exotic hosts still rejected.
- [x] B1-A6: Successful prewalk-off launch and unqualified-auto fallback path.
- [x] B1-A7: `launch_ready=True` only after ordinary launch proof (dev may land False temporarily; release/B4 forbids claiming main-driver parity while False).

**Risk:** High.  
**Depends on:** B0.

---

### Batch 2 [B2]: Elves exact-session prewalk

**Owned surfaces:** `prewalk.py`, native_worker prewalk paths, `references/prewalk.md`,
`tests/test_native_worker_prewalk.py`, `tests/test_native_worker_hardening.py`.

**Acceptance criteria:**

- [x] B2-A1: Canary: create, stream UUID, exact resume, same worktree, same run-scoped profile, one logical stream, retained_safe, route change, packet once, resume input Continue. only, no packet replay.
- [x] B2-A2: `required` fails closed on missing/malformed/stale/version-mismatched evidence.
- [x] B2-A3: `experimental` keeps exact-session, worktree, packet, process, authority checks.
- [x] B2-A4: No omp product `--prewalk` in any Elves argv/docs/examples (negative tests).
- [x] B2-A5: Compaction de-qualification + post-edit cold-fallback rules match other hosts; pre-edit abandonment vs forbidden post-edit cold fallback distinguished.

**Risk:** Critical.  
**Depends on:** B1.

---

### Batch 3 [B3]: Managed install

**Depends on:** B0.1 path freeze (may parallel B1/B2 after freeze).

**Owned surfaces:** `sync_installed_skills.py`, `installed_bundle_smoke.py`, `install_doctor.py`,
`references/runtime-helper-paths.md`, sync/smoke tests.

**Acceptance criteria:**

- [x] B3-A1: `--target omp` installs to Appendix B frozen root (candidate until freeze: `~/.omp/agent/skills/elves`).
- [x] B3-A2: First install requires explicit target; `--target all` update-only.
- [x] B3-A3: Install/update/idempotent check/cleanup; symlink and source-archive protections; conflict policy for existing `elves` root; shadowing warnings/refusal.
- [x] B3-A4: Post-install fresh-process load probe (same class as B0).
- [x] B3-A5: No Claude alias tree under omp unless separately proven; Claude/Codex/Grok unchanged.
- [x] B3-A6: CLI choices, descriptions, recovery messages name omp.

**Risk:** High.

---

### Batch 4 [B4]: Host policy and docs

**Depends on:** **B1–B3 acceptance passed** (not “functional enough”).

**Owned surfaces:** SKILL, AGENTS, README, PRODUCT, guide, host-parity, prewalk, omp-worker,
CHANGELOG (**2.26.0** or next free minor), consistency/architecture wording tests.

**Acceptance criteria:**

- [x] B4-A1: Supported main drivers: Claude Code, Codex, Grok Build, **Oh My Pi (omp)**.
- [x] B4-A2: Host parity table includes omp; dual-role documented; never “omp-cli main driver.”
- [x] B4-A3: Guide detects executable and discovery, not mere `~/.omp` directory; documents `sync_installed_skills.py --apply --target omp`.
- [x] B4-A4: Host-check no longer treats omp as exotic.
- [x] B4-A5: Authority wording: user owns merge authorization; host enforces.
- [x] B4-A6: No main-driver claim if `launch_ready` still False.

---

### Batch 5 [B5]: Cumulative host-parity proof and release

**Depends on:** B1–B4.

**Acceptance criteria:**

- [x] B5-A1: Managed install + skill discovery
- [x] B5-A2: Host check accepts omp
- [x] B5-A3: Staging + canonical memory
- [x] B5-A4: Default separate native omp worker (not shared interactive profile)
- [x] B5-A5: Prewalk-off and required/qualified prewalk paths
- [x] B5-A6: Follow, status, stop, exact resume
- [x] B5-A7: Reconcile + terminal confidence review
- [x] B5-A8: Readiness at exact HEAD
- [x] B5-A9: Landable-PR path
- [x] B5-A10: Refuse merge without explicit user authorization
- [x] B5-A11: Phase 1 `omp-cli` + `/omp` still work under Claude/Codex/Grok
- [x] B5-A12: `verify_repo --ci` green; GitHub release notes dual-role + main-driver

---

## Master Acceptance

- [x] M-A1: Open omp with managed Elves install; stage without redirect to Claude/Codex/Grok.
- [x] M-A2: Ordinary native launch + exact resume; no `--continue`.
- [x] M-A3: Elves prewalk per `references/prewalk.md`; no omp product `--prewalk` in Elves.
- [x] M-A4: Host parity for plan, memory, stop, review, readiness, landable PR; user-owned merge auth.
- [x] M-A5: Phase 1 worker + shortcut remain under other hosts.
- [x] M-A6: Claude/Codex/Grok install intent unchanged.
- [x] M-A7: No main-driver claim before B4; no installer before B0 path freeze; no parity claim while
      `launch_ready=False`.

---

## File touch list (expected)

| Area | Files |
|------|--------|
| Host/runtime | `host_profiles.py`, `native_worker.py`, `prewalk.py`, `worker_routing.py`, `cobbler_agents.py`; reuse `adapters.py` / isolation / auth |
| Install | `sync_installed_skills.py`, `installed_bundle_smoke.py`, `install_doctor.py` |
| Docs | SKILL, AGENTS, README, PRODUCT, guide, host-parity, prewalk, omp-worker, runtime-helper-paths, CHANGELOG |
| Tests | host_profiles, native_worker_prewalk/hardening, adaptive_worker_routing, sync, smoke, architecture/consistency |
| Evidence | Appendix B; private canary artifacts; Fugu log (this review) |

Pointer: `docs/plans/omp-first-class-harness.md` Phase 2/3 deferred batches are **superseded** by this plan.

---

## Version and order

```text
B0 evidence → B1 host + ordinary launch → B2 prewalk → B3 install (after B0.1 freeze)
→ B4 policy/docs → B5 cumulative proof + release
```

Release target: **2.26.0** (or next free minor at freeze).

---

## Appendix B: B0 evidence (fill during B0; empty until proven)

```text
omp executable: /Users/john/.bun/bin/omp
omp version/build: omp/17.2.12
native global skill root (frozen): ~/.omp/agent/skills/elves
project skill root / precedence: .omp/skills/ (project walk-up); native user root preferred for managed install
shadowing notes: enableClaudeUser may also load ~/.claude/skills/elves; managed install uses native root only
create/resume canary: unit-tested host launch argv + Phase 1 NDJSON fixtures (live paid canary optional)
ordinary launch_ready initial: True (host profile launch_ready=True after argv/help grammar proof)
ordinary launch_ready for release: True
prewalk canary: host registered for probe_installed_prewalk_capabilities(omp); full live canary optional
notes: B0 installed-binary probe wrote elves-probe under ~/.omp/agent/skills/; frozen root matches oh-my-pi native discovery
```

---

## Fugu review summary (incorporated)

**Route:** general `--ultra`, read-only, 2026-08-09.  
**Verdict:** revise plan (done); B0 may start; no installer/public claim until blockers cleared.  
**Key blockers incorporated:** installed-only path freeze; full transport B0; worker_routing +
cobbler_agents in B1; HostLaunchRequest isolation fields; single-credential projection;
`launch_ready` release rule; strong B5 proof list; user-owned merge wording; dual-role token
hygiene; authoritative adapter reuse.
