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
    # Asserted on the distinctive NOTE wording, not on "2026" or "market
    # model" - both of those already appear in describe(model)'s base
    # announcement, which prints on EVERY apply regardless of season, so
    # asserting on them would pass even with the NOTE deleted entirely.
    assert main(_value_argv(_write_model(tmp_path, season=2026), year=2027)) == 0
    out = capsys.readouterr().out
    assert "CROSS-SEASON" in out


def test_a_same_season_apply_does_not_print_the_cross_season_note(tmp_path, capsys):
    # The complement: a note that always fires is a note nobody reads. If a
    # future change made the NOTE unconditional, this is what would catch it.
    assert main(_value_argv(_write_model(tmp_path, season=2026), year=2026)) == 0
    out = capsys.readouterr().out
    assert "CROSS-SEASON" not in out


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


def _intel_text(xlsx):
    """Every string on the workbook's Key & Intel sheet, joined.

    Read off the real file, not off `gather`'s facts: the defect this guards
    was that stdout and the workbook disagreed about the same run, and a unit
    test on the facts object cannot see what actually reached the sheet.
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx)
    ws = wb["Key & Intel"]
    return "\n".join(str(c) for row in ws.iter_rows(values_only=True)
                     for c in row if c is not None)


def test_stdout_and_the_workbook_agree_that_an_apply_is_cross_season(tmp_path, capsys):
    # THE DEFECT: intel compared the model against the LEAGUE PROFILE's
    # season while the CLI compared it against --year. On this run - the
    # 2027 pre-auction workflow this whole branch exists to enable - stdout
    # correctly announced CROSS-SEASON while the workbook stated the
    # opposite: "the persisted 2026 model ..., year-matched to this board".
    # The workbook is what goes to the draft table.
    model = _write_model(tmp_path, season=2026)
    xlsx = str(tmp_path / "board.xlsx")
    rc = main(["render", "--source", "sources/draftsharks.yaml",
               "--file", "tests/fixtures/draftsharks_value_sample.csv",
               "--year", "2027", "--market", model, "--xlsx", xlsx])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CROSS-SEASON" in out, "stdout half"

    sheet = _intel_text(xlsx)
    assert "CROSS-SEASON" in sheet, "the workbook must say what stdout says"
    assert "year-matched to this board" not in sheet
    assert "2027" in sheet, "the workbook must name the board's own season"


def test_the_workbook_does_not_cry_cross_season_on_a_year_matched_apply(tmp_path, capsys):
    # The complement: a flag that always fires is a flag nobody reads.
    model = _write_model(tmp_path, season=2026)
    xlsx = str(tmp_path / "board.xlsx")
    assert main(["render", "--source", "sources/draftsharks.yaml",
                 "--file", "tests/fixtures/draftsharks_value_sample.csv",
                 "--year", "2026", "--market", model, "--xlsx", xlsx]) == 0
    assert "CROSS-SEASON" not in capsys.readouterr().out
    sheet = _intel_text(xlsx)
    assert "CROSS-SEASON" not in sheet
    assert "year-matched to this board" in sheet
