import pytest

from sffl.fit import load_prices, score_fit, choose_policy, top10_cost
from sffl.identity import NFL_TEAMS, Resolver
from sffl.league import load_league
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")
PRICES = "tests/fixtures/prices_sample.csv"


def player(name, pos, pts):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_season_points": float(pts)}, raw_name=name)


def filler_players():
    """One TQB, one K and one DST so replacement_levels never sees an empty pool.

    Names are chosen to not appear in tests/fixtures/prices_sample.csv, so they
    are never matched to an observed price and leave the n/mae/top10_mae
    assertions in the price-matching tests untouched.
    """
    return [
        player("Filler Quarterback", "TQB", 50),
        player("Filler Kicker", "K", 50),
        player("Filler Defense", "DST", 50),
    ]


def build_priced_pool():
    """A pool with all four POOLS populated: fixture players priced by
    prices_sample.csv, plus filler_players() for TQB/K/DST so replacement_levels
    never sees an empty pool.
    """
    return [
        player("Ja'Marr Chase", "WR", 200),
        player("Chase Brown", "RB", 120),
    ] + filler_players()


def test_load_prices_normalizes_hand_typed_names():
    prices = load_prices(PRICES)
    # the roster sheet misspells Ja'Marr Chase as "JAMAAR CHASE"; assert the
    # alias actually landed on the canonical key, not merely that some key
    # somewhere contains "chase" (which "chase brown" would satisfy on its
    # own, alias or no alias, making that assertion vacuous)
    assert "jamarr chase" in prices
    assert len(prices) == 5


def test_score_fit_reports_error_metrics():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Chase Brown", "RB", 120)]
    pool += filler_players()
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["policy"] == "starter"
    assert rep["n"] >= 1
    assert rep["mae"] >= 0
    assert rep["rmse"] >= rep["mae"]


def test_score_fit_rejects_an_unknown_policy():
    pool = [player("Ja'Marr Chase", "WR", 200)]
    pool += filler_players()
    with pytest.raises(ValueError):
        score_fit(LG, pool, load_prices(PRICES), "vibes")


def test_choose_policy_returns_one_of_the_two_and_both_reports():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Chase Brown", "RB", 120),
            player("Bijan Robinson", "RB", 180), player("Nico Collins", "WR", 90)]
    pool += filler_players()
    best, reports = choose_policy(LG, pool, load_prices(PRICES))
    assert best in ("starter", "draftable")
    assert len(reports) == 2
    assert {r["policy"] for r in reports} == {"starter", "draftable"}


def test_players_with_no_observed_price_are_excluded_from_the_fit():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Nobody At All", "WR", 150)]
    pool += filler_players()
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["n"] == 1


def test_score_fit_reports_zero_matches_without_raising():
    # None of these names appear in prices_sample.csv. score_fit must report the
    # zero-match fit honestly rather than raise, so a caller inspecting `n` can see it.
    pool = [player("Totally Unknown Player", "WR", 200)]
    pool += filler_players()
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["n"] == 0
    assert rep["mae"] == float("inf")
    assert rep["rmse"] == float("inf")
    assert rep["top10_mae"] == float("inf")


def test_choose_policy_raises_when_no_player_matches_any_price():
    # Both policies see zero matches here, so there is no evidence to pick a
    # winner on. choose_policy must raise rather than arbitrarily return
    # "starter" because Python's min() ties on (inf, inf).
    pool = [player("Totally Unknown Player", "WR", 200)]
    pool += filler_players()
    with pytest.raises(ValueError, match="identity/aliases.yaml"):
        choose_policy(LG, pool, load_prices(PRICES))


REAL_PRICES = "data/league/auction-rosters-2025.csv"


def test_defense_roster_spellings_resolve_to_franchise_names():
    prices = load_prices(REAL_PRICES)
    for franchise in ("philadelphia eagles", "pittsburgh steelers",
                      "minnesota vikings", "houston texans"):
        assert franchise in prices, franchise


def test_skill_misspellings_resolve():
    prices = load_prices(REAL_PRICES)
    for name in ("evan mcpherson", "tetairoa mcmillan", "treveyon henderson",
                 "jaxon smith njigba", "jauan jennings", "wil lutz"):
        assert name in prices, name


