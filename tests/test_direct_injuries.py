"""The direct injury feed (sffl.direct_injuries). No network: every source is
a constructed payload handed to a fake `get`, with invented players and ids."""

import datetime
import json
import os

import pytest

from sffl import direct_injuries as di
from sffl import injuries

NOW = datetime.datetime(2026, 10, 23, 16, 45, 0)

CROSSWALK = (
    "mfl_id,cbs_id,gsis_id,sleeper_id,espn_id,name\n"
    "1,9000001,00-0090001,7001,5001,Pat Example\n"
    "2,9000002,00-0090002,7002,5002.0,Lee Sample\n"
    "3,NA,00-0090003,7003,5003,Kim Placeholder\n"
    "4,9000004,NA,NA,NA,Sam Nobody\n"
)

NFLVERSE = (
    "season,season_type,game_type,team,week,gsis_id,position,full_name,"
    "first_name,last_name,report_primary_injury,report_secondary_injury,"
    "report_status,practice_primary_injury,practice_secondary_injury,"
    "practice_status\n"
    "2026,REG,REG,SEA,5,00-0090001,WR,Pat Example,Pat,Example,Knee,NA,Out,"
    "Knee,NA,Did Not Participate In Practice\n"
    "2026,REG,REG,SEA,6,00-0090001,WR,Pat Example,Pat,Example,Knee,Ankle,"
    "Questionable,Knee,NA,Limited Participation in Practice\n"
    "2026,REG,REG,MIA,6,00-0090002,RB,Lee Sample,Lee,Sample,Hamstring,NA,,"
    "Hamstring,NA,Full Participation in Practice\n"
    "2026,REG,REG,SF,6,00-0090009,QB,Dee Thrower,Dee,Thrower,Shoulder,NA,"
    "Questionable,Shoulder,NA,NA\n"
)

STAMP = b'{"last_updated":"2026-10-23 08:41:10 EDT"}'

SLEEPER = {
    "7001": {"full_name": "Pat Example", "team": "SEA", "position": "WR",
             "active": True, "injury_status": "Out",
             "injury_body_part": "Knee", "news_updated": 1792800000000},
    "7002": {"full_name": "Lee Sample", "team": "MIA", "position": "RB",
             "active": True, "injury_status": None},
    "7003": {"full_name": "Kim Placeholder", "team": "DEN", "position": "TE",
             "active": True, "injury_status": "Questionable",
             "gsis_id": "00-0090003"},
    "7004": {"full_name": "Gone Away", "team": None, "position": "WR",
             "active": False, "injury_status": "IR"},
}

ESPN = {"injuries": [{"displayName": "Seattle", "injuries": [{
    "athlete": {"displayName": "Pat Example",
                "team": {"abbreviation": "SEA"},
                "position": {"abbreviation": "WR"},
                "links": [{"href": "https://www.espn.com/nfl/player/_/id/5001/pat-example"}]},
    "status": "Out", "date": "2026-10-23T14:05Z",
    "shortComment": "Example (knee) did not practice Thursday.",
    "longComment": "Longer text.",
    "details": {"returnDate": "2026-11-01"}}]}]}


def _get(responses, calls=None):
    """A fake `http_get`: url -> bytes, or an exception to raise."""
    def get(url, max_bytes):
        if calls is not None:
            calls.append(url)
        value = responses[url]
        if isinstance(value, Exception):
            raise value
        return value
    return get


def _responses(**override):
    r = {
        di.CROSSWALK_URL: CROSSWALK.encode(),
        di.NFLVERSE_STAMP_URL: STAMP,
        di.NFLVERSE_URL % 2026: NFLVERSE.encode(),
        di.SLEEPER_URL: json.dumps(SLEEPER).encode(),
        di.ESPN_URL: json.dumps(ESPN).encode(),
    }
    r.update(override)
    return r


# ------------------------------------------------------------- limits

