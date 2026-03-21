#!/usr/bin/env bash
# =============================================================================
# Elves Preflight Checklist
# Run before starting an autonomous Elves session to verify the environment.
#
# Usage: ./scripts/preflight.sh
#
# Exit codes:
#   0 — no critical failures (warnings may be present)
#   1 — one or more critical failures found
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers (disabled automatically when not a tty)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  BOLD='\033[1m'; RESET='\033[0m'
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'
else
  BOLD=''; RESET=''; GREEN=''; YELLOW=''; RED=''; CYAN=''
fi

PASS="${GREEN}✓${RESET}"
WARN="${YELLOW}⚠${RESET}"
FAIL="${RED}✗${RESET}"

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
declare -a SUMMARY_LINES=()
HARD_FAILURES=0

pass()  { echo -e "  ${PASS} $*"; SUMMARY_LINES+=("${GREEN}✓${RESET} $*"); }
warn()  { echo -e "  ${WARN} $*"; SUMMARY_LINES+=("${YELLOW}⚠${RESET} $*"); }
fail()  { echo -e "  ${FAIL} $*"; SUMMARY_LINES+=("${RED}✗${RESET} $*"); HARD_FAILURES=$(( HARD_FAILURES + 1 )); }
info()  { echo -e "    ${CYAN}→${RESET} $*"; }
header(){ echo; echo -e "${BOLD}── $* ──────────────────────────────────────────${RESET}"; }

# ---------------------------------------------------------------------------
# Cloud / headless environment detection (skip sleep checks if true)
# ---------------------------------------------------------------------------
is_cloud_env() {
  # Codex / OpenAI sandbox
  [ -n "${OPENAI_CODEX:-}" ] && return 0
  # GitHub Codespaces
  [ -n "${CODESPACES:-}" ] && return 0
  # Generic CI signals
  [ -n "${CI:-}" ] && return 0
  [ -n "${GITHUB_ACTIONS:-}" ] && return 0
  [ -n "${GITLAB_CI:-}" ] && return 0
  [ -n "${CIRCLECI:-}" ] && return 0
  # Cloud VM heuristics (no battery hardware)
  if [ "$(uname -s)" = "Linux" ]; then
    ls /sys/class/power_supply/ 2>/dev/null | grep -q "BAT" || return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# 1. Git remote
# ---------------------------------------------------------------------------
header "Git Remote"

REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$REMOTE_URL" ]; then
  fail "No git remote 'origin' found"
  info "Fix: git remote add origin <url>"
else
  pass "Remote origin: ${REMOTE_URL}"
fi

# ---------------------------------------------------------------------------
# 2. gh CLI authentication
# ---------------------------------------------------------------------------
header "GitHub CLI (gh)"

if ! command -v gh &>/dev/null; then
  fail "gh CLI not installed — required for PR operations"
  info "Install: https://cli.github.com"
else
  GH_STATUS=$(gh auth status 2>&1 || true)
  if echo "$GH_STATUS" | grep -q "Logged in"; then
    GH_USER=$(echo "$GH_STATUS" | grep -o "account [^ ]*" | head -1 | awk '{print $2}')
    pass "gh authenticated${GH_USER:+ as ${GH_USER}}"
  else
    fail "gh CLI is not authenticated"
    info "Fix: gh auth login"
  fi
fi

# ---------------------------------------------------------------------------
# 3. Push dry-run
# ---------------------------------------------------------------------------
header "Push Access (dry-run)"

CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ -z "$CURRENT_BRANCH" ]; then
  warn "Cannot determine current branch (detached HEAD?)"
else
  PUSH_RESULT=$(git push --dry-run origin "HEAD:${CURRENT_BRANCH}" 2>&1 || true)
  if echo "$PUSH_RESULT" | grep -qE "Everything up-to-date|Would push|To "; then
    pass "Can push to origin/${CURRENT_BRANCH}"
  elif echo "$PUSH_RESULT" | grep -qiE "error|denied|rejected|fatal"; then
    fail "Push dry-run failed for origin/${CURRENT_BRANCH}"
    info "Output: $(echo "$PUSH_RESULT" | head -3)"
  else
    # Ambiguous — treat as warning
    warn "Push dry-run result unclear for origin/${CURRENT_BRANCH}"
    info "Output: $(echo "$PUSH_RESULT" | head -3)"
  fi
fi

# ---------------------------------------------------------------------------
# 4. Project type detection
# ---------------------------------------------------------------------------
header "Project Type Detection"

PROJECT_NODE=0; PROJECT_PYTHON=0; PROJECT_GO=0; PROJECT_RUST=0; PROJECT_MAKE=0
NODE_MGR=""

if [ -f package.json ]; then
  PROJECT_NODE=1
  if [ -f pnpm-lock.yaml ]; then NODE_MGR="pnpm"
  elif [ -f yarn.lock ];    then NODE_MGR="yarn"
  else                           NODE_MGR="npm"
  fi
  pass "Node.js project detected (manager: ${NODE_MGR})"
