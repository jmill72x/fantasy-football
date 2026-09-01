"""Drive CBS's set-lineup UI. The ONLY module here that can change a roster.

NOT UNIT TESTED, ON PURPOSE - it launches a browser and mutates a live team.
The logic worth testing is pure and lives in `sffl.lineup_write`; this file
is the thin, dangerous part, kept small so all of it can be read at once.

WHAT CBS ACTUALLY DOES, measured live 2026-09-01:

  * `/teams` is Jeff's own roster, resolved from the session - never built
    from a team id. Constructing one is how this project twice landed on
    another manager's roster, so it is not done here at any point.
  * Pressing "Set Lineup" on that page switches it into edit mode IN PLACE
    (the URL does not change; the body HTML shrinks from ~252k to ~184k).
  * In edit mode every roster row gains a `div.moveSource` button and carries
    its CBS player id in a `playerpage/<id>` link. Ids are the join key
    throughout - no name matching anywhere in the write path.
  * SWAPS ARE CLIENT-SIDE UNTIL COMMITTED. Clicking source then target
    rearranges the DOM and sends NO request (verified by watching the
    network: the only non-GET during a swap is a Taboola analytics beacon).
    The SAME "Set Lineup" button then commits them, POSTing to
    /teams/set-lineup with hidden point=<week> and team=<id>.
    An earlier version of this module concluded there was no save control -
    it had searched for the words save/submit/apply/done and "Set Lineup"
    matches none of them - and therefore reloaded after each swap to verify
    it, which THREW THE UNCOMMITTED CHANGES AWAY and made every run report
    "0 of 1 swaps applied" against a lineup it had in fact rearranged
    correctly. The commit being atomic is good news: all swaps land together
    or none do, so a partial application is not a state this can produce.
"""

import re

from sffl.lineup_write import LineupSlot, verify_applied

LEAGUE_BASE = "https://stripesfantasyfootballleague.football.cbssports.com"
TEAM_URL = LEAGUE_BASE + "/teams"

# Rows above this marker are starters; rows below are reserves. The same
# marker `sffl.cbs_roster` splits on, and for the same reason: CBS does not
# label the starting slots, it just orders them first.
_RESERVES = "RESERVES"

_READ_ROWS_JS = """() => {
  const marker = Array.from(document.querySelectorAll('tr'))
    .findIndex(r => (r.innerText || '').trim().toUpperCase().startsWith('RESERVES'));
  const rows = Array.from(document.querySelectorAll('tr'));
  const out = [];
  rows.forEach((r, i) => {
    const a = r.querySelector('a[href*=playerpage]');
    if (!a) return;
    const m = (a.getAttribute('href') || '').match(/playerpage\\/(\\d+)/);
    if (!m) return;
    out.push({
      player_id: m[1],
      name: (a.textContent || '').trim(),
      pos: r.cells && r.cells[1] ? r.cells[1].innerText.trim() : '',
      starting: marker === -1 ? true : i < marker,
      has_button: !!r.querySelector('.moveSource')
    });
  });
  return out;
}"""


class LineupWriteError(Exception):
    """Refused or failed. Carries what was applied - see `apply_swaps`."""


def _read_rows(page):
    return [LineupSlot(r["player_id"], r["name"], r["pos"], r["starting"])
            for r in page.evaluate(_READ_ROWS_JS)]


def open_edit_mode(page):
    """Navigate to Jeff's own team page and switch it into edit mode.

    Returns the rows as `LineupSlot`s. Raises if edit mode did not engage -
    detected by the move buttons appearing, not by a URL change, because the
    URL does not change.
    """
    page.goto(TEAM_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)
    button = page.locator("input[type=submit][value='Set Lineup']")
    if button.count() == 0:
        raise LineupWriteError(
            "no 'Set Lineup' control on %s - either the session expired (the "
            "page is a login form) or CBS changed this page. Refusing to "
            "guess at a write URL: constructing one is how this project "
            "twice operated on another manager's roster." % TEAM_URL)
    button.first.click(timeout=15000)
    page.wait_for_timeout(8000)
    rows = _read_rows(page)
    if not rows:
        raise LineupWriteError(
            "edit mode showed no roster rows - CBS has served this state "
            "before ('A ROSTER HAS NOT BEEN LOADED FOR THIS TEAM'), and "
            "clicking into it would move players that are not there")
    if not any(r for r in page.evaluate(_READ_ROWS_JS) if r["has_button"]):
        raise LineupWriteError(
            "roster rows loaded but none carry a move button - the page is "
            "not in edit mode, so a click would do nothing while this code "
            "reported progress")
    return rows


def _row(page, player_id, cls):
    return page.locator("tr:has(a[href*='playerpage/%s']) .%s"
                        % (player_id, cls))


