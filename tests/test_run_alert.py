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
# Every call is isolated (-I) and every sffl call goes through
# ops/run_module.py: nothing may import from the repo root (board 1d0ce259).
if [ "$1" != "-I" ]; then echo "python call without -I" >> "$STUB_LOG"; exit 99; fi
if [ "$2" = "-c" ]; then echo 8; exit 0; fi
if [ "$2" != "ops/run_module.py" ] || [ "$3" != "sffl.cli" ]; then
  echo "python call not through run_module" >> "$STUB_LOG"; exit 98
fi
case "$4" in
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


# launchd stops a job with SIGTERM and SIGKILLs it after ExitTimeOut (20 s by
# default). Bash runs a trap only when the FOREGROUND command returns, so a
# TERM during a long alert or collect used to wait for it and lose the race
# to the SIGKILL (Ultron 11-12, board 6ef63374). The long steps now run as a
# waited-on child: the trap runs at once, stops the child and logs.

@pytest.mark.parametrize("step", ["alert", "collect", "injuries-fetch"])
def test_a_term_during_a_long_step_stops_it_and_logs_at_once(tree, step):
    import signal
    py = tree / ".venv" / "bin" / "python"
    text = PY_STUB
    if step == "injuries-fetch":
        env_mode = {"FETCH_MODE": "hang"}
    else:
        env_mode = {}
        anchor = {"alert": "  alert)\n", "collect": "  collect) exit 0 ;;"}[step]
        repl = {"alert": "  alert)\n    exec sleep 60 ;;\n  alert-unused)\n",
                "collect": "  collect) exec sleep 60 ;;"}[step]
        assert anchor in text
        text = text.replace(anchor, repl)
    py.write_text(text)
    log = tree / "stub.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS",
              "SFFL_INJURY_FETCH_TIMEOUT_S", "DRY_RUN", "FETCH_MODE"):
        e.pop(k, None)
    e.update(STUB_LOG=str(log), CLAUDE_BIN="/nonexistent/claude-must-not-run")
    e.update(env_mode)
    p = subprocess.Popen(["/bin/bash", str(tree / "ops" / "run_alert.sh"),
                          "tuesday"], env=e, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        if log.exists() and " %s " % step in log.read_text():
            break
        time.sleep(0.05)
    time.sleep(0.3)                 # the stub has exec'd its sleep by now
    t0 = time.time()
    p.send_signal(signal.SIGTERM)
    # communicate() returns only once the sleep, which holds the pipes, is
    # gone: the child was stopped, not left behind.
    out, err = p.communicate(timeout=30)
    took = time.time() - t0
    assert took < 5, took           # well inside launchd's 20 s
    assert p.returncode == -signal.SIGTERM
    for stream in (out, err):
        assert [s[:3] for s in _stamps(stream)] == [
            ("tuesday", "live", "started"),
            ("tuesday", "live", "finished, killed by SIGTERM")], stream
    if step != "collect":           # nothing after the stopped step ran
        assert " collect " not in log.read_text()


# Ultron's review of john/lows-1121 (L2): after the TERM the script waits for
# the step (up to SFFL_STOP_WAIT_S, 10 s by default) so it can clean up - a
# git inside collect releasing its index.lock - and only then logs and dies.

def _start_and_stop(tree, collect_body, **env):
    import signal
    py = tree / ".venv" / "bin" / "python"
    py.write_text(PY_STUB.replace("  collect) exit 0 ;;",
                                  "  collect)\n%s ;;" % collect_body))
    log = tree / "stub.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS", "SFFL_STOP_WAIT_S",
              "SFFL_INJURY_FETCH_TIMEOUT_S", "DRY_RUN", "FETCH_MODE"):
        e.pop(k, None)
    e.update(STUB_LOG=str(log), CLAUDE_BIN="/nonexistent/claude-must-not-run")
    e.update(env)
    p = subprocess.Popen(["/bin/bash", str(tree / "ops" / "run_alert.sh"),
                          "tuesday"], env=e, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        if log.exists() and "collect ready" in log.read_text():
            break
        time.sleep(0.05)
    t0 = time.time()
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    return p, out, err, time.time() - t0, log.read_text()


def test_a_stop_waits_for_the_step_to_clean_up_before_logging(tree):
    import signal
    body = ("    trap 'sleep 1; echo \"collect cleaned up\"; "
            "echo \"collect cleaned up\" >> \"$STUB_LOG\"; exit 0' TERM\n"
            "    echo \"collect ready\" >> \"$STUB_LOG\"\n"
            "    while :; do sleep 0.1; done")
    p, out, err, took, log = _start_and_stop(tree, body)
    assert "collect cleaned up" in log      # the step finished its cleanup
    # ...before the script logged and died, not after it, orphaned.
    assert out.index("collect cleaned up") < out.index("killed by SIGTERM")
    assert 1 <= took < 5, took
    assert p.returncode == -signal.SIGTERM
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM"
    assert "did not exit" not in err


def test_a_step_that_ignores_the_stop_is_waited_for_only_so_long(tree):
    import signal
    # Its own output goes elsewhere, so the test's pipes close when the
    # script dies, not when the stuck step finally does.
    body = ("    exec >/dev/null 2>&1\n"
            "    trap '' TERM\n"
            "    echo \"collect ready\" >> \"$STUB_LOG\"\n"
            "    sleep 6")
    p, out, err, took, _log = _start_and_stop(tree, body, SFFL_STOP_WAIT_S="1")
    assert 1 <= took < 4, took
    assert p.returncode == -signal.SIGTERM
    assert "did not exit within 1s of SIGTERM" in err
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM"


def test_a_signal_during_the_fork_still_stops_the_child(tree):
    """L1 (Ultron, john/lows-1121): a TERM between `... &` and `CHILD=$!`
    used to find no child to stop, which then ran on, orphaned. Forced here
    by a copy of the script that signals itself in exactly that gap."""
    import signal
    script = tree / "ops" / "run_alert.sh"
    text = script.read_text()
    anchor = '    ( trap - TERM INT HUP; exec "$@" ) &\n'
    assert text.count(anchor) == 1
    script.write_text(text.replace(anchor, anchor + "    kill -s TERM $$\n"))
    log = tree / "stub.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS", "SFFL_STOP_WAIT_S",
              "SFFL_INJURY_FETCH_TIMEOUT_S", "DRY_RUN"):
        e.pop(k, None)
    e.update(STUB_LOG=str(log), CLAUDE_BIN="/nonexistent/claude-must-not-run",
             FETCH_MODE="hang")
    p = subprocess.Popen(["/bin/bash", str(script), "tuesday"], env=e,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    # The hung fetch holds the pipes for 30 s unless it was stopped.
    out, err = _communicate_or_fail(p, 15)
    assert p.returncode == -signal.SIGTERM, err
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM", err
    assert " alert " not in log.read_text() + " ", err


def _text(b):
    if b is None:
        return ""
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else b


def _communicate_or_fail(p, timeout):
    """communicate(), but a timeout fails the test with the stderr captured
    so far (Ultron 11-21: a flaky fork-test failure showed no stderr)."""
    try:
        return p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        partial = _text(exc.stderr)
        p.kill()
        try:
            _out, rest = p.communicate(timeout=5)
            partial += _text(rest)
        except subprocess.TimeoutExpired:
            pass                    # an orphaned step still holds the pipes
        pytest.fail("run_alert.sh still running after %ss; stderr so far:\n%s"
                    % (timeout, partial))


# Ultron's lows on run_alert.sh (11-21, board 9aad4392).

CLEANUP_BODY = ("    trap 'sleep 1; echo \"collect cleaned up\"; "
                "echo \"collect cleaned up\" >> \"$STUB_LOG\"; exit 0' TERM\n"
                "    echo \"collect ready\" >> \"$STUB_LOG\"\n"
                "    while :; do sleep 0.1; done")


@pytest.mark.parametrize("value", ["abc", "5s", "1.5", "-1", "16", "08", " 3"])
def test_a_bad_stop_wait_falls_back_to_10_and_the_stop_still_works(tree, value):
    """L-a: a non-integer SFFL_STOP_WAIT_S made the trap's arithmetic fail,
    so the stop died with exit 127 and logged no "finished" line."""
    import signal
    p, out, err, took, log = _start_and_stop(tree, CLEANUP_BODY,
                                             SFFL_STOP_WAIT_S=value)
    assert "SFFL_STOP_WAIT_S is not a whole number of seconds from 0 to 15; "\
           "using 10" in err
    assert "collect cleaned up" in log      # waited (10 s), not cut short
    assert p.returncode == -signal.SIGTERM, (p.returncode, err)
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM"
    assert "did not exit" not in err
    assert took < 5, took


@pytest.mark.parametrize("value", ["0", "15"])
def test_the_stop_wait_accepts_0_to_15(tree, value):
    import signal
    body = ("    exec >/dev/null 2>&1\n"
            "    trap '' TERM\n"
            "    echo \"collect ready\" >> \"$STUB_LOG\"\n"
            "    sleep 3")
    if value == "15":
        body = CLEANUP_BODY
    p, out, err, took, log = _start_and_stop(tree, body,
                                             SFFL_STOP_WAIT_S=value)
    assert "SFFL_STOP_WAIT_S" not in err
    assert p.returncode == -signal.SIGTERM
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM"
    if value == "0":                # no wait at all for a stuck step
        assert took < 1, took
        assert "did not exit within 0s of SIGTERM" in err
    else:
        assert "collect cleaned up" in log and took < 5, took


def test_the_first_held_signal_is_the_one_acted_on(tree):
    """L-c: two signals in the fork gap, TERM then HUP, each its own kill
    builtin, so bash handles TERM first (a command boundary runs pending
    traps). The script dies by TERM, not the later HUP. Sent the other way
    round this would not test "first wins": HUP is lower-numbered, and bash
    3.2 runs traps that are pending together in signal-number order."""
    import signal
    script = tree / "ops" / "run_alert.sh"
    text = script.read_text()
    anchor = '    ( trap - TERM INT HUP; exec "$@" ) &\n'
    assert text.count(anchor) == 1
    script.write_text(text.replace(
        anchor, anchor + "    kill -s TERM $$\n    kill -s HUP $$\n"))
    log = tree / "stub.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS", "SFFL_STOP_WAIT_S",
              "SFFL_INJURY_FETCH_TIMEOUT_S", "DRY_RUN"):
        e.pop(k, None)
    e.update(STUB_LOG=str(log), CLAUDE_BIN="/nonexistent/claude-must-not-run",
             FETCH_MODE="hang")
    p = subprocess.Popen(["/bin/bash", str(script), "tuesday"], env=e,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    out, err = _communicate_or_fail(p, 15)
    assert p.returncode == -signal.SIGTERM, err
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM", err
    assert " alert " not in log.read_text() + " ", err


def test_a_lost_first_term_is_sent_again_about_1s_in(tree):
    """Ultron 11-21: a TERM that reaches the child inside bash's fork path,
    before its `trap -`, can be swallowed. That window is microseconds wide
    and can't be hit on purpose, so this step loses its FIRST TERM by design
    (its trap swallows it once, then restores the default) and the second
    TERM, about 1 s in, must stop it well before the 10 s wait runs out."""
    import signal
    body = ("    exec >/dev/null 2>&1\n"
            "    trap 'trap - TERM' TERM\n"
            "    echo \"collect ready\" >> \"$STUB_LOG\"\n"
            "    while :; do sleep 0.1; done")
    p, out, err, took, _log = _start_and_stop(tree, body)
    assert 0.9 <= took < 4, (took, err)
    assert p.returncode == -signal.SIGTERM, err
    assert "did not exit" not in err
    assert _stamps(out)[-1][2] == "finished, killed by SIGTERM"


# ------------------------------- nothing imported from the repo root (1d0ce259)
#
# `python -m` and `python -c` put the current directory first on sys.path, and
# the job runs from the repo root, so a stray json.py there would have been
# imported (Ultron 11-11). Python 3.9 has no -P, so every call runs with -I
# and sffl starts through ops/run_module.py. These run the REAL venv python
# (this test's own interpreter) on a scratch tree whose repo root and ops/
# are full of planted modules, each of which writes to a log if it is ever
# imported. src/ must hold only sffl (run_module.py refuses otherwise) and
# goes after the stdlib, before site-packages (Ultron's review, 11-21).

import sys  # noqa: E402

RUN_MODULE = os.path.join(HERE, "..", "ops", "run_module.py")
PLANTED = ("json", "datetime", "runpy", "argparse", "re", "sffl")
PLANTED_IN = ("", "ops")      # the repo root, and run_module.py's own folder

PLANT = """import os
with open(os.environ["PLANT_LOG"], "a") as fh:
    fh.write("planted %s imported\\n")
"""

# A stand-in sffl.cli in the scratch tree's src/: it imports what the real
# one would, records where they came from, and answers each subcommand.
FAKE_CLI = r"""import argparse, json, datetime, os, re, sys
src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
stdlib = os.path.dirname(os.__file__)
site = [i for i, p in enumerate(sys.path) if p.endswith("site-packages")]
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write("cli %s json=%s datetime=%s argparse=%s src_at=%d stdlib_at=%d "
             "site_at=%d\n" % (
        sys.argv[1], json.__file__, datetime.__file__, argparse.__file__,
        sys.path.index(src), sys.path.index(stdlib), site[0]))
if sys.argv[1] == "injuries-fetch":
    out = sys.argv[sys.argv.index("--out") + 1]
    with open(out, "w") as fh:
        json.dump({"report": [], "intel": [], "meta": {}}, fh)
sys.exit(0)
"""


def _plant(root):
    for where in PLANTED_IN:
        for name in PLANTED:
            (root / where / ("%s.py" % name)).write_text(PLANT % name)


@pytest.fixture
def real_tree(tmp_path):
    root = tmp_path / "repo"
    (root / "ops").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "src" / "sffl").mkdir(parents=True)
    (root / "data" / "captures").mkdir(parents=True)
    shutil.copy(SCRIPT, str(root / "ops" / "run_alert.sh"))
    shutil.copy(RUN_MODULE, str(root / "ops" / "run_module.py"))
    # The real interpreter, by its venv path (pyvenv.cfg is found from it).
    _exe(str(root / ".venv" / "bin" / "python"),
         '#!/bin/bash\nexec "%s" "$@"\n' % sys.executable)
    (root / "src" / "sffl" / "__init__.py").write_text("")
    (root / "src" / "sffl" / "cli.py").write_text(FAKE_CLI)
    _plant(root)
    return root


