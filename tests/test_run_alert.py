"""ops/run_alert.sh run for real, in a scratch tree with every program stubbed.

The script `cd`s to its own repo root and runs `./.venv/bin/python` and
`ops/fetch_injuries.sh` from there, so a copy of it in a temporary tree whose
`.venv/bin/python` and `ops/fetch_injuries.sh` are stubs runs end to end with
no CBS, no network and no `claude`. Each stub appends its argv to a log; the
python stub answers the week computation, plays the injury fetch the way the
test asks (write a file, fail, or hang) and records whether the injury file
existed when the alert started.

These pin the StatsDeck switch (docs/plans/2026-10-20-replace-statsdeck.md,
step 5, and the injury-feed switch checklist): the direct feed by default,
the one-line rollback, a hard timeout that really kills the fetch, a dry run
that fetches as `--kind manual` without ESPN, and the old file removed first.
"""

import os
import shutil
import stat
import subprocess
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "ops", "run_alert.sh")

PY_STUB = r"""#!/bin/bash
# argv log: one line per call, words separated by a space.
echo "python $*" >> "$STUB_LOG"
if [ "$1" = "-c" ]; then echo 8; exit 0; fi
case "$3" in
  injuries-fetch)
    out=""
    prev=""
    for a in "$@"; do
      if [ "$prev" = "--out" ]; then out="$a"; fi
      prev="$a"
    done
    if [ -e "$out" ]; then echo "fetch saw an old file" >> "$STUB_LOG"; fi
    case "${FETCH_MODE:-ok}" in
      ok)   echo '{"report": [], "intel": [], "meta": {"generated_at": "x"}}' > "$out"; exit 0 ;;
      fail) exit 1 ;;
      hang) exec sleep 30 ;;
    esac ;;
  alert)
    for a in "$@"; do
      case "$a" in data/captures/injuries-*.json)
        if [ -e "$a" ]; then echo "alert saw injuries file" >> "$STUB_LOG";
        else echo "alert saw no injuries file" >> "$STUB_LOG"; fi ;;
      esac
    done
    exit 0 ;;
  collect) exit 0 ;;
esac
exit 0
"""

FETCH_SH_STUB = r"""#!/bin/bash
echo "fetch_injuries.sh $*" >> "$STUB_LOG"
echo '{"report": [], "intel": []}' > "$1"
"""


def _exe(path, text):
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "repo"
    (root / "ops").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(SCRIPT, str(root / "ops" / "run_alert.sh"))
    _exe(str(root / ".venv" / "bin" / "python"), PY_STUB)
    _exe(str(root / "ops" / "fetch_injuries.sh"), FETCH_SH_STUB)
    (root / "data" / "captures").mkdir(parents=True)
    # The last StatsDeck-shaped file, as the switch finds it.
    (root / "data" / "captures" / "injuries-friday.json").write_text(
        '{"report": [], "intel": []}')
    return root


def _run(tree, *args, **env):
    log = tree / "stub.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS",
              "SFFL_INJURY_FETCH_TIMEOUT_S", "DRY_RUN", "FETCH_MODE"):
        e.pop(k, None)
    e.update(STUB_LOG=str(log), CLAUDE_BIN="/nonexistent/claude-must-not-run")
    e.update(env)
    t0 = time.time()
    r = subprocess.run(["/bin/bash", str(tree / "ops" / "run_alert.sh")]
                       + list(args), env=e, capture_output=True, text=True,
                       timeout=60)
    lines = log.read_text().splitlines() if log.exists() else []
    return r, lines, time.time() - t0


def _call(lines, word):
    hits = [l for l in lines if l.startswith("python") and " %s " % word in
            l + " "]
    assert len(hits) == 1, (word, lines)
    return hits[0].split()


def test_scheduled_run_uses_the_direct_feed_and_cbs_designations(tree):
    r, lines, _ = _run(tree, "friday")
    assert r.returncode == 0, r.stderr
    fetch = _call(lines, "injuries-fetch")
    assert fetch[fetch.index("--kind") + 1] == "friday"
    assert fetch[fetch.index("--out") + 1] == "data/captures/injuries-friday.json"
    assert "--allow-live-path" in fetch
    assert not {"--espn", "--force-espn", "--no-espn"} & set(fetch)
    # The StatsDeck-shaped file was gone before the fetch ran.
    assert "fetch saw an old file" not in lines
    alert = _call(lines, "alert")
    assert "--cbs-designations" in alert and "--dry-run" not in alert
    assert "alert saw injuries file" in lines
    assert not any(l.startswith("fetch_injuries.sh") for l in lines)
    _call(lines, "collect")


def test_dry_run_fetches_as_manual_without_espn_and_skips_collect(tree):
    r, lines, _ = _run(tree, "sunday", "--dry-run")
    assert r.returncode == 0, r.stderr
    fetch = _call(lines, "injuries-fetch")
    assert fetch[fetch.index("--kind") + 1] == "manual"
    assert "--espn" not in fetch and "--force-espn" not in fetch
    assert "--dry-run" in _call(lines, "alert")
    assert not any(" collect " in l + " " for l in lines)


def test_hung_fetch_is_killed_and_the_alert_still_runs(tree):
    r, lines, took = _run(tree, "friday", FETCH_MODE="hang",
                          SFFL_INJURY_FETCH_TIMEOUT_S="2")
    assert took < 20
    assert "killed after 2s" in r.stderr
    assert "alert saw no injuries file" in lines
    assert not (tree / "data" / "captures" / "injuries-friday.json").exists()


