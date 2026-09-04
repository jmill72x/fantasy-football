"""Authenticated capture of the CBS league site.

THE ONLY MODULE THAT DRIVES A BROWSER. Everything downstream reads the text
files this writes, so the rest of the pipeline stays fixture-testable and
offline - the same discipline `cbs_weekly.parse` already follows.

WHY PLAYWRIGHT AND NOT SOMETHING LIGHTER. Four alternatives were tested on
2026-08-29 and each failed for a recorded reason: a headless `claude -p` has no
Chrome tools at all; AppleScript to the live Chrome timed out and would couple
unattended runs to Jeff's interactive browser; reading Chrome's cookie store is
policy-blocked and its encryption moves between versions; and CBS's legacy
fantasy JSON API 500s without a token whose only documented issuer wants a
password this project must never handle. Playwright with a persistent profile
needs a password exactly once, typed by Jeff into a real browser window, and
never through this code.

WHY A BAD CAPTURE MUST RAISE. An expired session does not return an error - it
returns HTTP 200 and a perfectly well-formed login page. Saved blindly, that
page parses to zero roster rows, the lineup optimises to empty, and the alert
confidently reports a roster Jeff does not have. Every capture is therefore
checked before it is written, and a failed check raises rather than returning
a shorter string.
"""

import os

# What CBS serves instead of the page when the session has expired. Verified
# 2026-08-29: an unauthenticated GET of the league 302s to cbssports.com/login.
# The login page has:
#   - HTML title: "Sign In - CBSSports.com"
#   - final URL: https://www.cbssports.com/login?... (path contains /login)
#   - body text: only 284 chars (but not all login pages may be short)
# This constant checks the title (the title never appears in body text).
# The URL /login path is checked separately. Body text is not checked for
# session expiry, to prevent the danger: a long login page (>1000 chars) would
# pass the character floor and save as a real capture, parsing downstream to
# an empty roster ('Jeff rosters nobody') — the exact failure this guard exists
# to prevent.
SESSION_EXPIRED_TITLE = "Sign In - CBSSports.com"

# A real CBS roster or projections page is thousands of characters. Anything
# under this is an interstitial, a rate limit, or an error page. The bound is
# deliberately far below any real page and far above any error page, so it
# never has to be tuned.
_MIN_PLAUSIBLE_CHARS = 1000

# wait_until="networkidle" never fires on the authenticated CBS site: verified
# live on 2026-08-29, it timed out after 60s because the logged-in page holds
# long-lived polling/streaming connections open indefinitely. The LOGGED-OUT
# login page reaches networkidle quickly, which is why this hid through three
# earlier fix rounds - the failure only appears once the session actually
# works. Fix: navigate with "domcontentloaded" (fires as soon as the DOM is
# parsed, regardless of open connections), then wait out this settle period.
# Verified live: immediately after domcontentloaded the body is EMPTY - CBS
# renders the roster client-side after DOM-ready - so this sleep is
# load-bearing, not decoration. With it, the same page returns fully
# rendered (7584 chars). This is a blind wait, not a readiness signal, by
# design: any selector-based wait risks hanging on an unexpected page (e.g.
# a login page missing the expected element), and the whole point of this
# fix is to stop hanging.
_SETTLE_WAIT_MS = 6000

# Per-page navigation timeout, passed to page.goto(). Named so a timeout can
# report which constant it hit and so it is tunable in one place instead of
# a bare literal.
#
# RAISED 30s -> 90s on 2026-09-04, after the first real scheduled Friday run
# lost five of eight lineup slots to it. `?print_rows=9999` - the parameter
# that stops CBS hiding rostered players outside its default top 100 - turns
# the RB/WR/TE page into 1710 rows, and that page MEASURES at ~33s to
# domcontentloaded. 30s was not a margin, it was a coin flip.
#
# Asking for fewer rows is not available as a fix: measured the same day,
# print_rows of 200, 400, 500, 1000, 1710 and 2000 ALL return CBS's default
# 100 rows in ~7.6s, and only 9999 returns the full set. There is no middle
# setting to retreat to, so the page is heavy or it is incomplete.
#
# 90s is three times the measured load. These jobs run at 4:45pm Friday and
# 11:30am Sunday with no deadline pressure; a slow capture costs seconds
# nobody is waiting on, while a failed one costs the whole lineup.
_NAV_TIMEOUT_MS = 90000

# One retry on a navigation timeout. The measured failure is a page that is
# slow, not a page that is broken - so the second attempt usually succeeds,
# and when it does not the error is the same one the caller already handles.
# Deliberately ONE retry, not a loop: four position pages plus four
# rest-of-season pages times unbounded retries is how a background job turns
# into a hung one.
_NAV_RETRIES = 1


