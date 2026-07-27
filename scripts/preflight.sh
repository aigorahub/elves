#!/usr/bin/env bash
# =============================================================================
# Elves Preflight Checklist
# Run before starting an autonomous Elves session to verify the environment.
#
# Usage:
#   ./scripts/preflight.sh
#   ./scripts/preflight.sh --create-worktree <branch> [--dry-run] [--base <ref>] [--worktree-dir <path>]
#   ./scripts/preflight.sh --gc-worktrees [--apply] [--base <ref>] [--path <worktree-dir>]
#
# Exit codes:
#   0 — no critical failures (warnings may be present)
#   1 — one or more critical failures found
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Diagnostic redaction boundary
# ---------------------------------------------------------------------------
redact_stream() {
  LC_ALL=C awk '
    /-----BEGIN [A-Z ]*PRIVATE KEY-----/ {
      print "[REDACTED]"
      in_pem_block = 1
      next
    }
    in_pem_block && /-----END [A-Z ]*PRIVATE KEY-----/ {
      in_pem_block = 0
      next
    }
    in_pem_block { next }
    { print }
  ' | LC_ALL=C sed -E \
    -e 's#([a-z][a-z0-9+.-]*://)[^/@[:space:]]+@#\1[REDACTED]@#gI' \
    -e 's#(https://hooks\.slack\.[^/[:space:]]+/services/)[^/[:space:]]+/[^/[:space:]]+/[^/[:space:]?]+#\1[REDACTED]#gI' \
    -e 's#((api[_-]?key|[A-Za-z0-9_-]*token|jwt|bearer|authorization|auth|password|passwd|secret|credential|cookie|private[_-]?key)"?[[:space:]]*[:=][[:space:]]*(bearer[[:space:]]+)?"?)[^[:space:],;"}&]{8,}#\1[REDACTED]#gI' \
    -e 's#(Bearer[[:space:]]+)[A-Za-z0-9._+=/-]{8,}#\1[REDACTED]#gI' \
    -e 's#sk-(proj-|svcacct-)?[A-Za-z0-9_-]{10,}#[REDACTED]#g' \
    -e 's#xai-[A-Za-z0-9]{10,}#[REDACTED]#g' \
    -e 's#ghp_[A-Za-z0-9]{20,}#[REDACTED]#g' \
    -e 's#gho_[A-Za-z0-9]{20,}#[REDACTED]#g' \
    -e 's#gh[usr]_[A-Za-z0-9]{20,}#[REDACTED]#g' \
    -e 's#github_pat_[A-Za-z0-9_]{20,}#[REDACTED]#g' \
    -e 's#AKIA[0-9A-Z]{16}#[REDACTED]#g'
}

redact_text() {
  printf '%s' "${1:-}" | redact_stream
}

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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -gt 0 ]; then
  if ! command -v python3 &>/dev/null; then
    echo "error: python3 is required for preflight worktree helper mode" >&2
    exit 1
  fi
  if [ "${1}" = "--gc-worktrees" ]; then
    shift
    if [ ! -f "${SCRIPT_DIR}/worktree_gc.py" ]; then
      echo "error: ${SCRIPT_DIR}/worktree_gc.py is missing" >&2
      exit 1
    fi
    exec python3 "${SCRIPT_DIR}/worktree_gc.py" "$@"
  fi
  if [ ! -f "${SCRIPT_DIR}/preflight_worktree.py" ]; then
    echo "error: ${SCRIPT_DIR}/preflight_worktree.py is missing" >&2
    exit 1
  fi
  exec python3 "${SCRIPT_DIR}/preflight_worktree.py" "$@"
fi

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
declare -a SUMMARY_LINES=()
HARD_FAILURES=0

pass() {
  local MESSAGE
  MESSAGE=$(redact_text "$*")
  echo -e "  ${PASS} ${MESSAGE}"
  SUMMARY_LINES+=("${GREEN}✓${RESET} ${MESSAGE}")
}

warn() {
  local MESSAGE
  MESSAGE=$(redact_text "$*")
  echo -e "  ${WARN} ${MESSAGE}"
  SUMMARY_LINES+=("${YELLOW}⚠${RESET} ${MESSAGE}")
}

fail() {
  local MESSAGE
  MESSAGE=$(redact_text "$*")
  echo -e "  ${FAIL} ${MESSAGE}"
  SUMMARY_LINES+=("${RED}✗${RESET} ${MESSAGE}")
  HARD_FAILURES=$(( HARD_FAILURES + 1 ))
}

