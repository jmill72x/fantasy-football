"""The season-bound defaults warn when they are another season's (sffl.season).

STALE means the value's season is older than the run's: `--year` for the
board commands, the season of today's date otherwise - and January and
February still belong to the previous season, so the 2026 season's last weeks
and its 2027-01-12 results run stay silent. Nothing here depends on the real
today: every date is fixed, or `sffl.season.today` is stubbed.
"""

import datetime
import os
import re
import time

import pytest

from sffl import season
from sffl.cli import DEFAULT_LEAGUE, main
from sffl.league import load_league
from sffl.render.rows import DEFAULT_BYES

DS = "sources/draftsharks.yaml"
FIXTURE = "tests/fixtures/draftsharks_value_sample.csv"
HERE = os.path.dirname(os.path.abspath(__file__))
RUN_ALERT = os.path.join(HERE, "..", "ops", "run_alert.sh")

D = datetime.date


# --------------------------------------------------- the season of a date

@pytest.mark.parametrize("day,expected", [
    (D(2026, 3, 1), 2026),
    (D(2026, 9, 9), 2026),      # 2026's week 1 begins
    (D(2026, 10, 21), 2026),
    (D(2026, 12, 31), 2026),
    (D(2027, 1, 5), 2026),      # week 17, STRIPES's last playoff week, ends
    (D(2027, 1, 12), 2026),     # the Tuesday run that collects week 18's results
    (D(2027, 1, 31), 2026),
    (D(2027, 2, 28), 2026),
    (D(2027, 3, 1), 2027),      # the NFL's new league year
    (D(2027, 9, 15), 2027),
    (D(2026, 2, 28), 2025),
])
def test_january_and_february_belong_to_the_season_before(day, expected):
    assert season.season_for(day) == expected


def test_the_injury_feed_uses_the_same_rule():
    from sffl import direct_injuries
    assert direct_injuries.season_for is season.season_for


def test_the_runs_season_is_year_when_given_else_the_date():
    assert season.run_season(year=2027) == (2027, "--year 2027")
    assert season.run_season(day=D(2027, 1, 12)) == (
        2026, "by today's date, 2027-01-12")


def test_today_is_the_default_day(monkeypatch):
    monkeypatch.setattr(season, "today", lambda: D(2027, 9, 15))
    assert season.run_season() == (2027, "by today's date, 2027-09-15")


# ------------------------------------------------------- what stale means

def test_a_value_for_the_runs_own_season_is_silent():
    assert season.check("league profile", "p.yaml", 2026, 2026, "b") is None


def test_a_value_that_names_no_season_is_not_checked():
    assert season.check("bye file", "byes.yaml", None, 2027, "b") is None


def test_an_older_value_is_stale_and_names_its_fix():
    m = season.check("league profile", "leagues/sffl/2026.yaml", 2026, 2027,
                     "--year 2027")
    assert m.stale and m.step == 2
    assert season.line(m) == (
        "STALE SEASON VALUE: The league profile leagues/sffl/2026.yaml is for "
        "the 2026 season, but this run is for 2027 (--year 2027). Fix: use "
        "the 2027 profile (--league, or DEFAULT_LEAGUE in src/sffl/cli.py) "
        "(preseason runbook, step 2).")


def test_a_newer_value_is_ahead_the_same_mistake_the_other_way():
    m = season.check("bye file", "leagues/nfl-byes-2027.yaml", 2027, 2026,
                     "by today's date, 2027-01-12")
    assert not m.stale and m.step == 3
    assert season.title(m) == "SEASON VALUE AHEAD"
    assert "use the 2026 bye file" in season.detail(m)


def test_an_unknown_value_name_is_refused():
    with pytest.raises(ValueError):
        season.check("calibration curves", "c.yaml", 2025, 2027, "b")


def _all_three(run_day, profile=2026, byes=2026, week1=D(2026, 9, 9)):
    run, basis = season.run_season(day=run_day)
    found = [season.check("league profile", "p", profile, run, basis),
             season.check("bye file", "b", byes, run, basis),
             season.check("week-1 date", "w", season.season_for(week1), run,
                          basis)]
    return [m for m in found if m is not None]


def test_every_day_of_the_2026_season_through_february_is_silent():
    # Today's runs, the playoffs, the January results run: all silent.
    day = D(2026, 3, 1)
    while day <= D(2027, 2, 28):
        assert _all_three(day) == [], day
        day += datetime.timedelta(days=1)


def test_the_first_day_of_the_2027_league_year_finds_all_three_stale():
    found = _all_three(D(2027, 3, 1))
    assert [m.value for m in found] == ["league profile", "bye file",
                                        "week-1 date"]
    assert all(m.stale and m.run_season == 2027 for m in found)