def test_players_genuinely_absent_from_the_extract_stay_unresolved():
    # Joe Mixon and Ricky Pearsall are not in the 2026 Draft Sharks extract.
    # They must NOT be force-matched onto a similarly spelled player. Jordan
    # Mason was genuinely bought for $2 (his own real price, not Joe Mixon's
    # $1); pin the exact value so an aliasing bug that landed Mixon's $1 on
    # Mason - which Task 2's max() collision rule would silently accept as
    # max(2.0, 1.0) == 2.0 - cannot hide behind a "!= 1.0" check.
    prices = load_prices(REAL_PRICES)
    assert prices["jordan mason"] == 2.0
    assert "erick all" not in prices or prices.get("erick all") != 13.0


def test_no_alias_chains_in_resolver():
    # Alias chains break the non-transitive lookup in load_prices. This test
    # catches the whole bug class by ensuring no alias value is itself a key.
    resolver = Resolver("identity/aliases.yaml")
    aliases = resolver.aliases
    keys = set(aliases.keys())
    values = set(aliases.values())
    chains = keys & values
    assert not chains, "alias chains detected: %s" % {k: aliases[k] for k in chains}


def test_cameron_skattebo_joins_from_roster_sheet_spelling():
    # The roster sheet writes "CAM SKATEBO" (one t); our alias must point
    # directly to "Cameron Skattebo", not through an intermediate spelling.
    prices = load_prices(REAL_PRICES)
    assert "cameron skattebo" in prices


def test_tqb_units_join_by_their_2025_starting_quarterback():
    prices = load_prices(REAL_PRICES)
    # the sheet wrote "JOSH ALLEN"; the pool names the unit "BUF"
    assert prices.get("buf") == 23.0
    assert prices.get("bal") == 31.0
    assert prices.get("was") == 28.0


def test_tqb_map_uses_2025_teams_not_the_2026_extract():
    # Kyler Murray was ARI in 2025 and appears on another team in the 2026 file.
    prices = load_prices(REAL_PRICES)
    assert prices.get("ari") == 1.0


def test_all_21_priced_tqb_units_join_distinct_franchises():
    # All 21 priced 2025 Team QB units land on 21 *distinct* franchises (e.g.
    # BUF's Josh Allen and ARI's Kyler Murray were bought by the same roster,
    # but they are two different franchises, not a collision on one). This
    # test only proves the join is complete; it does not exercise the
    # collision-resolution branch in load_prices - see
    # test_a_franchise_with_two_colliding_tqb_prices_keeps_the_higher_price
    # for that, which needs a synthetic fixture because no real 2025 entry
    # collides.
    #
    # Filtered against NFL_TEAMS rather than len(k) == 3: six franchises
    # (GB, KC, LV, NE, SF, TB) have canonical two-letter codes, so a
    # length-3 filter would silently undercount a fully correct join.
    prices = load_prices(REAL_PRICES)
    tqb_keys = [k for k in prices if k.upper() in NFL_TEAMS]
    assert len(tqb_keys) == 21


TQB_COLLISION_STARTERS = "tests/fixtures/tqb_starters_collision.yaml"


def test_a_franchise_with_two_colliding_tqb_prices_keeps_the_higher_price():
    # Two distinct quarterback names ("Quarterback A", "Quarterback B") are
    # mapped to the same franchise "JAC" by a fixture starter map, so both
    # rows collapse onto the same output key regardless of the real 2025
    # data, which never collides. Checked in both file orders so the test
    # would fail under "last write wins" as well as "first write wins" - only
    # max() passes both.
    higher_first = load_prices("tests/fixtures/prices_tqb_collision_high_first.csv",
                                tqb_starters_path=TQB_COLLISION_STARTERS)
    lower_first = load_prices("tests/fixtures/prices_tqb_collision_low_first.csv",
                               tqb_starters_path=TQB_COLLISION_STARTERS)
    assert higher_first.get("jac") == 30.0
    assert lower_first.get("jac") == 30.0


