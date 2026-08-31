"""PRE-REGISTERED gate: does a bigger-sample def_pa/def_ya curve rank DSTs
better on the WEEKLY path than the shipped 4-defense interpolation?

Binding spec: docs/superpowers/specs/2026-08-30-def-curve-weekly-gate.md
(committed BEFORE this script was written or run). That document wins over
this docstring if they ever disagree.

THE METRIC IS RANK, NOT ERROR. The alert starts exactly one defense a week;
a curve that is uniformly low but orders defenses correctly costs nothing,
and a lower-error curve that inverts the top two costs a decision every
week. So the primary statistic is Spearman rank correlation between a
defense's PREDICTED full weekly DST score and its REALIZED one, not MAE.
See poc/measure_weekly_calibration.py's closing note for the same standard
stated independently, before this gate existed.

FULL WEEKLY SCORE, NOT THE BANDED COMPONENT. def_pa/def_ya are two inputs
among several - sacks, interceptions, fumble recoveries, touchdowns and
safeties are unbanded and the curve never touches them - and the alert
ranks on the total `score_week` produces, so that is what this measures.

PREDICTOR = PRODUCTION. `pool.score_week` is what `sffl week` actually
calls; it runs def_pa/def_ya through `pool._calibrated_band_value` (the
monotone envelope), not raw interpolation. This script predicts by calling
`score_week` itself, on a synthetic one-week `PlayerProjection` built from
each held-out defense's own per-game means (exactly how a real weekly
projection line is shaped) - never `calibrate.expected_points` directly.

CROSS-VALIDATION IS BY DEFENSE, NEVER BY ROW. `sffl.calibrate_eval.
player_folds` already partitions disjoint player (here: defense) ids
into folds deterministically; this script reuses it rather than writing a
new splitter, exactly as instructed. Every one of the three candidate
builders - the shipped `calibrate.build_curves`, `build_curves_isotonic`,
`build_curves_pooled` - is refit from scratch on each fold's fit-only
lines, so a defense's own weeks are never in both its fit and holdout set,
for ANY candidate, including the "shipped" one. The parentheticals in the
gate spec ("4 defenses", "26") describe how much data each method uses to
build its CURRENT (or a prospective) production curve; for a fair
comparison here, all three are evaluated by the same leave-defense-out
harness over the same population, exactly as `calibrate_eval.
cross_validate` already treats any builder uniformly.

DATA HYGIENE FINDING, discovered before any Spearman number was computed
(see `_load_canonical_dst_lines` below): the held-back file
data/weekly/2025/_held_back/DST.full.csv carries the Minnesota Vikings
under TWO different CBS player_ids (1916 and 1918) with byte-identical
stats for all 17 weeks - almost certainly a re-scrape that picked up a new
CBS id mid-season. Splitting folds by raw player_id would put "two"
Vikings in different folds while their weeks are identical, which is
exactly the leak the gate's own design section warns against ("a defense's
own weeks in its own fit set would let interpolation predict it almost
exactly"). Both ids are relabeled to one canonical id (keyed on (name,
team)) before folding, and the resulting exact-duplicate rows are dropped.
This also means the true number of distinct 2025 defenses in the data is
21, not the 26 stated as background in the dispatch prompt - the 4
build-set-only teams (Bengals/Broncos/Packers/Vikings) turn out to be
byte-identical, already-included rows inside the held-back "full" file, not
4 additional ones. Both facts are reported, not corrected in the number
that gets compared to the pre-registered SE estimate.

Run:
    PYTHONPATH=src ./.venv/bin/python poc/measure_dst_ranking.py
"""

import math
import os
from collections import defaultdict

from sffl.calibrate import (
    MIN_WEEKS,
    build_curves,
    build_curves_isotonic,
    build_curves_pooled,
)
from sffl.calibrate_eval import player_folds
from sffl.league import load_league
from sffl.pool import score_week
from sffl.schema import PlayerProjection
from sffl.scoring import score_game
from sffl.weekly import load_weekly