# Pulls, per `<tr>`, the row's own rendered text (`tr.innerText`, the exact
# per-element algorithm `page.inner_text("body")` also uses, just scoped to
# one subtree) and the CBS id lifted from a `playerpage/<id>` link inside
# it - `tr a[href*='playerpage/']`, verified live 2026-08-30 to pair 100 of
# 107 rows on the RB-WR-TE page, 98/98 on K, and - genuinely surprising,
# corrected from an earlier assumption baked into this task's brief - ALSO
# 32/32 on BOTH the TQB and DST pages. A TQB/DST "player" IS an NFL team's
# aggregate unit, not a person, but CBS still gives each one its own
# synthetic `playerpage/<id>` - and, confirmed on the live Chargers rows,
# its TQB unit (1974) and DST unit (1924) get DIFFERENT ids, so this is a
# genuinely distinguishing id per (team, unit-type), not a shared team id
# that would collide the two. A `<tr>` with no such link (page furniture,
# an ad) is simply absent from the returned list - `_prefix_ids` below
# treats "no entry for this row" identically to "this row's own text could
# not be found," i.e. it is emitted unchanged.
_ID_EXTRACT_JS = """
() => {
  const rows = [];
  document.querySelectorAll('tr').forEach(tr => {
    const a = tr.querySelector("a[href*='playerpage/']");
    if (!a) return;
    const href = a.getAttribute('href') || '';
    const m = href.match(/playerpage\\/(\\d+)/);
    if (!m) return;
    const text = tr.innerText;
    if (!text) return;
    rows.push({id: m[1], text: text});
  });
  return {full: document.body.innerText, rows: rows};
}
"""


