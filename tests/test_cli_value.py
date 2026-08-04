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
