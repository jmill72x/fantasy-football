"""Weekly collection of the CBS pages into the three private copies.

WHY THIS EXISTS. `data/captures/` is overwritten by every alert run, dry runs
included, and CBS drops a season's per-week data when it rolls the site over.
Next season's model work compares projections with what actually happened, so
each week's pages are copied, after the alert has run, into:

  1. the local archive  `<archive>/<season>/cbs-weekly/wkNN/<unit>/`
  2. the Pi             `<Documents>/fantasy-football-data/<season>/cbs-weekly/wkNN/<unit>/`
  3. the private repo   `<data repo>/<season>/cbs/weekly/wkNN/<unit>/`, committed
     and pushed (Jeff's standing OK of 2026-10-19 covers only that repo and only
     these commits - see NEXT.md).

A UNIT is one dated folder: `<YYYY-MM-DD>-<kind>` (the run's own captures),
`<YYYY-MM-DD>-results` (CBS's actual stats for a week) or
`<YYYY-MM-DD>-backfill`. Each holds its files, a COLLECTED.txt saying what it
is, and a MANIFEST.sha256 in `shasum -a 256` format.

NEVER OVERWRITE. A unit that already exists at a destination is verified
against its manifest and left alone, so re-running the collection for the same
day is a safe retry: whichever copies are missing get made, the others are
checked.

NEVER BREAK THE ALERT. `ops/run_alert.sh` runs this AFTER `sffl alert` has
sent the digest, skips it on dry runs, and folds its failure into the job's
exit status. Every step here reports a status instead of raising, so one
failed copy (the Pi is down, the push is rejected) never stops the others.

No CBS writes, ever: the only CBS traffic is `sffl.capture.capture`, which
reads pages.
"""

import datetime
import hashlib
import os
import shlex
import shutil
import subprocess

MANIFEST = "MANIFEST.sha256"
NOTE = "COLLECTED.txt"

# Bounded so a hung ssh or push can't hold the launchd job open for long.
_SSH_TIMEOUT_S = 120
_PUSH_TIMEOUT_S = 180
_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]

OK = "ok"
EXISTS = "exists"      # already there and verified: not an error
SKIPPED = "skipped"    # nothing to do (no fresh capture, step turned off)
FAILED = "failed"


class Step(object):
    """One destination's outcome for one unit (or the repo's commit/push)."""

    def __init__(self, where, unit, status, detail=""):
        self.where = where
        self.unit = unit
        self.status = status
        self.detail = detail

    def line(self):
        return "COLLECT %s %s %s%s" % (
            self.status.upper(), self.where, self.unit,
            (": " + self.detail) if self.detail else "")

    def __repr__(self):
        return "Step(%r, %r, %r)" % (self.where, self.unit, self.status)


def week_dir(week):
    return "wk%02d" % int(week)


def unit_name(day, label):
    """`2026-10-20-tuesday`, `2026-10-20-results`. Dated, so never reused."""
    return "%s-%s" % (day.isoformat(), label)


def fresh_files(captures_dir, names, since_epoch):
    """Split the expected capture files into (fresh, not_fresh).

    `names` are capture keys as `sffl alert` writes them (`<key>.txt`, or a
    full file name ending in `.json`). A file counts only if it was written at
    or after `since_epoch`, the moment the run started: a stale page left by
    an earlier run (a group that failed THIS run) must never be filed under
    this week. Returns ({dest_name: src_path}, [dest_name, ...]).

    The lookup is by name, and on macOS's case-insensitive disk `TQB.txt`
    finds the `tqb.txt` the alert has always written; the copy is filed under
    the canonical name, so every week's folder looks the same.
    """
    fresh = {}
    missing = []
    for name in names:
        dest = name if name.endswith((".txt", ".json")) else name + ".txt"
        src = os.path.join(captures_dir, dest)
        try:
            ok = os.path.getmtime(src) >= since_epoch
        except OSError:
            ok = False
        if ok:
            fresh[dest] = src
        else:
            missing.append(dest)
    return fresh, missing


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_manifest(folder):
    """sha256 every file in `folder` (flat) except the manifest itself."""
    names = sorted(n for n in os.listdir(folder)
                   if n != MANIFEST and os.path.isfile(os.path.join(folder, n)))
    lines = ["%s  %s\n" % (sha256_file(os.path.join(folder, n)), n)
             for n in names]
    with open(os.path.join(folder, MANIFEST), "w") as fh:
        fh.writelines(lines)
    return names