def _prefix_ids(full_text, rows):
    """Insert `"id=<id>\\t"` immediately before each identified row's own
    text within `full_text`, leaving every other character - including
    every id-less row (page furniture; a TQB/DST row DOES normally get an
    id too, see `_ID_EXTRACT_JS`'s comment above) - byte-for-byte unchanged.

    `rows` is `[{"id": ..., "text": ...}, ...]` in DOCUMENT ORDER (as
    `document.querySelectorAll('tr')` returns them) - assumed to also be
    the order those rows' own text appears in `full_text`, which holds for
    ordinary top-to-bottom table layout (no CSS reordering of table rows).
    Pure and independent of Playwright/the DOM, so it is unit-testable
    without a browser - see `_ID_EXTRACT_JS` above for how `rows` and
    `full_text` are actually produced from a live page.

    A row whose own text cannot be located (verbatim, at or after where
    the previous row's search left off) is skipped rather than raising -
    the row's untouched text still reaches the output via the final
    `full_text[cursor:]` append, exactly as if it had never been paired
    with an id at all. Losing one row's id to an unexpected layout quirk
    is far cheaper than losing (or corrupting) the whole page.

    THE PREFIX LANDS RIGHT AT THE START OF THE LAST NON-BLANK LINE IN THE
    ROW'S OWN TEXT, not at its literal first character - verified necessary
    live,
    2026-08-30: a `<tr>`'s `innerText` can start with a hidden cell's
    rendered content (whitespace, OR - confirmed on a real page, review
    round 1 - a short non-blank label like an action button's "Add")
    followed by a line break BEFORE the row's real content - e.g.
    `" \n\tSgt Hu...\t..."` for the Chargers TQB row. Inserting at the
    literal start would put `"id=1974\t"` on its OWN throwaway line
    ("id=1974\t "), orphaned from the actual content line the parser reads
    next - a silent, total loss of every id on every page this happens on.

    GENERAL ON PURPOSE, NOT "SKIP LEADING BLANK SEGMENTS": an earlier
    version of this function only skipped past a leading segment if it was
    blank once stripped, which is exactly wrong for a leading NON-blank
    cell ("Add\n\t..." - confirmed live, this shape already exists on real
    pages: the roster page's rows have no leading blank at all, while the
    DST projections page's rows have `' '` on 32 of 32 - one CBS layout
    tweak away from a THIRD shape appearing) - that version would stop at
    the first non-blank segment and insert there, re-orphaning the id
    exactly as before, SILENTLY (no exception, no warning - a page in that
    shape parses every row with `player_id == ""` and nothing says so).
    Anchoring on the START of the LAST NON-BLANK line instead does not need
    to know or guess WHAT is in any leading segment - blank, "Add", or
    anything else - it is content-agnostic and correct for every shape
    observed so far, and a row with no embedded newline at all (the
    ordinary case, no quirk) still gets offset 0, unchanged from inserting
    at the literal start.

    THIS MUST BE THE LAST NON-BLANK LINE, NOT SIMPLY THE LAST NEWLINE:
    review round 2 caught the mirror-image bug an earlier version had - a
    row's real content followed by a TRAILING empty or whitespace-only
    cell (`"\\tChargers\\t18.4\\n"`, or `"\\tChargers\\t18.4\\n "`) puts a
    "\\n" AFTER the content, so anchoring on the literal last "\\n" lands
    the prefix past the row's own content entirely - either onto the START
    OF THE NEXT ROW's text (a silent WRONG-PLAYER join: the id remains
    present and unique, so neither `ID COVERAGE LOST` nor a duplicate-id
    warning fires) or onto a trailing blank line of this row's own text
    (a silent, total loss of this row's id - caught by `cbs_weekly`'s
    unmatched-line watchdog but SILENT in `cbs_roster`, exactly as
    described above for an all-blank row). Skipping backward past any
    trailing blank line(s) to the last line that actually has content
    fixes both: the row with no trailing quirk is unaffected (its last
    line already has content, so behavior is unchanged), and a row with a
    trailing blank line gets the prefix anchored on its real content,
    never on a neighbor's.

    A ROW WHOSE OWN TEXT IS BLANK ON EVERY LINE (no real content anywhere,
    a genuinely degenerate row) IS SKIPPED ENTIRELY, not merely un-offset.
    Review round 1 caught the alternative: anchoring on the last newline of
    an all-blank `row_text` still lands somewhere WITHIN that blank span,
    which can sit at or past the boundary where the NEXT row's own text
    begins in `full_text` - migrating this row's id prefix onto the
    FOLLOWING row's line (`"id=A\tid=B\t..."`), which then fails to parse
    as ANY recognized row - loud (raises) in `cbs_weekly` (the merged
    text still contains " • ", so it is caught as an unmatched line), but
    a SILENT drop in `cbs_roster` (`_ROW` has no such watchdog - a line
    that fails to match is simply skipped, no warning). A row with nothing
    to identify is skipped up front instead, leaving its own (blank, inert)
    text untouched and never touching its neighbor's.
    """
    cursor = 0        # up to here, `pieces` already accounts for `full_text`
    search_from = 0   # where the NEXT row's `.find` should start looking
    pieces = []
    for row in rows:
        row_text = row["text"]
        if not row_text or not row_text.strip():
            continue
        idx = full_text.find(row_text, search_from)
        if idx == -1:
            continue
        # Anchor on the START of the LAST NON-BLANK line, not merely the
        # last "\n" - a trailing empty/whitespace-only cell puts a "\n"
        # AFTER the real content, and anchoring on that literal last "\n"
        # would land the prefix past the row's own content (see docstring).
        lines = row_text.split("\n")
        last_nonblank = 0
        for i, line in enumerate(lines):
            if line.strip():
                last_nonblank = i
        offset = sum(len(l) + 1 for l in lines[:last_nonblank])
        content_idx = idx + offset
        pieces.append(full_text[cursor:content_idx])
        pieces.append("id=%s\t" % row["id"])
        cursor = content_idx
        search_from = idx + len(row_text)
    pieces.append(full_text[cursor:])
    return "".join(pieces)


def _capture_page_text(page):
    """The page's body text, with each identifiable player row prefixed by
    its own `id=<id>\\t` - see `_ID_EXTRACT_JS` and `_prefix_ids` above.

    One `page.evaluate` round trip per page: extracting `rows` and
    `full_text` together, rather than a separate `page.inner_text("body")`
    call plus N separate `tr.inner_text()` calls, avoids a race where the
    page could re-render (client-side, as CBS's pages do - see
    `_SETTLE_WAIT_MS`) between the two and produce a `full_text` that no
    longer matches the `rows` extracted from a different render pass.
    """
    data = page.evaluate(_ID_EXTRACT_JS)
    return _prefix_ids(data["full"], data["rows"])


class CaptureError(Exception):
    """A page was fetched but must not be used."""


class SessionExpired(CaptureError):
    """CBS served its login page - the stored browser profile needs a re-login."""


def _is_session_expired(title, url):
    """Return True if the page title or final URL indicate an expired session.

    Used by both the capture validation and the manual login script to detect
    when a redirect to the CBS login page has occurred.
    """
    return SESSION_EXPIRED_TITLE in title or "/login" in url


