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
  * THERE IS NO SAVE BUTTON. Measured: zero save/submit/apply/done controls
    on the page in edit mode. Each move applies on its own and there is
    nothing to roll back, which is why `apply_swaps` re-reads and verifies
    after EVERY step and stops at the first divergence rather than pressing
    on and reporting a success it cannot support.
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


def _click_player(page, player_id):
    """Press one row's move button, addressed by CBS player id."""
    sel = ("tr:has(a[href*='playerpage/%s']) .moveSource" % player_id)
    loc = page.locator(sel)
    if loc.count() == 0:
        raise LineupWriteError(
            "no move button for player id %s - refusing to click a row this "
            "code cannot identify" % player_id)
    loc.first.click(timeout=15000)
    page.wait_for_timeout(3500)


def apply_swaps(page, swaps, target_ids, on_step=None):
    """Apply `swaps` one at a time, verifying after each. Returns applied count.

    STOPS AT THE FIRST DIVERGENCE. CBS applies each move as it happens and
    offers no save or undo, so the only safe posture is to check the board
    after every step and refuse to continue once it stops matching the plan.
    The count returned is what actually landed; the caller must report that
    number rather than the number requested.

    Raises `LineupWriteError` naming the step that failed AND how many
    preceding steps are still applied, because that is the state the human
    now has to reconcile.
    """
    applied = 0
    for i, swap in enumerate(swaps, 1):
        if on_step:
            on_step(i, swap)
        _click_player(page, swap.bench_id)
        _click_player(page, swap.promote_id)
        page.reload(wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        rows = _read_rows(page)
        now = set(r.player_id for r in rows if r.starting)
        expected_after = set(target_ids)
        for later in swaps[i:]:
            expected_after.discard(later.promote_id)
            expected_after.add(later.bench_id)
        if now != expected_after:
            raise LineupWriteError(
                "step %d (bench %s, start %s) did not take effect as planned. "
                "%d of %d swaps are APPLIED and cannot be rolled back by this "
                "tool. Expected starters after this step: %s. Actually "
                "starting: %s. Fix the rest on CBS directly."
                % (i, swap.bench_name, swap.promote_name, applied, len(swaps),
                   ", ".join(sorted(expected_after)), ", ".join(sorted(now))))
        applied += 1
    ok, wrong, missing = verify_applied(_read_rows(page), target_ids)
    if not ok:
        raise LineupWriteError(
            "all %d swaps reported success but the final lineup does not "
            "match the target. Wrongly starting: %s. Missing: %s."
            % (applied, ", ".join(wrong) or "none",
               ", ".join(missing) or "none"))
    return applied