def verify_manifest(folder):
    """None if every file in the folder's manifest matches, else the reason."""
    path = os.path.join(folder, MANIFEST)
    if not os.path.isfile(path):
        return "no %s in %s" % (MANIFEST, folder)
    bad = []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            digest, name = line.split("  ", 1)
            f = os.path.join(folder, name)
            if not os.path.isfile(f) or sha256_file(f) != digest:
                bad.append(name)
    if bad:
        return "checksum mismatch in %s: %s" % (folder, ", ".join(bad))
    return None


def to_archive(files, note, archive_root, season, week, unit):
    """Build the unit in the local archive. Returns (Step, unit_path or None).

    Built in a hidden temp folder and renamed into place, so a crash half way
    leaves no half-filled unit that a later run would take as "already there".
    Folders 700, files 600, like the rest of the archive.
    """
    parent = os.path.join(archive_root, str(season), "cbs-weekly",
                          week_dir(week))
    final = os.path.join(parent, unit)
    where = "archive"
    try:
        if os.path.exists(final):
            why = verify_manifest(final)
            if why:
                return Step(where, unit, FAILED, why), None
            return Step(where, unit, EXISTS, final), final
        old = os.umask(0o077)
        try:
            os.makedirs(parent, exist_ok=True)
            tmp = os.path.join(parent, ".tmp-" + unit)
            if os.path.exists(tmp):
                shutil.rmtree(tmp)
            os.mkdir(tmp, 0o700)
            for dest, src in sorted(files.items()):
                shutil.copy2(src, os.path.join(tmp, dest))
                os.chmod(os.path.join(tmp, dest), 0o600)
            with open(os.path.join(tmp, NOTE), "w") as fh:
                fh.write(note)
            os.chmod(os.path.join(tmp, NOTE), 0o600)
            write_manifest(tmp)
            os.chmod(os.path.join(tmp, MANIFEST), 0o600)
            for dest, src in files.items():
                if sha256_file(src) != sha256_file(os.path.join(tmp, dest)):
                    raise OSError("copy of %s does not match its source" % src)
            os.rename(tmp, final)
        finally:
            os.umask(old)
        return Step(where, unit, OK, final), final
    except (OSError, ValueError) as exc:
        return Step(where, unit, FAILED, str(exc)), None


def _ssh(host, command, runner):
    return runner(["ssh"] + _SSH_OPTS + [host, command],
                  capture_output=True, text=True, timeout=_SSH_TIMEOUT_S)


def pi_root(host, runner=subprocess.run):
    """`<data disk>/Documents/fantasy-football-data` on the Pi, by lookup.

    The data disk's mount name changes with the disk, so it is never
    hard-coded (the data repo's README gives the same lookup).
    """
    proc = _ssh(host, "ls -d /srv/dev-disk-by-uuid-*/Documents | head -1",
                runner)
    docs = (proc.stdout or "").strip()
    if proc.returncode != 0 or not docs.startswith("/srv/"):
        raise OSError("could not find the Documents share on %s (exit %d: %s)"
                      % (host, proc.returncode, (proc.stderr or "").strip()))
    return docs + "/fantasy-football-data"


