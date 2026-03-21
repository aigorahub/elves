# Verification Patterns

Patterns for verifying code actually works, beyond running `npm test`. Add these to the `## Tool Configuration` section of your survival guide.

## 1. Headless Browser Verification

**When:** Web apps with multi-step user flows (signup, checkout, onboarding).

**What it catches:** Broken routes, missing env vars, UI state bugs. A unit test can verify `createUser()` returns the right object. This verifies the button is visible, fires the right request, and lands the user on the right page.

**Config:** `e2e: npx playwright test tests/e2e/`

```typescript
// tests/e2e/signup.spec.ts
import { test, expect } from '@playwright/test';

test('user can sign up and reach the dashboard', async ({ page }) => {
  await page.goto('/signup');
  await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible();
  await page.getByLabel('Email').fill('test+e2e@example.com');
  await page.getByLabel('Password').fill('TestPass123!');
  await page.getByRole('button', { name: 'Sign up' }).click();
  await expect(page.getByText('Check your email')).toBeVisible({ timeout: 5000 });
  await page.goto('/confirm?token=test-token');
  await expect(page).toHaveURL('/dashboard');
});
```

Assert state at every step, not just the end.

## 2. Video Recording of Test Output

**When:** Any E2E run the agent does overnight. Video is proof of what the agent saw and the fastest way to debug a failure without re-running the suite.

**What it catches:** Visual failures an assertion misses: wrong text, broken layout, a spinner that never resolves.

**Config:** `e2e: npx playwright test --reporter=html`

```typescript
// playwright.config.ts
export default defineConfig({
  use: {
    video: 'on-first-retry',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  reporter: [['html', { outputFolder: 'playwright-report', open: 'never' }]],
});
```

After the run, log the report path in the execution log so the human knows where to find it.

## 3. Smoke Testing Deployed Previews

**When:** After any preview deployment (Vercel, Netlify, Railway).

**What it catches:** Missing production env vars, CDN misconfigurations, cold-start errors, assets that build locally but 404 in production.

**Config:** `smoke: bash scripts/smoke.sh ${PREVIEW_URL}`

```bash
#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:?Usage: smoke.sh <base-url>}"
FAILURES=0
check() {
  local label="$1" url="$2" want="${3:-200}" body="${4:-}"
  status=$(curl -s -o /tmp/smoke_body -w "%{http_code}" "$url")
  [ "$status" != "$want" ] && { echo "FAIL [$label] HTTP $status"; FAILURES=$((FAILURES+1)); return; }
  [ -n "$body" ] && ! grep -q "$body" /tmp/smoke_body && { echo "FAIL [$label] missing: $body"; FAILURES=$((FAILURES+1)); return; }
  echo "OK   [$label] HTTP $status"
}
check "health"   "$BASE_URL/api/health" 200 '"status":"ok"'
check "homepage" "$BASE_URL/"           200
check "api-auth" "$BASE_URL/api/users"  401  # 401 = auth required, not broken
[ $FAILURES -gt 0 ] && { echo "$FAILURES check(s) failed"; exit 1; }
echo "All smoke checks passed"
```

## 4. Interactive CLI Testing

**When:** The project is a CLI tool that requires a TTY. Regular shell scripts can't drive interactive prompts. tmux can.

**What it catches:** readline failures, broken interactive menus, spinners that lock up outside a TTY.

```bash
#!/usr/bin/env bash
SESSION="elves-cli-test"
tmux new-session -d -s "$SESSION" -x 200 -y 50
tmux send-keys -t "$SESSION" "my-cli init --name test-project" Enter; sleep 2
tmux send-keys -t "$SESSION" "yes" Enter; sleep 1
tmux capture-pane -t "$SESSION" -p > /tmp/cli-output.txt
tmux kill-session -t "$SESSION"
grep -q "Project initialized" /tmp/cli-output.txt || { echo "FAIL: no confirmation"; exit 1; }
echo "CLI test passed"
```

## 5. Programmatic State Assertions

**When:** Any batch that writes to a database, filesystem, or external API. "The code ran" isn't verification. "The right records exist" is.

**What it catches:** Silent failures where code runs and tests pass but nothing was written. Wrong values, missing foreign keys, empty generated files.

**Config:** `e2e: bash scripts/assert-state.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
# Database: table exists after migration
count=$(psql "$DATABASE_URL" -tAc \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='users'")
[ "$count" -eq 1 ] || { echo "FAIL: users table missing"; exit 1; }
# Filesystem: generated files exist and are non-empty
for f in src/generated/schema.ts src/generated/client.ts; do
  [ -s "$f" ] || { echo "FAIL: $f missing or empty"; exit 1; }
done
echo "State assertions passed"
```

## 6. Custom Verification Scripts

**When:** Every batch, as a catchall. A `verify.sh` bundles project-specific checks into one pass/fail signal.

**What it catches:** Integration gaps, config drift, invariants that don't belong in any test framework.

**Config:** `e2e: bash verify.sh`

```bash
#!/usr/bin/env bash
# verify.sh -- runs after each batch. Exit 0 = pass, non-zero = fail.
set -euo pipefail
FAILURES=0
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES+1)); }
pass() { echo "OK:   $1"; }

[ -f "dist/index.js" ]                             && pass "dist exists"       || fail "dist/index.js missing"
curl -sf http://localhost:3000/health -o /dev/null  && pass "health endpoint"  || fail "health not responding"
grep -rq "DEBUG=true" src/ 2>/dev/null             && fail "DEBUG=true in src" || pass "no debug flags"

[ $FAILURES -gt 0 ] && { echo "$FAILURES check(s) failed"; exit 1; }
echo "verify.sh passed"
```

Edit this during planning to add project-specific checks. Keep it under 60 lines. If it grows larger, split it into focused scripts and call them from here.
