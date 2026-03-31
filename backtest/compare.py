"""
Multi-config comparison tool for backtesting.

Runs the same historical data against multiple BacktestConfig variations
to find optimal parameters. Outputs a comparison table.

Usage:
    from backtest.compare import compare_configs
    from data.historical import fetch_all_assets

    candles = fetch_all_assets(days=30)
    results = compare_configs(candles, configs={
        "conservative": BacktestConfig(kelly_alpha=0.10),
        "moderate": BacktestConfig(kelly_alpha=0.25),
        "aggressive": BacktestConfig(kelly_alpha=0.40),
    })
"""

from backtest.runner import BacktestConfig, BacktestResult, run_backtest
from data.historical import HistoricalCandle


def compare_configs(
    candles_by_asset: dict[str, list[HistoricalCandle]],
    configs: dict[str, BacktestConfig],
) -> dict[str, BacktestResult]:
    """
    Run backtests with multiple configs and return all results.

    Args:
        candles_by_asset: Historical candle data for all assets.
        configs: Dict mapping config name to BacktestConfig.

    Returns:
        Dict mapping config name to BacktestResult.
    """
    results = {}
    for name, config in configs.items():
        print(f"\nRunning backtest: {name}...")
        results[name] = run_backtest(candles_by_asset, config)
    return results


def print_comparison(results: dict[str, BacktestResult]):
    """Print a side-by-side comparison table of backtest results."""
    print("\n" + "=" * 100)
    print("BACKTEST COMPARISON")
    print("=" * 100)

    header = f"{'Config':<20} {'Balance':>10} {'ROI':>8} {'Trades':>7} {'Win%':>7} {'Brier':>7} {'MaxDD':>7} {'Reversals':>10}"
    print(header)
    print("-" * 100)

    for name, r in results.items():
        rev_str = f"{len(r.reversal_trades)} ({r.reversal_win_rate:.0%})" if r.reversal_trades else "0"
        row = (
            f"{name:<20} "
            f"${r.final_balance:>9.2f} "
            f"{r.roi_pct:>+7.1f}% "
            f"{r.total_trades:>7} "
            f"{r.win_rate:>6.1%} "
            f"{r.calculate_brier_score():>7.4f} "
            f"{r.max_drawdown_pct:>6.1f}% "
            f"{rev_str:>10}"
        )
        print(row)

    print("=" * 100)

    # Find best config
    best = max(results.items(), key=lambda x: x[1].final_balance)
    print(f"\nBest config: {best[0]} (${best[1].final_balance:.2f})")
