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
    assert "refusing to value 2026 projections against the 2025" in msg
    assert "--tqb-starters" in msg


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
