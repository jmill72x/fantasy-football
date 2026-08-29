import pytest

from sffl.cbs_weekly import OUT_STATUSES, is_out


@pytest.mark.parametrize("tag", ["O", "IR", "PUP", "SUSP"])
def test_a_player_who_will_not_play_is_out(tag):
    assert is_out(tag) is True


@pytest.mark.parametrize("tag", ["Q", "D", "NA", "", "  "])
def test_a_player_who_might_play_is_not_out(tag):
    # Q and D usually play. Silently benching them would be a worse error
    # than starting them, so they are flagged elsewhere, never excluded here.
    assert is_out(tag) is False


def test_out_statuses_is_exactly_the_four_that_mean_will_not_play():
    assert OUT_STATUSES == frozenset({"O", "IR", "PUP", "SUSP"})


def test_status_is_case_and_whitespace_insensitive():
    assert is_out(" o ") is True
    assert is_out("ir") is True