def test_tqb_starters_rejects_an_unknown_franchise_code():
    # "PHIL" (should be "PHI") would otherwise join nothing and silently drop
    # a TQB price from the fit with no signal anywhere.
    with pytest.raises(ValueError, match="PHIL"):
        load_prices(REAL_PRICES,
                    tqb_starters_path="tests/fixtures/tqb_starters_bad_code.yaml")


def test_fit_reports_error_per_pool():
    rep = score_fit(LG, build_priced_pool(), load_prices(PRICES), "starter")
    assert "by_pool" in rep
    assert "FLEX" in rep["by_pool"]
    assert rep["by_pool"]["FLEX"]["n"] >= 1
    assert rep["by_pool"]["FLEX"]["mae"] >= 0


def test_pools_with_no_matched_prices_report_zero_not_a_fake_average():
    rep = score_fit(LG, build_priced_pool(), load_prices(PRICES), "starter")
    for name, stats in rep["by_pool"].items():
        if stats["n"] == 0:
            assert stats["mae"] == 0.0


def _report(policy, top10_mae, top10_bias, mae=5.0):
    return {"policy": policy, "n": 100, "mae": mae, "rmse": mae * 1.5,
            "top10_mae": top10_mae, "top10_bias": top10_bias, "by_pool": {}}


def test_top10_cost_charges_systematic_error_twice_and_noise_once():
    # Same top-10 mae, opposite character: one policy is wrong in both
    # directions, the other is wrong in one. Only the second is unrecoverable.
    noisy = _report("starter", top10_mae=10.0, top10_bias=0.0)
    biased = _report("draftable", top10_mae=10.0, top10_bias=-10.0)
    assert top10_cost(noisy) == 10.0
    assert top10_cost(biased) == 20.0
    assert top10_cost(noisy) < top10_cost(biased)


def test_a_lower_top10_mae_does_not_win_when_it_is_all_bias():
    # MEASURED, not quoted. The previous value here (top10_bias=-0.25 for
    # starter) was lifted from the $26+ band of a different table and
    # asserted that starter's top-10 is essentially unbiased. It over-prices
    # by about $5/player across the ten most expensive priced players. The
    # policy decision these numbers pin is correct either way - starter wins
    # for any bias weight above 0.25 - but a green test asserting a bias
    # that is not there is this codebase's signature failure in miniature.
    #
    # Reproduced with (PYTHONPATH=src):
    #   pool = build_pool(lg, "sources/draftsharks.yaml",
    #       "data/extracts/Draft Sharks/2026/rankings-2026-08-23.csv", 2026, None)
    #   curves = load_curves("calibration/2025.yaml")  # score_season_calibrated
    #   prices = load_prices("data/league/auction-rosters-2026.csv",
    #       tqb_starters_path="identity/tqb-2026-starters.yaml", season=2026)
    #   score_fit(lg, pool, prices, policy)
    # This is exactly what `sffl fit-market` runs, and the starter figures
    # below reproduce market/2026.yaml's persisted `diagnostics` exactly.
    #
    # draftable wins on top10_mae ($9.08 vs $10.06) and must still lose: its
    # top-10 error is almost entirely systematic (|top10_bias| is ~100% of
    # top10_mae - every one of its ten most expensive matched players is
    # under-priced in the same direction). starter's error is roughly half
    # noise, half bias (|top10_bias| is ~half of top10_mae) - a materially
    # different, and much more recoverable, kind of wrong. That relationship,
    # not the exact decimals, is what the decision rests on and what will
    # still hold the next time projections are refreshed and these numbers
    # drift.
    starter = _report("starter", top10_mae=10.0638, top10_bias=5.1042)
    draftable = _report("draftable", top10_mae=9.0782, top10_bias=-9.0782)
    assert draftable["top10_mae"] < starter["top10_mae"]
    # draftable's top-10 error is almost entirely systematic bias ...
    assert abs(draftable["top10_bias"]) / draftable["top10_mae"] > 0.95
    # ... starter's is not - noise and bias are roughly comparable in size
    assert abs(starter["top10_bias"]) / starter["top10_mae"] < 0.6
    assert top10_cost(starter) < top10_cost(draftable)


