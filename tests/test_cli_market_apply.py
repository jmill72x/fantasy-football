import pytest

from sffl.cli import main


def _write_model(tmp_path, season=2026):
    from sffl.market_model import MarketModel, save
    p = str(tmp_path / "m.yaml")
    save(p, MarketModel(season=season, fitted_on="2026-08-30",
                        curve=(2.05, 0.662), policy="starter",
                        evidence={"observations": 130}, diagnostics={}))
    return p


def _value_argv(model, year=2026):
    return ["value",
            "--source", "sources/draftsharks.yaml",
            "--file", "tests/fixtures/draftsharks_market_fit_sample.csv",
            "--year", str(year), "--market", model]


def test_applying_a_model_prices_the_board(tmp_path, capsys):
    assert main(_value_argv(_write_model(tmp_path))) == 0
    assert "market model" in capsys.readouterr().out


def test_a_cross_season_apply_is_permitted_and_announced(tmp_path, capsys):
    # The whole point: last year's model of the room, applied to this year's
    # projections, is the correct thing to want - but it must never be silent.
    assert main(_value_argv(_write_model(tmp_path, season=2026), year=2027)) == 0
    out = capsys.readouterr().out
    assert "2026" in out and "market model" in out


def test_market_and_prices_together_are_refused(tmp_path):
    argv = _value_argv(_write_model(tmp_path)) + [
        "--prices", "tests/fixtures/prices_market_fit_sample.csv"]
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert "--market" in str(exc.value) and "--prices" in str(exc.value)


def test_policy_fit_needs_no_prices_when_a_model_is_supplied(tmp_path):
    # The deadlock, gone: the persisted policy was chosen from year-matched
    # prices, so a pre-auction run needs no price file at all.
    argv = _value_argv(_write_model(tmp_path)) + ["--policy", "fit"]
    assert main(argv) == 0