info() {
  local MESSAGE
  MESSAGE=$(redact_text "$*")
  echo -e "    ${CYAN}→${RESET} ${MESSAGE}"
}

header() {
  local MESSAGE
  MESSAGE=$(redact_text "$*")
  echo
  echo -e "${BOLD}── ${MESSAGE} ──────────────────────────────────────────${RESET}"
}

# ---------------------------------------------------------------------------
# 0. Skill installation advisory
# ---------------------------------------------------------------------------
header "Skill Installation"

if command -v python3 &>/dev/null && [ -f "${SCRIPT_DIR}/install_doctor.py" ]; then
  INSTALL_ADVISORY=$(python3 "${SCRIPT_DIR}/install_doctor.py" --startup 2>/dev/null || true)
  if [ -n "${INSTALL_ADVISORY}" ]; then
    warn "Elves install advisory"
    while IFS= read -r LINE; do
      if [ -n "${LINE}" ]; then
        CLEAN_LINE="${LINE#- }"
        info "${CLEAN_LINE}"
      fi
    done <<< "${INSTALL_ADVISORY}"
    info "Full report: python3 ${SCRIPT_DIR}/install_doctor.py --doctor"
  else
    pass "No actionable Elves install/update advisory"
  fi
else
  info "Install doctor unavailable (python3 or script missing)"
fi

# ---------------------------------------------------------------------------
# Cloud / headless environment detection (skip sleep checks if true)
# ---------------------------------------------------------------------------
is_cloud_env() {
  # Codex / OpenAI sandbox
  [ -n "${OPENAI_CODEX:-}" ] && return 0
  # GitHub Codespaces
  [ -n "${CODESPACES:-}" ] && return 0
  # Explicit hosted CI providers
  [ -n "${GITHUB_ACTIONS:-}" ] && return 0
  [ -n "${GITLAB_CI:-}" ] && return 0
  [ -n "${CIRCLECI:-}" ] && return 0
  return 1
}

declare -a PREFLIGHT_ENV=(
  "CI=true"
  "DEBIAN_FRONTEND=noninteractive"
  "HOMEBREW_NO_AUTO_UPDATE=1"
  "NEXT_TELEMETRY_DISABLED=1"
  "NUXT_TELEMETRY_DISABLED=1"
  "DOTNET_CLI_TELEMETRY_OPTOUT=1"
  "PYTHONDONTWRITEBYTECODE=1"
  "PIP_DISABLE_PIP_VERSION_CHECK=1"
  "NPM_CONFIG_YES=true"
)

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
    GH_USER=$(echo "$GH_STATUS" | awk '/Logged in/{for(i=1;i<NF;i++){if($i=="account"||$i=="as"){print $(i+1); exit}}}')
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
# 5. Ephemeral artifact gitignore
# ---------------------------------------------------------------------------
header "Ephemeral Artifact Gitignore"

# Check if common tool working directories are gitignored
EPHEMERAL_DIRS=(.playwright-mcp docs/audit)
MISSING_IGNORES=0

for DIR in "${EPHEMERAL_DIRS[@]}"; do
  if git check-ignore -q "${DIR}/" 2>/dev/null; then
    pass "${DIR}/ is gitignored"
  else
    MISSING_IGNORES=1
    warn "${DIR}/ is NOT in .gitignore — add it to prevent committing ephemeral artifacts"
    info "echo '${DIR}/' >> .gitignore"
  fi
done

if [ "$MISSING_IGNORES" -eq 0 ]; then
  pass "All known ephemeral directories are gitignored"
fi

# ---------------------------------------------------------------------------
# 6. Non-interactive environment
# ---------------------------------------------------------------------------
header "Non-Interactive Environment"

