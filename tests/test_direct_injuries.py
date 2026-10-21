"""The direct injury feed (sffl.direct_injuries). No network: every source is
a constructed payload handed to a fake `get`, with invented players and ids,
and tests/conftest.py refuses any real connection."""

import datetime
import http.client
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

NFLVERSE_HEADER = (
    "season,season_type,game_type,team,week,gsis_id,position,full_name,"
    "first_name,last_name,report_primary_injury,report_secondary_injury,"
    "report_status,practice_primary_injury,practice_secondary_injury,"
    "practice_status\n")
NFLVERSE = NFLVERSE_HEADER + (
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


def _run(tmp_path, kind="friday", now=NOW, cache="cache", out="x.direct.json",
         calls=None, **override):
    path = str(tmp_path / out)
    code = di.fetch(path, str(tmp_path / cache), now=now, season=2026,
                    kind=kind, get=_get(_responses(**override), calls),
                    log=lambda *a: None)
    return code, path


# ------------------------------------------------------------- limits

class _FakeResponse(object):
    def __init__(self, body, url, length=None):
        self.body, self.url, self.pos = body, url, 0
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def read(self, n):
        chunk = self.body[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_opener(monkeypatch, body=b"{}", error=None, final_url=None,
                 length=None, seen=None):
    class _Opener(object):
        def open(self, req, timeout=None):
            if seen is not None:
                seen["ua"] = req.get_header("User-agent")
                seen["timeout"] = timeout
            if error is not None:
                raise error
            return _FakeResponse(body, final_url or req.full_url, length)
    monkeypatch.setattr(di.urllib.request, "build_opener",
                        lambda *handlers: _Opener())


def test_only_https_to_the_allowed_hosts_and_the_note_names_only_the_host():
    di.check_url("https://api.sleeper.app/v1/players/nfl")
    for bad in ("http://api.sleeper.app/v1/players/nfl",
                "https://example.com/some/secret/path",
                "https://stripesfantasyfootballleague.football.cbssports.com/teams"):
        with pytest.raises(di.FetchError) as exc:
            di.check_url(bad)
        assert "/" not in str(exc.value).split(" ")[1]     # a host, no path


def test_a_redirect_to_another_host_is_refused_as_a_redirect():
    handler = di._CheckedRedirect()
    with pytest.raises(di.FetchError) as exc:
        handler.redirect_request(None, None, 302, "Found", {},
                                 "https://elsewhere.example/x")
    assert exc.value.kind == "redirect"


def test_a_response_over_its_byte_cap_is_refused(monkeypatch):
    _fake_opener(monkeypatch, body=b"x" * 11)
    with pytest.raises(di.FetchError) as exc:
        di.http_get("https://api.sleeper.app/v1/players/nfl", 10)
    assert exc.value.kind == "size"


def test_an_announced_length_over_the_cap_is_refused_before_reading(monkeypatch):
    _fake_opener(monkeypatch, body=b"x", length=999)
    with pytest.raises(di.FetchError) as exc:
        di.http_get("https://api.sleeper.app/v1/players/nfl", 10)
    assert exc.value.kind == "size"


def test_a_body_shorter_than_its_content_length_is_refused(monkeypatch):
    _fake_opener(monkeypatch, body=b'{"a":', length=20)
    with pytest.raises(di.FetchError) as exc:
        di.http_get(di.ESPN_URL, 100)
    assert exc.value.kind == "short"


def test_a_request_over_its_wall_clock_limit_is_refused(monkeypatch):
    _fake_opener(monkeypatch, body=b"x" * (3 * di.CHUNK))
    ticks = iter([0.0, 50.0, 130.0, 200.0, 300.0])
    with pytest.raises(di.FetchError) as exc:
        di.http_get(di.ESPN_URL, 10 * di.CHUNK, clock=lambda: next(ticks))
    assert exc.value.kind == "time"


def test_an_http_error_keeps_its_status(monkeypatch):
    err = di.urllib.error.HTTPError(di.ESPN_URL, 403, "Forbidden", {}, None)
    _fake_opener(monkeypatch, error=err)
    with pytest.raises(di.FetchError) as exc:
        di.http_get(di.ESPN_URL, 100)
    assert (exc.value.status, exc.value.kind) == (403, "http")


def test_an_http_client_error_becomes_a_fetch_error(monkeypatch):
    _fake_opener(monkeypatch, error=http.client.IncompleteRead(b"partial"))
    with pytest.raises(di.FetchError) as exc:
        di.http_get(di.ESPN_URL, 100)
    assert exc.value.kind == "network"
    assert "IncompleteRead" in str(exc.value) and "espn.com/" not in str(exc.value)


def test_a_final_url_off_the_allowlist_is_refused(monkeypatch):
    _fake_opener(monkeypatch, final_url="https://elsewhere.example/x")
    with pytest.raises(di.FetchError) as exc:
        di.http_get(di.ESPN_URL, 100)
    assert exc.value.kind == "redirect"


def test_every_request_names_the_tool_and_says_personal_non_commercial(monkeypatch):
    seen = {}
    _fake_opener(monkeypatch, seen=seen)
    di.http_get(di.ESPN_URL, 100)
    assert seen["ua"].startswith("sffl-injuries/")
    assert "personal, non-commercial" in seen["ua"]
    assert "http" not in seen["ua"] and "github" not in seen["ua"]
    assert seen["timeout"] == di.TIMEOUT_S


# ------------------------------------------------------------- parsers

def test_the_crosswalk_maps_each_source_id_to_cbs():
    xw = di.parse_crosswalk(CROSSWALK)
    assert xw["gsis"]["00-0090001"] == "9000001"
    assert xw["sleeper"]["7002"] == "9000002"
    assert xw["espn"]["5002"] == "9000002"          # "5002.0" cleaned
    assert "00-0090003" not in xw["gsis"]           # no CBS id: skipped


def test_a_crosswalk_without_its_columns_or_cbs_ids_raises():
    with pytest.raises(ValueError):
        di.parse_crosswalk("a,b\n1,2\n")
    with pytest.raises(ValueError):
        di.parse_crosswalk("cbs_id,gsis_id,sleeper_id,espn_id\nNA,1,2,3\n")


def test_the_nflverse_stamp_keeps_only_a_short_zone_or_an_offset():
    assert di.parse_stamp(STAMP) == "2026-10-23 08:41 EDT"
    assert di.parse_stamp(b'{"last_updated":"2026-10-23 08:41:10 -04:00"}') == (
        "2026-10-23 08:41 -04:00")
    assert di.parse_stamp(b'{"last_updated":"2026-10-23 08:41:10 <b>x</b>"}') == (
        "2026-10-23 08:41")
    with pytest.raises(ValueError):
        di.parse_stamp(b'{"other": 1}')


def test_nflverse_keeps_only_the_latest_week_in_the_contract_shape():
    week, rows, skipped = di.parse_nflverse(NFLVERSE, "2026-10-23 08:41 EDT",
                                            di.parse_crosswalk(CROSSWALK))
    assert (week, skipped) == (6, 0)
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


def test_an_unreadable_nflverse_row_is_skipped_and_counted():
    text = NFLVERSE + "2026,REG,REG,SEA,six,00-0090008,WR,Bad Row,B,R,,,,,,\n"
    week, rows, skipped = di.parse_nflverse(text, "x", di.parse_crosswalk(CROSSWALK))
    assert (week, len(rows), skipped) == (6, 3, 1)


def test_nflverse_without_its_columns_raises():
    with pytest.raises(ValueError):
        di.parse_nflverse("season,week\n2026,6\n", "x", di.parse_crosswalk(CROSSWALK))


def test_sleeper_rows_are_injured_active_players_with_cbs_ids():
    rows, skipped = di.sleeper_rows(SLEEPER, di.parse_crosswalk(CROSSWALK))
    by_name = dict((r["player"], r) for r in rows)
    assert sorted(by_name) == ["Kim Placeholder", "Pat Example"] and skipped == 0
    assert by_name["Pat Example"]["cbs_id"] == "9000001"
    assert by_name["Pat Example"]["notes"] == "Knee"
    assert by_name["Pat Example"]["reported_date"]
    assert by_name["Kim Placeholder"]["cbs_id"] == ""   # crosswalk has none


def test_a_sleeper_row_with_a_field_of_the_wrong_type_is_skipped_not_the_feed():
    players = dict(SLEEPER)
    players["7100"] = {"full_name": "Odd Types", "team": "SEA", "active": "yes",
                       "injury_status": "Out"}
    players["7101"] = {"full_name": ["not", "a", "name"], "team": "SEA",
                       "active": True, "injury_status": "Out"}
    players["7102"] = "not even an object"
    rows, skipped = di.sleeper_rows(players, di.parse_crosswalk(CROSSWALK))
    assert sorted(r["player"] for r in rows) == ["Kim Placeholder", "Pat Example"]
    assert skipped == 3


def test_a_player_sleeper_no_longer_lists_as_hurt_is_news_once():
    prev = {"sleeper:7002": {"status": "Questionable", "since": "x"}}
    rows = di.sleeper_cleared_rows(SLEEPER, di.parse_crosswalk(CROSSWALK), prev)
    assert [(r["player"], r["status"]) for r in rows] == [("Lee Sample", "cleared")]


def test_espn_rows_take_the_id_from_the_player_link_and_the_short_comment():
    rows, skipped = di.espn_rows(ESPN, di.parse_crosswalk(CROSSWALK))
    assert (len(rows), skipped) == (1, 0)
    r = rows[0]
    assert (r["espn_id"], r["cbs_id"], r["status"]) == ("5001", "9000001", "Out")
    assert r["notes"] == "Example (knee) did not practice Thursday."
    assert r["return_date"] == "2026-11-01"
    assert r["reported_date"].startswith("2026-10-2")


def test_a_malformed_espn_row_or_team_is_skipped_and_counted():
    data = json.loads(json.dumps(ESPN))
    items = data["injuries"][0]["injuries"]
    items.append({"athlete": "not an object", "status": "Out"})
    items.append({"athlete": {"displayName": "No Status"}, "status": 7})
    data["injuries"].append({"displayName": "Broken", "injuries": "nope"})
    rows, skipped = di.espn_rows(data, di.parse_crosswalk(CROSSWALK))
    assert [r["player"] for r in rows] == ["Pat Example"] and skipped == 3


def test_an_espn_payload_of_the_wrong_shape_raises():
    with pytest.raises(ValueError):
        di.espn_rows({"teams": []}, di.parse_crosswalk(CROSSWALK))


def test_third_party_text_is_capped():
    data = json.loads(json.dumps(ESPN))
    data["injuries"][0]["injuries"][0]["shortComment"] = "word " * 400
    rows, _ = di.espn_rows(data, di.parse_crosswalk(CROSSWALK))
    assert len(rows[0]["notes"]) <= di.NOTE_MAX and rows[0]["notes"].endswith("...")


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

URL = "https://api.sleeper.app/x"


def test_a_fresh_cache_is_used_without_a_request(tmp_path):
    calls = []
    get = _get({URL: b'{"a": 1}'}, calls)
    d = str(tmp_path)
    di.cached_get(d, "s.json", URL, 100, 3600, NOW, get, di._decode_json)
    parsed, _, how = di.cached_get(d, "s.json", URL, 100, 3600,
                                   NOW + datetime.timedelta(minutes=30), get,
                                   di._decode_json)
    assert (parsed, how, len(calls)) == ({"a": 1}, "cached", 1)


def test_an_expired_cache_fetches_again(tmp_path):
    calls = []
    get = _get({URL: b'{"a": 1}'}, calls)
    d = str(tmp_path)
    di.cached_get(d, "s.json", URL, 100, 3600, NOW, get, di._decode_json)
    di.cached_get(d, "s.json", URL, 100, 3600,
                  NOW + datetime.timedelta(hours=2), get, di._decode_json)
    assert len(calls) == 2


def test_a_body_is_parsed_before_it_replaces_the_cached_copy(tmp_path):
    d = str(tmp_path)
    di.cached_get(d, "s.json", URL, 100, 60, NOW, _get({URL: b'{"good": 1}'}),
                  di._decode_json)
    later = NOW + datetime.timedelta(days=2)
    parsed, _, how = di.cached_get(d, "s.json", URL, 100, 60, later,
                                   _get({URL: b"<html>blocked</html>"}),
                                   di._decode_json)
    assert parsed == {"good": 1} and how.startswith("previous good copy")
    assert open(os.path.join(d, "s.json"), "rb").read() == b'{"good": 1}'


def test_a_failed_get_falls_back_to_the_previous_good_copy(tmp_path):
    d = str(tmp_path)
    di.cached_get(d, "s.json", URL, 100, 60, NOW, _get({URL: b'{"good": 1}'}),
                  di._decode_json)
    parsed, _, how = di.cached_get(
        d, "s.json", URL, 100, 60, NOW + datetime.timedelta(days=2),
        _get({URL: di.FetchError("HTTP 503 from api.sleeper.app", status=503)}),
        di._decode_json)
    assert parsed == {"good": 1} and "HTTP 503" in how


def test_with_no_previous_copy_an_unreadable_body_raises(tmp_path):
    with pytest.raises(ValueError):
        di.cached_get(str(tmp_path), "s.json", URL, 100, 60, NOW,
                      _get({URL: b"<html>"}), di._decode_json)
    assert not os.path.exists(str(tmp_path / "s.json"))


# ------------------------------------------------------------- the run

def test_a_run_writes_a_file_the_alert_can_read(tmp_path):
    code, out = _run(tmp_path)
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
    assert injuries.source_notes(out) == ["Sleeper statuses as of 2026-10-23 16:45 (0 h old)"]


def test_a_second_scheduled_run_reports_what_changed_since_the_first(tmp_path):
    _run(tmp_path)
    changed = json.loads(json.dumps(SLEEPER))
    changed["7001"]["injury_status"] = "IR"
    _run(tmp_path, now=NOW + datetime.timedelta(days=2),
         **{di.SLEEPER_URL: json.dumps(changed).encode()})
    rows = json.load(open(str(tmp_path / "x.direct.json")))["intel"]
    pat = [r for r in rows if r["source"] == "sleeper" and r["player"] == "Pat Example"][0]
    assert (pat["status"], pat["previous_status"]) == ("IR", "Out")


def test_a_manual_run_neither_reads_nor_writes_the_change_state(tmp_path):
    _run(tmp_path)                                      # a scheduled baseline
    state_path = tmp_path / "cache" / di.STATE_FILE
    before = state_path.read_text()
    changed = json.loads(json.dumps(SLEEPER))
    changed["7001"]["injury_status"] = "IR"
    _run(tmp_path, kind="manual", now=NOW + datetime.timedelta(days=1),
         **{di.SLEEPER_URL: json.dumps(changed).encode()})
    assert state_path.read_text() == before
    rows = json.load(open(str(tmp_path / "x.direct.json")))["intel"]
    assert not any(r.get("previous_status") for r in rows)


def test_no_official_report_means_no_file_at_all(tmp_path):
    _run(tmp_path)                                      # an earlier output
    code, out = _run(tmp_path, now=NOW + datetime.timedelta(days=1),
                     **{di.NFLVERSE_STAMP_URL: di.FetchError("down")})
    assert code == 1 and not os.path.exists(out)


def test_a_garbled_nflverse_file_is_fatal_but_only_nflverse_is(tmp_path):
    code, out = _run(tmp_path, **{di.NFLVERSE_URL % 2026: b"\xff\xfe garbage"})
    assert code == 1 and not os.path.exists(out)


def test_a_shrunken_week_is_refused_as_truncated(tmp_path):
    _run(tmp_path)                                       # week 6: 3 rows
    one_row = NFLVERSE_HEADER + NFLVERSE.split("\n", 1)[1].split("\n")[1] + "\n"
    code, out = _run(tmp_path, now=NOW + datetime.timedelta(days=2),
                     **{di.NFLVERSE_URL % 2026: one_row.encode()})
    assert code == 1 and not os.path.exists(out)


def test_a_new_week_with_few_rows_is_not_a_shrink(tmp_path):
    _run(tmp_path)                                       # week 6: 3 rows
    week7 = NFLVERSE_HEADER + (
        "2026,REG,REG,SEA,7,00-0090001,WR,Pat Example,Pat,Example,Knee,NA,,"
        "Knee,NA,Limited Participation in Practice\n")
    code, out = _run(tmp_path, now=NOW + datetime.timedelta(days=5),
                     **{di.NFLVERSE_URL % 2026: (NFLVERSE + week7.split("\n", 1)[1]).encode()})
    assert code == 0 and json.load(open(out))["meta"]["week"] == 7


@pytest.mark.parametrize("bad", [
    {di.ESPN_URL: RuntimeError("an error no one expected")},
    {di.SLEEPER_URL: b"<html>not json</html>"},
    {di.CROSSWALK_URL: b"\xff\xfe"},
])
def test_one_bad_optional_source_never_aborts_the_feed(tmp_path, bad):
    code, out = _run(tmp_path, **bad)
    assert code == 0
    raw = json.load(open(out))
    assert len(raw["report"]) == 3
    failed = [n for n, i in raw["meta"]["sources"].items() if not i.get("ok")]
    assert len(failed) == 1
    assert raw["meta"]["sources"][failed[0]]["error_type"]


@pytest.mark.parametrize("response", [
    di.FetchError("HTTP 401 from site.api.espn.com", status=401, kind="http"),
    di.FetchError("HTTP 403 from site.api.espn.com", status=403, kind="http"),
    di.FetchError("HTTP 429 from site.api.espn.com", status=429, kind="http"),
    di.FetchError("HTTP 451 from site.api.espn.com", status=451, kind="http"),
    di.FetchError("redirect to elsewhere.example refused", kind="redirect"),
    b"<html>Access denied</html>",
])
def test_espn_saying_no_switches_it_off_until_someone_looks(tmp_path, response):
    code, out = _run(tmp_path, **{di.ESPN_URL: response})
    espn = json.load(open(out))["meta"]["sources"]["espn"]
    assert code == 0 and espn["off"] and not espn["ok"]
    assert os.path.exists(str(tmp_path / "cache" / di.ESPN_OFF_FILE))
    assert any(n.startswith("!! espn unavailable") for n in injuries.source_notes(out))

    calls = []
    _run(tmp_path, now=NOW + datetime.timedelta(days=2), calls=calls)
    assert di.ESPN_URL not in calls
    assert json.load(open(out))["meta"]["sources"]["espn"]["off"]


def test_an_ordinary_espn_failure_does_not_switch_it_off(tmp_path):
    code, out = _run(tmp_path, **{di.ESPN_URL: di.FetchError(
        "HTTP 503 from site.api.espn.com", status=503, kind="http")})
    assert not os.path.exists(str(tmp_path / "cache" / di.ESPN_OFF_FILE))
    assert not json.load(open(out))["meta"]["sources"]["espn"]["ok"]


def test_espn_is_called_at_most_once_per_twelve_hours_unless_forced(tmp_path):
    calls = []
    _run(tmp_path, calls=calls)
    _run(tmp_path, now=NOW + datetime.timedelta(hours=3), calls=calls)
    assert calls.count(di.ESPN_URL) == 1
    out = str(tmp_path / "x.direct.json")
    assert json.load(open(out))["meta"]["sources"]["espn"]["skipped"]
    di.fetch(out, str(tmp_path / "cache"), now=NOW + datetime.timedelta(hours=4),
             season=2026, kind="friday", get=_get(_responses(), calls),
             log=lambda *a: None, force_espn=True)
    assert calls.count(di.ESPN_URL) == 2


def test_the_espn_markers_can_live_in_a_shared_folder(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / di.ESPN_OFF_FILE).write_text('{"since": "t", "why": "HTTP 403"}')
    calls = []
    di.fetch(str(tmp_path / "x.direct.json"), str(tmp_path / "manual"), now=NOW,
             season=2026, kind="manual", get=_get(_responses(), calls),
             log=lambda *a: None, espn_dir=str(shared))
    assert di.ESPN_URL not in calls


def test_an_espn_active_row_is_kept_only_as_a_return(tmp_path):
    def espn_with(status):
        data = json.loads(json.dumps(ESPN))
        data["injuries"][0]["injuries"][0]["status"] = status
        return json.dumps(data).encode()

    _, out = _run(tmp_path, **{di.ESPN_URL: espn_with("Active")})
    assert not [r for r in json.load(open(out))["intel"] if r["source"] == "espn"]
    assert json.load(open(out))["meta"]["sources"]["espn"]["active_recaps_left_out"] == 1
    _run(tmp_path, now=NOW + datetime.timedelta(days=1),
         **{di.ESPN_URL: espn_with("Questionable")})
    _run(tmp_path, now=NOW + datetime.timedelta(days=2),
         **{di.ESPN_URL: espn_with("Active")})
    espn = [r for r in json.load(open(out))["intel"] if r["source"] == "espn"]
    assert [(r["status"], r["previous_status"]) for r in espn] == [
        ("Active", "Questionable")]


def test_the_output_must_be_json_and_only_an_earlier_output_is_replaced(tmp_path):
    code, _ = _run(tmp_path, out="x.direct.txt")
    assert code == 2
    other = tmp_path / "notes.json"
    other.write_text('{"someone": "else"}')
    code, _ = _run(tmp_path, out="notes.json")
    assert code == 2 and other.read_text() == '{"someone": "else"}'
    code, out = _run(tmp_path)                       # first output
    code, out = _run(tmp_path, now=NOW + datetime.timedelta(days=1))
    assert code == 0                                 # an earlier output is replaced


def test_the_season_turns_over_in_march():
    assert di.season_for(datetime.date(2027, 1, 10)) == 2026
    assert di.season_for(datetime.date(2027, 3, 1)) == 2027


# ------------------------------------------------------------- the command

from sffl import cli  # noqa: E402


@pytest.fixture
def fetch_calls(monkeypatch):
    """`direct_injuries.fetch` stubbed: the command's checks run, nothing is
    fetched or written."""
    calls = []

    def fake(out, cache_dir, **kwargs):
        calls.append(dict(kwargs, out=out, cache_dir=cache_dir))
        return 0

    monkeypatch.setattr(di, "fetch", fake)
    return calls


CAPTURES = os.path.join(cli._REPO_ROOT, "data", "captures")


def test_the_command_writes_only_inside_data_captures(fetch_calls, tmp_path, capsys):
    assert cli.main(["injuries-fetch", "--out", str(tmp_path / "x.direct.json")]) == 2
    assert "data/captures" in capsys.readouterr().err
    assert fetch_calls == []


def test_the_command_writes_only_json(fetch_calls, capsys):
    assert cli.main(["injuries-fetch", "--out", "data/captures/x.direct.txt"]) == 2
    assert fetch_calls == []


@pytest.mark.parametrize("name", ["injuries-friday.json", "Injuries-Friday.JSON",
                                  "INJURIES-SUNDAY.json"])
def test_the_command_refuses_the_live_file_in_any_case(fetch_calls, capsys, name):
    assert cli.main(["injuries-fetch", "--out", "data/captures/" + name]) == 2
    assert "live alert's injury file" in capsys.readouterr().err
    assert fetch_calls == []


def test_another_name_for_the_live_file_is_refused(tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    live = captures / "injuries-tuesday.json"
    live.write_text("{}")
    alias = captures / "other.json"
    os.link(str(live), str(alias))
    problem = cli._injuries_out_problem(str(alias), str(captures), False)
    assert problem and "same file as the live" in problem
    assert cli._injuries_out_problem(str(alias), str(captures), True) is None


def test_a_manual_run_caches_on_its_own_and_leaves_espn_out(fetch_calls):
    assert cli.main(["injuries-fetch", "--out", "data/captures/x.direct.json"]) == 0
    call = fetch_calls[-1]
    assert call["out"] == os.path.join(os.path.realpath(CAPTURES), "x.direct.json")
    assert call["cache_dir"] == os.path.join(cli._REPO_ROOT, "data", "cache", "manual")
    assert call["espn_dir"] == os.path.join(cli._REPO_ROOT, "data", "cache")
    assert call["use_espn"] is False and call["kind"] == "manual"
    cli.main(["injuries-fetch", "--out", "data/captures/x.direct.json", "--espn"])
    assert fetch_calls[-1]["use_espn"] is True


def test_a_scheduled_run_caches_in_data_cache_with_espn_on(fetch_calls):
    cli.main(["injuries-fetch", "--kind", "friday", "--out",
              "data/captures/injuries-friday.direct.json"])
    call = fetch_calls[-1]
    assert call["cache_dir"] == os.path.join(cli._REPO_ROOT, "data", "cache")
    assert call["use_espn"] is True and call["force_espn"] is False