def to_pi(unit_path, host, root, season, week, unit, runner=subprocess.run):
    """Copy the archived unit to the Pi and check it there with sha256sum."""
    where = "pi"
    parent = "%s/%s/cbs-weekly/%s" % (root, season, week_dir(week))
    target = parent + "/" + unit
    q_parent, q_target = shlex.quote(parent), shlex.quote(target)
    check = "cd %s && sha256sum -c --quiet %s" % (q_target, MANIFEST)
    try:
        proc = _ssh(host, "if test -e %s; then echo EXISTS; else umask 077 "
                          "&& mkdir -p %s && echo NEW; fi" % (q_target, q_parent),
                    runner)
        state = (proc.stdout or "").strip()
        if proc.returncode != 0 or state not in ("EXISTS", "NEW"):
            return Step(where, unit, FAILED, "ssh %s failed (exit %d): %s" % (
                host, proc.returncode, (proc.stderr or "").strip()))
        if state == "NEW":
            cp = runner(["scp", "-p", "-r", "-q"] + _SSH_OPTS
                        + [unit_path, "%s:%s/" % (host, parent)],
                        capture_output=True, text=True, timeout=_SSH_TIMEOUT_S)
            if cp.returncode != 0:
                return Step(where, unit, FAILED, "scp failed (exit %d): %s" % (
                    cp.returncode, (cp.stderr or "").strip()))
        ver = _ssh(host, check, runner)
        if ver.returncode != 0:
            return Step(where, unit, FAILED, "sha256sum -c failed on %s: %s" % (
                target, ((ver.stdout or "") + (ver.stderr or "")).strip()))
        return Step(where, unit, OK if state == "NEW" else EXISTS, target)
    except (OSError, subprocess.SubprocessError) as exc:
        return Step(where, unit, FAILED, str(exc))


def _git(repo, args, runner, timeout=60, env=None):
    return runner(["git", "-C", repo] + args, capture_output=True, text=True,
                  timeout=timeout, env=env)


def to_repo(unit_path, repo, season, week, unit, runner=subprocess.run):
    """Copy the archived unit into the data repo and add it to MANIFEST.sha256.

    Returns (Step, [repo-relative paths to commit]). Does not commit: one
    commit carries every unit of a run (see `commit_and_push`).
    """
    where = "repo"
    rel = "%s/cbs/weekly/%s/%s" % (season, week_dir(week), unit)
    dest = os.path.join(repo, rel)
    try:
        branch = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], runner)
        if branch.returncode != 0 or branch.stdout.strip() != "main":
            return Step(where, unit, FAILED,
                        "%s is not on main (%s); nothing copied"
                        % (repo, (branch.stdout or branch.stderr).strip())), []
        if os.path.exists(dest):
            why = verify_manifest(dest)
            if why:
                return Step(where, unit, FAILED, why), []
            # Copied by an earlier run that died before its commit: hand the
            # paths on so this run's commit picks them up.
            st = _git(repo, ["status", "--porcelain", "--", rel, MANIFEST],
                      runner)
            pending = [rel, MANIFEST] if st.stdout.strip() else []
            return Step(where, unit, EXISTS, dest), pending
        shutil.copytree(unit_path, dest)
        for name in os.listdir(dest):
            os.chmod(os.path.join(dest, name), 0o644)
        why = verify_manifest(dest)
        if why:
            raise OSError(why)
        add_to_repo_manifest(repo, rel)
        return Step(where, unit, OK, dest), [rel, MANIFEST]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return Step(where, unit, FAILED, str(exc)), []


def add_to_repo_manifest(repo, rel):
    """Add every file under `rel` to the repo's top-level MANIFEST.sha256.

    Existing lines are kept as they are (not re-hashed: a re-hash would
    silently bless a file that had gone bad), the new ones are added, and the
    whole list stays sorted by path, as `find . | sort` wrote it.
    """
    path = os.path.join(repo, MANIFEST)
    entries = {}
    if os.path.isfile(path):
        with open(path) as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line:
                    entries[line.split("  ", 1)[1]] = line
    base = os.path.join(repo, rel)
    for name in sorted(os.listdir(base)):
        key = "./%s/%s" % (rel, name)
        entries[key] = "%s  %s" % (sha256_file(os.path.join(base, name)), key)
    with open(path, "w") as fh:
        fh.write("".join(entries[k] + "\n" for k in sorted(entries)))


