from sffl.identity import (normalize_name, normalize_team, player_key,
                          resolve_key)


def test_strips_suffixes():
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert normalize_name("Kenneth Walker III") == "kenneth walker"
    assert normalize_name("Aaron Jones Sr.") == "aaron jones"
    assert normalize_name("Michael Penix Jr.") == "michael penix"


def test_folds_punctuation_and_case():
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("De'Von Achane") == "devon achane"
    assert normalize_name("T.J. Hockenson") == "tj hockenson"
    assert normalize_name("  Amon-Ra  St. Brown ") == "amon ra st brown"


def test_canonical_teams():
    assert normalize_team("JAX") == "JAC"
    assert normalize_team("JAC") == "JAC"
    assert normalize_team("LVR") == "LV"
    assert normalize_team("LV") == "LV"
    assert normalize_team("WSH") == "WAS"
    assert normalize_team("wsh") == "WAS"
    assert normalize_team("") == ""


def test_html_entities_are_decoded_before_normalization():
    # One real vendor file HTML-escapes names (e.g. "Ja&apos;Marr Chase"). If
    # normalize_name doesn't decode the entity first, re.sub strips "&" and
    # ";" but leaves "apos" fused into the name, producing a player_key that
    # never matches the correctly-spelled version from another vendor.
    assert normalize_name("Ja&apos;Marr Chase") == normalize_name("Ja'Marr Chase")
    assert normalize_name("Ja&apos;Marr Chase") == "jamarr chase"


def test_player_key_is_stable_across_sources():
    # Draft Sharks says "Cameron Ward / TEN"; Footballguys says "Cam Ward / TEN".
    # Normalization alone does NOT unify these - that is the alias layer's job.
    a = player_key("Trevor Lawrence", "JAC", "QB")
    b = player_key("Trevor Lawrence", "JAX", "qb")
    assert a == b == "trevor lawrence|JAC|QB"


def test_footballguys_lowercase_td_folds_to_dst_not_a_typo():
    # sources/footballguys.yaml's `filters.pos` list carries a literal
    # lowercase "td" as THAT VENDOR's own position code for a team defense
    # row - confirmed via `git log -S` against identity.py, not guessed.
    # Removing this fold would silently zero out every Footballguys defense.
    assert player_key("Broncos", "DEN", "td") == player_key(
        "Broncos", "DEN", "DST")


# --- Task 3b: resolve_key, the id-first join with player_key as fallback --

def test_resolve_key_uses_the_id_when_one_is_present():
    key = resolve_key("2966320", "Ja'Marr Chase", "CIN", "WR")
    assert key == "id:2966320"


def test_resolve_key_falls_back_to_player_key_when_there_is_no_id():
    key = resolve_key("", "Ja'Marr Chase", "CIN", "WR")
    assert key == player_key("Ja'Marr Chase", "CIN", "WR")


def test_resolve_key_id_and_composite_are_in_different_namespaces():
    # A row with an id and a row without one must never accidentally compare
    # equal just because one happens to look like the other's string shape.
    with_id = resolve_key("123", "X", "Y", "Z")
    without_id = resolve_key("", "X", "Y", "Z")
    assert with_id != without_id


def test_resolve_key_distinguishes_same_name_team_position_by_id_alone():
    # THE CASE THE COMPOSITE KEY CANNOT RESOLVE: two players sharing name,
    # team, AND position - the residual collision `player_key` alone must
    # treat as one indistinguishable entity. A real CBS id tells them apart.
    same_composite = player_key("Mike Williams", "LAC", "WR")
    a = resolve_key("111", "Mike Williams", "LAC", "WR")
    b = resolve_key("222", "Mike Williams", "LAC", "WR")
    assert a != b
    assert player_key("Mike Williams", "LAC", "WR") == same_composite
    # Without ids, the same two rows WOULD collide - this is exactly the
    # gap resolve_key's id-first preference closes.
    assert resolve_key("", "Mike Williams", "LAC", "WR") == resolve_key(
        "", "Mike Williams", "LAC", "WR") == same_composite
