"""The persisted market model: how this room converts value into dollars.

WHY THIS FILE EXISTS. Fitting and applying are two different operations that
were fused into one command, and only FITTING is season-bound. Fitting asks how
the room behaves and needs year-matched prices, which exist only after an
auction. Applying asks what a player will cost and needs only a curve. Fusing
them meant a pre-auction run had to either refuse (guard trips) or silently fit
across seasons (the artifact-era curve returns, b=0.531 against the year-matched
truth of 0.662, TQB joins 21 -> 15, every number looking plausible).

Separating them makes the guard honest: refuse a cross-season FIT, permit a
cross-season APPLY, and say loudly which model is in use and from when. Last
year's model of this room is not a compromise forced by missing data - it is the
correct thing to want, because the room's behaviour is a property of the twelve
people in it, which persists across seasons far better than any player's value.

WHY `evidence` AND `diagnostics` ARE STORED RATHER THAN RE-DERIVED. The failure
this whole split exists to prevent was invisible precisely because nothing
recorded what had been fitted against what. An artifact that cannot answer
"which prices, which projections, how many observations" would reproduce the
original problem in a new place. They are a record of one fitting run, never
recomputed on load, and never used in any calculation.
"""

import os
from collections import namedtuple

import yaml

MarketModel = namedtuple(
    "MarketModel", "season fitted_on curve policy evidence diagnostics")

# Mirrors fit.POLICIES. Duplicated deliberately rather than imported: this
# module must stay free of the fitting path so a pure APPLY never drags in the
# machinery that needs prices.
_KNOWN_POLICIES = ("starter", "draftable")

_REQUIRED = ("season", "fitted_on", "curve", "policy")


def describe(model):
    """One line naming the model in use. Printed on every apply."""
    ev = model.evidence or {}
    return ("using the %d market model (a=%.4f, b=%.4f, n=%s, fitted %s, "
            "policy=%s)"
            % (model.season, model.curve[0], model.curve[1],
               ev.get("observations", "?"), model.fitted_on, model.policy))


def save(path, model, overwrite=False):
    """Write the model. Refuses to clobber an existing file unless told to.

    The artifact is the evidence a board was priced from; a stray re-run must
    not quietly replace it, because the board and its justification would then
    disagree with nothing to show for it.
    """
    if os.path.exists(path) and not overwrite:
        raise OSError(
            "%s already exists; refusing to overwrite the market model a board "
            "may have been priced from. Pass overwrite=True (CLI: --force) if "
            "you really mean to replace it." % path)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    # float(repr(x)) == x in Python 3, and yaml.safe_dump writes repr for
    # floats, so a and b survive the round trip exactly. That is required:
    # a lost digit moves the board and looks like a logic bug rather than a
    # serialisation one.
    body = {
        "season": int(model.season),
        "fitted_on": str(model.fitted_on),
        "curve": {"a": float(model.curve[0]), "b": float(model.curve[1])},
        "policy": str(model.policy),
        "evidence": dict(model.evidence or {}),
        "diagnostics": dict(model.diagnostics or {}),
    }
    with open(path, "w") as fh:
        yaml.safe_dump(body, fh, default_flow_style=False, sort_keys=True)


def load(path):
    """Read a model, validating what a hand edit could break."""
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}

    missing = [k for k in _REQUIRED if raw.get(k) is None]
    if missing:
        raise ValueError(
            "%s is not a usable market model: missing %s. A model must carry "
            "the season it was fitted from, the date, the curve, and the "
            "replacement policy chosen from the same prices."
            % (path, ", ".join(sorted(missing))))

    curve = raw["curve"] or {}
    if curve.get("a") is None or curve.get("b") is None:
        raise ValueError("%s: curve must carry both 'a' and 'b'" % path)
    a = float(curve["a"])
    b = float(curve["b"])

    # The fitter enforces both of these, but a hand-edited artifact never went
    # through the fitter - and this file is meant to be human-readable, which
    # means human-editable.
    if b <= 0.0:
        raise ValueError(
            "%s: exponent b=%.4f is not monotonic increasing; a better player "
            "would cost less, which no real auction does." % (path, b))
    if a < 1.0:
        raise ValueError(
            "%s: intercept a=%.4f is below the $1 floor, which would clamp "
            "every cheap player to an identical estimate and destroy ordering "
            "among them." % (path, a))

    policy = str(raw["policy"])
    if policy not in _KNOWN_POLICIES:
        raise ValueError(
            "%s: unknown replacement policy %r; expected one of %s"
            % (path, policy, list(_KNOWN_POLICIES)))

    return MarketModel(
        season=int(raw["season"]),
        fitted_on=str(raw["fitted_on"]),
        curve=(a, b),
        policy=policy,
        evidence=dict(raw.get("evidence") or {}),
        diagnostics=dict(raw.get("diagnostics") or {}),
    )
