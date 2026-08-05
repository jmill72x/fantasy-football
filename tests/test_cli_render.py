import argparse
import os

from sffl.cli import _value_pool, main
from sffl.identity import NFL_TEAMS
from sffl.league import load_league

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


def test_dropping_unrostered_players_changes_no_dollar_value():
    # cmd_render drops non-NFL team codes AFTER _value_pool has priced the
    # whole pool, so removing them cannot move anyone's _dollars or
    # _est_price - replacement levels and the market curve are already
    # fixed by then. That is true by structure today and the ordering is
    # deliberate: filtering first would shrink the pool the replacement
    # level is computed from and quietly reprice the entire board. Nothing
    # enforced it, and this exact class of "obviously true" invariant has
    # broken three times in the renderers' history, so pin it: value, then
    # filter, then assert every survivor's numbers are byte-identical.
    args = argparse.Namespace(
        source=DS, file=UNROSTERED_FIXTURE, year=2026, set=None,
        curves=None, prices=None, policy="starter", tqb_starters=None)
    pool, _curve, _prices = _value_pool(load_league("leagues/sffl/2026.yaml"), args)

    before = dict((p.name, (p.stats["_dollars"], p.stats.get("_est_price")))
                  for p in pool)
    rosterable = [p for p in pool if p.team in NFL_TEAMS]
    assert len(rosterable) < len(pool), (
        "the fixture must contain at least one unrostered player, or this "
        "test filters nothing and proves nothing"
    )

    for p in rosterable:
        assert (p.stats["_dollars"], p.stats.get("_est_price")) == before[p.name], (
            "%s was repriced by dropping unrostered players" % p.name)
