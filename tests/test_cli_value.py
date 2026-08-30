import pytest
from sffl.cli import main

DS = "sources/draftsharks.yaml"
# A dedicated fixture, not tests/fixtures/draftsharks_sample.csv: the value
# command needs at least one player in every replacement pool (TQB, FLEX, K,
# DST), and replacement_levels() raises if any pool is completely empty. The
# shared sample fixture has no kicker, so it adds a Test Kicker row on top of
# the same four players the other ingest/pool/scoring tests already use.
FIXTURE = "tests/fixtures/draftsharks_value_sample.csv"


TQB_2026 = "identity/tqb-2026-starters.yaml"


def test_value_command_runs_and_returns_zero(capsys):
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "$" in out


def test_fit_policy_requires_prices(capsys):
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "fit"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "--prices" in out


def test_value_writes_a_csv(tmp_path):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--out", path])
    assert rc == 0
    with open(path) as fh:
        header = fh.readline()
    assert "dollars" in header
    assert "spread" in header


PRICES = "tests/fixtures/prices_sample.csv"


def test_fit_policy_prints_the_match_denominator(capsys):
    # The bug this whole branch exists to fix was "108 of 156 prices joined,
    # and nothing said so" - the printed n must carry a denominator and the
    # shortfall, not just a bare match count.
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "fit", "--prices", PRICES,
               "--tqb-starters", TQB_2026])
    out = capsys.readouterr().out
    assert rc == 0
    assert "of 5 prices" in out
    assert "unmatched" in out
    # PRICES joins to exactly 1 observation, one short of fit_price_curve's
    # 8-observation minimum, so the EST$ curve fit also takes the "not
    # fitted" path on this run - confirm it says so out loud.
    assert "WARNING" in out


def test_tqb_starters_flag_is_accepted_and_overridable(capsys):
    # A future season's roster sheet needs its own starter map; the flag
    # must be plumbed through to load_prices rather than hardcoded.
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "fit", "--prices", PRICES,
               "--tqb-starters", TQB_2026])
    assert rc == 0


def test_a_starter_map_from_another_season_is_refused_not_quietly_used():
    """The guard the 2026 refit paid for.

    Valuing 2026 projections against 2025 prices produced a phantom $13.2
    top-end bias, an EST$ curve fitted to remove it, and a deferred code
    change waiting on evidence that never existed. Nothing in the output
    looked wrong. The season stamp makes it loud.
    """
    with pytest.raises(SystemExit) as e:
        main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
              "--policy", "fit", "--prices", PRICES,
              "--tqb-starters", "identity/tqb-2025-starters.yaml"])
    msg = str(e.value)
    # The guard now lives in fit.load_prices (Task 2), not in the CLI, so the
    # wording changed from "refusing to value... projections" to "refusing to
    # load... prices" -- but the refusal, and the two years it names, did not.
    assert "refusing to load 2026 prices" in msg
    assert "2025" in msg
    assert "identity/tqb-2025-starters.yaml" in msg


def test_est_price_column_appears_when_prices_are_supplied(tmp_path, capsys):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--prices", PRICES,
               "--tqb-starters", TQB_2026, "--out", path])
    out = capsys.readouterr().out
    assert rc == 0
    with open(path) as fh:
        header = fh.readline()
    assert "est_price" in header
    # PRICES joins to exactly 1 observation here (Ja'Marr Chase), one short
    # of fit_price_curve's 8-observation minimum, so this run takes the
    # "curve not fitted" path - assert the WARNING actually prints rather
    # than degrading silently.
    assert "WARNING" in out


def test_est_price_is_blank_without_prices(tmp_path):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--out", path])
    assert rc == 0
    with open(path) as fh:
        lines = fh.read().splitlines()
    header = lines[0].split(",")
    idx = header.index("est_price")
    # every data row leaves it empty rather than reporting a fabricated 0 or a
    # copy of dollars
    assert all(row.split(",")[idx] == "" for row in lines[1:])


# The fixtures above join to exactly 1 matched price (Ja'Marr Chase), well
# under fit_price_curve's 8-observation minimum, so every test using them
# exercises only the "curve not fitted" path - none of them proves _est_price
# is ever a real number, that EST$ ever prints on a board line, or that the
# bias table ever appears. This dedicated fixture pair joins 8 invented FLEX
# players (no real player names) with a monotonically increasing price, which
# is enough for fit_price_curve to succeed and exercise all three.
MARKET_FIT_FIXTURE = "tests/fixtures/draftsharks_market_fit_sample.csv"
MARKET_FIT_PRICES = "tests/fixtures/prices_market_fit_sample.csv"


