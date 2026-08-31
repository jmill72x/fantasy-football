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
_NAV_TIMEOUT_MS = 30000


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

    THE PREFIX LANDS AFTER ANY LEADING BLANK LINE(S) WITHIN THE ROW'S OWN
    TEXT, not at its literal first character - verified necessary live,
    2026-08-30: a `<tr>`'s `innerText` can start with a hidden cell's
    rendered whitespace (CBS's action-buttons column, e.g.) followed by a
    line break BEFORE the row's real content - e.g. `" \n\tSgt Hu...\t..."`
    for the Chargers TQB row. Inserting at the literal start would put
    `"id=1974\t"` on its OWN throwaway line ("id=1974\t "), orphaned from
    the actual content line the parser reads next - a silent, total loss of
    every id on every page this happens on, discovered only by parsing a
    real capture and checking `player_id` (see `sffl.cbs_weekly`'s tests).
    Every leading `\n`-terminated segment that is blank once stripped is
    skipped past; a row with no such quirk (the ordinary case) sees this
    skip past nothing (offset 0), unchanged from inserting at the start.
    """
    cursor = 0        # up to here, `pieces` already accounts for `full_text`
    search_from = 0   # where the NEXT row's `.find` should start looking
    pieces = []
    for row in rows:
        row_text = row["text"]
        if not row_text:
            continue
        idx = full_text.find(row_text, search_from)
        if idx == -1:
            continue
        offset = 0
        for segment in row_text.split("\n")[:-1]:
            if segment.strip():
                break
            offset += len(segment) + 1  # +1 for the "\n" this segment ends on
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
      text: the body text of the page
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
                    page.goto(url, timeout=timeout_ms,
                              wait_until="domcontentloaded")
                except PlaywrightTimeoutError as exc:
                    raise CaptureError(
                        "timed out navigating to %s after %dms - CBS may be "
                        "slow, unreachable, or stuck on an interstitial. "
                        "Nothing saved. (%s)" % (url, timeout_ms, exc)) from exc
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
