import os

from sffl.cli import main

DS = "sources/draftsharks.yaml"
FIXTURE = "tests/fixtures/draftsharks_value_sample.csv"


def test_render_writes_both_artifacts(tmp_path):
    pdf = str(tmp_path / "board.pdf")
    xlsx = str(tmp_path / "board.xlsx")
    rc = main(["render", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--pdf", pdf, "--xlsx", xlsx])
    assert rc == 0
    assert os.path.getsize(pdf) > 0
    assert os.path.getsize(xlsx) > 0


def test_render_requires_at_least_one_output(capsys):
    rc = main(["render", "--source", DS, "--file", FIXTURE, "--year", "2026"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "--pdf" in out and "--xlsx" in out


# A dedicated fixture: draftsharks_value_sample.csv plus one extra WR row on
# team "UNS" (an unsigned free agent placeholder, not a real NFL franchise).
# The real Draft Sharks extract has 23 such rows (UNS x22, RK x1) - they have
# no bye week and build_rows correctly raises rather than rendering a blank,
# so cmd_render must filter them out itself and say how many it dropped,
# rather than silently shrinking the board or crashing.
UNROSTERED_FIXTURE = "tests/fixtures/draftsharks_render_unrostered_sample.csv"


def test_render_drops_unrostered_players_and_reports_the_count(tmp_path, capsys):
    pdf = str(tmp_path / "board.pdf")
    rc = main(["render", "--source", DS, "--file", UNROSTERED_FIXTURE, "--year", "2026",
               "--pdf", pdf])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dropped 1" in out
    assert "UNS" in out