def test_market_curve_fits_and_populates_est_price(tmp_path, capsys):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", MARKET_FIT_FIXTURE, "--year", "2026",
               "--policy", "starter", "--prices", MARKET_FIT_PRICES,
               "--tqb-starters", TQB_2026, "--out", path])
    out = capsys.readouterr().out
    assert rc == 0

    # the board line carries a real EST$ figure, not just the header
    assert "est $" in out
    # the bias table is the evidence the calibration worked, not just ran
    assert "bias against observed prices" in out

    with open(path) as fh:
        lines = fh.read().splitlines()
    header = lines[0].split(",")
    idx = header.index("est_price")
    values = [row.split(",")[idx] for row in lines[1:]]
    # at least one row carries an actual fitted number, parseable as a float
    assert any(v != "" for v in values)
    numeric = [v for v in values if v != ""]
    for v in numeric:
        float(v)  # raises if it is not a real number


def _strip_season_column(src, dest):
    """A copy of a prices CSV with its `season` column removed.

    Stands in for data/league/auction-rosters-2025.csv, which predates the
    column and must keep working. Built by removing the column rather than
    committing a second column-less fixture, so it cannot drift from the one
    the rest of these tests fit against.
    """
    import csv
    with open(src, newline="") as fh:
        reader = csv.DictReader(fh)
        fields = [f for f in reader.fieldnames if f != "season"]
        rows = [dict((k, r[k]) for k in fields) for r in reader]
    with open(dest, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return dest


def test_a_prices_file_that_cannot_state_its_season_says_so_on_stdout(tmp_path, capsys):
    # THE HEADLINE DEFECT. `prices_season` returned None for a column-less
    # file and the guard did not fire - no warning, no note, exit 0 - so
    # 2025 prices against 2026 projections fitted b=0.531 in silence and a
    # phantom top-end bias got a code change built to correct it.
    #
    # The verification half of Decision 2 shipped; this is the announcement
    # half. The file must still LOAD (the real 2025 file predates the
    # column), and the run must SAY it could not check.
    prices = _strip_season_column(MARKET_FIT_PRICES,
                                  str(tmp_path / "no_season.csv"))
    rc = main(["value", "--source", DS, "--file", MARKET_FIT_FIXTURE,
               "--year", "2026", "--policy", "fit", "--prices", prices,
               "--tqb-starters", TQB_2026])
    out = capsys.readouterr().out
    assert rc == 0, "a column-less file must keep working on value/render"
    assert "UNVERIFIED PRICES SEASON" in out
    assert "no_season.csv" in out, "the announcement must name the file"
    assert "proxy" in out.lower(), (
        "it must explain that the season is taken on trust from the TQB map")
    # And it really did price the board - this is an announcement, not a
    # refusal, so everything downstream of the load must still have run.
    assert "market curve" in out


def test_a_prices_file_that_states_its_season_prints_no_such_note(capsys):
    # The complement. A banner on every run is a banner nobody reads.
    rc = main(["value", "--source", DS, "--file", MARKET_FIT_FIXTURE,
               "--year", "2026", "--policy", "fit", "--prices",
               MARKET_FIT_PRICES, "--tqb-starters", TQB_2026])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UNVERIFIED" not in out


def _intel_text(xlsx):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx)["Key & Intel"]
    return "\n".join(str(c) for row in ws.iter_rows(values_only=True)
                     for c in row if c is not None)


def test_stdout_and_the_workbook_agree_that_the_prices_season_is_unverified(tmp_path, capsys):
    # Same class as the cross-season finding, on the other branch of the
    # condition: stdout printed the UNVERIFIED PRICES SEASON banner while the
    # workbook asserted "year-matched by construction" - the stronger and
    # false claim, on the artifact a human reads under time pressure.
    #
    # Read off the real .xlsx, because that disagreement is invisible to any
    # unit test on the facts object.
    prices = _strip_season_column(MARKET_FIT_PRICES,
                                  str(tmp_path / "no_season.csv"))
    xlsx = str(tmp_path / "board.xlsx")
    rc = main(["render", "--source", DS, "--file", MARKET_FIT_FIXTURE,
               "--year", "2026", "--policy", "fit", "--prices", prices,
               "--tqb-starters", TQB_2026, "--xlsx", xlsx])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UNVERIFIED PRICES SEASON" in out, "stdout half"

    sheet = _intel_text(xlsx)
    assert "year-matched by construction" not in sheet, (
        "the workbook must not make a guarantee stdout just said it cannot make")
    assert "COULD NOT VERIFY" in sheet
    assert "no_season.csv" in sheet, "the page must name the file it could not check"


def test_the_workbook_still_claims_year_matched_when_the_file_says_its_season(tmp_path, capsys):
    # The complement: the fixture carries a season column, so the guarantee
    # is real and must still be stated.
    xlsx = str(tmp_path / "board.xlsx")
    assert main(["render", "--source", DS, "--file", MARKET_FIT_FIXTURE,
                 "--year", "2026", "--policy", "fit", "--prices",
                 MARKET_FIT_PRICES, "--tqb-starters", TQB_2026,
                 "--xlsx", xlsx]) == 0
    assert "UNVERIFIED" not in capsys.readouterr().out
    sheet = _intel_text(xlsx)
    assert "year-matched by construction" in sheet
    assert "COULD NOT VERIFY" not in sheet
