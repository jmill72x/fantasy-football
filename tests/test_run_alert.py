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