NON_INTERACTIVE_MISSING=0
for SPEC in "${PREFLIGHT_ENV[@]}"; do
  VAR_NAME=${SPEC%%=*}
  EXPECTED_VALUE=${SPEC#*=}
  if [ "${!VAR_NAME:-}" != "${EXPECTED_VALUE}" ]; then
    NON_INTERACTIVE_MISSING=1
    break
  fi
done

if [ "$NON_INTERACTIVE_MISSING" -eq 0 ]; then
  pass "Recommended non-interactive env vars are already set"
else
  warn "Current shell is missing one or more recommended non-interactive env vars"
  info "Gate dry-runs below will use safe defaults anyway, but export these before a long unattended run:"
  for SPEC in "${PREFLIGHT_ENV[@]}"; do
    info "export ${SPEC}"
  done
fi

# ---------------------------------------------------------------------------
# 7. Validation gate dry run
# ---------------------------------------------------------------------------
header "Validation Gates"

check_npm_script() {
  local SCRIPT="$1"
  if node -e "const p=require('./package.json'); process.exit(p.scripts&&p.scripts['${SCRIPT}']?0:1)" 2>/dev/null; then
    return 0
  fi
  return 1
}

playwright_config_present() {
  [ -f playwright.config.js ]  || [ -f playwright.config.cjs ] || \
  [ -f playwright.config.mjs ] || [ -f playwright.config.ts ]
}

run_gate() {
  local LABEL="$1"
  local CMD="$2"
  local GATE_LOG
  local OUTPUT

  GATE_LOG=$(mktemp "${TMPDIR:-/tmp}/elves-preflight-gate.XXXXXX")
  trap 'rm -f "${GATE_LOG}"' RETURN
  info "${CMD}"

  if env "${PREFLIGHT_ENV[@]}" bash -lc "${CMD}" >"${GATE_LOG}" 2>&1; then
    pass "${LABEL}"
  else
    warn "${LABEL} — failed during preflight dry run"
    OUTPUT=$(head -5 "${GATE_LOG}" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')
    info "Output: ${OUTPUT:-'(no output)'}"
  fi
}

if [ $PROJECT_NODE -eq 1 ]; then
  echo -e "  ${CYAN}Node.js (${NODE_MGR})${RESET}"
  if ! command -v node &>/dev/null; then
    fail "  node is not installed"
  elif ! command -v "${NODE_MGR}" &>/dev/null; then
    fail "  ${NODE_MGR} is not installed"
  else
    for SCRIPT in lint typecheck build test; do
      if check_npm_script "$SCRIPT"; then
        case "$NODE_MGR" in
          npm)
            if [ "$SCRIPT" = "test" ]; then
              GATE_CMD="npm test --if-present"
            else
              GATE_CMD="npm run ${SCRIPT} --if-present"
            fi
            ;;
          pnpm)
            GATE_CMD="pnpm ${SCRIPT}"
            ;;
          yarn)
            GATE_CMD="yarn ${SCRIPT}"
            ;;
        esac
        run_gate "  ${GATE_CMD}" "${GATE_CMD}"
      else
        info "Skipping ${NODE_MGR} ${SCRIPT} — not defined in package.json"
      fi
    done

    if check_npm_script "e2e"; then
      case "$NODE_MGR" in
        npm)  GATE_CMD="npm run e2e --if-present" ;;
        pnpm) GATE_CMD="pnpm e2e" ;;
        yarn) GATE_CMD="yarn e2e" ;;
      esac
      run_gate "  ${GATE_CMD}" "${GATE_CMD}"
    elif playwright_config_present; then
      case "$NODE_MGR" in
        npm)  GATE_CMD="npx playwright test" ;;
        pnpm) GATE_CMD="pnpm exec playwright test" ;;
        yarn) GATE_CMD="yarn playwright test" ;;
      esac
      run_gate "  ${GATE_CMD}" "${GATE_CMD}"
    fi
  fi
fi

if [ $PROJECT_PYTHON -eq 1 ]; then
  echo -e "  ${CYAN}Python${RESET}"
  command -v ruff &>/dev/null && run_gate "  ruff check ." "ruff check ." || info "Skipping lint — ruff not found"
  command -v mypy &>/dev/null && run_gate "  mypy ." "mypy ." || info "Skipping typecheck — mypy not found"
  command -v pytest &>/dev/null && run_gate "  pytest" "pytest" || info "Skipping tests — pytest not found"
fi

if [ $PROJECT_GO -eq 1 ]; then
  echo -e "  ${CYAN}Go${RESET}"
  if command -v go &>/dev/null; then
    run_gate "  go build ./..." "go build ./..."
    run_gate "  go test ./..." "go test ./..."
  else
    fail "  go is not installed"
  fi
  command -v golangci-lint &>/dev/null && run_gate "  golangci-lint run" "golangci-lint run" || info "Skipping lint — golangci-lint not found"
fi

if [ $PROJECT_RUST -eq 1 ]; then
  echo -e "  ${CYAN}Rust${RESET}"
  if command -v cargo &>/dev/null; then
    run_gate "  cargo clippy" "cargo clippy"
    run_gate "  cargo build" "cargo build"
    run_gate "  cargo test" "cargo test"
  else
    fail "  cargo is not installed"
  fi
fi

if [ $PROJECT_MAKE -eq 1 ]; then
  echo -e "  ${CYAN}Makefile${RESET}"
  for TARGET in lint typecheck build test e2e; do
    if make -n "$TARGET" &>/dev/null 2>&1; then
      run_gate "  make ${TARGET}" "make ${TARGET}"
    else
      info "Skipping make ${TARGET} — target not defined"
    fi
  done
