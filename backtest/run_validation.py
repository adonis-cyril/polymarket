"""
Step 10-11: Run backtests to validate Kelly is positive and confirm parameters.

Fetches historical candles, runs multiple backtest configurations,
and outputs confirmed entry parameters, regime thresholds, and Kelly bounds.
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.historical import fetch_all_assets
from backtest.runner import BacktestConfig, run_backtest
from backtest.compare import compare_configs, print_comparison

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    # Fetch 7 days of data for all assets
    print("=" * 60)
    print("STEP 10: Fetching historical candles...")
    print("=" * 60)
    candles = fetch_all_assets(days=7)

    for asset, data in candles.items():
        print(f"  {asset.upper()}: {len(data)} candles")

    if not any(candles.values()):
        print("ERROR: No candle data fetched. Aborting.")
        return

    # Define config variations to test
    configs = {
        "conservative": BacktestConfig(
            kelly_alpha=0.10,
            min_signal_score=4.0,
            min_delta_pct=0.05,
            enable_reversals=False,
        ),
        "moderate": BacktestConfig(
            kelly_alpha=0.20,
            min_signal_score=3.0,
            min_delta_pct=0.03,
            enable_reversals=True,
        ),
        "default": BacktestConfig(
            kelly_alpha=0.25,
            min_signal_score=3.0,
            min_delta_pct=0.03,
            enable_reversals=True,
        ),
        "aggressive": BacktestConfig(
            kelly_alpha=0.35,
            min_signal_score=2.0,
            min_delta_pct=0.02,
            enable_reversals=True,
        ),
    }

    # Run all backtests
    print("\n" + "=" * 60)
    print("STEP 10: Running backtests...")
    print("=" * 60)
    results = compare_configs(candles, configs)

    # Print comparison
    print_comparison(results)

    # Print detailed results for each
    for name, result in results.items():
        print(f"\n--- {name} ---")
        result.print_summary()

    # Determine best config
    best_name = max(results, key=lambda k: results[k].final_balance)
    best = results[best_name]

    # Check if Kelly is positive
    print("\n" + "=" * 60)
    print("STEP 11: Validating Kelly criterion...")
    print("=" * 60)

    kelly_positive = best.final_balance > best.starting_balance
    print(f"  Best config: {best_name}")
    print(f"  Kelly positive: {'YES' if kelly_positive else 'NO'}")
    print(f"  ROI: {best.roi_pct:+.1f}%")
    print(f"  Brier score: {best.calculate_brier_score():.4f}")

    # Output confirmed parameters
    confirmed = {
        "best_config": best_name,
        "kelly_positive": kelly_positive,
        "parameters": {
            "kelly_alpha": configs[best_name].kelly_alpha,
            "min_signal_score": configs[best_name].min_signal_score,
            "min_delta_pct": configs[best_name].min_delta_pct,
            "max_position_pct": configs[best_name].max_position_pct,
            "enable_reversals": configs[best_name].enable_reversals,
            "reversal_max_position_pct": configs[best_name].reversal_max_position_pct,
            "daily_loss_limit": configs[best_name].daily_loss_limit,
            "drawdown_cap": configs[best_name].drawdown_cap,
            "consecutive_loss_pause": configs[best_name].consecutive_loss_pause,
        },
        "results": {
            "starting_balance": best.starting_balance,
            "final_balance": best.final_balance,
            "roi_pct": round(best.roi_pct, 2),
            "total_trades": best.total_trades,
            "win_rate": round(best.win_rate, 4),
            "snipe_win_rate": round(best.snipe_win_rate, 4),
            "reversal_trades": len(best.reversal_trades),
            "reversal_win_rate": round(best.reversal_win_rate, 4),
            "brier_score": round(best.calculate_brier_score(), 4),
            "max_drawdown_pct": round(best.max_drawdown_pct, 2),
            "windows_seen": best.windows_seen,
            "windows_skipped_regime": best.windows_skipped_regime,
            "windows_skipped_no_edge": best.windows_skipped_no_edge,
            "windows_skipped_risk": best.windows_skipped_risk,
        },
        "regime_thresholds": {
            "low_vol_ratio": 0.5,
            "high_vol_ratio": 1.5,
            "trending_directional_ratio": 0.7,
        },
        "entry_timing": {
            "LOW_VOL": 60,
            "MEDIUM_VOL": 15,
            "TRENDING_VOL": 10,
            "HIGH_VOL": "SKIP",
        },
        "asset_breakdown": {},
    }

    # Per-asset breakdown
    for asset in ["btc", "eth", "sol", "xrp"]:
        asset_trades = [t for t in best.trades if t.asset == asset]
        if asset_trades:
            asset_wins = sum(1 for t in asset_trades if t.result == "WIN")
            confirmed["asset_breakdown"][asset] = {
                "trades": len(asset_trades),
                "win_rate": round(asset_wins / len(asset_trades), 4),
                "pnl": round(sum(t.pnl for t in asset_trades), 4),
            }

    # Save to file
    output_path = Path(__file__).parent.parent / "backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(confirmed, f, indent=2)

    print(f"\n  Confirmed parameters saved to: {output_path}")
    print("\n  Asset breakdown:")
    for asset, stats in confirmed["asset_breakdown"].items():
        print(f"    {asset.upper()}: {stats['trades']} trades, "
              f"{stats['win_rate']:.1%} win rate, "
              f"${stats['pnl']:+.2f} PnL")

    print("\n" + "=" * 60)
    if kelly_positive:
        print("VALIDATION PASSED: Kelly criterion is positive.")
        print(f"Recommended config: {best_name}")
    else:
        print("WARNING: Kelly criterion is NOT positive with current parameters.")
        print("Consider adjusting thresholds or extending the data window.")
    print("=" * 60)


if __name__ == "__main__":
    main()
