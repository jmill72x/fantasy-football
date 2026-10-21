"""Guard: no real CBS ids and no licensed vendor or CBS rows in tests/fixtures/.

This repo is public. The fixtures were cleaned on 2026-10-19 (see
tests/fixtures/README.md): the CBS pages are constructed copies and the Draft
Sharks samples carry invented numbers. These tests stop real data creeping
back in, by comparing every fixture line with the licensed originals in the
PRIVATE data repo (jmill72x/fantasy-football-data), read at runtime.

- The reference is never embedded here and never printed. A failure names the
  fixture file, the line number and the kind of match, nothing else, and is
  raised without a traceback so no local variable is shown either.
- Without the data repo (a fresh clone, CI) every check that needs it skips
  with a reason. Set SFFL_DATA_REPO if the clone is somewhere other than
  ~/Projects/fantasy-football-data.

Reference tiers, by data-repo path:

  vendor     */*/preseason/**/*.csv     Draft Sharks, Footballguys, FantasyPros
  snapshot   */cbs/snapshot-*/**/*.txt  the 2026-10-19 CBS captures and the
                                        real pages the fixtures replaced
  game-log   */cbs/game-logs/**/*.csv   the 2025 CBS game logs
  weekly     */cbs/weekly/**/*.txt      CBS pages `sffl collect` adds after
                                        every alert run; grows all season

What counts as a match (the private rescan tool,
~/.local/state/jarvis/reports/fantasy-rewrite-tools/rescan.py, is the deeper
check over the whole repo; these are the parts that guard the fixtures):

  real-cbs-id   an `id=` value, or a bare 6 to 8 digit token, that is a real
                CBS player id (an `id=` on any real CBS page, or a game log's
                player_id).
  numeric-run   a run of 4+ consecutive non-zero numbers (2+ of them with a
                decimal point or 3+ digits) that also runs, in order, in one
                reference row. Against vendor, snapshot and game-log rows any
                such run counts. Against weekly rows a short run with a
                DIFFERENT player's row is an expected coincidence: CBS
                projections are short decimals, and on 2026-10-19 16
                constructed fixture lines shared a 4- or 5-number run with
                another player's row in weeks 1 to 6. There a run counts only
                when the reference row names the same player as the fixture
                line, or when it is LONG_RUN numbers or more, as a copied
                row's is.
  name+values   a fixture line naming a reference player that also carries
                NAME_VALUES distinctive values (a decimal of 1 or more, or
                above 100) from one row of that same player. Not applied to
                weekly rows: the constructed rows keep real names on purpose,
                so over a season of weekly rows for the same player a few
                short decimals will coincide (2026-10-19, most shared with one
                row: weekly 3, vendor 2, snapshot 2, game log 1).

Known coincidences that still trip a rule go in ALLOWLIST, keyed on the exact
line (its sha256), so an entry stops applying the moment its line changes.
"""
import csv
import glob
import hashlib
import io
import os
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATA_REPO = Path(os.environ.get(
    "SFFL_DATA_REPO", "~/Projects/fantasy-football-data")).expanduser()

VENDOR_GLOBS = ("*/*/preseason/**/*.csv",)
SNAPSHOT_GLOBS = ("*/cbs/snapshot-*/**/*.txt",)
GAME_LOG_GLOBS = ("*/cbs/game-logs/**/*.csv",)
WEEKLY_GLOBS = ("*/cbs/weekly/**/*.txt",)
SKIP_REFERENCE_NAMES = {"COLLECTED.txt", "MANIFEST.sha256"}
STRICT_TIERS = {"vendor", "snapshot", "game-log"}

# Observed on 2026-10-19: different-player weekly runs reach 5 numbers; a
# copied CBS row runs 10 or more.
LONG_RUN = 8
NAME_VALUES = {"vendor": 4, "snapshot": 4, "game-log": 4}

# Whole fixture files left out of the scan, each by a recorded decision.
EXEMPT_FIXTURES = {
    # Real 2025 CBS game logs: the evidence behind the scoring validation,
    # kept by Jeff's decision (tests/fixtures/README.md, "Not cleaned").
    "weekly_sample.csv",
}