fi

# ---------------------------------------------------------------------------
# 8. Sleep prevention
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
# 9. Stale branch detection
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
    info "Consider: merge origin/${DEFAULT_BRANCH} into this branch before starting, or cut a fresh branch from the updated default branch"
  else
    fail "Branch is ${BEHIND} commits behind origin/${DEFAULT_BRANCH} — significant drift"
    info "Fix before starting: git merge origin/${DEFAULT_BRANCH}"
  fi
  [ "$AHEAD" -gt 0 ] && info "Branch has ${AHEAD} commit(s) not in origin/${DEFAULT_BRANCH} (expected on feature/PR branches)"
fi

# ---------------------------------------------------------------------------
# 10. Workspace ownership
# ---------------------------------------------------------------------------
header "Workspace Ownership"

CURRENT_WORKTREE=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
if [ -z "${CURRENT_BRANCH}" ]; then
  warn "Cannot verify workspace ownership while HEAD is detached"
  info "Before launch, record the checkout path and collision tripwire manually"
else
  WORKTREE_OUTPUT=$(git worktree list --porcelain 2>/dev/null || true)
  if [ -z "${WORKTREE_OUTPUT}" ]; then
    warn "Could not inspect git worktrees"
    info "Run manually: git worktree list"
  else
    declare -a MATCHING_WORKTREES=()
    WORKTREE_PATH=""
    while IFS= read -r LINE; do
      LINE="${LINE%$'\r'}"
      case "${LINE}" in
        worktree\ *)
          WORKTREE_PATH="${LINE#worktree }"
          ;;
        branch\ refs/heads/*)
          WORKTREE_BRANCH="${LINE#branch refs/heads/}"
          if [ "${WORKTREE_BRANCH}" = "${CURRENT_BRANCH}" ]; then
            MATCHING_WORKTREES+=("${WORKTREE_PATH}")
          fi
          ;;
      esac
    done <<< "${WORKTREE_OUTPUT}"

    MATCHING_COUNT=${#MATCHING_WORKTREES[@]}
    if [ "${MATCHING_COUNT}" -eq 0 ]; then
      warn "Current branch ${CURRENT_BRANCH} was not found in git worktree list"
      info "Current checkout: ${CURRENT_WORKTREE}"
    elif [ "${MATCHING_COUNT}" -eq 1 ]; then
      pass "Current branch is checked out in one worktree: ${MATCHING_WORKTREES[0]}"
      info "Collision tripwire: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
    else
      fail "Current branch ${CURRENT_BRANCH} is checked out in ${MATCHING_COUNT} worktrees"
      for PATH_IN_USE in "${MATCHING_WORKTREES[@]}"; do
        if [ "${PATH_IN_USE}" = "${CURRENT_WORKTREE}" ]; then
          info "Branch checkout: ${PATH_IN_USE} (current checkout)"
        else
          info "Branch checkout: ${PATH_IN_USE}"
        fi
      done
      info "Use one owned branch and checkout per Elves run before launching"
      if command -v python3 &>/dev/null && [ -f "${SCRIPT_DIR}/preflight_worktree.py" ]; then
        RECOMMEND_ARGS=(--recommend-from-current "${CURRENT_BRANCH}")
        if [ -n "${DEFAULT_BRANCH}" ]; then
          RECOMMEND_ARGS+=(--base "origin/${DEFAULT_BRANCH}")
        fi
        RECOMMENDED_WORKTREE=$(
          python3 "${SCRIPT_DIR}/preflight_worktree.py" "${RECOMMEND_ARGS[@]}" 2>/dev/null || true
        )
        if [ -n "${RECOMMENDED_WORKTREE}" ]; then
          info "Recommended dedicated worktree command follows"
          while IFS= read -r LINE; do
            [ -n "${LINE}" ] && info "${LINE}"
          done <<< "${RECOMMENDED_WORKTREE}"
        else
          info "Run: ./scripts/preflight.sh --create-worktree <branch> --base origin/${DEFAULT_BRANCH:-main}"
        fi
      else
        info "Run: ./scripts/preflight.sh --create-worktree <branch> --base origin/${DEFAULT_BRANCH:-main}"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 11. Slack webhook test
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
# 12. Plan file check
# ---------------------------------------------------------------------------
header "Plan File"

SESSION_CONTRACT_PATH="${ELVES_SESSION_PATH:-}"
if [ -z "${SESSION_CONTRACT_PATH}" ] && [ -f ".elves-session.json" ]; then
  SESSION_CONTRACT_PATH=".elves-session.json"
fi

PLAN_CONTRACT_READY=1
if [ -z "${ELVES_PLAN_PATH:-}" ]; then
  if [ -z "${SESSION_CONTRACT_PATH}" ]; then
    info "ELVES_PLAN_PATH not set — will need to specify plan path at session start"
  else
    info "Using plan_path recorded in ${SESSION_CONTRACT_PATH}"
  fi
elif [ -f "${ELVES_PLAN_PATH}" ]; then
  PLAN_LINES=$(wc -l < "${ELVES_PLAN_PATH}" 2>/dev/null || echo "?")
  pass "Plan file found: ${ELVES_PLAN_PATH} (${PLAN_LINES} lines)"
else
  fail "Plan file not found: ${ELVES_PLAN_PATH}"
  info "Create the file or update ELVES_PLAN_PATH"
  PLAN_CONTRACT_READY=0
fi

if [ -n "${SESSION_CONTRACT_PATH}" ] && [ ! -f "${SESSION_CONTRACT_PATH}" ]; then
  fail "Session file not found: ${SESSION_CONTRACT_PATH}"
  info "Create the file or update ELVES_SESSION_PATH"
  PLAN_CONTRACT_READY=0
fi

if [ "${PLAN_CONTRACT_READY}" -eq 1 ] && \
   { [ -n "${ELVES_PLAN_PATH:-}" ] || [ -n "${SESSION_CONTRACT_PATH}" ]; }; then
  if ! command -v python3 &>/dev/null || [ ! -f "${SCRIPT_DIR}/acceptance_contract.py" ]; then
    fail "Acceptance staging validator unavailable"
  else
    ACCEPTANCE_LOG=$(mktemp "${TMPDIR:-/tmp}/elves-preflight-acceptance.XXXXXX")
    ACCEPTANCE_ARGS=(validate --repo-root "${PWD}")
    if [ -n "${SESSION_CONTRACT_PATH}" ]; then
      ACCEPTANCE_ARGS+=(--session "${SESSION_CONTRACT_PATH}")
    fi
    if [ -n "${ELVES_PLAN_PATH:-}" ]; then
      ACCEPTANCE_ARGS+=(--plan "${ELVES_PLAN_PATH}")
    fi
    if python3 "${SCRIPT_DIR}/acceptance_contract.py" "${ACCEPTANCE_ARGS[@]}" \
      >"${ACCEPTANCE_LOG}" 2>&1; then
      pass "Plan/session Acceptance staging contract passed"
    else
      fail "Plan/session Acceptance staging contract failed"
      while IFS= read -r LINE; do
        [ -n "${LINE}" ] && info "${LINE}"
      done < "${ACCEPTANCE_LOG}"
    fi
    rm -f "${ACCEPTANCE_LOG}"
  fi
fi

# ---------------------------------------------------------------------------
# 13. Survival guide validation (advisory)
# ---------------------------------------------------------------------------
header "Survival Guide (advisory)"

if [ -z "${ELVES_SURVIVAL_GUIDE_PATH:-}" ]; then
  info "ELVES_SURVIVAL_GUIDE_PATH not set — skipping survival guide validation"
  info "Recommended during staging: export ELVES_SURVIVAL_GUIDE_PATH=/path/to/survival-guide.md"
elif [ ! -f "${ELVES_SURVIVAL_GUIDE_PATH}" ]; then
  warn "Survival guide not found at ${ELVES_SURVIVAL_GUIDE_PATH}"
  info "This is advisory only — the guide can still be generated during staging"
elif ! command -v python3 &>/dev/null || [ ! -f "${SCRIPT_DIR}/validate_survival_guide.py" ]; then
  warn "Survival guide validator unavailable (python3 or script missing)"
else
  GUIDE_LOG=$(mktemp "${TMPDIR:-/tmp}/elves-preflight-guide.XXXXXX")
  if python3 "${SCRIPT_DIR}/validate_survival_guide.py" "${ELVES_SURVIVAL_GUIDE_PATH}" >"${GUIDE_LOG}" 2>&1; then
    pass "Survival guide validation passed"
  else
    warn "Survival guide validation found advisory issues"
    while IFS= read -r LINE; do
      [ -n "${LINE}" ] && info "${LINE}"
    done < "${GUIDE_LOG}"
  fi
  rm -f "${GUIDE_LOG}"
fi

# ---------------------------------------------------------------------------
# 14. Summary
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
