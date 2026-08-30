import pytest

from sffl.market_model import MarketModel, describe, load, save

MODEL = MarketModel(
    season=2026,
    fitted_on="2026-08-30",
    curve=(2.0512345678901234, 0.6623456789012345),
    policy="starter",
    evidence={"prices_file": "data/league/auction-rosters-2026.csv",
              "prices_rows": 156, "observations": 130,
              "projections_source": "draftsharks", "projections_year": 2026,
              "tqb_starters": "identity/tqb-2026-starters.yaml"},
    diagnostics={"mae": 6.31, "top10_mae": 5.10, "top10_bias": 5.10})


def test_the_curve_round_trips_to_the_exact_same_floats(tmp_path):
    # Load-bearing: the 2026 board must not move when the fit is persisted
    # instead of computed in-process. A lost digit here shows up later as a
    # board that differs for no visible reason.
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    got = load(str(p))
    assert got.curve[0] == MODEL.curve[0]
    assert got.curve[1] == MODEL.curve[1]


def test_every_field_round_trips(tmp_path):
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    got = load(str(p))
    assert got.season == 2026
    assert got.policy == "starter"
    assert got.evidence["observations"] == 130
    assert got.diagnostics["top10_bias"] == 5.10


def test_saving_over_an_existing_file_is_refused(tmp_path):
    # The artifact is the evidence a board was priced from. A stray re-run
    # must not quietly replace it.
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    with pytest.raises(OSError):
        save(str(p), MODEL)


def test_overwrite_is_possible_when_asked_for_explicitly(tmp_path):
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    save(str(p), MODEL, overwrite=True)


def test_a_missing_required_field_raises_naming_it(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("season: 2026\npolicy: starter\n")
    with pytest.raises(ValueError) as exc:
        load(str(p))
    assert "curve" in str(exc.value)
    assert "bad.yaml" in str(exc.value)


def test_a_non_monotonic_curve_is_refused_on_load(tmp_path):
    # b <= 0 means a better player costs less, which no auction does. The
    # fitter refuses it; so must the loader, since a hand-edited artifact
    # bypasses the fitter entirely.
    p = tmp_path / "bad.yaml"
    p.write_text(
        "season: 2026\nfitted_on: '2026-08-30'\npolicy: starter\n"
        "curve: {a: 2.0, b: -0.5}\nevidence: {}\ndiagnostics: {}\n")
    with pytest.raises(ValueError) as exc:
        load(str(p))
    assert "monotonic" in str(exc.value).lower()


def test_an_unknown_policy_is_refused_on_load(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "season: 2026\nfitted_on: '2026-08-30'\npolicy: nonsense\n"
        "curve: {a: 2.0, b: 0.6}\nevidence: {}\ndiagnostics: {}\n")
    with pytest.raises(ValueError):
        load(str(p))


def test_describe_names_the_season_and_the_coefficients():
    line = describe(MODEL)
    assert "2026" in line
    assert "0.662" in line
    assert "130" in line