def test_failed_fetch_leaves_no_file_and_the_alert_still_runs(tree):
    r, lines, _ = _run(tree, "tuesday", FETCH_MODE="fail")
    assert "injury fetch failed (exit 1)" in r.stderr
    assert "alert saw no injuries file" in lines
    _call(lines, "collect")


def test_rollback_line_runs_fetch_injuries_sh_and_never_the_direct_feed(tree):
    text = (tree / "ops" / "run_alert.sh").read_text()
    line = 'INJURY_FEED="${SFFL_INJURY_FEED:-direct}"'
    assert text.count(line) == 1
    (tree / "ops" / "run_alert.sh").write_text(
        text.replace(line, 'INJURY_FEED="${SFFL_INJURY_FEED:-statsdeck}"'))
    r, lines, _ = _run(tree, "friday")
    assert r.returncode == 0, r.stderr
    assert [l for l in lines if l.startswith("fetch_injuries.sh")] == [
        "fetch_injuries.sh data/captures/injuries-friday.json"]
    assert not any("injuries-fetch" in l for l in lines)
    assert "alert saw injuries file" in lines


def test_designations_have_their_own_off_switch(tree):
    r, lines, _ = _run(tree, "friday", SFFL_CBS_DESIGNATIONS="0")
    assert r.returncode == 0, r.stderr
    assert "--cbs-designations" not in _call(lines, "alert")


# ------------------------------------------- dated run lines (board c4dfbfe4)
#
# launchd appends every run to logs/alert-<kind>.log (stdout) and .err
# (stderr) with no date of its own, so on 10-30 an August block was read as
# that day's. Each run now opens and closes with a dated line in both files.

import re  # noqa: E402

STAMP = re.compile(r"^=== run_alert (\w+) \((live|dry run)\) (.+) "
                   r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \w+) ===$")


def _stamps(text):
    return [STAMP.match(l).groups() for l in text.splitlines()
            if STAMP.match(l)]


def test_every_run_is_dated_at_start_and_end_in_both_logs(tree):
    r, _lines, _ = _run(tree, "tuesday")
    assert r.returncode == 0, r.stderr
    for stream in (r.stdout, r.stderr):
        lines = [l for l in stream.splitlines() if l.strip()]
        assert STAMP.match(lines[0]) and STAMP.match(lines[-1]), stream
        (k1, m1, what1, _t1), (k2, m2, what2, _t2) = _stamps(stream)
        assert (k1, m1, what1) == ("tuesday", "live", "started")
        assert (k2, m2, what2) == ("tuesday", "live", "finished, exit 0")


def test_a_dry_run_and_a_failed_alert_say_so_in_their_lines(tree):
    r, _lines, _ = _run(tree, "friday", "--dry-run")
    assert [s[:3] for s in _stamps(r.stdout)] == [
        ("friday", "dry run", "started"), ("friday", "dry run", "finished, exit 0")]
    py = tree / ".venv" / "bin" / "python"
    py.write_text(PY_STUB.replace("    exit 0 ;;\n  collect)",
                                  "    exit 3 ;;\n  collect)"))
    r, _lines, _ = _run(tree, "sunday")
    assert r.returncode == 3
    assert _stamps(r.stderr)[-1][:3] == ("sunday", "live", "finished, exit 3")


def test_a_failed_collect_is_the_exit_code_when_the_alert_passed(tree):
    py = tree / ".venv" / "bin" / "python"
    py.write_text(PY_STUB.replace("  collect) exit 0 ;;", "  collect) exit 4 ;;"))
    r, _lines, _ = _run(tree, "tuesday")
    assert r.returncode == 4
    assert _stamps(r.stdout)[-1][:3] == ("tuesday", "live", "finished, exit 4")


# The "finished" line comes from an EXIT trap (Ultron, 11-12), so a run that
# dies early still closes its block: a `set -u` abort keeps its exit code, and
# a TERM still ends the script by that signal (launchd sees the same status).

def test_a_set_u_abort_still_logs_finished_with_its_exit_code(tree):
    script = tree / "ops" / "run_alert.sh"
    text = script.read_text()
    anchor = 'INJURY_FEED="${SFFL_INJURY_FEED:-direct}"\n'
    assert anchor in text
    script.write_text(text.replace(anchor, anchor + ': "$NOT_SET_FOR_TEST"\n'))
    r, lines, _ = _run(tree, "tuesday")
    assert r.returncode == 1
    assert "NOT_SET_FOR_TEST" in r.stderr
    assert not [l for l in lines if " alert " in l + " "]
    for stream in (r.stdout, r.stderr):
        assert [s[:3] for s in _stamps(stream)] == [
            ("tuesday", "live", "started"),
            ("tuesday", "live", "finished, exit 1")], stream


def test_a_killed_run_logs_finished_and_still_dies_by_the_signal(tree):
    import signal
    py = tree / ".venv" / "bin" / "python"
    py.write_text(PY_STUB.replace("  collect) exit 0 ;;",
                                  "  collect) sleep 2; exit 0 ;;"))
    log = tree / "stub.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS", "DRY_RUN"):
        e.pop(k, None)
    e.update(STUB_LOG=str(log), CLAUDE_BIN="/nonexistent/claude-must-not-run")
    p = subprocess.Popen(["/bin/bash", str(tree / "ops" / "run_alert.sh"),
                          "tuesday"], env=e, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        if log.exists() and " collect " in log.read_text():
            break
        time.sleep(0.05)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    assert p.returncode == -signal.SIGTERM
    for stream in (out, err):
        assert [s[:3] for s in _stamps(stream)] == [
            ("tuesday", "live", "started"),
            ("tuesday", "live", "finished, killed by SIGTERM")], stream