def test_a_real_run_imports_nothing_from_the_repo_root(real_tree):
    log = real_tree / "stub.log"
    plant_log = real_tree / "plant.log"
    e = dict(os.environ)
    for k in ("SFFL_INJURY_FEED", "SFFL_CBS_DESIGNATIONS", "DRY_RUN",
              "PYTHONPATH"):
        e.pop(k, None)
    # A PYTHONPATH pointing at the planted root is ignored too (-I implies -E).
    e.update(STUB_LOG=str(log), PLANT_LOG=str(plant_log),
             PYTHONPATH=str(real_tree),
             CLAUDE_BIN="/nonexistent/claude-must-not-run")
    r = subprocess.run(["/bin/bash", str(real_tree / "ops" / "run_alert.sh"),
                        "friday"], env=e, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert not plant_log.exists(), (plant_log.read_text(), r.stderr)
    lines = log.read_text().splitlines()
    assert [l.split()[1] for l in lines] == [
        "injuries-fetch", "alert", "collect"], (lines, r.stderr)
    for l in lines:
        fields = dict(f.split("=", 1) for f in l.split()[2:])
        # src after the stdlib, before the venv's site-packages.
        assert (int(fields["stdlib_at"]) < int(fields["src_at"])
                < int(fields["site_at"])), l
        for mod in ("json", "datetime", "argparse"):
            assert not fields[mod].startswith(str(real_tree) + os.sep), l


def test_the_old_command_did_import_the_planted_module(real_tree):
    """The control: the pre-fix call really is fooled by this tree."""
    plant_log = real_tree / "plant.log"
    e = dict(os.environ, PLANT_LOG=str(plant_log), STUB_LOG=os.devnull,
             PYTHONPATH="src")
    subprocess.run([sys.executable, "-m", "sffl.cli", "alert"],
                   cwd=str(real_tree), env=e, capture_output=True, timeout=60)
    assert "planted" in plant_log.read_text()


def test_run_module_refuses_to_run_without_dash_i(real_tree):
    plant_log = real_tree / "plant.log"
    e = dict(os.environ, PLANT_LOG=str(plant_log), STUB_LOG=os.devnull)
    e.pop("PYTHONPATH", None)
    r = subprocess.run([sys.executable, "ops/run_module.py", "sffl.cli",
                        "alert"], cwd=str(real_tree), env=e,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "python -I" in r.stderr, r.stderr
    r = subprocess.run([sys.executable, "-I", "ops/run_module.py", "json"],
                       cwd=str(real_tree), env=e, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 2 and "usage" in r.stderr, r.stderr
    assert not plant_log.exists()


@pytest.mark.parametrize("stray", ["json.py", "yaml.py", "yaml", "sffl.py"])
def test_run_module_refuses_a_stray_module_in_src(real_tree, stray):
    """A stray src/json.py could not shadow the stdlib (src goes after it),
    but a src/yaml.py would shadow the installed yaml: anything at src/'s top
    level but the sffl package stops the run before any import."""
    plant_log = real_tree / "plant.log"
    log = real_tree / "stub.log"
    target = real_tree / "src" / stray
    if stray.endswith(".py"):
        target.write_text(PLANT % stray)
    else:
        target.mkdir()
        (target / "__init__.py").write_text(PLANT % stray)
    e = dict(os.environ, PLANT_LOG=str(plant_log), STUB_LOG=str(log))
    r = subprocess.run([sys.executable, "-I", "ops/run_module.py", "sffl.cli",
                        "alert"], cwd=str(real_tree), env=e,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stderr
    assert "refusing to run" in r.stderr and stray in r.stderr, r.stderr
    assert not plant_log.exists() and not log.exists(), r.stderr


def test_run_module_ignores_dotfiles_and_pycache_in_src(real_tree):
    (real_tree / "src" / ".DS_Store").write_text("")
    (real_tree / "src" / "__pycache__").mkdir()
    log = real_tree / "stub.log"
    e = dict(os.environ, PLANT_LOG=str(real_tree / "plant.log"),
             STUB_LOG=str(log))
    r = subprocess.run([sys.executable, "-I", "ops/run_module.py", "sffl.cli",
                        "alert"], cwd=str(real_tree), env=e,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert log.read_text().startswith("cli alert ")


def test_run_module_keeps_the_exit_code_and_argv_of_dash_m(real_tree):
    cli = real_tree / "src" / "sffl" / "cli.py"
    cli.write_text("import sys\nprint(repr(sys.argv))\nsys.exit(7)\n")
    r = subprocess.run([sys.executable, "-I", "ops/run_module.py", "sffl.cli",
                        "alert", "--kind", "friday"], cwd=str(real_tree),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 7, r.stderr
    assert r.stdout.strip() == repr([str(cli), "alert", "--kind", "friday"])


# The only python calls the job's scripts may make: the venv's python with
# -I, either running a -c snippet or starting an sffl module through
# ops/run_module.py. Anything else that names python fails.
APPROVED_PY = [
    re.compile(r'^PY=\./\.venv/bin/python$'),
    re.compile(r'"\$PY" -I -c "'),
    re.compile(r'"\$PY" -I ops/run_module\.py sffl\.[a-z_.]+( |$)'),
    re.compile(r'"\$REPO/\.venv/bin/python" -I "\$REPO/ops/run_module\.py" '
               r'sffl\.[a-z_.]+( |$)'),
]
PY_MENTION = re.compile(r'python|\$\{?PY\b', re.I)


def _unapproved_python(code):
    """What is left of a line once its one approved python call is cut out,
    if any python is left there."""
    code = code.strip()
    for pat in APPROVED_PY:
        code = pat.sub(" ", code, count=1)
    return code if PY_MENTION.search(code) else None


def test_the_live_scripts_make_only_approved_python_calls():
    """Every python call in the job's two scripts is one of the approved
    forms (Ultron's review, 11-21: not only bin/python and "$PY")."""
    seen = 0
    for name in ("run_alert.sh", "fetch_injuries.sh"):
        path = os.path.join(HERE, "..", "ops", name)
        for n, line in enumerate(open(path), 1):
            code = line.split("#", 1)[0]
            if PY_MENTION.search(code):
                seen += 1
                assert _unapproved_python(code) is None, (name, n, line)
    assert seen == 6      # PY=, the week, fetch, alert, collect, the stream


@pytest.mark.parametrize("line", [
    './.venv/bin/python -m sffl.cli alert',
    '"$PY" -c "print(1)"',
    '"$PY" -m sffl.cli alert',
    'env PYTHONPATH=src "$PY" -I ops/run_module.py sffl.cli alert',
    'python3 -I ops/run_module.py sffl.cli alert',
    '/usr/bin/env python -c 1',
    '"$PY" -I ops/other.py',
    '"$PY" -I ops/run_module.py sffl.cli alert; python x.py',
    'PY=python3',
])
def test_the_static_check_catches_other_python_calls(line):
    assert _unapproved_python(line) is not None
