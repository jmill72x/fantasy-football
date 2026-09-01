"""Submit a CBS waiver claim (one add, one drop). The other write path.

NOT UNIT TESTED, ON PURPOSE - it launches a browser and changes a real
roster. The decisions worth testing are pure and live in `sffl.lineup` /
`sffl.trade`; this file is the thin, dangerous part, kept small enough to
read in one sitting.

WHAT CBS ACTUALLY DOES, measured live 2026-09-01:

  * A free agent's row carries `a.addPlayerSm` pointing at
    `/stats/stats-main?default_add=<POS>:<id>`. Opening that URL STAGES the
    add and renders a transaction panel; it sends nothing.
  * The panel then prints "SELECT PLAYER TO DROP OR CLICK SUBMIT TO
    CONTINUE" above Jeff's own roster, where each row's edit cell holds
    `<a onclick="setSelectedDropPlayer(<id>, 'drop')" title="Drop">`.
    Clicking it stages the drop, still client-side.
  * The form POSTs to `/transactions/add-drop` and carries a CSRF-ish
    `form::_eid_`, plus two checkboxes:
      - `form::state`        "Add this move to the list of pending waiver
                             offers (don't execute it immediately)"
      - `form::move_to_top`  "Move to top of pending offers"
  * The panel states the consequences itself: "You have 5 waiver offers
    remaining this period" and "This transaction will be processed on 9/16
    and will be effective Week 2."

WHY THE DEFAULT IS A PENDING OFFER. `form::state` is checked by default
here, so a claim JOINS THE WAIVER QUEUE rather than executing at once. A
queued offer sits in "PENDING ADD/DROPS" for days and Jeff can cancel it;
an immediate execution drops a real player the moment it is submitted, and
this project's own rule is that a drop is the one thing that can actually
cost something. `--now` turns that off, deliberately and explicitly.
"""

LEAGUE_BASE = "https://stripesfantasyfootballleague.football.cbssports.com"
STAGE_URL = LEAGUE_BASE + "/stats/stats-main?default_add=%s:%s"


class ClaimError(Exception):
    """Refused, or failed. Nothing has been submitted when this is raised
    before `submit_claim`'s final click - see that function."""


def stage_add(page, pos, add_id):
    """Open the claim page with `add_id` staged. Sends nothing."""
    page.goto(STAGE_URL % (pos, add_id), wait_until="domcontentloaded",
              timeout=45000)
    page.wait_for_timeout(8000)
    body = page.inner_text("body")
    if "SELECT PLAYER TO DROP" not in body.upper():
        raise ClaimError(
            "the add did not stage - CBS did not offer a drop list for player "
            "id %s at %s. Nothing was submitted. This usually means the "
            "player is not actually a free agent." % (add_id, pos))
    return body


def droppable_ids(page):
    """Player ids CBS is offering as the drop, straight off its own links.

    Read from the `setSelectedDropPlayer(<id>, 'drop')` handlers rather than
    from a roster the caller supplies, so the claim can only ever drop
    someone CBS itself listed as droppable on this page.
    """
    return page.evaluate("""() => Array.from(
        document.querySelectorAll("a[onclick*=setSelectedDropPlayer]"))
        .map(a => (a.getAttribute('onclick')||'')
                   .match(/setSelectedDropPlayer\\((\\d+)/))
        .filter(Boolean).map(m => m[1])""")


def select_drop(page, drop_id):
    """Stage the drop. Still client-side; nothing is sent."""
    offered = droppable_ids(page)
    if drop_id not in offered:
        raise ClaimError(
            "CBS does not list player id %s as droppable on this claim - "
            "refusing to click a row it did not offer. Nothing was "
            "submitted. Offered: %s"
            % (drop_id, ", ".join(offered) or "none"))
    page.locator("a[onclick*='setSelectedDropPlayer(%s,']" % drop_id).first.click(
        timeout=15000)
    page.wait_for_timeout(3000)


def _set_checkbox(page, name, want):
    box = page.locator("input[name='%s']" % name)
    if box.count() == 0:
        return False
    if box.first.is_checked() != want:
        box.first.click(timeout=10000)
        page.wait_for_timeout(1500)
    return True


def submit_claim(page, queue_as_waiver=True, move_to_top=False):
    """Press Submit. THIS IS THE POINT OF NO RETURN for this module.

    Everything before this call is staged in the browser and sends nothing.
    Returns the panel text afterwards so the caller can quote CBS's own
    confirmation rather than asserting success on its own authority.
    """
    _set_checkbox(page, "form::state", queue_as_waiver)
    _set_checkbox(page, "form::move_to_top", move_to_top)
    button = page.locator("input[name='submit']")
    if button.count() == 0:
        raise ClaimError(
            "no Submit control on the staged claim - nothing was sent")
    button.first.click(timeout=20000)
    page.wait_for_timeout(9000)
    return page.inner_text("body")


def pending_claims(page):
    """What CBS currently lists under PENDING ADD/DROPS, as text.

    Used to VERIFY after submitting: this module never reports a claim as
    filed on the strength of having clicked a button.
    """
    page.goto(LEAGUE_BASE + "/transactions", wait_until="domcontentloaded",
              timeout=45000)
    page.wait_for_timeout(6000)
    return page.inner_text("body")