LEAGUE_PROFILE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "leagues", "sffl", "2026.yaml")
HELD_BACK_DST = os.path.join(
    os.path.dirname(__file__), "..", "data", "weekly", "2025",
    "_held_back", "DST.full.csv")

GATE_MARGIN = 0.15  # pre-registered; see the spec. Not adjustable here.

BASELINE_NAME = "shipped interpolation (build_curves)"
CANDIDATES = {
    "isotonic": build_curves_isotonic,
    "pooled": build_curves_pooled,
}
STATS = ("def_pa", "def_ya")


def _load_canonical_dst_lines(path):
    """Load weekly DST lines, deduped and re-keyed to one id per real team.

    See the module docstring's "DATA HYGIENE FINDING" for why this is
    necessary before any fold can honestly claim to split "by defense."
    """
    raw = load_weekly(path)
    canon_id = {}
    out = []
    seen_rows = set()
    dupe_report = []
    for ln in raw:
        team_key = (ln.name, ln.team)
        canonical = canon_id.setdefault(team_key, ln.player_id)
        if canonical != ln.player_id:
            dupe_report.append((team_key, ln.player_id, canonical))
        ln.player_id = canonical
        row_key = (canonical, ln.week)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        out.append(ln)
    return out, dupe_report


def _mean_stats(weeks):
    keys = set()
    for w in weeks:
        keys.update(w.stats.keys())
    n = len(weeks)
    return {k: sum(w.stats.get(k, 0.0) for w in weeks) / n for k in keys}


def _realized_score(lg, weeks):
    """mean(score_game(actual week)) - the true weekly outcome, no curve."""
    return sum(score_game(lg, w.stats, pos="DST") for w in weeks) / len(weeks)


def _predicted_score(lg, weeks, curves):
    """score_week on a synthetic one-week projection built from this
    defense's own per-game means - the same shape a real weekly projection
    takes, scored by the exact function `sffl week` calls in production.
    """
    proj = PlayerProjection(
        name=weeks[0].name, team=weeks[0].team, pos="DST",
        source="measure_dst_ranking", source_year=2025,
        games=1, stats=_mean_stats(weeks),
    )
    return score_week(lg, proj, curves)


def cross_validate_full_score(lg, lines, pa_builder, ya_builder, k,
                               min_weeks=MIN_WEEKS):
    """One (predicted, realized, name) triple per defense with >= min_weeks
    weeks, collected out-of-fold. `pa_builder`/`ya_builder` may be the same
    function (both stats swapped together) or different (one stat left at
    baseline - "def_pa and def_ya may be adopted independently").
    """
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    out = {}
    for fold in player_folds(lines, k):
        fit_lines = [ln for ln in lines if ln.player_id not in fold]
        pa_curves = pa_builder(lg, fit_lines)
        ya_curves = ya_builder(lg, fit_lines) if ya_builder is not pa_builder else pa_curves
        curves = {
            "def_pa": pa_curves.get("def_pa") or [],
            "def_ya": ya_curves.get("def_ya") or [],
        }
        for pid in fold:
            weeks = by_player[pid]
            if len(weeks) < min_weeks:
                continue
            pred = _predicted_score(lg, weeks, curves)
            real = _realized_score(lg, weeks)
            out[pid] = (pred, real, weeks[0].name)
    return out


