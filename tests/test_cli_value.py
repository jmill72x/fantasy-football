from sffl.cli import main

DS = "sources/draftsharks.yaml"
# A dedicated fixture, not tests/fixtures/draftsharks_sample.csv: the value
# command needs at least one player in every replacement pool (TQB, FLEX, K,
# DST), and replacement_levels() raises if any pool is completely empty. The
# shared sample fixture has no kicker, so it adds a Test Kicker row on top of
# the same four players the other ingest/pool/scoring tests already use.
FIXTURE = "tests/fixtures/draftsharks_value_sample.csv"


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
               "--policy", "fit", "--prices", PRICES])
    out = capsys.readouterr().out
    assert rc == 0
    assert "of 5 prices" in out
    assert "unmatched" in out


def test_tqb_starters_flag_is_accepted_and_overridable(capsys):
    # A future season's roster sheet needs its own starter map; the flag
    # must be plumbed through to load_prices rather than hardcoded.
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "fit", "--prices", PRICES,
               "--tqb-starters", "identity/tqb-2025-starters.yaml"])
    assert rc == 0


def test_est_price_column_appears_when_prices_are_supplied(tmp_path):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--prices", PRICES, "--out", path])
    assert rc == 0
    with open(path) as fh:
        header = fh.readline()
    assert "est_price" in header


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