def test_bias_penalty_does_not_hand_the_choice_to_a_wildly_noisy_policy():
    # The guard against over-correcting: an unbiased policy that is simply bad
    # must not beat a mildly biased accurate one.
    unbiased_but_awful = _report("starter", top10_mae=30.0, top10_bias=0.0)
    slightly_biased_good = _report("draftable", top10_mae=5.0, top10_bias=-2.0)
    assert top10_cost(slightly_biased_good) < top10_cost(unbiased_but_awful)


def test_score_fit_reports_signed_top10_bias():
    """top10_bias must be SIGNED, which is the whole point of adding it.

    top10_mae cannot tell a policy that is wrong in both directions from one
    that is wrong in a single direction, and choose_policy now depends on the
    difference. |bias| <= mae always, by the triangle inequality; equality
    means every top-10 error points the same way.
    """
    pool = [player("Ja'Marr Chase", "WR", 300), player("Bijan Robinson", "RB", 280)]
    pool += filler_players()
    report = score_fit(LG, pool, load_prices(PRICES), "starter")
    if report["n"]:
        assert abs(report["top10_bias"]) <= report["top10_mae"] + 1e-9


def test_the_2026_prices_pick_starter_over_draftable():
    """The regression this rule exists for.

    Measured year-matched on the real 2026 prices (see the reproduction
    recipe in test_a_lower_top10_mae_does_not_win_when_it_is_all_bias),
    draftable wins top10_mae ($9.08 vs $10.06) while under-pricing its ten
    most expensive matched players almost entirely one-directionally, by
    about $9 apiece. Before top10_cost, choose_policy shipped that board.

    starter's top10_bias is +5.10, not the -0.25 an earlier version of this
    test asserted (that number was lifted from the $26+ band of a different
    table). The measured bias here is still small enough, relative to
    draftable's near-total systematic error, that the decision is unaffected -
    which is what this test actually pins.
    """
    starter = _report("starter", top10_mae=10.0638, top10_bias=5.1042)
    draftable = _report("draftable", top10_mae=9.0782, top10_bias=-9.0782)
    assert min([starter, draftable], key=top10_cost)["policy"] == "starter"


def test_prices_season_reads_the_column_when_present():
    from sffl.fit import prices_season
    assert prices_season("data/league/auction-rosters-2026.csv") == 2026


def test_prices_season_is_none_when_the_file_predates_the_column(tmp_path):
    p = tmp_path / "old.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    from sffl.fit import prices_season
    assert prices_season(str(p)) is None


def test_loading_prices_from_the_wrong_season_is_refused(tmp_path):
    # HOLE 1: this configuration used to run to completion and silently
    # refit the artifact-era curve. The prices file now states its own
    # season, so the lie is detectable rather than proxied by the TQB map.
    #
    # The TQB map here is deliberately MATCHED (2026) so the map-season check
    # passes cleanly and execution actually reaches the file-season check -
    # only the prices file lies. That is the exact configuration that used
    # to run to completion: mismatched prices with a matched map. Asserting
    # on the distinctive "declares season" wording (rather than a bare year
    # substring any of the three guards could produce) is what pins this
    # test to the file-season check specifically.
    from sffl.fit import load_prices
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price,season\nJA'MARR CHASE,42,2025\n")
    with pytest.raises(ValueError) as exc:
        load_prices(str(p), tqb_starters_path="identity/tqb-2026-starters.yaml",
                    season=2026)
    assert "declares season 2025" in str(exc.value)
    assert "2026" in str(exc.value)


def test_a_tqb_map_with_no_season_key_is_refused_when_a_season_is_asserted(tmp_path):
    # HOLE 2: a map with no season: key used to skip the guard entirely.
    from sffl.fit import load_prices
    m = tmp_path / "map.yaml"
    m.write_text("starters:\n  Joe Burrow: CIN\n")
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    with pytest.raises(ValueError) as exc:
        load_prices(str(p), tqb_starters_path=str(m), season=2026)
    assert "season" in str(exc.value).lower()


def test_a_direct_call_gets_the_same_guard_as_the_cli(tmp_path):
    # HOLE 3: the guard used to live only in cli._value_pool, so any other
    # caller bypassed it. It is enforced here now, at the load itself.
    from sffl.fit import DEFAULT_TQB_STARTERS, load_prices
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    with pytest.raises(ValueError):
        load_prices(str(p), tqb_starters_path=DEFAULT_TQB_STARTERS,
                    season=2026)  # the default map is 2025


