from sffl.identity import (IdentityIndex, normalize_name, normalize_team,
                          player_key, resolve_key)


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



# --- Task 3b review round 1: IdentityIndex, the genuine two-step,
# id-first/composite-fallback ASYMMETRIC join (resolve_key is the wrong
# tool for this - see its own docstring) ------------------------------------

def test_identity_index_finds_by_id():
    idx = IdentityIndex()
    idx.add("2966320", "Ja'Marr Chase", "CIN", "WR", "chase-row")
    assert idx.get("2966320", "Ja'Marr Chase", "CIN", "WR") == "chase-row"


def test_identity_index_finds_by_composite_when_neither_side_has_an_id():
    idx = IdentityIndex()
    idx.add("", "Ja'Marr Chase", "CIN", "WR", "chase-row")
    assert idx.get("", "Ja'Marr Chase", "CIN", "WR") == "chase-row"


def test_identity_index_falls_back_to_composite_when_the_lookup_id_misses():
    """THE ASYMMETRIC CASE THIS CLASS EXISTS FOR: the stored row has NO id
    (its page lost id extraction this run), but the CALLER supplies one
    anyway (its own page still has ids). A real id on the caller's side
    must not prevent falling back to the composite match - this is exactly
    the fix for the prohibited outcome `resolve_key` produced when used as
    a single-key roster<->projections join (see its own docstring)."""
    idx = IdentityIndex()
    idx.add("", "Ja'Marr Chase", "CIN", "WR", "chase-row")  # no id stored
    # Looked up WITH an id the stored row does not have (asymmetric loss):
    # must still find it via composite, not return None.
    assert idx.get("2966320", "Ja'Marr Chase", "CIN", "WR") == "chase-row"


def test_identity_index_finds_by_composite_when_the_stored_row_has_an_id_too():
    """The REVERSE asymmetry: the stored row HAS an id (indexed under
    both), but the lookup itself carries none. Every id-bearing row must
    ALSO be reachable via its own composite key."""
    idx = IdentityIndex()
    idx.add("2966320", "Ja'Marr Chase", "CIN", "WR", "chase-row")
    assert idx.get("", "Ja'Marr Chase", "CIN", "WR") == "chase-row"


def test_identity_index_id_lookup_never_falls_through_to_a_stale_composite():
    """Two rows sharing a composite key but told apart by DIFFERENT ids
    (the case `player_key` alone cannot resolve) must each be found
    correctly by their OWN id - the composite entry for that shared key is
    retired to ambiguous, but that must never matter when the caller
    supplies a real, present id."""
    idx = IdentityIndex()
    idx.add("111", "Mike Williams", "LAC", "WR", "row-a")
    idx.add("222", "Mike Williams", "LAC", "WR", "row-b")
    assert idx.get("111", "Mike Williams", "LAC", "WR") == "row-a"
    assert idx.get("222", "Mike Williams", "LAC", "WR") == "row-b"


def test_identity_index_never_guesses_an_ambiguous_composite():
    """The composite key two DIFFERENT rows share is retired the moment
    the second one is added - a lookup that can ONLY reach the composite
    (no id, or an id neither row was stored under) must get None, never an
    arbitrary pick of one of the two."""
    idx = IdentityIndex()
    idx.add("111", "Mike Williams", "LAC", "WR", "row-a")
    idx.add("222", "Mike Williams", "LAC", "WR", "row-b")
    assert idx.get("", "Mike Williams", "LAC", "WR") is None
    assert idx.get("999", "Mike Williams", "LAC", "WR") is None


def test_identity_index_add_keeps_the_first_row_seen_under_a_shared_id():
    """Mirrors `_cmd_alert`'s `by_key` "keep the first, drop the second"
    convention for a genuine id collision - `add` must not silently let a
    later row overwrite an earlier one stored under the same id."""
    idx = IdentityIndex()
    idx.add("999", "Real Player", "LAC", "WR", "first-row")
    idx.add("999", "Real Player", "LAC", "WR", "second-row")
    assert idx.get("999", "Real Player", "LAC", "WR") == "first-row"


def test_identity_index_unknown_key_resolves_to_none():
    idx = IdentityIndex()
    idx.add("111", "Someone", "LAC", "WR", "row")
    assert idx.get("222", "Nobody", "XX", "K") is None