# (fixture file, kind, sha256 of the exact line without its newline) -> why.
# Each entry must be a checked coincidence: the matched reference row belongs
# to a different player, and the fixture row is constructed. Empty today: the
# two coincidences the private rescan reported on 2026-10-19
# (cbs_weekly_k.txt, Brandon Aubrey's row against Nick Folk's, and
# cbs_weekly_tab_rbwrte.txt, Calvin Ridley's against Mason Tipton's) are
# short different-player runs against weekly pages, which the numeric-run
# rule already passes.
ALLOWLIST = {}

NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
ID_TOKEN = re.compile(r"(?<![\w.])\d{6,8}(?![\w.])")
CBS_ID = re.compile(r"id=(\d+)")
CBS_NAME = re.compile(
    r"(?:^|\t| )([A-Z][\w.'-]*(?: [A-Z0-9][\w.'-]*)*) (?:[A-Z]{1,3} )?"
    r"(?:QB|RB|WR|TE|K|DST|TQB)(?: [A-Z]+)? •")
NAME_COLUMNS = ("Player", "player", "Name", "name", "PLAYER NAME")
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm(tok):
    v = float(tok)
    return None if v == 0 else repr(round(v, 4))


def _distinctive(tok):
    bare = tok.lstrip("-")
    return (("." in bare and not bare.endswith(".0"))
            or len(bare.split(".")[0]) >= 3)


def _valuable(tok):
    v = abs(float(tok))
    return (v >= 1 and v != int(v)) or v > 100


def _numbers(line):
    return [(t, _norm(t)) for t in NUM.findall(line.replace("\\t", " "))
            if _norm(t) is not None]


def _grams(seq):
    for i in range(len(seq) - 3):
        win = seq[i:i + 4]
        if sum(_distinctive(t) for t, _ in win) >= 2:
            yield i, tuple(n for _, n in win)


def _words(text):
    return re.sub(r"[\W_]+", " ", text.lower()).split()


def _name_key(name):
    words = _words(name)
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _line_key(line):
    """Padded so a name key matches only on whole words."""
    return " %s " % " ".join(_words(line))


def _sha(line):
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


class Reference(object):
    """The licensed reference, held in memory only. Its repr is redacted so a
    traceback or --showlocals can never print a value."""

    def __init__(self):
        self.ids = set()
        self.rows = []       # (tier, player key or "", {gram: first index})
        self.grams = {}      # gram -> [row index]
        self.valuables = {}  # (tier, player key) -> [values of one row]
        self.files = {}      # tier -> file count

    def __repr__(self):
        return "<Reference: %d files, %d rows, contents redacted>" % (
            sum(self.files.values()), len(self.rows))

    def add_row(self, tier, name, line):
        seq = _numbers(line)
        key = _name_key(name) if name else ""
        grams = {}
        for i, g in _grams(seq):
            grams.setdefault(g, i)
        if grams:
            idx = len(self.rows)
            self.rows.append((tier, key, grams))
            for g in grams:
                self.grams.setdefault(g, []).append(idx)
        if len(key) > 4 and tier in NAME_VALUES:
            vals = {n for t, n in seq if _valuable(t)}
            if vals:
                self.valuables.setdefault((tier, key), []).append(vals)


def _files(globs):
    out = set()
    for pattern in globs:
        out.update(p for p in glob.glob(str(DATA_REPO / pattern), recursive=True)
                   if os.path.basename(p) not in SKIP_REFERENCE_NAMES)
    return sorted(out)


def _add_csv(ref, tier, path):
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    raws = text.splitlines()
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return
    header = rows[0]
    ncol = next((i for i, h in enumerate(header) if h in NAME_COLUMNS), None)
    icol = header.index("player_id") if "player_id" in header else None
    for raw, row in zip(raws[1:], rows[1:]):
        name = row[ncol] if ncol is not None and ncol < len(row) else ""
        ref.add_row(tier, name, raw)
        if icol is not None and icol < len(row) and row[icol].isdigit():
            ref.ids.add(row[icol])


