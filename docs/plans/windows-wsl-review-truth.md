# Plan: truthful review results and Windows through WSL2

## Mission

Prevent an optional review dispatch from reporting success when it produced no review report.
Make Windows a documented and checked Elves host through WSL2, with exact setup guidance for a
machine that has WSL installed but has no Linux distribution.

Done means a caller can distinguish review success, review unavailability, and a blocking review
failure. A Windows user can install a WSL2 distribution, run a supported host inside it, and get a
clear provider-isolation check before a paid provider launch.

## Scope

### In scope

- Council result and CLI semantics when zero independent reports succeed.
- Windows and WSL environment checks in the install doctor.
- Actionable Windows remediation in filesystem-sandbox diagnostics.
- Windows through WSL2 installation and provider-support documentation in the README, public
  guide, operations guide, and provider reference.
- Focused tests, full repository verification, and the repository version update.

### Out of scope

- Native Win32 execution of Elves workers or provider CLIs.
- A new Windows AppContainer or Windows Sandbox backend.
- Automatic WSL installation, elevation, reboot, or Linux package installation.
- Changes to sandbox policy on macOS or Linux.
- Changes to Manus or Devin remote-service transport.

## Batches

### Batch 1 [B1]: Make zero-report review results non-successful

- **Intent / why:** A review command can exit 0 and print `OK` when all configured lanes produced
  no report. This can be read as a clean review.
- **Non-obvious rationale:** `phase_required=false` must keep the outer workflow free to use a
  host-native fallback. It must not make the review result successful. Use `blocked` for workflow
  authority and `ok` for actual dispatch success.
- **Build On targets:** `evaluate_quorum`, `CouncilResult`, lane attempt evidence, and current CLI
  JSON output.
- **Owned surfaces:** `scripts/cobbler_runtime/dispatch.py`, `scripts/cobbler_runtime/dispatch_models.py`,
  `scripts/cobbler_agents.py`, and dispatch tests.
- **Forbidden surfaces:** provider sandbox strength, merge authority, credentials, and unrelated
  full-run behavior.
- **Acceptance evidence:** focused unit and CLI tests that prove zero-report and successful-report
  results.
- **Failure modes / pitfalls:** Do not turn an unavailable optional council into a blocking phase.
  Do not remove lane skip reasons, `successful_count`, or `model_calls_made` evidence.
- **HEAD / run-doc paths / route-session identity / output format:** Start
  `a638c6188452e936f366d8d390b1b133d7454a7e`; plan is this file; survival and execution log use
  the matching `windows-wsl-review-truth` names; Fugu is a read-only plan review.

**Tasks:**

- [x] Separate review success from phase blocking when no report succeeds.
- [x] Add stable `success`, `unavailable`, and `blocked` result states.
- [x] Make the human output, JSON output, and exit status distinguish all three states.
- [x] Preserve successful optional councils and required-phase blocking behavior.

**Acceptance criteria:**

- [x] B1-A1: An optional council with zero successful reports returns `ok=false`,
  `blocked=false`, `council_verified=false`, and low confidence.
- [x] B1-A2: The council CLI returns a non-zero status and does not print `council: OK` when zero
  reports succeed.
- [x] B1-A3: JSON includes the explicit result state. Human output says `UNAVAILABLE` when no
  report exists and `BLOCKED` only for a blocking result. Exit-only callers receive distinct
  statuses for unavailable and blocked results.
- [x] B1-A4: The result keeps the failed lane reason, `successful_count=0`, and
  `model_calls_made=false` when isolation prevents every external attempt.
- [x] B1-A5: An optional council with one valid report remains successful, and a required phase
  with unmet quorum remains blocked.

**Docs likely touched:** CHANGELOG.

**Risk:** standard. The result feeds review and fallback decisions.

**Caution:** `ok=false` must not imply `blocked=true` for an optional phase.

**Affected surfaces:** council result aggregation, CLI exit status, dispatch tests.

**Constitution impacts:** A review cannot claim success without review evidence.

**Review focus:** zero-report semantics and fallback authority.

**Focused tests:** dispatch quorum tests, council CLI tests, and isolation-skip result tests.

**Depends on:** none.

### Batch 2 [B2]: Support Windows hosts through WSL2

- **Intent / why:** Elves uses Bash and POSIX isolation. Windows users need a supported path and
  exact recovery when WSL exists without a distribution.
- **Non-obvious rationale:** WSL2 supplies the existing Linux runtime and `bwrap` boundary. Native
  Windows support needs a separate runtime and sandbox project. Do not describe native Win32 as
  supported.
- **Build On targets:** `install_doctor.py`, the shared sandbox capability probe, current shell
  install commands, and the Windows WSL operations note.
- **Owned surfaces:** install doctor and tests, sandbox diagnostics and tests, README, public
  guide, operations guide, provider-shortcut reference, versioned top-level docs, and CHANGELOG.
- **Forbidden surfaces:** automatic elevation or package changes, AppContainer experiments,
  provider credential handling, and macOS or Linux sandbox weakening.
- **Acceptance evidence:** deterministic platform-probe tests, rendered doctor tests, sandbox
  diagnostic tests, documentation consistency checks, and full repository verification.