def _rank(values):
    """Average ranks (1-based), ties split evenly."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for m in range(i, j + 1):
            ranks[order[m]] = avg
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def spearman(xs, ys):
    """Rank both lists (average ranks for ties), Pearson-correlate the
    ranks. Pure stdlib - no numpy/scipy, per the gate's constraints.
    """
    return _pearson(_rank(xs), _rank(ys))


def top1_hit(triples):
    """True iff the defense with the highest PREDICTED score also has the
    highest REALIZED score.
    """
    best_pred = max(triples, key=lambda t: t[0])
    best_real = max(triples, key=lambda t: t[1])
    return best_pred[2] == best_real[2]


def evaluate(lg, lines, pa_builder, ya_builder, k):
    oof = cross_validate_full_score(lg, lines, pa_builder, ya_builder, k)
    triples = list(oof.values())
    preds = [t[0] for t in triples]
    reals = [t[1] for t in triples]
    return {
        "n": len(triples),
        "spearman": spearman(preds, reals),
        "top1": top1_hit(triples),
        "oof": oof,
    }


def main():
    lg = load_league(LEAGUE_PROFILE_PATH)
    lines, dupes = _load_canonical_dst_lines(HELD_BACK_DST)

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)
    n_defenses = len(by_player)

    print("=" * 78)
    print("DATA")
    print("=" * 78)
    print("Loaded %d rows, %d distinct defenses (canonical) from %s"
          % (len(lines), n_defenses, HELD_BACK_DST))
    for team_key, dup_id, canonical in sorted(set(dupes)):
        print("  DUPLICATE ID FOUND: %r had id=%s, relabeled to canonical id=%s"
              % (team_key, dup_id, canonical))
    weeks_per = sorted(len(v) for v in by_player.values())
    print("  weeks per defense: min=%d max=%d" % (weeks_per[0], weeks_per[-1]))
    print()
    print("NOTE: the dispatch background states '26 defenses' available from")
    print("held-back data. Measured: %d distinct real defenses (21 canonical" % n_defenses)
    print("teams once the id collision above is fixed), because the 4 teams")
    print("in the original build-set-only file (data/weekly/2025/DST.csv) are")
    print("byte-identical, already-included rows inside this held-back file,")
    print("not 4 additional ones on top of it. Verified by diff, all 4 match.")
    print()

    fold_counts = [("k=5", 5), ("leave-one-out (k=%d)" % n_defenses, n_defenses)]

    all_results = {}  # (fold_label) -> {"baseline": {...}, (stat, cand): {...}}
    for fold_label, k in fold_counts:
        baseline = evaluate(lg, lines, build_curves, build_curves, k)
        row = {"baseline": baseline}
        for stat in STATS:
            for cand_name, cand_builder in CANDIDATES.items():
                pa_b = cand_builder if stat == "def_pa" else build_curves
                ya_b = cand_builder if stat == "def_ya" else build_curves
                row[(stat, cand_name)] = evaluate(lg, lines, pa_b, ya_b, k)
        all_results[fold_label] = row

    print("=" * 78)
    print("PRIMARY: Spearman rank correlation, predicted vs realized FULL")
    print("weekly DST score (score_week output), out-of-fold by defense")
    print("=" * 78)
    header = "%-45s %10s %10s %10s %8s" % (
        "candidate", "fold", "n", "spearman", "top1")
    print(header)
    for fold_label, _k in fold_counts:
        row = all_results[fold_label]
        b = row["baseline"]
        print("%-45s %10s %10d %10.4f %8s" % (
            BASELINE_NAME, fold_label, b["n"],
            b["spearman"] if b["spearman"] is not None else float("nan"),
            "HIT" if b["top1"] else "miss"))
        for stat in STATS:
            for cand_name in CANDIDATES:
                r = row[(stat, cand_name)]
                label = "%s (%s only)" % (cand_name, stat)
                print("%-45s %10s %10d %10.4f %8s" % (
                    label, fold_label, r["n"],
                    r["spearman"] if r["spearman"] is not None else float("nan"),
                    "HIT" if r["top1"] else "miss"))
    print()

    print("=" * 78)
    print("MARGIN vs baseline (candidate spearman - baseline spearman)")
    print("=" * 78)
    margins = {}  # (stat, cand) -> {fold_label: margin}
    for stat in STATS:
        for cand_name in CANDIDATES:
            margins[(stat, cand_name)] = {}
            for fold_label, _k in fold_counts:
                row = all_results[fold_label]
                b_sp = row["baseline"]["spearman"]
                c_sp = row[(stat, cand_name)]["spearman"]
                margin = None if (b_sp is None or c_sp is None) else c_sp - b_sp
                margins[(stat, cand_name)][fold_label] = margin
                b_top1 = row["baseline"]["top1"]
                c_top1 = row[(stat, cand_name)]["top1"]
                print("%-20s fold=%-25s margin=%8s  top1 base=%-5s cand=%-5s"
                      % ("%s/%s" % (stat, cand_name), fold_label,
                         ("%.4f" % margin) if margin is not None else "n/a",
                         b_top1, c_top1))
    print()

    print("=" * 78)
    print("GATE EVALUATION (all four conditions must hold to adopt)")
    print("=" * 78)
    cleared = []
    for stat in STATS:
        for cand_name in CANDIDATES:
            key = (stat, cand_name)
            per_fold_margin = margins[key]
            cond1 = all(m is not None and m >= GATE_MARGIN for m in per_fold_margin.values())
            cond2 = True
            for fold_label, _k in fold_counts:
                row = all_results[fold_label]
                if row[key]["top1"] is False and row["baseline"]["top1"] is True:
                    cond2 = False
            cond3 = cond1  # "holds under both k=5 and LOO" is folded into cond1's `all(...)`
            verdict = "CLEARS 0.15 on both fold counts, top1 not reduced" if (cond1 and cond2) else "does not clear"
            print("%-20s cond1(margin>=0.15 both folds)=%-5s cond2(top1 not reduced)=%-5s -> %s"
                  % ("%s/%s" % key, cond1, cond2, verdict))
            if cond1 and cond2 and cond3:
                cleared.append(key)
    print()

    print("=" * 78)
    print("DROP-ONE (condition 4), only for combos that cleared 0.15 above")
    print("=" * 78)
    if not cleared:
        print("Nothing cleared the 0.15 margin on both fold counts - no drop-one to run.")
    for stat, cand_name in cleared:
        cand_builder = CANDIDATES[cand_name]
        pa_b = cand_builder if stat == "def_pa" else build_curves
        ya_b = cand_builder if stat == "def_ya" else build_curves
        print("\n--- drop-one for %s/%s (k=5) ---" % (stat, cand_name))
        worst_margin = None
        worst_defense = None
        for dropped_pid in sorted(by_player.keys()):
            remaining = [ln for ln in lines if ln.player_id != dropped_pid]
            remaining_defenses = len(set(ln.player_id for ln in remaining))
            k = min(5, remaining_defenses)
            b = evaluate(lg, remaining, build_curves, build_curves, k)
            c = evaluate(lg, remaining, pa_b, ya_b, k)
            if b["spearman"] is None or c["spearman"] is None:
                margin = None
            else:
                margin = c["spearman"] - b["spearman"]
            name = by_player[dropped_pid][0].name
            print("  drop %-14s -> margin=%s" % (
                name, ("%.4f" % margin) if margin is not None else "n/a"))
            if margin is not None and (worst_margin is None or margin < worst_margin):
                worst_margin = margin
                worst_defense = name
        print("  WORST margin after any single drop: %s (dropping %s)" % (
            ("%.4f" % worst_margin) if worst_margin is not None else "n/a", worst_defense))
        if worst_margin is not None and worst_margin < GATE_MARGIN:
            print("  -> FAILS drop-one: effect depends on defense %r, not the curve." % worst_defense)
        else:
            print("  -> survives drop-one.")

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    if not cleared:
        print("UNDERPOWERED - keep the baseline. No candidate/stat combination")
        print("beat the shipped interpolation's Spearman by >= 0.15 on BOTH k=5")
        print("and leave-one-out. This is a statement about measurement power")
        print("at n=%d (SE ~ 1/sqrt(n-1) ~ %.3f), not a claim the candidates" % (
            n_defenses, 1.0 / math.sqrt(max(n_defenses - 1, 1))))
        print("failed. The 4-defense curves stand for want of evidence, not")
        print("for merit. What would change the answer: another season of")
        print("weekly DST data to raise n materially above ~21.")
    else:
        print("Cleared combinations (before drop-one): %s" % cleared)
        print("See the drop-one section above for whether each survives it.")


if __name__ == "__main__":
    main()
