import os

import pytest

from sffl.cli import main


def _args(tmp_path, **over):
    out = over.pop("out", str(tmp_path / "2026.yaml"))
    argv = ["fit-market",
            "--source", "sources/draftsharks.yaml",
            "--file", over.pop("file", "tests/fixtures/draftsharks_market_fit_sample.csv"),
            "--year", str(over.pop("year", 2026)),
            "--prices", over.pop("prices", "tests/fixtures/prices_market_fit_sample.csv"),
            "--tqb-starters", over.pop("tqb", "identity/tqb-2026-starters.yaml"),
            "--out", out]
    for k, v in over.items():
        argv += ["--" + k.replace("_", "-"), str(v)]
    return argv, out


def test_a_year_matched_fit_writes_a_usable_model(tmp_path):
    from sffl.market_model import load
    argv, out = _args(tmp_path)
    assert main(argv) == 0
    m = load(out)
    assert m.season == 2026
    assert m.curve[1] > 0
    assert m.policy in ("starter", "draftable")
    assert m.evidence["observations"] > 0
    assert m.evidence["projections_year"] == 2026


def test_the_model_records_which_prices_and_projections_it_saw(tmp_path):
    # The failure this split exists to prevent was invisible for want of a
    # record of what was fitted against what.
    from sffl.market_model import load
    argv, out = _args(tmp_path)
    main(argv)
    ev = load(out).evidence
    assert "prices_market_fit_sample.csv" in ev["prices_file"]
    assert ev["tqb_starters"].endswith("tqb-2026-starters.yaml")


def test_a_cross_season_fit_is_refused(tmp_path):
    argv, _ = _args(tmp_path, year=2027)
    with pytest.raises(SystemExit):
        main(argv)


def test_it_refuses_to_overwrite_without_force(tmp_path):
    argv, out = _args(tmp_path)
    assert main(argv) == 0
    with pytest.raises(SystemExit):
        main(argv)


def test_force_allows_a_deliberate_refit(tmp_path):
    argv, out = _args(tmp_path)
    assert main(argv) == 0
    argv2, _ = _args(tmp_path, out=out)
    argv2 = argv2 + ["--force"]
    assert main(argv2) == 0


def test_nothing_is_written_when_the_fit_is_refused(tmp_path):
    out = str(tmp_path / "never.yaml")
    argv, _ = _args(tmp_path, year=2027, out=out)
    with pytest.raises(SystemExit):
        main(argv)
    assert not os.path.exists(out)


def test_a_fit_is_refused_when_the_prices_file_cannot_state_its_season(tmp_path):
    # A fit bakes a prices/projections pairing into a persisted artifact that
    # later seasons trust and never re-derive, so "the season is taken on
    # trust from the TQB map" - which is only a proxy - is not good enough
    # here. value/render keep working against a column-less file with a
    # loud note; a FIT refuses.
    import csv
    src = "tests/fixtures/prices_market_fit_sample.csv"
    dest = str(tmp_path / "no_season.csv")
    with open(src, newline="") as fh:
        reader = csv.DictReader(fh)
        fields = [f for f in reader.fieldnames if f != "season"]
        rows = [dict((k, r[k]) for k in fields) for r in reader]
    with open(dest, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    out = str(tmp_path / "never.yaml")
    argv, _ = _args(tmp_path, prices=dest, out=out)
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert "season" in str(exc.value)
    assert not os.path.exists(out), "a refused fit must write nothing"