def test_the_digest_banner_and_the_board_note():
    found = _all_three(D(2027, 9, 15))
    lines = season.banner(found)
    assert lines[0] == ("!! STALE SEASON VALUES - this run is for the 2027 "
                        "season (by today's date, 2027-09-15), but:")
    assert len(lines) == 5 and lines[-1].startswith("  Everything below")
    assert lines[3] == ("  - the week-1 date w is the 2026 season's: the "
                        "week number is wrong (preseason runbook, step 13).")
    assert all(len(line) < 140 for line in lines)     # short, for the phone
    assert season.board_note(found[:2]) == (
        "!! STALE SEASON VALUES: the league profile is the 2026 season's; the "
        "bye file is the 2026 season's, not this 2027 board's - re-render "
        "with this season's (preseason runbook, steps 2 and 3).")


def test_a_banner_with_a_newer_value_does_not_call_it_stale():
    found = _all_three(D(2027, 1, 12), week1=D(2027, 9, 8))
    assert [m.value for m in found] == ["week-1 date"]
    assert season.banner(found)[0].startswith(
        "!! SEASON VALUES FROM ANOTHER SEASON - this run is for the 2026")


# ------------------------------------- the values' own seasons, in the repo

def test_file_season_reads_the_key_then_the_file_name(tmp_path):
    keyed = tmp_path / "nfl-byes-2027.yaml"
    keyed.write_text("season: 2026\nbyes: {}\n")
    assert season.file_season(str(keyed)) == 2026     # the key wins
    named = tmp_path / "nfl-byes-2027.yaml.copy"
    named.write_text("byes: {}\n")
    assert season.file_season(str(named)) == 2027
    bare = tmp_path / "byes.yaml"
    bare.write_text("byes: {}\n")
    assert season.file_season(str(bare)) is None
    assert season.file_season(str(tmp_path / "missing-2031.yaml")) == 2031


def test_each_default_file_says_the_season_its_name_says():
    # Season-agnostic on purpose: next year's copies must update the key, and
    # a copy that kept last year's key fails here, not on auction night.
    for path, own in ((DEFAULT_LEAGUE, load_league(DEFAULT_LEAGUE).season),
                      (DEFAULT_BYES, season.file_season(DEFAULT_BYES))):
        named = int(re.search(r"(20\d\d)", os.path.basename(path)).group(1))
        assert own == named, path


def _week1_in_script():
    text = open(RUN_ALERT).read()
    return text, D.fromisoformat(
        re.search(r'^WEEK1="(\d{4}-\d\d-\d\d)"$', text, re.M).group(1))


def test_the_alert_scripts_week1_is_a_wednesday_and_reaches_the_alert():
    text, week1 = _week1_in_script()
    assert week1.weekday() == 2          # weeks run Wednesday to Tuesday
    assert '" "$WEEK1")' in text         # the week number is computed from it
    alert = text[text.index("-m sffl.cli alert"):text.index("ALERT_RC=$?")]
    assert '--week1 "$WEEK1"' in alert   # and the alert checks it


# ------------------------------------------- the --year commands, for real

def test_a_2026_board_prints_no_season_warning(capsys):
    assert main(["value", "--source", DS, "--file", FIXTURE,
                 "--year", "2026"]) == 0
    assert "SEASON VALUE" not in capsys.readouterr().out


def test_a_2027_board_on_the_2026_profile_warns_and_still_runs(capsys):
    assert main(["value", "--source", DS, "--file", FIXTURE,
                 "--year", "2027"]) == 0
    out = capsys.readouterr().out
    assert "** STALE SEASON VALUE **" in out
    assert "league profile leagues/sffl/2026.yaml" in out
    assert "bye file" not in out          # value takes no --byes


def _model(tmp_path):
    from sffl.market_model import MarketModel, save
    path = str(tmp_path / "m.yaml")
    save(path, MarketModel(season=2026, fitted_on="2026-08-30",
                           curve=(2.05, 0.662), policy="starter",
                           evidence={"observations": 130}, diagnostics={}))
    return path