def commit_and_push(repo, paths, message, push=True, runner=subprocess.run):
    """Commit ONLY `paths`, then push main. Returns a list of Steps.

    `git commit -- <paths>` commits those paths alone, so anything else a
    person has staged in the data repo stays out of the job's commit.

    Push runs even when this run had nothing new to commit, if main is ahead
    of origin: a commit whose push failed last time goes out with the next run.
    The ssh options make a missing key fail at once instead of prompting.
    """
    steps = []
    if paths:
        uniq = sorted(set(paths))
        add = _git(repo, ["add", "--"] + uniq, runner)
        if add.returncode != 0:
            return [Step("commit", "-", FAILED, add.stderr.strip())]
        com = _git(repo, ["commit", "-q", "-m", message, "--"] + uniq, runner)
        if com.returncode != 0:
            return [Step("commit", "-", FAILED,
                         (com.stdout + com.stderr).strip())]
        head = _git(repo, ["rev-parse", "--short", "HEAD"], runner)
        steps.append(Step("commit", "-", OK, head.stdout.strip()))
    if not push:
        steps.append(Step("push", "-", SKIPPED, "--no-push"))
        return steps
    ahead = _git(repo, ["rev-list", "--count", "origin/main..main"], runner)
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        steps.append(Step("push", "-", SKIPPED, "nothing to push"))
        return steps
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = "ssh " + " ".join(_SSH_OPTS)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = _git(repo, ["push", "-q", "origin", "main"], runner,
                 timeout=_PUSH_TIMEOUT_S, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        steps.append(Step("push", "-", FAILED, str(exc)))
        return steps
    if p.returncode != 0:
        steps.append(Step("push", "-", FAILED, "exit %d: %s" % (
            p.returncode, (p.stdout + p.stderr).strip())))
    else:
        steps.append(Step("push", "-", OK, "origin main"))
    return steps


def collect_units(units, archive_root, season, repo=None, pi_host=None,
                  push=True, message=None, runner=subprocess.run):
    """Run every unit through archive -> Pi -> repo, then one commit and push.

    `units` is a list of (week, unit_name, {dest_name: src_path}, note).
    Each destination is independent: a unit that failed to reach the Pi still
    goes to the repo, from the archived copy. Returns the list of Steps.
    """
    steps = []
    to_commit = []
    root = None
    root_error = None
    if pi_host:
        try:
            root = pi_root(pi_host, runner)
        except (OSError, subprocess.SubprocessError) as exc:
            root_error = str(exc)
    for week, unit, files, note in units:
        step, path = to_archive(files, note, archive_root, season, week, unit)
        steps.append(step)
        if path is None:
            continue
        if not pi_host:
            steps.append(Step("pi", unit, SKIPPED, "--no-pi"))
        elif root_error:
            steps.append(Step("pi", unit, FAILED, root_error))
        else:
            steps.append(to_pi(path, pi_host, root, season, week, unit,
                               runner))
        if repo:
            step, paths = to_repo(path, repo, season, week, unit, runner)
            steps.append(step)
            to_commit.extend(paths)
        else:
            steps.append(Step("repo", unit, SKIPPED, "no data repo"))
    if repo:
        msg = message or "chore: automated: collect %s CBS pages" % season
        steps.extend(commit_and_push(repo, to_commit, msg, push, runner))
    return steps


def failed(steps):
    return [s for s in steps if s.status == FAILED]


def note_text(kind, season, week, unit, missing=(), extra=""):
    """COLLECTED.txt: what the unit is, so a folder explains itself."""
    lines = [
        "unit: %s" % unit,
        "season: %s" % season,
        "week: %d" % int(week),
        "what: %s" % kind,
        "collected_at: %s" % datetime.datetime.now().isoformat(
            timespec="seconds"),
        "collected_by: sffl collect (fantasy-football ops/run_alert.sh)",
    ]
    if missing:
        lines.append("not_refreshed_this_run: %s" % ", ".join(missing))
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"
