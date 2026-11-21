"""Score an auction's real prices against a market model fitted before it.

WHY THIS EXISTS. The one clean out-of-sample test this project gets each year
is the new auction's prices scored against LAST year's model, before anything
is refit on them. Once `fit-market` sees the new prices the test is spent. In
2026 it was measured by hand (NEXT.md, "2026 PRICES - THE HOLDOUT RESULT"),
because `value` refuses `--market` with `--prices`: that refusal is right for
pricing a board and wrong for this. `sffl score-auction` is the command, and
this module is its arithmetic, kept free of the CLI so it can be tested on
invented rows.

WHAT IS COMPARED. Every priced player that joins the board, flat-priced K/DST
included at their flat MY$ and EST$. That is the population the 2026 table
used (156 of 156), not the non-flat population `fit-market` fits on: the test
asks how the board did against the whole room, and K/DST are on the board.

THE SIGN. Error is model minus paid. A negative bias means the model
under-predicts what the room paid (EST$ at $26+ in 2026: -$8.74, all sixteen
round-one prices under the estimate).

THE BANDS are by the price actually PAID, not by the model's dollars, so a
band's n is a fact about the auction and does not move when the model does.
Their edges are the 2026 table's: $26+ (round one), $10-25, $4-9, $1-3.
"""

from sffl.identity import normalize_name

# (lowest price in the band, label). Ordered high to low; a price falls in the
# first band whose floor it reaches, and the last band takes everything below
# $4 so a stray sub-$1 price is still counted rather than silently dropped.
BANDS = ((26.0, "$26+"), (10.0, "$10-25"), (4.0, "$4-9"), (None, "$1-3"))


def band_of(price):
    """The label of the band a paid price falls in."""
    for floor, label in BANDS:
        if floor is None or price >= floor:
            return label
    raise AssertionError("BANDS must end with an open floor")


def join(pool, prices):
    """Pair each priced player with the board's MY$ and EST$.

    Returns (rows, unmatched): rows are (name, my, est, paid) tuples in pool
    order, and unmatched are the price keys no pool player carries, sorted.
    The keys are the canonical names `fit.load_prices` produced (aliases and
    the Team QB map already applied), so a name in `unmatched` is one that
    needs an alias or a TQB map entry.

    A player without `_est_price` means no curve was applied, and scoring
    EST$ would then measure nothing; that is refused rather than skipped.
    """
    rows = []
    seen = set()
    for p in pool:
        key = normalize_name(p.name)
        if key not in prices or key in seen:
            continue
        if "_est_price" not in p.stats:
            raise ValueError(
                "%s has no EST$ (_est_price): apply a market model before "
                "scoring against it" % p.name)
        seen.add(key)
        rows.append((p.name, float(p.stats["_dollars"]),
                     float(p.stats["_est_price"]), float(prices[key])))
    unmatched = sorted(k for k in prices if k not in seen)
    return rows, unmatched


def errors(pairs):
    """mae, rmse and bias of (model, paid) pairs, or None when there are none."""
    if not pairs:
        return None
    diffs = [m - paid for m, paid in pairs]
    n = float(len(diffs))
    return {
        "mae": sum(abs(d) for d in diffs) / n,
        "rmse": (sum(d * d for d in diffs) / n) ** 0.5,
        "bias": sum(diffs) / n,
    }


def score(rows):
    """The overall and per-band errors for EST$ and MY$.

    `rows` is what `join` returns. The result:
      {"n": int, "est": {...}, "my": {...},
       "bands": [{"label", "n", "est", "my"}, ...]}  # in BANDS order
    where each {...} is `errors`' dict, or None for an empty band.
    """
    out = {"n": len(rows),
           "est": errors([(est, paid) for _, _, est, paid in rows]),
           "my": errors([(my, paid) for _, my, _, paid in rows]),
           "bands": []}
    for _, label in BANDS:
        inside = [r for r in rows if band_of(r[3]) == label]
        out["bands"].append({
            "label": label, "n": len(inside),
            "est": errors([(est, paid) for _, _, est, paid in inside]),
            "my": errors([(my, paid) for _, my, _, paid in inside]),
        })
    return out


def _money(value, signed=False):
    if value is None:
        return "-"
    if signed:
        return "%s$%.2f" % ("-" if value < 0 else "+", abs(value))
    return "$%.2f" % value


def _cells(stats):
    if stats is None:
        return ("-", "-", "-")
    return (_money(stats["mae"]), _money(stats["rmse"]),
            _money(stats["bias"], signed=True))


def format_report(report):
    """The two tables NEXT.md's 2026 holdout result records, as text lines."""
    lines = ["overall (n=%d):" % report["n"],
             "  %-6s %8s %8s %8s" % ("", "mae", "rmse", "bias")]
    for key, label in (("est", "EST$"), ("my", "MY$")):
        lines.append("  %-6s %8s %8s %8s" % ((label,) + _cells(report[key])))
    lines.append("")
    lines.append("by price paid:")
    lines.append("  %-7s %4s | %8s %8s %8s | %8s %8s %8s"
                 % ("band", "n", "EST mae", "EST rmse", "EST bias",
                    "MY mae", "MY rmse", "MY bias"))
    for b in report["bands"]:
        lines.append("  %-7s %4d | %8s %8s %8s | %8s %8s %8s"
                     % ((b["label"], b["n"]) + _cells(b["est"])
                        + _cells(b["my"])))
    return lines