fi
[ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ] && { PROJECT_PYTHON=1; pass "Python project detected"; }
[ -f go.mod ]         && { PROJECT_GO=1;   pass "Go project detected"; }
[ -f Cargo.toml ]     && { PROJECT_RUST=1; pass "Rust project detected"; }
[ -f Makefile ]       && { PROJECT_MAKE=1; pass "Makefile present"; }
[ -d .github/workflows ] && pass "GitHub Actions CI detected"

if [ $PROJECT_NODE -eq 0 ] && [ $PROJECT_PYTHON -eq 0 ] && \
   [ $PROJECT_GO -eq 0 ] && [ $PROJECT_RUST -eq 0 ] && [ $PROJECT_MAKE -eq 0 ]; then
  warn "No recognised project type detected (no package.json / pyproject.toml / go.mod / Cargo.toml / Makefile)"
fi

# ---------------------------------------------------------------------------
# 5. Validation gate probe (check commands exist / scripts are defined)
# ---------------------------------------------------------------------------
header "Validation Gates"

check_npm_script() {
  local SCRIPT="$1"
  if node -e "const p=require('./package.json'); process.exit(p.scripts&&p.scripts['${SCRIPT}']?0:1)" 2>/dev/null; then
    return 0
  fi
  return 1
}

if [ $PROJECT_NODE -eq 1 ]; then
  echo -e "  ${CYAN}Node.js (${NODE_MGR})${RESET}"
  for SCRIPT in lint typecheck build test; do
    if check_npm_script "$SCRIPT"; then
      pass "  ${NODE_MGR} run ${SCRIPT} — defined"
    else
      warn "  ${NODE_MGR} run ${SCRIPT} — not defined in package.json"
    fi
  done
fi

if [ $PROJECT_PYTHON -eq 1 ]; then
  echo -e "  ${CYAN}Python${RESET}"
  command -v ruff   &>/dev/null && pass "  ruff available (lint)"   || warn "  ruff not found — lint unavailable"
  command -v mypy   &>/dev/null && pass "  mypy available (typecheck)" || warn "  mypy not found — typecheck unavailable"
  command -v pytest &>/dev/null && pass "  pytest available (test)"  || warn "  pytest not found — test unavailable"
fi

if [ $PROJECT_GO -eq 1 ]; then
  echo -e "  ${CYAN}Go${RESET}"
  command -v go           &>/dev/null && pass "  go available (build/test)" || fail "  go not installed"
  command -v golangci-lint &>/dev/null && pass "  golangci-lint available (lint)" || warn "  golangci-lint not found — lint unavailable"
fi

if [ $PROJECT_RUST -eq 1 ]; then
  echo -e "  ${CYAN}Rust${RESET}"
  command -v cargo &>/dev/null && pass "  cargo available (build/test/clippy)" || fail "  cargo not installed"
fi

if [ $PROJECT_MAKE -eq 1 ]; then
  echo -e "  ${CYAN}Makefile${RESET}"
  for TARGET in lint typecheck build test; do
    if make -n "$TARGET" &>/dev/null 2>&1; then
      pass "  make ${TARGET} — target exists"
    else
      warn "  make ${TARGET} — target not defined"
    fi
  done
fi

# ---------------------------------------------------------------------------
# 6. Sleep prevention
# ---------------------------------------------------------------------------
header "Sleep Prevention"

if is_cloud_env; then
  pass "Cloud/CI environment detected — sleep prevention not applicable"
else
  OS="$(uname -s)"
  case "$OS" in
    Darwin)
      if pgrep -x caffeinate > /dev/null 2>&1; then
        pass "caffeinate is running — sleep prevented"
      else
        warn "caffeinate is NOT running — the machine may sleep mid-session"
        info "Recommended: caffeinate -dims -w \$\$ &"
        info "Or start your session with: caffeinate -dims <your-command>"
      fi
      # Battery check via pmset
      if command -v pmset &>/dev/null; then
        BATT_LINE=$(pmset -g batt 2>/dev/null || true)
        if echo "$BATT_LINE" | grep -q "Battery Power"; then
          fail "Running on battery power — plug in before going offline"
        elif echo "$BATT_LINE" | grep -q "AC Power"; then
          pass "On AC power"
        else
          warn "Could not determine power source"
        fi
      else
        warn "pmset not available — could not check power source"
      fi
      ;;
    Linux)
      if command -v systemd-inhibit &>/dev/null; then
        info "TIP: Prevent idle sleep with: systemd-inhibit --what=idle <your-command>"
      fi
      # Battery check
      BAT_PATH=""
      for P in /sys/class/power_supply/BAT0 /sys/class/power_supply/BAT1; do
        [ -f "${P}/status" ] && { BAT_PATH="$P"; break; }
      done
      if [ -n "$BAT_PATH" ]; then
        BAT_STATUS=$(cat "${BAT_PATH}/status" 2>/dev/null || echo "Unknown")
        if [ "$BAT_STATUS" = "Discharging" ]; then
          fail "Running on battery power — plug in before going offline"
        elif [ "$BAT_STATUS" = "Charging" ] || [ "$BAT_STATUS" = "Full" ]; then
          pass "On AC power (battery: ${BAT_STATUS})"
        else
          warn "Battery status: ${BAT_STATUS}"
        fi
      else
        pass "No battery detected — likely a desktop or cloud VM"
      fi
      ;;
    *)
      warn "Unknown OS (${OS}) — cannot check sleep prevention"
      ;;
  esac