def _add_cbs_page(ref, tier, path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            ref.ids.update(CBS_ID.findall(line))
            m = CBS_NAME.search(line)
            ref.add_row(tier, m.group(1) if m else "", line)


def load_reference():
    ref = Reference()
    for tier, globs, loader in (
            ("vendor", VENDOR_GLOBS, _add_csv),
            ("snapshot", SNAPSHOT_GLOBS, _add_cbs_page),
            ("game-log", GAME_LOG_GLOBS, _add_csv),
            ("weekly", WEEKLY_GLOBS, _add_cbs_page)):
        paths = _files(globs)
        ref.files[tier] = len(paths)
        for p in paths:
            loader(ref, tier, p)
    return ref


def _real_id(ref, line):
    return any(t in ref.ids for t in CBS_ID.findall(line) + ID_TOKEN.findall(line))


def _longest_run(pairs):
    """Numbers in the longest stretch where consecutive fixture grams are
    consecutive grams of the reference row too (one shared gram is 4)."""
    have = set(pairs)
    best = 0
    for i, j in pairs:
        if (i - 1, j - 1) in have:
            continue
        n = 1
        while (i + n, j + n) in have:
            n += 1
        best = max(best, n + 3)
    return best


def _numeric_run(ref, line):
    shared = {}  # reference row -> [(fixture gram index, row gram index)]
    for i, g in _grams(_numbers(line)):
        for idx in ref.grams.get(g, ()):
            shared.setdefault(idx, []).append((i, ref.rows[idx][2][g]))
    key = _line_key(line)
    for idx, pairs in shared.items():
        tier, player, _ = ref.rows[idx]
        if (tier in STRICT_TIERS
                or (player and (" %s " % player) in key)
                or _longest_run(pairs) >= LONG_RUN):
            return True
    return False


def _name_values(ref, line):
    vals = {n for t, n in _numbers(line) if _valuable(t)}
    if len(vals) < min(NAME_VALUES.values()):
        return False
    key = _line_key(line)
    for (tier, player), rows in ref.valuables.items():
        if (" %s " % player) in key and any(
                len(vals & r) >= NAME_VALUES[tier] for r in rows):
            return True
    return False


CHECKS = (("real-cbs-id", _real_id), ("numeric-run", _numeric_run),
          ("name+values", _name_values))


def scan_lines(ref, name, lines):
    """Findings for one fixture as [(name, line number, kind)]. Never returns
    or records what matched."""
    findings = []
    for lineno, line in enumerate(lines, 1):
        line = line.rstrip("\r\n")
        for kind, check in CHECKS:
            if (name, kind, _sha(line)) not in ALLOWLIST and check(ref, line):
                findings.append((name, lineno, kind))
    return findings


def fixture_files():
    return sorted(p for p in FIXTURES.iterdir()
                  if p.is_file() and p.name not in EXEMPT_FIXTURES)


def scan_fixtures(ref):
    findings = []
    for p in fixture_files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_lines(ref, p.name, text.split("\n")))
    return findings


@pytest.fixture(scope="module")
def reference():
    if not (DATA_REPO / "MANIFEST.sha256").is_file():
        pytest.skip("private data repo not found at %s (fresh clone or CI); "
                    "the fixture guard needs its licensed reference. Set "
                    "SFFL_DATA_REPO to point at a clone." % DATA_REPO)
    ref = load_reference()
    empty = sorted(t for t, n in ref.files.items() if n == 0)
    if empty or not ref.ids:
        # The repo is there but a layout change hid a reference set: fail
        # rather than let the guard pass by reading nothing.
        pytest.fail("data repo at %s gave no %s reference; update the globs "
                    "in tests/test_fixture_guard.py"
                    % (DATA_REPO, ", ".join(empty) or "CBS id"), pytrace=False)
    return ref


@pytest.fixture(scope="module")
def findings(reference):
    return scan_fixtures(reference)


def _fail_on(findings, kinds, what):
    hits = [f for f in findings if f[2] in kinds]
    if hits:
        pytest.fail(
            "%s in tests/fixtures (file:line kind; the matched content is "
            "never shown, run the private rescan tool to see it):\n  %s"
            % (what, "\n  ".join("%s:%d %s" % h for h in hits)),
            pytrace=False)


def test_no_real_cbs_ids_in_fixtures(findings):
    _fail_on(findings, {"real-cbs-id"}, "real CBS player ids")


def test_no_vendor_or_cbs_rows_in_fixtures(findings):
    _fail_on(findings, {"numeric-run", "name+values"},
             "rows matching licensed vendor or CBS data")


# The self-tests plant a real line, read from the data repo at runtime, and
# scan it in memory: it is never written to disk or shown.

# Weeks 1 to 5 backfill: in no strict tier, so a hit exercises the weekly
# rules (same player, LONG_RUN) rather than "any run counts".
BACKFILL = ("*/cbs/weekly/*/*-backfill/RB-WR-TE.txt",)


