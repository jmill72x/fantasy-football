"""Run one sffl module the way `python -m` does, with nothing from the
current directory on sys.path. The alert jobs call it as

    ./.venv/bin/python -I ops/run_module.py sffl.cli alert --kind friday ...

WHY (Ultron 11-11, board 1d0ce259). `python -m` and `python -c` put the
current directory first on sys.path, ahead of PYTHONPATH and the standard
library, and the jobs run from the repo root. A stray `json.py`,
`datetime.py`, `runpy.py` or `sffl.py` left there would have been imported
by the scheduled run in place of the real one.

WHY THIS WAY on Python 3.9.6 (the venv): `-P` and PYTHONSAFEPATH, which only
drop that first entry, arrived in 3.11. `-I` (isolated mode, since 3.4) adds
neither the current directory nor the script's own folder to sys.path, and
it implies -E (PYTHON* variables, PYTHONPATH among them, are ignored) and -s
(no user site-packages; the venv already had none). The venv's own
site-packages still load. So under -I something must put src on the path,
and this file does: the absolute src/ beside its own ops/ folder, found from
`__file__`, never from the working directory. The working directory stays
the repo root, because every default path in `sffl alert` and `sffl collect`
is repo-relative.

WHERE src GOES (Ultron's review, 11-21): AFTER the standard library and just
before the first site-packages entry, so nothing in src/ can stand in for a
stdlib module, and sffl still wins over anything installed. And src/ must
hold nothing importable at its top level but the sffl package: anything else
there (a stray yaml.py would shadow the installed yaml) is refused before
the run starts, naming the entry.

The -I check comes first, with only `sys` imported (built in, always
loaded): without -I this file's own folder, ops/, is on sys.path, so even
`import runpy` could load a stray ops/runpy.py.

runpy.run_module(..., run_name="__main__", alter_sys=True) is what `-m`
itself calls: the module runs as __main__ and sys.argv[0] becomes its file,
so argparse and the exit code behave exactly as before.
"""

import sys

if not sys.flags.isolated:
    # Without -I, ops/, PYTHONPATH and the user site would all apply.
    sys.stderr.write("run_module.py: run it with python -I\n")
    sys.exit(2)

import os  # noqa: E402
import runpy  # noqa: E402

SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

# Names at src/'s top level that can never be imported as a module.
_HARMLESS = {"sffl", "__pycache__"}


def _strays(src):
    return sorted(n for n in os.listdir(src)
                  if n not in _HARMLESS and not n.startswith("."))


def _insert_at(path):
    """The index of the first site-packages entry (after the stdlib), or the
    end of the path when there is none."""
    for i, entry in enumerate(path):
        if os.path.basename(entry.rstrip(os.sep)) == "site-packages":
            return i
    return len(path)


def main():
    if len(sys.argv) < 2 or not sys.argv[1].startswith("sffl."):
        print("usage: python -I ops/run_module.py sffl.<module> [args...]",
              file=sys.stderr)
        return 2
    strays = _strays(SRC)
    if strays:
        print("run_module.py: refusing to run: src/ holds more than the sffl "
              "package (%s); remove it and run again" % ", ".join(strays),
              file=sys.stderr)
        return 2
    module = sys.argv[1]
    sys.path.insert(_insert_at(sys.path), SRC)
    sys.argv = [module] + sys.argv[2:]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
