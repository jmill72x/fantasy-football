from sffl.identity import normalize_name, normalize_team, player_key


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
