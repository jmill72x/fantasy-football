"""`sffl score-auction`: runbook step 12.1 as a command.

Invented fixtures only (the market-fit sample extract and its prices). The
real 2026 reproduction needs the licensed extract; NEXT.md records it.
"""

import csv
import re

import pytest

from sffl.cli import main
from sffl.identity import normalize_name

EXTRACT = "tests/fixtures/draftsharks_market_fit_sample.csv"
PRICES = "tests/fixtures/prices_market_fit_sample.csv"
TQB = "identity/tqb-2026-starters.yaml"


def _model(tmp_path, season=2025, prices_file="data/league/old.csv"):
    from sffl.market_model import MarketModel, save
    p = str(tmp_path / ("m%d.yaml" % season))
    save(p, MarketModel(season=season, fitted_on="2025-08-30",
                        curve=(2.05, 0.662), policy="starter",
                        evidence={"observations": 130,
                                  "prices_file": prices_file},
                        diagnostics={}), overwrite=True)
    return p


def _argv(model, prices=PRICES, year=2026, extract=EXTRACT, tqb=TQB):
    return ["score-auction", "--source", "sources/draftsharks.yaml",
            "--file", extract, "--year", str(year), "--market", model,
            "--prices", prices, "--tqb-starters", tqb]


def _cell(out, row, col):
    """A dollar figure from the overall table: row EST$/MY$, col 0..2."""
    line = [l for l in out.splitlines() if l.strip().startswith(row + " ")][0]
    vals = re.findall(r"[+-]?\$-?\d+\.\d\d", line)
    return float(vals[col].replace("$", ""))


def test_it_scores_every_joined_price(tmp_path, capsys):
    assert main(_argv(_model(tmp_path))) == 0
    out = capsys.readouterr().out
    assert "8 of 8 priced players join the board" in out
    assert "overall (n=8)" in out
    assert "by price paid:" in out
    for label in ("$26+", "$10-25", "$4-9", "$1-3"):
        assert re.search(r"^\s+%s\s" % re.escape(label), out, re.M), label
    # Last year's model on this year's prices: announced, not refused.
    assert "CROSS-SEASON" in out
    assert "NOT OUT OF SAMPLE" not in out


def test_the_numbers_are_the_board_value_market_prints(tmp_path, capsys):
    # Same valuation path as `value --market`: score the CSV that command
    # writes by hand and the command's table must agree.
    model = _model(tmp_path)
    board = str(tmp_path / "board.csv")
    assert main(["value", "--source", "sources/draftsharks.yaml",
                 "--file", EXTRACT, "--year", "2026", "--market", model,
                 "--out", board]) == 0
    paid = {}
    with open(PRICES) as fh:
        for r in csv.DictReader(fh):
            paid[normalize_name(r["player_as_written"])] = float(r["price"])
    est, my = [], []
    with open(board) as fh:
        for r in csv.DictReader(fh):
            key = normalize_name(r["name"])
            if key in paid:
                est.append(float(r["est_price"]) - paid[key])
                my.append(float(r["dollars"]) - paid[key])
    assert len(est) == 8
    capsys.readouterr()

    assert main(_argv(model)) == 0
    out = capsys.readouterr().out
    # value --out rounds to cents, so allow a cent.
    assert _cell(out, "EST$", 0) == pytest.approx(
        sum(abs(d) for d in est) / 8, abs=0.011)
    assert _cell(out, "EST$", 2) == pytest.approx(sum(est) / 8, abs=0.011)
    assert _cell(out, "MY$", 1) == pytest.approx(
        (sum(d * d for d in my) / 8) ** 0.5, abs=0.011)


def test_unmatched_prices_are_named(tmp_path, capsys):
    prices = str(tmp_path / "prices.csv")
    with open(PRICES) as src, open(prices, "w") as dst:
        dst.write(src.read())
        dst.write("NOBODY ON THIS BOARD,3,2026\n")
    assert main(_argv(_model(tmp_path), prices=prices)) == 0
    out = capsys.readouterr().out
    assert "8 of 9 priced players join the board" in out
    assert "UNMATCHED" in out and "nobody on this board" in out


def test_a_same_season_model_is_flagged_in_sample(tmp_path, capsys):
    assert main(_argv(_model(tmp_path, season=2026))) == 0
    assert "NOT OUT OF SAMPLE" in capsys.readouterr().out


def test_a_model_fitted_on_these_prices_is_flagged_in_sample(tmp_path, capsys):
    assert main(_argv(_model(tmp_path, prices_file=PRICES))) == 0
    assert "NOT OUT OF SAMPLE" in capsys.readouterr().out


def test_prices_from_another_season_are_refused(tmp_path):
    # The prices file says 2026; asserting 2027 must not score it.
    with pytest.raises(SystemExit) as exc:
        main(_argv(_model(tmp_path, season=2026), year=2027,
                   tqb="identity/tqb-2026-starters.yaml"))
    assert "refusing to load 2027 prices" in str(exc.value)


def test_projections_from_another_season_are_refused(tmp_path):
    extract = tmp_path / "2025" / "rankings.csv"
    extract.parent.mkdir()
    with open(EXTRACT) as src:
        extract.write_text(src.read())
    with pytest.raises(SystemExit) as exc:
        main(_argv(_model(tmp_path), extract=str(extract)))
    assert "refusing to score" in str(exc.value)


def test_a_model_is_required(capsys):
    with pytest.raises(SystemExit):
        main(["score-auction", "--source", "sources/draftsharks.yaml",
              "--file", EXTRACT, "--year", "2026", "--prices", PRICES])
    assert "--market" in capsys.readouterr().err
