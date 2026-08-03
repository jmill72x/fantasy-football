"""load_profile must reject any declared column key score_game can't read.

Nothing checks profile keys against scoring's vocabulary otherwise, so a
misspelled stat (fg_under_30 instead of fg_u30, receptions instead of
rec_ct) ingests cleanly and silently discards that production - see the
real footballguys.yaml kck-fgc gap this was written against.
"""

import pytest

from sffl.ingest.profiles import load_profile
from sffl.scoring import STAT_KEYS

GOOD_PROFILE = "sources/draftsharks.yaml"


def _write(tmp_path, columns_yaml):
    path = tmp_path / "bogus.yaml"
    path.write_text(
        "name: bogus\n"
        "columns:\n"
        + columns_yaml
    )
    return str(path)


def test_real_profiles_load_cleanly():
    # Both shipped source profiles must pass validation as-is.
    for source in ("sources/draftsharks.yaml", "sources/footballguys.yaml"):
        p = load_profile(source)
        assert p.name


def test_every_declared_stat_key_is_in_the_scoring_vocabulary():
    p = load_profile(GOOD_PROFILE)
    stat_cols = {f for f in p.columns if f not in ("name", "team", "pos", "games", "set_name")}
    assert stat_cols
    assert stat_cols <= STAT_KEYS


def test_unknown_stat_key_raises_with_key_and_path(tmp_path):
    bad_path = _write(
        tmp_path,
        "  name: name\n"
        "  team: team\n"
        "  pos: pos\n"
        "  games: games\n"
        "  fg_under_30: fg-u30\n"  # league's spelling, not scoring's fg_u30
        "  receptions: rec\n",     # not a recognized stat key at all
    )

    with pytest.raises(ValueError) as excinfo:
        load_profile(bad_path)

    msg = str(excinfo.value)
    assert "fg_under_30" in msg
    assert "receptions" in msg
    assert bad_path in msg