def test_only_https_to_the_allowed_hosts():
    di.check_url("https://api.sleeper.app/v1/players/nfl")
    for bad in ("http://api.sleeper.app/v1/players/nfl",
                "https://example.com/x",
                "https://stripesfantasyfootballleague.football.cbssports.com/teams"):
        with pytest.raises(di.FetchError):
            di.check_url(bad)


def test_a_redirect_to_another_host_is_refused():
    handler = di._CheckedRedirect()
    with pytest.raises(di.FetchError):
        handler.redirect_request(None, None, 302, "Found", {},
                                 "https://elsewhere.example/x")


class _FakeResponse(object):
    def __init__(self, body, url):
        self.body, self.url = body, url

    def read(self, n):
        return self.body[:n]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_opener(monkeypatch, body=None, error=None, final_url=None):
    class _Opener(object):
        def open(self, req, timeout=None):
            if error is not None:
                raise error
            return _FakeResponse(body, final_url or req.full_url)
    monkeypatch.setattr(di.urllib.request, "build_opener",
                        lambda *handlers: _Opener())


def test_a_response_over_its_byte_cap_is_refused(monkeypatch):
    _fake_opener(monkeypatch, body=b"x" * 11)
    with pytest.raises(di.FetchError) as exc:
        di.http_get("https://api.sleeper.app/v1/players/nfl", 10)
    assert "more than 10 bytes" in str(exc.value)


def test_an_http_error_keeps_its_status(monkeypatch):
    err = di.urllib.error.HTTPError(di.ESPN_URL, 403, "Forbidden", {}, None)
    _fake_opener(monkeypatch, error=err)
    with pytest.raises(di.FetchError) as exc:
        di.http_get(di.ESPN_URL, 100)
    assert exc.value.status == 403


def test_a_final_url_off_the_allowlist_is_refused(monkeypatch):
    _fake_opener(monkeypatch, body=b"{}", final_url="https://elsewhere.example/x")
    with pytest.raises(di.FetchError):
        di.http_get(di.ESPN_URL, 100)


