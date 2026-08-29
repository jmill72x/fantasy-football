#!/bin/bash
# Regression guard for ops/run_alert.sh's bash-3.2 empty-array hazard - the
# only shell-syntax bug this repo has actually shipped: dry-run rehearsal
# (a non-empty array) passed, and the launchd path (an empty array) crashed
# in production with "unbound variable". See the comment above DRY_RUN_FLAG
# in run_alert.sh for the full story.
#
# macOS's /bin/bash is 3.2.57 (Apple ships no newer bash - GPLv3 licensing -
# and run_alert.sh's shebang pins it there regardless of what else is on
# $PATH). In bash <4.4, expanding an EMPTY array as "${ARR[@]}" under
# `set -u` raises "unbound variable"; only the bash-3.2-safe
# ${ARR[@]+"${ARR[@]}"} idiom, or a plain scalar, is safe.
#
# This check is static rather than a stubbed end-to-end run: run_alert.sh
# has no seam to swap out Playwright, the `claude` CLI, or the live CBS
# network for a fake, so exercising the real script here would mean either
# a larger rewrite to add one, or a fragile line-extraction-and-eval of the
# vulnerable snippet that could silently drift from the real file. A grep
# for the unsafe idiom, checked alongside the file's own `set -u`
# declaration, catches the actual bug class cheaply: nobody can reintroduce
# a bare "${NAME[@]}" array expansion in a script that also sets `-u`
# without this failing - which is exactly the change that broke it before.
#
# Usage: ops/lint_run_alert.sh   (exit 0 = pass, non-zero = regression found)
set -euo pipefail
cd "$(dirname "$0")"

SCRIPT="run_alert.sh"

grep -q 'set -u' "$SCRIPT" || {
    echo "FAIL: $SCRIPT no longer sets -u; this guard assumes it does, since" >&2
    echo "the hazard it checks for only bites under set -u." >&2
    exit 1
}

# Any "${NAME[@]}" expansion that is NOT wrapped in the bash-3.2-safe
# ${NAME[@]+"${NAME[@]}"} guard is the hazard. Comment-only lines
# (run_alert.sh names the unsafe idiom by example, in prose, right above
# DRY_RUN_FLAG) are excluded by filtering on the "N:# ..." shape AFTER
# `grep -n` so line numbers in the report still match the real file.
if grep -nE '\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}' "$SCRIPT" \
        | grep -vE '^[0-9]+:[[:space:]]*#' \
        | grep -vE '\[@\]\+"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"' \
        > /tmp/lint_run_alert.hits 2>/dev/null; then
    echo "FAIL: $SCRIPT expands an array as \"\${NAME[@]}\" without the" >&2
    echo "bash-3.2-safe \${NAME[@]+\"\${NAME[@]}\"} guard, in a script that" >&2
    echo "sets 'set -u'. On macOS's /bin/bash (3.2), an EMPTY such array" >&2
    echo "raises 'unbound variable' - the exact bug that broke the launchd" >&2
    echo "(no-argument) path once already, while dry-run rehearsal (a" >&2
    echo "non-empty array) passed. Either add the guard idiom or switch to" >&2
    echo "a scalar (see the DRY_RUN_FLAG comment in $SCRIPT). Offending" >&2
    echo "line(s):" >&2
    cat /tmp/lint_run_alert.hits >&2
    rm -f /tmp/lint_run_alert.hits
    exit 1
fi
rm -f /tmp/lint_run_alert.hits

# Confirm the syntax is valid under the bash that will actually run it in
# production - the shebang is #!/bin/bash, and macOS's /bin/bash is always
# 3.2, regardless of any newer bash a developer's $PATH might prefer.
/bin/bash -n "$SCRIPT" || {
    echo "FAIL: $SCRIPT has a syntax error under /bin/bash" >&2
    exit 1
}

echo "OK: $SCRIPT has no unguarded array expansion under set -u, and parses" \
     "under $(/bin/bash --version | head -1)"