def test_plan_2027_warns_about_the_bye_file_and_the_profile(tmp_path, capsys):
    assert main(["plan", "--source", DS, "--file", FIXTURE, "--year", "2027",
                 "--market", _model(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("** STALE SEASON VALUE **") == 2
    assert "bye file leagues/nfl-byes-2026.yaml" in out
    assert "step 3" in out


def _intel_text(xlsx):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx)["Key & Intel"]
    return "\n".join(str(c) for row in ws.iter_rows(values_only=True)
                     for c in row if c is not None)


def test_render_2027_puts_the_warning_on_the_key_and_intel_sheet(tmp_path,
                                                                  capsys):
    xlsx = str(tmp_path / "board.xlsx")
    assert main(["render", "--source", DS, "--file", FIXTURE, "--year", "2027",
                 "--market", _model(tmp_path), "--xlsx", xlsx]) == 0
    assert "** STALE SEASON VALUE **" in capsys.readouterr().out
    sheet = " ".join(_intel_text(xlsx).split())
    assert ("!! STALE SEASON VALUES: the league profile is the 2026 season's; "
            "the bye file is the 2026 season's, not this 2027 board's") in sheet


def test_render_2026_sheet_carries_no_season_note(tmp_path, capsys):
    xlsx = str(tmp_path / "board.xlsx")
    assert main(["render", "--source", DS, "--file", FIXTURE, "--year", "2026",
                 "--xlsx", xlsx]) == 0
    assert "SEASON VALUE" not in capsys.readouterr().out
    assert "SEASON VALUES" not in _intel_text(xlsx)


def _copy_with_season(src, dest, year):
    text = open(src).read()
    dest.write_text(re.sub(r"^season: \d{4}$", "season: %d" % year, text,
                           count=1, flags=re.M))
    return str(dest)


def test_the_runbooks_explicit_2027_files_silence_it(tmp_path, capsys):
    # Preseason runbook step 7's command shape: --league and --byes for the
    # new season, and the 2026 market model applied across seasons.
    league = _copy_with_season(DEFAULT_LEAGUE, tmp_path / "2027.yaml", 2027)
    byes = _copy_with_season(DEFAULT_BYES, tmp_path / "nfl-byes-2027.yaml",
                             2027)
    xlsx = str(tmp_path / "board.xlsx")
    assert main(["render", "--source", DS, "--file", FIXTURE, "--year", "2027",
                 "--market", _model(tmp_path), "--league", league,
                 "--byes", byes, "--xlsx", xlsx]) == 0
    out = capsys.readouterr().out
    assert "SEASON VALUE" not in out
    assert "CROSS-SEASON" in out          # the market model's own note stays
    assert "SEASON VALUES" not in _intel_text(xlsx)


def test_a_newer_profile_in_an_older_run_is_ahead(tmp_path, capsys):
    league = _copy_with_season(DEFAULT_LEAGUE, tmp_path / "2027.yaml", 2027)
    assert main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
                 "--league", league]) == 0
    out = capsys.readouterr().out
    assert "** SEASON VALUE AHEAD **" in out
    assert "use the 2026 profile" in out


# ------------------------------------------- collect, by the date it runs

@pytest.mark.parametrize("day,warned", [("2026-10-21", False),
                                        ("2027-01-12", False),
                                        ("2027-09-15", True)])
def test_collect_warns_when_the_profile_is_not_the_dates_season(
        tmp_path, capsys, day, warned):
    captures = tmp_path / "captures"
    captures.mkdir()
    rc = main(["collect", "--kind", "sunday", "--week", "7",
               "--since", str(time.time() + 3600), "--date", day,
               "--captures", str(captures),
               "--archive", str(tmp_path / "a"), "--no-pi", "--no-repo"])
    out = capsys.readouterr().out
    assert rc == 0                         # warned, never refused
    assert ("** STALE SEASON VALUE **" in out) is warned


# ------------------------------- week and trade, by the season of today

def _names(tmp_path, names):
    path = tmp_path / "roster.txt"
    path.write_text("\n".join(names) + "\n")
    return str(path)


@pytest.mark.parametrize("day,warned", [(D(2026, 10, 21), False),
                                        (D(2027, 1, 5), False),
                                        (D(2027, 9, 15), True)])
def test_week_and_trade_warn_on_a_profile_from_another_season(
        tmp_path, capsys, monkeypatch, day, warned):
    monkeypatch.setattr(season, "today", lambda: day)
    assert main(["week", "--projections", "tests/fixtures/cbs_weekly_rbwrte.txt",
                 "--group", "RB-WR-TE", "--week", "1", "--roster",
                 _names(tmp_path, ["Sam LaPorta", "Kyle Pitts"]),
                 "--waivers"]) == 0
    week_out = capsys.readouterr().out
    assert main(["trade", "--projections", "tests/fixtures/cbs_ros_rbwrte.txt",
                 "--roster", _names(tmp_path, ["Alpha Back", "Alpha Wide"]),
                 "--week", "1"]) == 0
    trade_out = capsys.readouterr().out
    for out in (week_out, trade_out):
        assert ("** STALE SEASON VALUE **" in out) is warned
