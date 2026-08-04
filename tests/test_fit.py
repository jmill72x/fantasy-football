import pytest

from sffl.fit import load_prices, score_fit, choose_policy
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
    # They must NOT be force-matched onto a similarly spelled player.
    prices = load_prices(REAL_PRICES)
    assert "jordan mason" not in prices or prices.get("jordan mason") != 1.0
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
    # mapped to the same synthetic franchise "ZZZ" by a fixture starter map,
    # so both rows collapse onto the same output key regardless of the real
    # 2025 data, which never collides. Checked in both file orders so the
    # test would fail under "last write wins" as well as "first write wins" -
    # only max() passes both.
    higher_first = load_prices("tests/fixtures/prices_tqb_collision_high_first.csv",
                                tqb_starters_path=TQB_COLLISION_STARTERS)
    lower_first = load_prices("tests/fixtures/prices_tqb_collision_low_first.csv",
                               tqb_starters_path=TQB_COLLISION_STARTERS)
    assert higher_first.get("zzz") == 30.0
    assert lower_first.get("zzz") == 30.0


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
