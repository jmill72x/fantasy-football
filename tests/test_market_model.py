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


# Pins the COMMITTED artifact itself, not merely the fit/apply roundtrip. The
# roundtrip test (tests/test_market_roundtrip.py) proves a curve fitted
# within one run survives being persisted and re-loaded; it says nothing
# about what actually sits in the repo. A hand-edit to market/2026.yaml, or a
# stray `fit-market --force` re-run against different evidence, would move
# every dollar on the 2026 board and no other test would fail - which is
# exactly the 2027 scenario this test exists to catch: a human opens the
# artifact, changes something, and the board silently shifts.
#
# If the model was DELIBERATELY refit (a corrected extract, a widened prices
# file, a genuine re-fit after the 2026 auction), these expected values must
# be updated deliberately too - by re-running the same `fit-market` command
# recorded in the file's own `evidence`, confirming the new numbers, and then
# editing this test to match. An unexplained failure here means the artifact
# changed and nobody meant it to: treat it as the board having moved, not as
# a stale test.
COMMITTED_MARKET_PATH = "market/2026.yaml"

_PIN_FAILURE_HINT = (
    "\n\nmarket/2026.yaml no longer matches the coefficients pinned here. "
    "If this model was deliberately refit, update THIS TEST's expected "
    "values to match on purpose - re-run the `fit-market` command recorded "
    "in the file's own `evidence` block, confirm the new numbers are "
    "intended, and only then edit this test. If nobody meant to refit it, "
    "something moved the board: a hand-edit to the YAML or a stray "
    "`fit-market --force` are the two ways that happens with no other test "
    "catching it.")


def test_the_committed_2026_artifact_is_pinned():
    # Deliberately refit 2026-08-30 (first time): calibration/2025.yaml was
    # regenerated to adopt build_curves_isotonic (built on the full dataset -
    # build set plus the previously held-back weeks) for five board-relevant
    # stats (pass_cmp, pass_yds, rec_ct, rec_yds, rush_yds). See
    # docs/superpowers/specs/2026-08-30-curve-adoption-third-measurement.md
    # (the gate that cleared) and
    # .superpowers/sdd/2026-08-30-regularised-calibration-curves/task-5-report.md.
    #
    # Deliberately re-refit 2026-08-30 (second time, same day): pass_yds was
    # REVERTED out of the isotonic bundle back to build_curves/build-set-only.
    # It had been adopted on a LEAKED cross-validation (a duplicate-entity id's
    # identical twin sat in the fit set - commit a8584da); re-run clean under
    # predict_weekly, isotonic loses condition 3 of the gate for pass_yds
    # (0.1572 vs baseline 0.1520). The four-stat bundle (pass_cmp, rec_ct,
    # rec_yds, rush_yds) was re-measured on its own - removing a stat changes
    # the bundle - and still clears the gate (top10_cost 15.168 -> 13.263,
    # mae 4.3392 -> 4.4154). See
    # .superpowers/sdd/2026-08-30-full-position-coverage/
    # pass-yds-revert-report.md. def_pa/def_ya are unchanged throughout
    # (still build_curves on the build set only). This is a genuine, measured
    # refit of the curves this model depends on - not a hand-edit or a stray
    # --force - and these expected values were updated deliberately to match,
    # per this test's own failure hint.
    model = load(COMMITTED_MARKET_PATH)

    assert model.season == 2026, _PIN_FAILURE_HINT
    assert model.policy == "starter", _PIN_FAILURE_HINT
    assert model.evidence.get("observations") == 130, _PIN_FAILURE_HINT
    # Exact float equality, not approx: the whole point of persisting rather
    # than re-fitting is that these exact bits reach every render unchanged,
    # so a pinned test that tolerated drift would defeat its own purpose.
    assert model.curve[0] == 2.028495994199789, _PIN_FAILURE_HINT
    assert model.curve[1] == 0.6511171620237226, _PIN_FAILURE_HINT


def test_the_apply_paths_policy_list_matches_the_fitters():
    # `market_model._KNOWN_POLICIES` duplicates `fit.POLICIES` on purpose -
    # importing fit here would drag the whole fitting path (prices, aliases,
    # the TQB map) into a pure APPLY, which is the separation this module
    # exists to keep. Duplication is the right trade, but nothing pinned the
    # two lists together: adding a third policy to `fit` would make `load`
    # reject a valid artifact the fitter had just written, and the failure
    # would surface as an unusable model file rather than as a missed edit.
    from sffl import fit
    from sffl.market_model import _KNOWN_POLICIES
    assert _KNOWN_POLICIES == fit.POLICIES, (
        "market_model._KNOWN_POLICIES and fit.POLICIES have drifted; a policy "
        "the fitter can choose must be a policy the apply path can load")
