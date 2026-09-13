#!/usr/bin/env python3
"""
Paper Trading Runner - Phase 5A Dry Run

IMPORTANT: This script is for PAPER TRADING ONLY.
- live_trading_enabled must be false
- allow_auto_execution must be false
- No real orders are placed
- No private keys are used

Usage:
    # 30-minute dry run (default)
    python3 scripts/run_paper.py

    # 3-hour run
    python3 scripts/run_paper.py --duration_hours 3

    # 24-hour run
    python3 scripts/run_paper.py --duration_hours 24

    # With real LLM (requires explicit limit)
    python3 scripts/run_paper.py --llm_provider xfyun_anthropic --max_llm_calls_per_hour 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.config import Config

# Engines
# Paper Trader
# Data providers
# WebSocket
# Risk
# Decomposed domains (Iteration 007/010): watchlist / llm-sampling /
# control-group / alpha-repeat / run-state moved verbatim to
# polysignal/runner/. Names are re-exported here and the runner inherits
# the mixins, so every existing import and call site is unchanged.
# PaperTradingRunner moved verbatim to polysignal/runner/paper_runner.py (D6 step 3)
from polysignal.runner.paper_runner import PaperTradingRunner  # noqa: F401
from polysignal.runner.run_state import (  # noqa: F401
    RunConfig,
    RunStatistics,
)
from polysignal.runner.watchlist import (  # noqa: F401
    AlphaCandidate,
    AvoidAnnotator,
    AvoidCandidate,
    MarketPrioritizer,
    MarketTrajectory,
    TrajectoryObservation,
    TrajectoryTracker,
    WatchlistEntry,
    WatchlistLoader,
    WatchlistMonitoringStats,
)

# Strategy


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Paper Trading Runner for PolySignal Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 30-minute dry run (default)
    python3 scripts/run_paper.py

    # 3-hour run
    python3 scripts/run_paper.py --duration_hours 3

    # 24-hour run
    python3 scripts/run_paper.py --duration_hours 24

    # With real LLM (requires explicit limit)
    python3 scripts/run_paper.py --llm_provider xfyun_anthropic --max_llm_calls_per_hour 10
        """,
    )

    # Duration
    duration_group = parser.add_mutually_exclusive_group()
    duration_group.add_argument(
        "--duration_minutes",
        type=int,
        default=30,
        help="Duration in minutes (default: 30)",
    )
    duration_group.add_argument(
        "--duration_hours",
        type=float,
        help="Duration in hours",
    )

    # Market scanning
    parser.add_argument(
        "--max_markets",
        type=int,
        default=10,
        help="Maximum markets to monitor (default: 10)",
    )
    parser.add_argument(
        "--scan_interval_seconds",
        type=int,
        default=120,
        help="Scan interval in seconds (default: 120)",
    )

    # Data mode
    parser.add_argument(
        "--data_mode",
        type=str,
        choices=["mock", "real_readonly", "hybrid"],
        default="hybrid",
        help="Data mode (default: hybrid)",
    )
    parser.add_argument(
        "--use_websocket",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=True,
        help="Use WebSocket for real-time data (default: true)",
    )

    # LLM
    parser.add_argument(
        "--llm_provider",
        type=str,
        default="mock",
        help="LLM provider (default: mock)",
    )
    parser.add_argument(
        "--max_llm_calls_per_hour",
        type=int,
        default=0,
        help="Maximum LLM calls per hour (required if llm_provider != mock)",
    )

    # Signals
    parser.add_argument(
        "--max_signals_per_hour",
        type=int,
        default=20,
        help="Maximum signals per hour (default: 20)",
    )

    # Telegram
    parser.add_argument(
        "--telegram_enabled",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=False,
        help="Enable Telegram alerts (default: false)",
    )
    parser.add_argument(
        "--max_telegram_messages_per_hour",
        type=int,
        default=0,
        help="Maximum Telegram messages per hour (default: 0)",
    )

    # LLM Sampling Mode (research/intelligence only, no trading)
    parser.add_argument(
        "--enable_llm_sampling",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=False,
        help="Enable LLM sampling mode for research/intelligence logging (default: false)",
    )
    parser.add_argument(
        "--llm_sampling_per_scan",
        type=int,
        default=1,
        help="Number of markets to sample with LLM per scan (default: 1)",
    )
    parser.add_argument(
        "--llm_sampling_min_volume",
        type=float,
        default=10000.0,
        help="Minimum 24h volume for LLM sampling candidates (default: 10000.0)",
    )
    parser.add_argument(
        "--llm_sampling_strategy",
        type=str,
        choices=["top_liquidity", "top_liquidity_or_near_miss", "random", "diversified"],
        default="top_liquidity_or_near_miss",
        help="Strategy for selecting LLM sampling candidates (default: top_liquidity_or_near_miss)",
    )
    parser.add_argument(
        "--llm_sampling_cooldown_minutes",
        type=int,
        default=60,
        help="Cooldown minutes before re-sampling same market (default: 60)",
    )
    parser.add_argument(
        "--llm_sampling_max_repeats_per_market",
        type=int,
        default=1,
        help="Maximum times to sample same market per run (default: 1)",
    )

    # Watchlist-Driven Monitoring (Phase 5F.5)
    # IMPORTANT: These are for RESEARCH/MONITORING only - do NOT affect trading
    parser.add_argument(
        "--watchlist_file",
        type=str,
        default=None,
        help="Path to persistent_watchlist.csv (Phase 5F.5)",
    )
    parser.add_argument(
        "--alpha_candidates_file",
        type=str,
        default=None,
        help="Path to alpha_candidates.csv (Phase 5F.5)",
    )
    parser.add_argument(
        "--avoid_candidates_file",
        type=str,
        default=None,
        help="Path to avoid_candidates.csv (Phase 5F.5)",
    )
    parser.add_argument(
        "--trajectories_file",
        type=str,
        default=None,
        help="Path to market_trajectories.json (Phase 5F.5)",
    )
    parser.add_argument(
        "--monitor_mode",
        type=str,
        choices=["default", "hybrid", "watchlist"],
        default="default",
        help="Monitor mode: default (no watchlist), hybrid (watchlist + discovery), watchlist (watchlist only with discovery) (default: default)",
    )
    parser.add_argument(
        "--watchlist_priority_ratio",
        type=float,
        default=0.6,
        help="Ratio of watchlist markets in hybrid mode (default: 0.6)",
    )
    parser.add_argument(
        "--discovery_ratio",
        type=float,
        default=0.2,
        help="Minimum ratio for new market discovery (default: 0.2, min: 0.1)",
    )
    parser.add_argument(
        "--track_trajectory",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=True,
        help="Track trajectory changes for watchlist markets (default: true)",
    )

    # Phase 6.5A — Control Group Sampling
    parser.add_argument(
        "--control_group_sampling_ratio",
        type=float,
        default=0.0,
        help="Ratio of markets for control group sampling (0.0-0.5, default: 0.0)",
    )
    parser.add_argument(
        "--exclude_avoid_from_control_group",
        action="store_true",
        default=False,
        help="Exclude avoid candidates from control group (default: false)",
    )

    # Phase 6.5B — Alpha Repeated Observation
    parser.add_argument(
        "--alpha_priority_ratio",
        type=float,
        default=0.0,
        help="Ratio of scan slots reserved for alpha candidates (0.0-0.8, default: 0.0)",
    )
    parser.add_argument(
        "--alpha_repeat_target",
        type=int,
        default=3,
        help="Target observations per alpha candidate before deprioritizing (default: 3)",
    )

    return parser.parse_args()


