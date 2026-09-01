# Fugu review: Windows through WSL2 plan

## Route

- Date: 2026-09-01
- Profile: regular Fugu review
- Wall limit: 900 seconds
- Extra includes: none

## Accepted findings

1. `bwrap` readiness does not prove external council readiness. Linux council dispatch fails the
   recursive process-boundary gate before the filesystem-sandbox probe.
2. The plan must reject WSL1 and an unknown WSL generation. Only confirmed WSL2 is supported.
3. Council output needs explicit success, unavailable, and blocked states in human output, JSON,
   and exit status.
4. Install discovery must accept Windows separators, include OMP, and use `shutil.which`.
5. All five shortcut launchers run inside WSL2 on Windows. Fugu, Grok, and OMP also need `bwrap`.
   Manus and Devin perform remote work without `dispatch_external.py` or a local repository
   sandbox.

## Host decision

Host inspection confirmed all five findings. The plan now includes them. Native Win32 execution
and a new Windows sandbox backend remain out of scope.