def check_page_text(text, url, title=""):
    """Raise unless `text` is plausibly the real page for `url`.

    Arguments:
      text: the body text of the page - Task 3b review round 1 note: this
        is called on the ALREADY id-PREFIXED text (see `capture()` below,
        which runs `_capture_page_text` before this), so the
        `_MIN_PLAUSIBLE_CHARS` floor is technically measured on text a
        little LONGER than the raw page (every `id=<id>\t` prefix adds a
        handful of characters, once per identifiable row - a few hundred
        to low thousands of characters on a real page with ~100 rows).
        Negligible against a 1000-character floor and a real page that is
        thousands of characters either way, so this is not a correctness
        issue - noted here so nobody re-derives the discrepancy from
        scratch on a future pass through this file.
      url: the final URL (after redirects), to detect /login redirects
      title: the HTML page title (the <title> tag), to detect CBS login pages

    Returns None on success so callers read as `check_page_text(...)` followed
    by a write, rather than threading a boolean nobody checks.

    Session expiry is checked first so the specific "log in again" diagnosis
    wins over generic "too short" or "empty page" errors — it's the actionable one.
    """
    # Check for session expiry by title and/or redirect to /login.
    # Title never appears in body text, so we need it explicitly.
    # URL check catches cases where the title is unhelpful or missing.
    if _is_session_expired(title, url):
        raise SessionExpired(
            "%s returned the CBS sign-in page, so the stored browser profile "
            "is no longer logged in. Nothing was saved - a login page parses "
            "to an EMPTY roster, which would read downstream as 'Jeff rosters "
            "nobody' rather than as a failure. Re-run "
            "`./.venv/bin/python ops/cbs_login.py` to log in again." % url)
    if not text.strip():
        raise CaptureError("%s returned an empty page - nothing saved" % url)
    if len(text) < _MIN_PLAUSIBLE_CHARS:
        raise CaptureError(
            "%s returned only %d characters, below the %d-character floor for "
            "a real CBS page - this is an interstitial or an error page, not "
            "a roster. Nothing saved."
            % (url, len(text), _MIN_PLAUSIBLE_CHARS))
    return None


def _goto_with_retry(page, url, timeout_ms):
    """`page.goto`, retried once on timeout. Raises the LAST timeout.

    Separate from `capture` so the retry policy is one readable thing rather
    than control flow threaded through the capture loop. See `_NAV_RETRIES`.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    last = None
    for attempt in range(_NAV_RETRIES + 1):
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return
        except PlaywrightTimeoutError as exc:
            last = exc
    raise last


def capture(urls, out_dir, profile_dir, timeout_ms=_NAV_TIMEOUT_MS):
    """Fetch each url with the stored login and save its text. Returns {url: path}.

    Each PLAYER ROW's saved text is prefixed with its own CBS
    `id=<id>\\t`, when the row could be paired with a `playerpage/<id>`
    link - see `_capture_page_text`/`_prefix_ids` above, and
    `sffl.cbs_weekly`/`sffl.cbs_roster` for where that prefix is parsed
    back out. This covers not just individual players but also TQB/DST
    team-aggregate rows (verified live 2026-08-30 - see `_ID_EXTRACT_JS`'s
    comment). A row with no such link (page furniture, an ad) is saved
    completely unchanged - nothing that parsed this page's text before
    this existed stops parsing it now.

    NOT UNIT TESTED ON PURPOSE - it launches a browser. The logic worth
    testing is pure and called here on every page: `check_page_text` and
    `_prefix_ids` (see their own tests).
    """
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    if not os.path.isdir(profile_dir):
        raise CaptureError(
            "no browser profile at %s - run "
            "`./.venv/bin/python ops/cbs_login.py` once to create it and log "
            "in to CBS" % profile_dir)

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    written = {}
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            profile_dir, headless=True, timeout=timeout_ms)
        try:
            page = ctx.new_page()
            for name, url in urls.items():
                # domcontentloaded, not networkidle: see _SETTLE_WAIT_MS above
                # for why networkidle hangs forever on the authenticated site.
                try:
                    _goto_with_retry(page, url, timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise CaptureError(
                        "timed out navigating to %s after %dms x %d attempt(s) "
                        "- CBS may be slow, unreachable, or stuck on an "
                        "interstitial. Nothing saved. (%s)"
                        % (url, timeout_ms, _NAV_RETRIES + 1, exc)) from exc
                # Blind settle wait: the DOM is ready but CBS renders the
                # roster client-side afterward. See _SETTLE_WAIT_MS comment.
                page.wait_for_timeout(_SETTLE_WAIT_MS)
                text = _capture_page_text(page)
                # Pass the final URL (after redirects) and page title, not the
                # requested URL. A redirect to /login is invisible in requested URL
                # but visible in page.url. Title never appears in body text.
                check_page_text(text, page.url, page.title())
                path = os.path.join(out_dir, "%s.txt" % name)
                with open(path, "w") as fh:
                    fh.write(text)
                written[url] = path
        finally:
            ctx.close()
    return written