- **Failure modes / pitfalls:** `wsl.exe` can exist with no distribution or only a WSL1
  distribution. Native-only Elves inside WSL2 does not require `bwrap`. Fugu, Grok, and OMP local
  shortcuts do require it. Linux external council lanes remain unavailable because the recursive
  process-boundary gate fails before the filesystem-sandbox probe. Manus and Devin do not use the
  shared local filesystem sandbox, but their Bash launchers still require WSL2 on Windows.
- **HEAD / run-doc paths / route-session identity / output format:** same run identity as B1;
  host-native implementation after Fugu reviews this plan.

**Tasks:**

- [ ] Add a bounded, testable Windows and WSL support report to the install doctor.
- [ ] Give a native Windows user with no distribution the exact `wsl --install -d Ubuntu`
  recovery command.
- [ ] Distinguish WSL1, WSL2, and unknown WSL generation. Give the exact WSL1 conversion command.
- [ ] Report local shortcut filesystem-sandbox readiness separately from external council
  recursive process-boundary readiness.
- [ ] Replace generic unsupported-platform sandbox text with Windows through WSL2 remediation.
- [ ] Make install-path classification accept Windows separators and include OMP installations.
- [ ] Add one Windows through WSL2 install path to the README and public guide.
- [ ] State the platform contract and provider differences in detailed references.
- [ ] Update Elves to version 2.35.0 and record the change.

**Acceptance criteria:**

- [ ] B2-A1: On native Windows with no installed WSL distribution, doctor JSON and prose report
  `needs_wsl_distribution` and show `wsl --install -d Ubuntu`.
- [ ] B2-A2: On native Windows with a WSL2 distribution, the doctor tells the user to run the
  supported host and Elves inside that distribution. It does not claim native Win32 support.
- [ ] B2-A3: WSL1 and an unknown WSL generation are not reported as supported. WSL1 reports
  `wsl --set-version <Distro> 2`. Only confirmed WSL2 is supported.
- [ ] B2-A4: Inside WSL2, the doctor reports local shortcut `bwrap` readiness separately from the
  external council recursive process boundary. `bwrap` does not mark external council ready.
- [ ] B2-A5: A native Windows or filesystem-sandbox failure names WSL2 and `bwrap` as the supported
  remediation. Existing recursive-containment errors remain unchanged.
- [ ] B2-A6: Windows-style install paths classify correctly. OMP global and local installations
  are included. The public guide includes the OMP doctor command.
- [ ] B2-A7: README and public guide take a Windows user from WSL status check through WSL2
  distribution setup, Linux package prerequisites, host installation inside WSL, Elves install,
  and doctor validation.
- [ ] B2-A8: Provider documentation states that all five Windows shortcut runners execute inside
  WSL2. Fugu, Grok, and OMP need the local kernel sandbox. Manus and Devin perform remote work
  without `dispatch_external.py` or a local repository sandbox.
- [ ] B2-A9: Version metadata, CHANGELOG, consistency checks, focused tests, and the full
  repository verifier pass at version 2.35.0.

**Docs likely touched:** README, guide, operations guide, provider shortcuts, SKILL, AGENTS, and
CHANGELOG.

**Risk:** standard. Platform claims and security-boundary claims must match actual behavior.

**Caution:** Do not present an experimental Windows sandbox API as production support.

**Affected surfaces:** installation health, sandbox errors, user setup, provider support matrix,
release metadata.

**Constitution impacts:** Provider code never runs without a qualified kernel boundary.

**Review focus:** support wording, no automatic privileged changes, and accurate provider scope.

**Focused tests:** `tests/test_install_doctor.py`, dispatch isolation tests, provider shortcut
tests, guide checks, release checks, and `scripts/verify_repo.py`.

**Depends on:** B1.

## Master acceptance

- [ ] M-A1: No review result can be successful when it contains zero independent review reports.
- [ ] M-A2: A Windows user has one supported WSL2 setup path with an exact no-distribution
  recovery command and provider-isolation readiness evidence.
- [ ] M-A3: Native Win32 remains fail-closed and is not described as a supported execution path.
- [ ] M-A4: All focused tests and the full repository verification pass at the exact branch tip.

## Non-negotiables

- Never weaken filesystem or recursive process containment.
- Never install WSL, a distribution, or Linux packages without an explicit operator action.
- Never describe zero reports as a clean or successful review.
- Never merge without explicit approval in this session.

## Test strategy

- **Primary gate:** focused unittest modules for dispatch, isolation, install doctor, and provider
  shortcuts.
- **Secondary gate:** guide, consistency, installed-bundle, and release checks selected by impact.
- **Terminal gate:** `python3 scripts/verify_repo.py --final-readiness` or the current equivalent
  shown by `--help`.
- **Known flaky tests:** none accepted for this run.
- **Durable docs:** update all public platform and provider statements touched by the change.

## Notes

- GitHub issue: https://github.com/aigorahub/elves/issues/269
- Microsoft documents `wsl --install -d <Distro>` for WSL installations with no distribution.
- Microsoft's `CreateProcessInSandbox` API is experimental and is outside this run.