def test_every_request_says_who_is_asking(monkeypatch):
    seen = {}

    class _Opener(object):
        def open(self, req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            seen["timeout"] = timeout
            return _FakeResponse(b"{}", req.full_url)

    monkeypatch.setattr(di.urllib.request, "build_opener",
                        lambda *handlers: _Opener())
    di.http_get(di.ESPN_URL, 100)
    assert "non-commercial" in seen["ua"] and "github.com" in seen["ua"]
    assert seen["timeout"] == di.TIMEOUT_S


# ------------------------------------------------------------- parsers

def test_the_crosswalk_maps_each_source_id_to_cbs():
    xw = di.parse_crosswalk(CROSSWALK)
    assert xw["gsis"]["00-0090001"] == "9000001"
    assert xw["sleeper"]["7002"] == "9000002"
    assert xw["espn"]["5002"] == "9000002"          # "5002.0" cleaned
    assert "00-0090003" not in xw["gsis"]           # no CBS id: skipped


def test_a_crosswalk_without_its_columns_raises():
    with pytest.raises(ValueError):
        di.parse_crosswalk("a,b\n1,2\n")


def test_the_nflverse_stamp_drops_seconds():
    assert di.parse_stamp(STAMP) == "2026-10-23 08:41 EDT"
    with pytest.raises(ValueError):
        di.parse_stamp(b'{"other": 1}')


def test_nflverse_keeps_only_the_latest_week_in_the_contract_shape():
    week, rows = di.parse_nflverse(NFLVERSE, "2026-10-23 08:41 EDT",
                                   di.parse_crosswalk(CROSSWALK))
    assert week == 6
    by_name = dict((r["player"], r) for r in rows)
    assert sorted(by_name) == ["Dee Thrower", "Lee Sample", "Pat Example"]
    pat = by_name["Pat Example"]
    assert (pat["status"], pat["practice"], pat["detail"]) == (
        "Questionable", "Limited Participation in Practice", "Knee, Ankle")
    assert (pat["cbs_id"], pat["source"], pat["as_of"]) == (
        "9000001", "nflverse", "2026-10-23 08:41 EDT")
    # On the report for practice only: StatsDeck's word for no designation.
    assert by_name["Lee Sample"]["status"] == "Not listed"
    assert by_name["Dee Thrower"]["practice"] == ""


def test_nflverse_without_its_columns_raises():
    with pytest.raises(ValueError):
        di.parse_nflverse("season,week\n2026,6\n", "x", di.parse_crosswalk(CROSSWALK))


def test_sleeper_rows_are_injured_active_players_with_cbs_ids():
    rows = di.sleeper_rows(SLEEPER, di.parse_crosswalk(CROSSWALK))
    by_name = dict((r["player"], r) for r in rows)
    assert sorted(by_name) == ["Kim Placeholder", "Pat Example"]
    assert by_name["Pat Example"]["cbs_id"] == "9000001"
    assert by_name["Pat Example"]["notes"] == "Knee"
    assert by_name["Pat Example"]["reported_date"]
    assert by_name["Kim Placeholder"]["cbs_id"] == ""   # crosswalk has none


def test_a_player_sleeper_no_longer_lists_as_hurt_is_news_once():
    prev = {"sleeper:7002": {"status": "Questionable", "since": "x"}}
    rows = di.sleeper_cleared_rows(SLEEPER, di.parse_crosswalk(CROSSWALK), prev)
    assert [(r["player"], r["status"]) for r in rows] == [("Lee Sample", "cleared")]


def test_espn_rows_take_the_id_from_the_player_link_and_the_short_comment():
    rows = di.espn_rows(ESPN, di.parse_crosswalk(CROSSWALK))
    assert len(rows) == 1
    r = rows[0]
    assert (r["espn_id"], r["cbs_id"], r["status"]) == ("5001", "9000001", "Out")
    assert r["notes"] == "Example (knee) did not practice Thursday."
    assert r["return_date"] == "2026-11-01"
    assert r["reported_date"].startswith("2026-10-2")


def test_an_espn_payload_of_the_wrong_shape_raises():
    with pytest.raises(ValueError):
        di.espn_rows({"teams": []}, di.parse_crosswalk(CROSSWALK))


# ------------------------------------------------------------- changes

def test_change_fields_come_from_our_own_last_snapshot():
    rows = [{"source": "sleeper", "_key": "1", "status": "Out"},
            {"source": "sleeper", "_key": "2", "status": "Questionable"},
            {"source": "sleeper", "_key": "3", "status": "Doubtful"}]
    prev = {"sleeper:1": {"status": "Questionable", "since": "2026-10-20T16:45:00"},
            "sleeper:2": {"status": "Questionable", "since": "2026-10-20T16:45:00"}}
    state = di.derive_changes(rows, prev, "2026-10-23T16:45:00")
    assert (rows[0]["previous_status"], rows[0]["status_since"]) == (
        "Questionable", "2026-10-23T16:45:00")
    # Unchanged: keeps when it was first seen, and is not a change.
    assert (rows[1]["previous_status"], rows[1]["status_since"]) == (
        "", "2026-10-20T16:45:00")
    # Never seen: its clock starts now, with nothing to compare.
    assert (rows[2]["previous_status"], rows[2]["status_since"]) == (
        "", "2026-10-23T16:45:00")
    assert state["sleeper:1"] == {"status": "Out", "since": "2026-10-23T16:45:00"}


def test_a_cleared_row_is_a_change_but_is_not_remembered():
    rows = [{"source": "sleeper", "_key": "1", "status": "cleared"}]
    state = di.derive_changes(
        rows, {"sleeper:1": {"status": "Out", "since": "t0"}}, "t1")
    assert rows[0]["previous_status"] == "Out"
    assert state == {}


# ------------------------------------------------------------- cache

def test_a_fresh_cache_is_used_without_a_request(tmp_path):
    calls = []
    get = _get({"https://api.sleeper.app/x": b"new"}, calls)
    d = str(tmp_path)
    di.cached_get(d, "s.json", "https://api.sleeper.app/x", 100, 3600, NOW, get)
    data, _, how = di.cached_get(d, "s.json", "https://api.sleeper.app/x", 100,
                                 3600, NOW + datetime.timedelta(minutes=30), get)
    assert (data, how, len(calls)) == (b"new", "cached", 1)


def test_an_expired_cache_fetches_again(tmp_path):
    calls = []
    get = _get({"https://api.sleeper.app/x": b"new"}, calls)
    d = str(tmp_path)
    di.cached_get(d, "s.json", "https://api.sleeper.app/x", 100, 3600, NOW, get)
    di.cached_get(d, "s.json", "https://api.sleeper.app/x", 100, 3600,
                  NOW + datetime.timedelta(hours=2), get)
    assert len(calls) == 2


def test_a_stale_copy_is_used_only_when_allowed(tmp_path):
    d = str(tmp_path)
    di.cached_get(d, "x.csv", "https://raw.githubusercontent.com/x", 100, 60,
                  NOW, _get({"https://raw.githubusercontent.com/x": b"old"}))
    later = NOW + datetime.timedelta(days=9)
    failing = _get({"https://raw.githubusercontent.com/x": di.FetchError("down")})
    data, _, how = di.cached_get(d, "x.csv", "https://raw.githubusercontent.com/x",
                                 100, 60, later, failing, stale_ok=True)
    assert data == b"old" and how.startswith("stale copy")
    with pytest.raises(di.FetchError):
        di.cached_get(d, "x.csv", "https://raw.githubusercontent.com/x", 100, 60,
                      later, failing)


# ------------------------------------------------------------- the run

def test_a_run_writes_a_file_the_alert_can_read(tmp_path):
    out = str(tmp_path / "injuries-friday.direct.json")
    code = di.fetch(out, str(tmp_path / "cache"), now=NOW, season=2026,
                    kind="friday", get=_get(_responses()), log=lambda *a: None)
    assert code == 0
    raw = json.load(open(out))
    assert raw["meta"]["week"] == 6
    assert set(raw["meta"]["sources"]) == {"crosswalk", "nflverse", "sleeper", "espn"}
    reports = injuries.load(out)
    official = [r for r in reports if r.source == "official"]
    assert len(official) == 3
    assert all(r.outlet == "nflverse" and r.as_of for r in official)
    assert set(r.outlet for r in reports if r.source == "intel") == {"sleeper", "espn"}
    assert not any("_key" in row for row in raw["report"] + raw["intel"])
    assert injuries.source_notes(out) == []


def test_a_second_run_reports_what_changed_since_the_first(tmp_path):
    cache, out = str(tmp_path / "cache"), str(tmp_path / "x.direct.json")
    quiet = lambda *a: None
    di.fetch(out, cache, now=NOW, season=2026, get=_get(_responses()), log=quiet)
    changed = json.loads(json.dumps(SLEEPER))
    changed["7001"]["injury_status"] = "IR"
    di.fetch(out, cache, now=NOW + datetime.timedelta(days=2), season=2026,
             get=_get(_responses(**{di.SLEEPER_URL: json.dumps(changed).encode()})),
             log=quiet)
    rows = json.load(open(out))["intel"]
    pat = [r for r in rows if r["source"] == "sleeper" and r["player"] == "Pat Example"][0]
    assert (pat["status"], pat["previous_status"]) == ("IR", "Out")


def test_no_official_report_means_no_file_at_all(tmp_path):
    out = tmp_path / "x.direct.json"
    out.write_text("{}")   # last run's file must not survive a failed run
    code = di.fetch(str(out), str(tmp_path / "cache"), now=NOW, season=2026,
                    get=_get(_responses(**{di.NFLVERSE_STAMP_URL: di.FetchError("down")})),
                    log=lambda *a: None)
    assert code == 1
    assert not out.exists()


def test_espn_blocking_us_switches_it_off_until_someone_looks(tmp_path):
    cache, out = str(tmp_path / "cache"), str(tmp_path / "x.direct.json")
    blocked = di.FetchError("HTTP 403 from site.api.espn.com", status=403)
    code = di.fetch(out, cache, now=NOW, season=2026,
                    get=_get(_responses(**{di.ESPN_URL: blocked})), log=lambda *a: None)
    assert code == 0
    espn = json.load(open(out))["meta"]["sources"]["espn"]
    assert espn["off"] and not espn["ok"]
    assert os.path.exists(os.path.join(cache, di.ESPN_OFF_FILE))
    assert any(n.startswith("espn unavailable") for n in injuries.source_notes(out))

    calls = []
    di.fetch(out, cache, now=NOW + datetime.timedelta(days=2), season=2026,
             get=_get(_responses(), calls), log=lambda *a: None)
    assert di.ESPN_URL not in calls
    assert json.load(open(out))["meta"]["sources"]["espn"]["off"]


def test_an_ordinary_espn_failure_does_not_switch_it_off(tmp_path):
    cache, out = str(tmp_path / "cache"), str(tmp_path / "x.direct.json")
    down = di.FetchError("HTTP 503 from site.api.espn.com", status=503)
    di.fetch(out, cache, now=NOW, season=2026,
             get=_get(_responses(**{di.ESPN_URL: down})), log=lambda *a: None)
    assert not os.path.exists(os.path.join(cache, di.ESPN_OFF_FILE))
    assert not json.load(open(out))["meta"]["sources"]["espn"]["ok"]


def test_a_missing_crosswalk_still_writes_rows_matched_by_name(tmp_path):
    out = str(tmp_path / "x.direct.json")
    code = di.fetch(out, str(tmp_path / "cache"), now=NOW, season=2026,
                    get=_get(_responses(**{di.CROSSWALK_URL: di.FetchError("down")})),
                    log=lambda *a: None)
    assert code == 0
    assert all(not r["cbs_id"] for r in json.load(open(out))["report"])
    assert any(n.startswith("crosswalk unavailable") for n in injuries.source_notes(out))


def test_the_season_turns_over_in_march():
    assert di.season_for(datetime.date(2027, 1, 10)) == 2026
    assert di.season_for(datetime.date(2027, 3, 1)) == 2027


def test_the_cli_refuses_the_live_alerts_own_file(tmp_path, capsys):
    from sffl import cli

    code = cli.main(["injuries-fetch", "--out",
                     str(tmp_path / "injuries-friday.json")])
    assert code == 2
    assert "live alert's injury file" in capsys.readouterr().err


def _espn_with(status):
    data = json.loads(json.dumps(ESPN))
    data["injuries"][0]["injuries"][0]["status"] = status
    return json.dumps(data).encode()


def test_an_espn_active_row_is_kept_only_as_a_return(tmp_path):
    # ESPN keeps an "Active" row (usually a game recap) for most players; only
    # a change to Active is injury news.
    cache, out = str(tmp_path / "cache"), str(tmp_path / "x.direct.json")
    quiet = lambda *a: None
    di.fetch(out, cache, now=NOW, season=2026, log=quiet,
             get=_get(_responses(**{di.ESPN_URL: _espn_with("Active")})))
    meta = json.load(open(out))["meta"]["sources"]["espn"]
    assert not [r for r in json.load(open(out))["intel"] if r["source"] == "espn"]
    assert meta["active_recaps_left_out"] == 1

    di.fetch(out, cache, now=NOW + datetime.timedelta(days=1), season=2026,
             log=quiet, get=_get(_responses(**{di.ESPN_URL: _espn_with("Questionable")})))
    di.fetch(out, cache, now=NOW + datetime.timedelta(days=2), season=2026,
             log=quiet, get=_get(_responses(**{di.ESPN_URL: _espn_with("Active")})))
    espn = [r for r in json.load(open(out))["intel"] if r["source"] == "espn"]
    assert [(r["status"], r["previous_status"]) for r in espn] == [
        ("Active", "Questionable")]
