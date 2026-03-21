#!/usr/bin/env bash
# =============================================================================
# Elves Notification Helper
# Sends a titled message via the best available channel.
#
# Usage:
#   ./scripts/notify.sh "Title" "Body text" ["https://optional-url"]
#   ./scripts/notify.sh --test
#
# Delivery order (first working method wins):
#   1. ELVES_SLACK_WEBHOOK  — Slack Block Kit message
#   2. ELVES_NOTIFY_CMD     — eval a custom command ($TITLE $BODY $URL available)
#   3. gh pr comment        — post to the current branch's open PR
#   4. stdout               — echo as last resort
#
# Exit: always 0 (errors are logged, not fatal)
# =============================================================================

set -uo pipefail

# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--test" ]; then
  TITLE="Elves Notification Test"
  BODY="This is a test notification sent by notify.sh at $(date). If you see this, notifications are working."
  URL=""
elif [ $# -ge 2 ]; then
  TITLE="${1}"
  BODY="${2}"
  URL="${3:-}"
else
  echo "Usage: $0 \"title\" \"body\" [\"url\"]" >&2
  echo "       $0 --test" >&2
  exit 1
fi

export TITLE BODY URL

# ---------------------------------------------------------------------------
# Logging helper (goes to stderr so it doesn't pollute piped output)
# ---------------------------------------------------------------------------
log()  { echo "[notify] $*" >&2; }
err()  { echo "[notify] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Method 1: Slack Block Kit via ELVES_SLACK_WEBHOOK
# ---------------------------------------------------------------------------
try_slack() {
  [ -z "${ELVES_SLACK_WEBHOOK:-}" ] && return 1

  # Build Block Kit payload with python3 (no jq dependency)
  PAYLOAD=$(python3 - <<PYEOF
import json, os, sys

title = os.environ.get("TITLE", "Elves")
body  = os.environ.get("BODY", "")
url   = os.environ.get("URL", "").strip()

blocks = [
    {
        "type": "header",
        "text": {"type": "plain_text", "text": title, "emoji": True}
    },
    {
        "type": "section",
        "text": {"type": "mrkdwn", "text": body}
    },
]

if url:
    blocks.append({
        "type": "actions",
        "elements": [{
            "type": "button",
            "text": {"type": "plain_text", "text": "Open", "emoji": True},
            "url": url,
            "action_id": "elves_open_link"
        }]
    })

blocks.append({"type": "divider"})

payload = {
    "text": title,   # fallback for notifications
    "blocks": blocks
}
print(json.dumps(payload))
PYEOF
)

  if [ -z "$PAYLOAD" ]; then
    err "Slack: failed to build payload (python3 error)"
    return 1
  fi

  HTTP_CODE=$(curl -s -o /tmp/elves_slack_response.txt -w "%{http_code}" \
    -X POST "${ELVES_SLACK_WEBHOOK}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" 2>/dev/null || echo "000")

  if [ "$HTTP_CODE" = "200" ]; then
    log "Slack: delivered (HTTP 200)"
    return 0
  else
    RESPONSE=$(cat /tmp/elves_slack_response.txt 2>/dev/null || echo "(no body)")
    err "Slack: HTTP ${HTTP_CODE} — ${RESPONSE}"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Method 2: Custom command via ELVES_NOTIFY_CMD
# ---------------------------------------------------------------------------
try_custom_cmd() {
  [ -z "${ELVES_NOTIFY_CMD:-}" ] && return 1

  log "Custom command: ${ELVES_NOTIFY_CMD}"
  # SECURITY NOTE: eval is intentional here. ELVES_NOTIFY_CMD is set by the user
  # in their own environment, not by untrusted input. It allows users to configure
  # arbitrary notification commands (e.g., 'curl -d "$BODY" ntfy.sh/my-topic').
  # TITLE, BODY, URL are already exported above.
  if eval "${ELVES_NOTIFY_CMD}" 2>/tmp/elves_custom_cmd_err.txt; then
    log "Custom command: delivered"
    return 0
  else
    ERR_MSG=$(cat /tmp/elves_custom_cmd_err.txt 2>/dev/null | head -3 || echo "(no output)")
    err "Custom command failed: ${ERR_MSG}"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Method 3: GitHub PR comment via gh
# ---------------------------------------------------------------------------
try_gh_pr_comment() {
  command -v gh &>/dev/null || { err "gh CLI not available for PR comment"; return 1; }
  git rev-parse --is-inside-work-tree &>/dev/null || { err "Not in a git repo"; return 1; }

  # Detect open PR on current branch
  PR_NUMBER=$(gh pr view --json number -q .number 2>/dev/null || true)
  if [ -z "$PR_NUMBER" ]; then
    err "No open PR found on current branch"
    return 1
  fi

  # Build comment body
  COMMENT_BODY="## ${TITLE}

${BODY}"
  if [ -n "${URL:-}" ]; then
    COMMENT_BODY="${COMMENT_BODY}

[Open](${URL})"
  fi

  if gh pr comment --body "$COMMENT_BODY" 2>/tmp/elves_gh_err.txt; then
    log "PR comment posted (PR #${PR_NUMBER})"
    return 0
  else
    ERR_MSG=$(cat /tmp/elves_gh_err.txt 2>/dev/null | head -3 || echo "(no output)")
    err "gh pr comment failed: ${ERR_MSG}"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Method 4: stdout fallback
# ---------------------------------------------------------------------------
fallback_stdout() {
  echo "──────────────────────────────────────────"
  echo "  ${TITLE}"
  echo "──────────────────────────────────────────"
  echo "${BODY}"
  [ -n "${URL:-}" ] && echo "  ${URL}"
  echo "──────────────────────────────────────────"
  return 0
}

# ---------------------------------------------------------------------------
# Dispatch — try each method in order, stop at first success
# ---------------------------------------------------------------------------
DELIVERED=0

if try_slack; then
  DELIVERED=1
elif try_custom_cmd; then
  DELIVERED=1
elif try_gh_pr_comment; then
  DELIVERED=1
else
  log "All notification channels failed or unconfigured — falling back to stdout"
  fallback_stdout
  DELIVERED=1
fi

[ "$DELIVERED" -eq 1 ] && exit 0 || exit 0   # always exit 0 — notifications are best-effort
