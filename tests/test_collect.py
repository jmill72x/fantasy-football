"""sffl collect: the weekly copy of CBS pages to the archive, Pi and data repo.

Everything runs against temp folders and a temp bare repo standing in for
jmill72x/fantasy-football-data. The Pi is a fake `runner` that records the
ssh/scp commands and answers like the Pi would; nothing here reaches the
network, CBS or the real data repo.
"""

import datetime
import os
import subprocess
import time

import pytest

from sffl import collect as col
from sffl.cli import _capture_keys, _parse_weeks, _stats_url, main

DAY = datetime.date(2026, 10, 20)


def _git(*args, cwd=None):
    return subprocess.run(["git"] + list(args), cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def data_repo(tmp_path):
    """A clone of a temp bare repo, on main, with a top-level manifest."""
    bare = tmp_path / "remote.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    repo = tmp_path / "data"
    _git("clone", "-q", str(bare), str(repo))
    _git("checkout", "-q", "-b", "main", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    _git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "README.md").write_text("data\n")
    (repo / "MANIFEST.sha256").write_text(
        "%s  ./README.md\n" % col.sha256_file(str(repo / "README.md")))
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    _git("push", "-q", "-u", "origin", "main", cwd=repo)
    return repo, bare


@pytest.fixture
def captures(tmp_path):
    """data/captures as a Tuesday run leaves it: fresh pages plus one stale."""
    d = tmp_path / "captures"
    d.mkdir()
    since = time.time() - 60
    for name in ["roster.txt", "RB-WR-TE.txt", "tqb.txt", "K.txt",
                 "RB-WR-TE-ROS.txt", "TQB-ROS.txt", "K-ROS.txt",
                 "DST-ROS.txt", "injuries-tuesday.json"]:
        (d / name).write_text("page %s\n" % name * 50)
    stale = d / "DST.txt"
    stale.write_text("last week's DST page\n")
    old = since - 3600
    os.utime(str(stale), (old, old))
    (d / "probe.txt").write_text("not a capture key\n")
    return d, since


def _ok_runner(log):
    """A fake subprocess.run: real git, a Pi that accepts everything."""
    def run(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        log.append(argv)
        out = ""
        if argv[0] == "ssh" and "ls -d /srv" in argv[-1]:
            out = "/srv/dev-disk-by-uuid-x/Documents\n"
        elif argv[0] == "ssh" and "test -e" in argv[-1]:
            out = "NEW\n"
        return subprocess.CompletedProcess(argv, 0, out, "")
    return run


def test_fresh_files_keeps_only_this_runs_known_captures(captures):
    d, since = captures
    fresh, missing = col.fresh_files(str(d), _capture_keys("tuesday"), since)
    assert "DST.txt" in missing            # stale: written before the run
    assert "probe.txt" not in fresh        # not something the alert writes
    # Filed under the canonical name even though the disk says tqb.txt.
    assert "TQB.txt" in fresh and "roster.txt" in fresh
    assert "injuries-tuesday.json" in fresh
    assert len(fresh) == 9


def test_archive_unit_is_private_verified_and_never_overwritten(tmp_path,
                                                                 captures):
    d, since = captures
    fresh, _ = col.fresh_files(str(d), _capture_keys("tuesday"), since)
    arch = tmp_path / "archive"
    step, path = col.to_archive(fresh, "note\n", str(arch), 2026, 6,
                                "2026-10-20-tuesday")
    assert step.status == col.OK
    assert path == str(arch / "2026" / "cbs-weekly" / "wk06"
                       / "2026-10-20-tuesday")
    assert col.verify_manifest(path) is None
    assert oct(os.stat(path).st_mode & 0o777) == "0o700"
    assert oct(os.stat(os.path.join(path, "TQB.txt")).st_mode & 0o777) \
        == "0o600"
    assert sorted(os.listdir(path)) == sorted(
        list(fresh) + [col.NOTE, col.MANIFEST])

    # Same unit again, with different source bytes: left alone.
    (d / "roster.txt").write_text("CHANGED\n")
    step2, path2 = col.to_archive(fresh, "note\n", str(arch), 2026, 6,
                                  "2026-10-20-tuesday")
    assert step2.status == col.EXISTS and path2 == path
    assert "CHANGED" not in open(os.path.join(path, "roster.txt")).read()

    # A damaged existing unit is reported, not trusted or repaired.
    with open(os.path.join(path, "K.txt"), "a") as fh:
        fh.write("x")
    step3, path3 = col.to_archive(fresh, "note\n", str(arch), 2026, 6,
                                  "2026-10-20-tuesday")
    assert step3.status == col.FAILED and path3 is None
    assert "K.txt" in step3.detail


def test_end_to_end_cli_into_scratch_archive_and_bare_repo(
        tmp_path, captures, data_repo, monkeypatch, capsys):
    """The whole collect step, as run_alert.sh calls it, minus CBS and the Pi."""
    d, since = captures
    repo, bare = data_repo
    arch = tmp_path / "archive"

    def fake_capture(urls, out_dir, profile_dir):
        os.makedirs(out_dir, exist_ok=True)
        (name, url), = urls.items()
        p = os.path.join(out_dir, name + ".txt")
        with open(p, "w") as fh:
            fh.write("stats page for %s\n" % url * 40)
        return {url: p}

    import sffl.capture
    monkeypatch.setattr(sffl.capture, "capture", fake_capture)
    argv = ["collect", "--kind", "tuesday", "--week", "6",
            "--since", str(since), "--results-week", "6",
            "--date", "2026-10-20", "--captures", str(d),
            "--archive", str(arch), "--data-repo", str(repo), "--no-pi"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "COLLECT FAILED" not in out
    assert "COLLECT OK push" in out

    wk = repo / "2026" / "cbs" / "weekly" / "wk06"
    assert sorted(os.listdir(str(wk))) == ["2026-10-20-results",
                                           "2026-10-20-tuesday"]
    res = sorted(os.listdir(str(wk / "2026-10-20-results")))
    assert res == sorted(["results-RB-WR-TE.txt", "results-TQB.txt",
                          "results-K.txt", "results-DST.txt",
                          col.NOTE, col.MANIFEST])
    note = (wk / "2026-10-20-tuesday" / col.NOTE).read_text()
    assert "not_refreshed_this_run: DST.txt" in note

    # Pushed: the bare remote's main is the local main, one new commit, and
    # the commit touches only the two units and the manifest.
    assert _git("rev-parse", "main", cwd=bare) == _git("rev-parse", "HEAD",
                                                        cwd=repo)
    msg = _git("log", "-1", "--format=%s", cwd=repo)
    assert msg.startswith("chore: automated: 2026 CBS pages")
    files = _git("show", "--name-only", "--format=", "HEAD", cwd=repo)
    assert all(f == "MANIFEST.sha256" or f.startswith("2026/cbs/weekly/wk06/")
               for f in files.splitlines())

    # The repo manifest covers the new files, stays sorted, and checks out.
    man = (repo / "MANIFEST.sha256").read_text().splitlines()
    paths = [l.split("  ", 1)[1] for l in man]
    assert paths == sorted(paths)
    assert "./2026/cbs/weekly/wk06/2026-10-20-tuesday/roster.txt" in paths
    r = subprocess.run(["shasum", "-a", "256", "-c", "MANIFEST.sha256"],
                       cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    # Running it again is a no-op that changes nothing and fails nothing.
    head = _git("rev-parse", "HEAD", cwd=repo)
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "COLLECT EXISTS archive" in out and "COLLECT EXISTS repo" in out
    assert _git("rev-parse", "HEAD", cwd=repo) == head


def test_no_fresh_capture_collects_nothing_and_is_not_a_failure(
        tmp_path, captures, data_repo, capsys):
    d, _ = captures
    repo, _bare = data_repo
    head = _git("rev-parse", "HEAD", cwd=repo)
    rc = main(["collect", "--kind", "sunday", "--week", "7",
               "--since", str(time.time() + 3600), "--captures", str(d),
               "--archive", str(tmp_path / "a"), "--data-repo", str(repo),
               "--no-pi"])
    assert rc == 0
    assert "COLLECT SKIPPED capture" in capsys.readouterr().out
    assert not (tmp_path / "a").exists()
    assert _git("rev-parse", "HEAD", cwd=repo) == head


def test_pi_copy_commands_and_never_overwrite(tmp_path, captures):
    d, since = captures
    fresh, _ = col.fresh_files(str(d), _capture_keys("tuesday"), since)
    _, path = col.to_archive(fresh, "n\n", str(tmp_path / "a"), 2026, 6,
                             "2026-10-20-tuesday")
    log = []
    root = col.pi_root("jeff@pinas", _ok_runner(log))
    assert root == "/srv/dev-disk-by-uuid-x/Documents/fantasy-football-data"
    step = col.to_pi(path, "jeff@pinas", root, 2026, 6, "2026-10-20-tuesday",
                     _ok_runner(log))
    assert step.status == col.OK
    scp = [a for a in log if a[0] == "scp"]
    assert len(scp) == 1
    assert scp[0][-1] == ("jeff@pinas:" + root + "/2026/cbs-weekly/wk06/")
    assert "BatchMode=yes" in scp[0]
    assert "sha256sum -c" in log[-1][-1]

    # Already on the Pi: no scp, just the check.
    def exists_runner(argv, **kw):
        log.append(argv)
        out = "EXISTS\n" if "test -e" in argv[-1] else ""
        return subprocess.CompletedProcess(argv, 0, out, "")
    n = len([a for a in log if a[0] == "scp"])
    step = col.to_pi(path, "jeff@pinas", root, 2026, 6, "2026-10-20-tuesday",
                     exists_runner)
    assert step.status == col.EXISTS
    assert len([a for a in log if a[0] == "scp"]) == n


def test_pi_down_still_archives_and_commits(tmp_path, captures, data_repo):
    d, since = captures
    repo, bare = data_repo
    fresh, _ = col.fresh_files(str(d), _capture_keys("tuesday"), since)

    def pi_down(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        return subprocess.CompletedProcess(argv, 255, "",
                                           "ssh: connect: timed out")
    steps = col.collect_units(
        [(6, "2026-10-20-tuesday", fresh, "n\n")], str(tmp_path / "a"), 2026,
        repo=str(repo), pi_host="jeff@pinas", runner=pi_down)
    by = dict((s.where, s.status) for s in steps)
    assert by == {"archive": col.OK, "pi": col.FAILED, "repo": col.OK,
                  "commit": col.OK, "push": col.OK}
    assert "timed out" in col.failed(steps)[0].detail


def test_failed_push_is_reported_and_goes_out_with_the_next_run(
        tmp_path, captures, data_repo):
    d, since = captures
    repo, bare = data_repo
    fresh, _ = col.fresh_files(str(d), _capture_keys("tuesday"), since)
    good = _git("remote", "get-url", "origin", cwd=repo)
    _git("remote", "set-url", "origin", str(tmp_path / "nowhere.git"),
         cwd=repo)
    steps = col.collect_units(
        [(6, "2026-10-20-tuesday", fresh, "n\n")], str(tmp_path / "a"), 2026,
        repo=str(repo))
    assert [s.where for s in col.failed(steps)] == ["push"]
    local = _git("rev-parse", "HEAD", cwd=repo)

    _git("remote", "set-url", "origin", good, cwd=repo)
    steps = col.commit_and_push(str(repo), [], "unused")
    assert [(s.where, s.status) for s in steps] == [("push", col.OK)]
    assert _git("rev-parse", "main", cwd=bare) == local


def test_repo_off_main_is_refused_and_others_staged_work_stays_out(
        tmp_path, captures, data_repo):
    d, since = captures
    repo, _ = data_repo
    fresh, _ = col.fresh_files(str(d), _capture_keys("tuesday"), since)
    # Someone's own staged edit must not ride along in the job's commit.
    (repo / "README.md").write_text("edited by hand\n")
    _git("add", "README.md", cwd=repo)
    steps = col.collect_units(
        [(6, "2026-10-20-tuesday", fresh, "n\n")], str(tmp_path / "a"), 2026,
        repo=str(repo), push=False)
    assert not col.failed(steps)
    committed = _git("show", "--name-only", "--format=", "HEAD", cwd=repo)
    assert "README.md" not in committed.splitlines()
    assert "M  README.md" in subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True,
        text=True).stdout

    _git("checkout", "-q", "-b", "side", cwd=repo)
    steps = col.collect_units(
        [(7, "2026-10-23-friday", fresh, "n\n")], str(tmp_path / "a"), 2026,
        repo=str(repo), push=False)
    assert [s.where for s in col.failed(steps)] == ["repo"]
    assert not (repo / "2026" / "cbs" / "weekly" / "wk07").exists()


def test_failure_notifies_once_per_channel_and_exits_1(
        tmp_path, captures, monkeypatch, capsys):
    d, since = captures
    sent = []
    import sffl.notify
    monkeypatch.setattr(sffl.notify, "topic_from_keychain", lambda: "t")
    monkeypatch.setattr(sffl.notify, "send",
                        lambda topic, title, body, **kw: sent.append(
                            ("ntfy", title, body)))
    monkeypatch.setattr(sffl.notify, "send_discord",
                        lambda title, body, **kw: sent.append(
                            ("discord", title, body)))
    # An archive path that can't be created: a file sits where a folder goes.
    blocker = tmp_path / "archive"
    blocker.write_text("not a folder")
    rc = main(["collect", "--kind", "tuesday", "--week", "6",
               "--since", str(since), "--captures", str(d),
               "--archive", str(blocker), "--no-repo", "--no-pi",
               "--notify"])
    assert rc == 1
    assert "COLLECT FAILED archive" in capsys.readouterr().out
    assert [s[0] for s in sent] == ["ntfy", "discord"]
    assert "digest went out" in sent[0][2]


def test_parse_weeks_and_stats_url():
    assert _parse_weeks("1-5") == [1, 2, 3, 4, 5]
    assert _parse_weeks("1,3") == [1, 3]
    assert _parse_weeks("") == []
    with pytest.raises(ValueError):
        _parse_weeks("0-2")
    url = _stats_url("RB-WR-TE", 6)
    assert "/all:RB:WR:TE/6:p/standard/stats?print_rows=9999" in url


def test_run_alert_collects_after_the_alert_and_never_on_a_dry_run():
    """Static check of ops/run_alert.sh: there is no seam to run it for real
    (see ops/lint_run_alert.sh's header for why)."""
    here = os.path.dirname(os.path.abspath(__file__))
    text = open(os.path.join(here, "..", "ops", "run_alert.sh")).read()
    alert = text.index("-m sffl.cli alert")
    coll = text.index("-m sffl.cli collect")
    assert alert < coll                                  # after the digest
    assert text.index("RUN_START=$(date +%s)") < text.index(
        "ops/fetch_injuries.sh \"$INJ\"")                # before any capture
    guard = text.rindex('if [ -z "$DRY_RUN_FLAG" ]', 0, coll)
    assert text.index("ALERT_RC=$?") < guard             # alert rc kept
    assert text.rstrip().endswith('exit "$COLLECT_RC"')