fi

# ---------------------------------------------------------------------------
# 7. Stale branch detection
# ---------------------------------------------------------------------------
header "Branch Staleness"

DEFAULT_BRANCH=""
for B in main master; do
  if git show-ref --verify --quiet "refs/remotes/origin/${B}" 2>/dev/null; then
    DEFAULT_BRANCH="$B"
    break
  fi
done

if [ -z "$DEFAULT_BRANCH" ]; then
  warn "Could not detect default branch (main/master not found in origin)"
else
  git fetch origin "$DEFAULT_BRANCH" --quiet 2>/dev/null || true
  BEHIND=$(git rev-list "HEAD..origin/${DEFAULT_BRANCH}" --count 2>/dev/null || echo "0")
  AHEAD=$(git rev-list "origin/${DEFAULT_BRANCH}..HEAD" --count 2>/dev/null || echo "0")
  if [ "$BEHIND" -eq 0 ]; then
    pass "Branch is up to date with origin/${DEFAULT_BRANCH}"
  elif [ "$BEHIND" -le 10 ]; then
    warn "Branch is ${BEHIND} commit(s) behind origin/${DEFAULT_BRANCH} — note in survival guide"
    info "Consider: git merge origin/${DEFAULT_BRANCH}  (or rebase, per project convention)"
  else
    fail "Branch is ${BEHIND} commits behind origin/${DEFAULT_BRANCH} — significant drift"
    info "Fix before starting: git merge origin/${DEFAULT_BRANCH}"
  fi
  [ "$AHEAD" -gt 0 ] && info "Branch is ${AHEAD} commit(s) ahead of origin/${DEFAULT_BRANCH} (unpushed)"
fi

# ---------------------------------------------------------------------------
# 8. Slack webhook test
# ---------------------------------------------------------------------------
header "Slack Notification"

if [ -z "${ELVES_SLACK_WEBHOOK:-}" ]; then
  info "ELVES_SLACK_WEBHOOK not set — Slack notifications disabled"
  info "Set it to receive session completion alerts"
else
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${ELVES_SLACK_WEBHOOK}" \
    -H "Content-Type: application/json" \
    -d '{"text":"Elves preflight test \u2014 notifications working."}' 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "200" ]; then
    pass "Slack webhook is working (HTTP 200)"
  else
    warn "Slack webhook returned HTTP ${HTTP_CODE} — notifications may not work"
    info "Check that ELVES_SLACK_WEBHOOK is a valid Slack incoming webhook URL"
  fi
fi

# ---------------------------------------------------------------------------
# 9. Plan file check
# ---------------------------------------------------------------------------
header "Plan File"

if [ -z "${ELVES_PLAN_PATH:-}" ]; then
  info "ELVES_PLAN_PATH not set — will need to specify plan path at session start"
else
  if [ -f "${ELVES_PLAN_PATH}" ]; then
    PLAN_LINES=$(wc -l < "${ELVES_PLAN_PATH}" 2>/dev/null || echo "?")
    pass "Plan file found: ${ELVES_PLAN_PATH} (${PLAN_LINES} lines)"
  else
    fail "Plan file not found: ${ELVES_PLAN_PATH}"
    info "Create the file or update ELVES_PLAN_PATH"
  fi
fi

# ---------------------------------------------------------------------------
# 10. Summary
# ---------------------------------------------------------------------------
echo
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Elves Preflight Summary${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
for LINE in "${SUMMARY_LINES[@]}"; do
  echo -e "  ${LINE}"
done
echo

WARN_COUNT=$(printf '%s\n' "${SUMMARY_LINES[@]}" | grep -c "^${YELLOW}⚠" 2>/dev/null || \
             printf '%s\n' "${SUMMARY_LINES[@]}" | grep -c "⚠" 2>/dev/null || echo 0)

if [ "$HARD_FAILURES" -eq 0 ] && [ "$WARN_COUNT" -eq 0 ]; then
  echo -e "${GREEN}${BOLD}All checks passed. Ready for an Elves session.${RESET}"
elif [ "$HARD_FAILURES" -eq 0 ]; then
  echo -e "${YELLOW}${BOLD}${WARN_COUNT} warning(s) — review before going offline.${RESET}"
else
  echo -e "${RED}${BOLD}${HARD_FAILURES} critical failure(s) — fix these before starting.${RESET}"
fi
echo

exit "$( [ "$HARD_FAILURES" -eq 0 ] && echo 0 || echo 1 )"
