"""Swap planning for the CBS lineup write path.

The governing fact: CBS's edit mode has NO SAVE BUTTON. Each move applies on
its own, so a sequence that stops halfway leaves a real, mixed lineup with
nothing to roll back. Everything here exists to make the plan reviewable
before a browser opens, and a partial application diagnosable after.
"""
import pytest

from sffl.lineup_write import (LineupSlot, describe_plan, plan_swaps,
                               verify_applied)


def slot(pid, name, pos, starting):
    return LineupSlot(pid, name, pos, starting)


def roster():
    return [slot("s1", "Starter One", "RB", True),
            slot("s2", "Starter Two", "WR", True),
            slot("s3", "Starter Three", "TE", True),
            slot("b1", "Bench One", "RB", False),
            slot("b2", "Bench Two", "WR", False)]


def test_a_matching_lineup_plans_nothing():
    assert plan_swaps(roster(), {"s1", "s2", "s3"}) == []
    assert "already matches" in describe_plan([])


def test_one_change_is_one_swap_pair():
    # CBS swaps two players per interaction - there is no "send to bench"
    # that does not also bring someone up.
    swaps = plan_swaps(roster(), {"s1", "s2", "b1"})
    assert len(swaps) == 1
    assert swaps[0].bench_id == "s3"
    assert swaps[0].promote_id == "b1"


def test_two_changes_pair_deterministically_in_page_order():
    # Determinism is what makes "it stopped after step 2" mean something.
    swaps = plan_swaps(roster(), {"s1", "b1", "b2"})
    assert [(s.bench_id, s.promote_id) for s in swaps] == [("s2", "b1"), ("s3", "b2")]
    again = plan_swaps(roster(), {"s1", "b1", "b2"})
    assert swaps == again


def test_a_target_naming_someone_off_the_roster_is_refused():
    # Swapping blind here would bench a real player to promote a phantom.
    with pytest.raises(ValueError) as e:
        plan_swaps(roster(), {"s1", "s2", "GHOST"})
    assert "not on the roster page" in str(e.value)


def test_a_target_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError) as e:
        plan_swaps(roster(), {"s1", "s2"})
    assert "different lineup shape" in str(e.value)


def test_the_description_warns_there_is_no_rollback():
    # The warning is the point of the text: a human approving this must know
    # a stopped run leaves earlier swaps applied.
    text = describe_plan(plan_swaps(roster(), {"s1", "s2", "b1"}))
    assert "no" in text and "save" in text
    assert "rollback" in text


def test_verify_compares_ids_not_row_order():
    # CBS reorders rows as players move, so "row 3 changed" proves nothing.
    after = [slot("s1", "Starter One", "RB", True),
             slot("b1", "Bench One", "RB", True),
             slot("s2", "Starter Two", "WR", True),
             slot("s3", "Starter Three", "TE", False)]
    ok, wrong, missing = verify_applied(after, {"s1", "s2", "b1"})
    assert ok and wrong == [] and missing == []


def test_verify_names_what_is_wrong_when_a_swap_did_not_land():
    ok, wrong, missing = verify_applied(roster(), {"s1", "s2", "b1"})
    assert not ok
    assert wrong == ["s3"]
    assert missing == ["b1"]


def test_a_renamed_player_does_not_break_verification():
    # Ids are the join key everywhere in the write path; CBS shortening a
    # display name must not read as a failed swap.
    after = [slot("s1", "S. One", "RB", True), slot("s2", "S. Two", "WR", True),
             slot("b1", "B. One", "RB", True), slot("s3", "S. Three", "TE", False)]
    ok, _wrong, _missing = verify_applied(after, {"s1", "s2", "b1"})
    assert ok
