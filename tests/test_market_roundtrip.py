"""Fit -> persist -> apply must reproduce fit-in-process, exactly.

The split is supposed to change WHEN the curve is fitted, not what it is. If
this test fails, either the persisted floats lost precision or the apply path
diverged from the fit path - and both look, from the board, like an
unexplained change in dollars.
"""


def _pool_dollars(argv):
    """Run a valuation and return {player name: (_dollars, _est_price)}."""
    from sffl.cli import main
    import sffl.cli as cli
    captured = {}
    real = cli.assign_expected_prices

    def spy(lg, pool, curve):
        k = real(lg, pool, curve)
        captured["rows"] = dict(
            (p.name, (round(p.stats["_dollars"], 6),
                      round(p.stats["_est_price"], 6))) for p in pool)
        captured["curve"] = curve
        return k

    cli.assign_expected_prices = spy
    try:
        assert main(argv) == 0
    finally:
        cli.assign_expected_prices = real
    return captured


COMMON = ["--source", "sources/draftsharks.yaml",
          "--file", "tests/fixtures/draftsharks_market_fit_sample.csv",
          "--year", "2026"]


def test_persisting_the_fit_does_not_move_the_board(tmp_path):
    out = str(tmp_path / "2026.yaml")
    from sffl.cli import main
    assert main(["fit-market"] + COMMON + [
        "--prices", "tests/fixtures/prices_market_fit_sample.csv",
        "--tqb-starters", "identity/tqb-2026-starters.yaml",
        "--out", out]) == 0

    direct = _pool_dollars(["value"] + COMMON + [
        "--prices", "tests/fixtures/prices_market_fit_sample.csv",
        "--tqb-starters", "identity/tqb-2026-starters.yaml",
        "--policy", "fit"])
    applied = _pool_dollars(["value"] + COMMON + ["--market", out])

    assert applied["curve"] == direct["curve"], "the persisted curve differs"
    assert applied["rows"] == direct["rows"], "the board moved"