def _real_line(globs, pattern):
    for path in _files(globs):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if re.search(pattern, line) and len(_numbers(line)) >= 12:
                    return line.rstrip("\n")
    pytest.fail("no usable real line found for the self-test", pytrace=False)


def _expect(reference, line, name, want):
    kinds = {k for _, _, k in scan_lines(reference, name, [line])}
    missing = sorted(set(want) - kinds)
    if missing:
        pytest.fail("planted row not flagged as %s (got %s)"
                    % (missing, sorted(kinds)), pytrace=False)


def test_guard_flags_a_planted_real_cbs_row(reference):
    real = _real_line(BACKFILL, r"id=\d+.*•")
    _expect(reference, real, "planted.txt", {"real-cbs-id", "numeric-run"})


def test_guard_flags_a_real_row_with_its_id_and_name_changed(reference):
    real = _real_line(BACKFILL, r"id=\d+.*•")
    disguised = CBS_NAME.sub(" Test Player WR •",
                             CBS_ID.sub("id=1234567", real))
    _expect(reference, disguised, "planted.txt", {"numeric-run"})


def test_guard_flags_a_planted_vendor_row(reference):
    real = _real_line(("*/draftsharks/preseason/*.csv",), r"[A-Za-z]")
    _expect(reference, real, "planted.csv", {"numeric-run", "name+values"})


# ---------------------------------------------- third-party news text (10-20)
#
# The direct injury feed and CBS's icon sidecars carry third-party text: ESPN's
# injury rows and comments, and CBS's news headlines (RotoWire's). Neither
# belongs in a fixture, constructed or not: a fixture is a CBS page. These
# shape checks need no private reference, so they run on a fresh clone too.

ESPN_ROW = re.compile(
    r'"(?:shortComment|longComment|fantasyStatus|returnDate)"\s*:'
    r'|"source"\s*:\s*"espn"|"espn_id"\s*:')
CBS_HEADLINE = re.compile(
    r'\bUpdate: [^:<>\n"]{2,80}: [^<>\n]{4,}|"subtab"\s*:\s*"Update"')
NEWS_CHECKS = (("espn-row", ESPN_ROW), ("cbs-headline", CBS_HEADLINE))


def scan_news(name, lines):
    """[(name, line number, kind)] for ESPN-shaped rows and CBS headlines."""
    return [(name, lineno, kind)
            for lineno, line in enumerate(lines, 1)
            for kind, pattern in NEWS_CHECKS if pattern.search(line)]


def test_no_espn_rows_or_cbs_headlines_in_fixtures():
    hits = []
    for p in fixture_files():
        try:
            hits.extend(scan_news(p.name, p.read_text(encoding="utf-8").split("\n")))
        except UnicodeDecodeError:
            continue
    _fail_on(hits, {"espn-row", "cbs-headline"},
             "third-party news text (ESPN rows or CBS headlines)")


@pytest.mark.parametrize("line,kind", [
    ('{"shortComment": "Example (knee) sat out.", "status": "Out"}', "espn-row"),
    ('  "source": "espn", "notes": "x"', "espn-row"),
    ("Update: Hawks' Pat Example: Gets 12 touches", "cbs-headline"),
    ('{"icon": "icon-news-note-recent", "subtab": "Update"}', "cbs-headline"),
])
def test_the_news_checks_flag_each_shape(line, kind):
    assert [k for _, _, k in scan_news("planted.txt", [line])] == [kind]


def test_the_news_checks_leave_ordinary_lines_alone():
    for line in ("Injury Report: <body part>: Questionable for Week 7",
                 "id=9000001\t\tWR\tPat Example WR \u2022 SEA\tMIA\t",
                 "`shortComment`, `longComment`"):
        assert scan_news("ok.txt", [line]) == [], line


def test_allowlist_entries_name_a_current_fixture_line():
    """An entry whose line changed or went away is dead weight: drop it."""
    current = set()
    for p in fixture_files():
        current.update((p.name, _sha(x.rstrip("\r")))
                       for x in p.read_text(encoding="utf-8").split("\n"))
    stale = sorted("%s %s" % (f, kind) for (f, kind, digest) in ALLOWLIST
                   if (f, digest) not in current)
    assert not stale, "stale ALLOWLIST entries: %s" % stale