def _cancel_pending(page):
    """Abort a half-started move so the page is left in a clean state.

    Called on every failure path after a source click. Without it the run
    would exit with a player still selected, and the next run's first click
    would land as a TARGET of the stale selection instead of a new source.
    """
    cancel = page.locator(".moveCancel")
    if cancel.count():
        try:
            cancel.first.click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass


def _swap(page, bench_id, promote_id):
    """One swap: select the starter, then click the promoted player.

    THE TWO CLICKS ARE NOT THE SAME CONTROL, which cost a failed live run to
    learn. Measured 2026-09-01: clicking a row's `.moveSource` re-renders the
    page - that row becomes `.moveCancel`, and only the POSITION-ELIGIBLE
    destinations become `.moveTarget` (2 of 12 rows, not all of them). So the
    second click must find `.moveTarget`, and its absence means CBS considers
    the swap illegal rather than that the row is missing.
    """
    src = _row(page, bench_id, "moveSource")
    if src.count() == 0:
        raise LineupWriteError(
            "no move button for player id %s - refusing to click a row this "
            "code cannot identify" % bench_id)
    src.first.click(timeout=15000)
    page.wait_for_timeout(3500)

    tgt = _row(page, promote_id, "moveTarget")
    if tgt.count() == 0:
        _cancel_pending(page)
        raise LineupWriteError(
            "CBS does not offer player id %s as a destination for this move, "
            "so the swap is not legal at these positions - the pending move "
            "was cancelled and nothing was changed. Eligible destinations "
            "were: %s" % (promote_id, ", ".join(_eligible_ids(page)) or "none"))
    tgt.first.click(timeout=15000)
    page.wait_for_timeout(3500)


def _eligible_ids(page):
    """Which player ids CBS is currently offering as move destinations."""
    return page.evaluate("""() => Array.from(document.querySelectorAll('tr'))
        .filter(r => r.querySelector('.moveTarget'))
        .map(r => {
          const a = r.querySelector('a[href*=playerpage]');
          const m = (a && a.getAttribute('href') || '').match(/playerpage\\/(\\d+)/);
          return m ? m[1] : '?';
        })""")


def apply_swaps(page, swaps, target_ids, on_step=None):
    """Apply every swap, then COMMIT once. Returns the number applied.

    The swaps are client-side rearrangements; nothing reaches CBS until the
    "Set Lineup" button is pressed at the end, so this deliberately does NOT
    reload between steps - doing so discards the uncommitted work, which is
    exactly the bug that made an earlier version report zero swaps applied
    against a correctly rearranged page.

    The DOM is checked after every swap anyway. That is not about durability
    (nothing is durable yet) but about not stacking a second swap on top of a
    first that silently did not take - the second's eligible destinations
    depend on where the first left things.

    Raises `LineupWriteError` before the commit if anything diverges, in
    which case NOTHING has been sent and the lineup on CBS is untouched.
    """
    for i, swap in enumerate(swaps, 1):
        if on_step:
            on_step(i, swap)
        _swap(page, swap.bench_id, swap.promote_id)
        rows = _read_rows(page)
        now = set(r.player_id for r in rows if r.starting)
        if swap.promote_id not in now or swap.bench_id in now:
            _cancel_pending(page)
            raise LineupWriteError(
                "step %d (bench %s, start %s) did not rearrange the page as "
                "planned. NOTHING HAS BEEN SENT to CBS - the lineup there is "
                "unchanged - because the commit happens only after every swap "
                "succeeds. Starters shown now: %s"
                % (i, swap.bench_name, swap.promote_name, ", ".join(sorted(now))))

    staged = set(r.player_id for r in _read_rows(page) if r.starting)
    if staged != set(target_ids):
        _cancel_pending(page)
        raise LineupWriteError(
            "the rearranged page does not match the target lineup, so it was "
            "NOT committed and CBS is unchanged. Staged: %s. Wanted: %s."
            % (", ".join(sorted(staged)), ", ".join(sorted(target_ids))))

    commit = page.locator("input[type=submit][value='Set Lineup']")
    if commit.count() == 0:
        raise LineupWriteError(
            "no 'Set Lineup' control to commit with - the swaps are staged in "
            "the browser only and have NOT been sent")
    commit.first.click(timeout=15000)
    page.wait_for_timeout(8000)

    # Only now is anything durable. Re-read from a fresh navigation rather
    # than trusting the post-submit render.
    page.goto(TEAM_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)
    ok, wrong, missing = verify_applied(_read_rows(page), target_ids)
    if not ok:
        raise LineupWriteError(
            "the lineup was submitted but CBS did not save it as planned. "
            "Wrongly starting: %s. Missing: %s. Check CBS directly."
            % (", ".join(wrong) or "none", ", ".join(missing) or "none"))
    return len(swaps)
