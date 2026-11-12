"""The repo is public: every private path stays ignored as a dir AND a symlink.

A pattern with a trailing slash (`.venv/`) matches directories only, and git
treats a symlink as a file, so a worktree's `.venv -> ../main/.venv` link (or
a `data/weekly` link to the licensed pages) showed as untracked and a
`git add -A` would have committed it (Ultron, 2026-11-12). Each path here is
checked both ways in a scratch repo carrying this repo's .gitignore.
"""

import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GITIGNORE = os.path.join(HERE, "..", ".gitignore")

PRIVATE = [".venv", "venv", "data/extracts", "data/weekly", "data/captures",
           "data/browser-profile", "data/cache", "logs", ".superpowers"]


@pytest.fixture
def scratch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    shutil.copy(GITIGNORE, str(repo / ".gitignore"))
    (repo / "data").mkdir()
    (tmp_path / "target").mkdir()
    return repo, tmp_path / "target"


def _ignored(repo, rel):
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel]
                          ).returncode == 0


@pytest.mark.parametrize("rel", PRIVATE)
@pytest.mark.parametrize("kind", ["dir", "symlink"])
def test_private_path_is_ignored_as_a_dir_and_as_a_symlink(scratch, rel, kind):
    repo, target = scratch
    p = repo / rel
    if kind == "dir":
        p.mkdir()
        (p / "x.txt").write_text("x\n")
    else:
        os.symlink(str(target), str(p))
    assert _ignored(repo, rel), "%s (%s) is not ignored" % (rel, kind)
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain",
                             "--untracked-files=all"], capture_output=True,
                            text=True, check=True).stdout
    assert rel not in status