async def main() -> None:
    """Main entry point"""
    # Load .env file if available (only when running as script)
    from dotenv import load_dotenv
    load_dotenv()

    args = parse_args()

    # Create run config
    run_config = RunConfig(
        duration_minutes=args.duration_minutes if not args.duration_hours else int(args.duration_hours * 60),
        duration_hours=args.duration_hours if args.duration_hours else args.duration_minutes / 60,
        max_markets=args.max_markets,
        scan_interval_seconds=args.scan_interval_seconds,
        data_mode=args.data_mode,
        use_websocket=args.use_websocket,
        llm_provider=args.llm_provider,
        max_llm_calls_per_hour=args.max_llm_calls_per_hour,
        max_signals_per_hour=args.max_signals_per_hour,
        telegram_enabled=args.telegram_enabled,
        max_telegram_messages_per_hour=args.max_telegram_messages_per_hour,
        enable_llm_sampling=args.enable_llm_sampling,
        llm_sampling_per_scan=args.llm_sampling_per_scan,
        llm_sampling_min_volume=args.llm_sampling_min_volume,
        llm_sampling_strategy=args.llm_sampling_strategy,
        llm_sampling_cooldown_minutes=args.llm_sampling_cooldown_minutes,
        llm_sampling_max_repeats_per_market=args.llm_sampling_max_repeats_per_market,
        # Watchlist-Driven Monitoring (Phase 5F.5)
        watchlist_file=args.watchlist_file,
        alpha_candidates_file=args.alpha_candidates_file,
        avoid_candidates_file=args.avoid_candidates_file,
        trajectories_file=args.trajectories_file,
        monitor_mode=args.monitor_mode,
        watchlist_priority_ratio=args.watchlist_priority_ratio,
        discovery_ratio=args.discovery_ratio,
        track_trajectory=args.track_trajectory,
        # Phase 6.5A — Control Group Sampling
        control_group_sampling_ratio=args.control_group_sampling_ratio,
        exclude_avoid_from_control_group=args.exclude_avoid_from_control_group,
        # Phase 6.5B — Alpha Repeated Observation
        alpha_priority_ratio=args.alpha_priority_ratio,
        alpha_repeat_target=args.alpha_repeat_target,
    )

    # Load config
    config = Config()

    # Create runner
    runner = PaperTradingRunner(config, run_config)

    # Run
    result = await runner.run()

    # Print final summary
    print("\n\n" + "=" * 60)
    print("Run Complete")
    print("=" * 60)
    print(f"Run ID: {result.get('run_id', 'unknown')}")
    print(f"Status: {result.get('status', 'unknown')}")
    print(f"Markets Checked: {result.get('markets_checked', 0)}")
    print(f"Real Markets Fetched: {result.get('real_markets_fetched', 0)}")
    print(f"Orderbooks Fetched: {result.get('orderbooks_fetched', 0)}")
    print(f"Signals Generated: {result.get('signals_generated', 0)}")
    print(f"Paper Trades: {result.get('paper_trades_created', 0)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