def test_a_season_matched_load_still_works():
    from sffl.fit import load_prices
    prices = load_prices("data/league/auction-rosters-2026.csv",
                         tqb_starters_path="identity/tqb-2026-starters.yaml",
                         season=2026)
    assert len(prices) > 100


def test_omitting_the_season_keeps_the_old_permissive_behaviour(tmp_path):
    # Callers that genuinely do not know the season (a poc script exploring
    # a file) are not forced to assert one. The guard binds when a season IS
    # asserted, which every production path does.
    from sffl.fit import load_prices
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    assert load_prices(str(p)) is not None


# --------------------------------------------------------------------------
# THE ANNOUNCEMENT HALF OF DECISION 2.
#
# Verification shipped; the announcement did not. `prices_season` returns None
# for a file with no `season` column and the guard simply did not fire - no
# warning, no note, nothing - so the byte-for-byte configuration that
# manufactured the phantom top-end bias (2025 prices, 2026 map, 2026
# projections) fitted price = 2.443 * value^0.531 at exit 0 in silence. A
# check that cannot run must SAY it could not run; its silence is otherwise
# indistinguishable from a pass.
# --------------------------------------------------------------------------

COLUMNLESS_PRICES = "data/league/auction-rosters-2025.csv"


def test_a_prices_file_with_no_season_column_says_so(tmp_path):
    from sffl.fit import UnverifiedPricesSeasonWarning, load_prices
    with pytest.warns(UnverifiedPricesSeasonWarning) as caught:
        prices = load_prices(COLUMNLESS_PRICES,
                             tqb_starters_path="identity/tqb-2025-starters.yaml",
                             season=2025)
    # It still LOADS - the pre-column files must keep working. What changes
    # is that the run is no longer silent about what it could not check.
    assert len(prices) > 100
    message = str(caught[0].message)
    assert COLUMNLESS_PRICES in message, "the warning must name the file"
    assert "2025" in message, "the warning must name the season taken on trust"
    assert "proxy" in message.lower(), (
        "the warning must say WHY the TQB map is not evidence of the season")


def test_a_prices_file_that_states_its_season_warns_about_nothing():
    # The complement: a warning that fires on every run is a warning nobody
    # reads. The 2026 file carries the column, so it is verified, not trusted.
    import warnings

    from sffl.fit import UnverifiedPricesSeasonWarning, load_prices
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_prices("data/league/auction-rosters-2026.csv",
                    tqb_starters_path="identity/tqb-2026-starters.yaml",
                    season=2026)
    assert not [w for w in caught
                if issubclass(w.category, UnverifiedPricesSeasonWarning)]


def test_no_season_asserted_means_nothing_to_verify_and_nothing_to_warn_about():
    # The warning is about an ASSERTION that could not be checked. A caller
    # that asserts nothing (a poc script exploring an unknown file) has made
    # no claim for this to qualify.
    import warnings

    from sffl.fit import UnverifiedPricesSeasonWarning, load_prices
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_prices(COLUMNLESS_PRICES)
    assert not [w for w in caught
                if issubclass(w.category, UnverifiedPricesSeasonWarning)]


def test_a_fit_refuses_a_prices_file_that_cannot_state_its_season(tmp_path):
    # A FIT is the one operation that bakes the pairing into a persisted
    # artifact later seasons trust without re-deriving it, so for a fit the
    # warning is not enough. Everything else keeps working (above).
    from sffl.fit import SeasonMismatchError, load_prices
    with pytest.raises(SeasonMismatchError) as exc:
        load_prices(COLUMNLESS_PRICES,
                    tqb_starters_path="identity/tqb-2025-starters.yaml",
                    season=2025, require_file_season=True)
    assert COLUMNLESS_PRICES in str(exc.value)
    assert "season" in str(exc.value)


def test_a_fit_accepts_a_prices_file_that_does_state_its_season():
    from sffl.fit import load_prices
    prices = load_prices("data/league/auction-rosters-2026.csv",
                         tqb_starters_path="identity/tqb-2026-starters.yaml",
                         season=2026, require_file_season=True)
    assert len(prices) > 100
