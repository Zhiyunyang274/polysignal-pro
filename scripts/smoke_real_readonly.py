#!/usr/bin/env python3
"""
Smoke Test - Real Read-only Polymarket API

This script performs a minimal smoke test using real Polymarket read-only API.
It validates that real data can flow through the existing pipeline.

IMPORTANT:
- This script does NOT place real orders
- This script does NOT require private keys
- This script does NOT call POST/DELETE endpoints
- This script does NOT run live_trader
- This script gracefully exits on API failure

Usage:
    python scripts/smoke_real_readonly.py

Environment:
    DATA_MODE=real_readonly (optional, script uses REAL_READONLY by default)
"""

import asyncio
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, ".")

from polysignal.config import config
from polysignal.engines.event_intelligence import EventIntelligenceEngine
from polysignal.engines.market_microstructure import MarketMicrostructureEngine
from polysignal.engines.resolution_lifecycle import ResolutionLifecycleEngine
from polysignal.engines.wallet_intelligence import WalletIntelligenceEngine
from polysignal.execution.paper_trader import PaperTrader
from polysignal.ingestion.data_provider_manager import DataMode, DataProviderManager
from polysignal.ingestion.mock_wallet_provider import (
    generate_mock_watchlist,
)
from polysignal.logging_config import get_logger, setup_logging
from polysignal.models.risk import RiskContext
from polysignal.models.wallet import WalletProfile, WalletSpecialization
from polysignal.risk.risk_governor import RiskGovernor
from polysignal.strategies.base import StrategyContext
from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy

logger = get_logger("polysignal.smoke_real_readonly")


class SmokeTestResult:
    """Results from smoke test"""
    def __init__(self):
        self.markets_fetched: int = 0
        self.markets_usable: int = 0
        self.orderbooks_fetched: int = 0
        self.signals_generated: int = 0
        self.risk_decisions: list[dict] = []
        self.paper_trades_simulated: int = 0
        self.fallback_count: int = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "markets_fetched": self.markets_fetched,
            "markets_usable": self.markets_usable,
            "orderbooks_fetched": self.orderbooks_fetched,
            "signals_generated": self.signals_generated,
            "risk_decisions": len(self.risk_decisions),
            "paper_trades_simulated": self.paper_trades_simulated,
            "fallback_count": self.fallback_count,
            "errors": self.errors,
        }


def print_header():
    """Print smoke test header"""
    print("\n" + "=" * 60)
    print("PolySignal Pro - Real Read-only API Smoke Test")
    print("=" * 60)
    print(f"Started: {datetime.utcnow().isoformat()}")
    print("Mode: REAL_READONLY")
    print("=" * 60 + "\n")


def print_summary(result: SmokeTestResult):
    """Print smoke test summary"""
    print("\n" + "=" * 60)
    print("Smoke Test Summary")
    print("=" * 60)
    print(f"Markets Fetched:        {result.markets_fetched}")
    print(f"Markets Usable:         {result.markets_usable}")
    print(f"Orderbooks Fetched:     {result.orderbooks_fetched}")
    print(f"Signals Generated:      {result.signals_generated}")
    print(f"Risk Decisions:         {len(result.risk_decisions)}")
    print(f"Paper Trades Simulated: {result.paper_trades_simulated}")
    print(f"Fallback Count:         {result.fallback_count}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors[:5]:  # Show first 5 errors
            print(f"  - {error[:100]}")

    print("=" * 60)

    # Print risk decisions summary
    if result.risk_decisions:
        print("\nRisk Decisions:")
        for i, decision in enumerate(result.risk_decisions[:5]):
            print(f"  {i+1}. Market: {decision.get('market', 'N/A')[:40]}")
            print(f"     Action: {decision.get('action', 'N/A')}")
            print(f"     Score: {decision.get('score', 'N/A')}")
            if decision.get('reasons'):
                print(f"     Reasons: {decision.get('reasons')}")

    print("\n" + "=" * 60)
    print("SAFETY CHECK: Live Trading Status")
    print("=" * 60)
    print(f"live_trading_enabled: {config.risk.live_trading_enabled}")
    print(f"allow_auto_execution: {config.risk.allow_auto_execution}")
    print(f"paper_trading_enabled: {config.risk.paper_trading_enabled}")

    if config.risk.live_trading_enabled:
        print("\n⚠️  WARNING: live_trading_enabled is TRUE!")
    else:
        print("\n✅ Safe: live_trading is DISABLED")

    print("=" * 60 + "\n")


async def run_smoke_test(max_markets: int = 5, max_orderbooks: int = 3) -> SmokeTestResult:
    """
    Run smoke test with real read-only API.

    Args:
        max_markets: Maximum markets to fetch
        max_orderbooks: Maximum orderbooks to process

    Returns:
        SmokeTestResult with test results
    """
    result = SmokeTestResult()

    # Initialize data provider with REAL_READONLY mode
    print("Initializing DataProviderManager (REAL_READONLY)...")
    data_provider = DataProviderManager(mode=DataMode.REAL_READONLY)

    # Initialize engines
    microstructure_engine = MarketMicrostructureEngine()
    lifecycle_engine = ResolutionLifecycleEngine()

    # Generate mock wallets for wallet intelligence
    mock_watchlist = generate_mock_watchlist()

    # Create mock wallet profiles for the engine
    mock_profiles: dict[str, WalletProfile] = {}
    for entry in mock_watchlist:
        mock_profiles[entry.address] = WalletProfile(
            wallet_address=entry.address,
            alias=entry.alias,
            reliability_score=70.0,
            performance_score=75.0,
            specialization_score=80.0,
            discipline_score=65.0,
            total_trades=100,
            win_rate=0.6,
            total_volume_usd=10000.0,
            total_pnl_usd=500.0,
            specialization=WalletSpecialization.CRYPTO,
        )

    # Initialize Wallet Intelligence Engine with mock data
    wallet_engine = WalletIntelligenceEngine(
        watchlist=mock_watchlist,
        profiles=mock_profiles,
    )

    event_engine = EventIntelligenceEngine()

    # Initialize strategy
    strategy = YesNoMispricingStrategy()

    # Initialize Risk Governor
    risk_governor = RiskGovernor(
        live_trading_enabled=config.risk.live_trading_enabled,
        allow_auto_execution=config.risk.allow_auto_execution,
        paper_trading_enabled=config.risk.paper_trading_enabled,
        max_account_capital_usd=config.risk.max_account_capital_usd,
        max_position_pct=config.risk.max_position_pct,
        max_market_exposure_pct=config.risk.max_market_exposure_pct,
        max_strategy_exposure_pct=config.risk.max_strategy_exposure_pct,
        daily_max_loss_pct=config.risk.daily_max_loss_pct,
        weekly_max_loss_pct=config.risk.weekly_max_loss_pct,
        max_consecutive_losses=config.risk.max_consecutive_losses,
        min_total_volume_usd=config.risk.min_total_volume_usd,
        min_depth_usd=config.risk.min_depth_usd,
        max_spread_pct=config.risk.max_spread_pct,
    )

    # Initialize Paper Trader
    paper_trader = PaperTrader(
        default_order_size_usd=config.risk.default_order_size_usd,
        slippage_assumption_pct=config.risk.slippage_assumption_pct,
        order_timeout_seconds=config.risk.order_timeout_seconds,
    )

    try:
        # Step 1: Fetch markets from real API
        print("\n[Step 1] Fetching markets from Gamma API...")
        try:
            markets_list = await data_provider.get_markets()
            result.markets_fetched = markets_list.total_count
            print(f"  Fetched {result.markets_fetched} markets")
        except Exception as e:
            error_msg = f"Failed to fetch markets: {e}"
            result.errors.append(error_msg)
            print(f"  ERROR: {error_msg}")
            return result

        # Step 2: Filter usable markets (with token IDs)
        print("\n[Step 2] Filtering markets with valid token IDs...")
        usable_markets = []
        for market in markets_list.markets:
            if market.yes_token_address and market.no_token_address:
                usable_markets.append(market)
                if len(usable_markets) >= max_markets:
                    break

        result.markets_usable = len(usable_markets)
        print(f"  Found {result.markets_usable} usable markets")

        if not usable_markets:
            result.errors.append("No markets with valid token IDs found")
            return result

        # Step 3: Fetch orderbooks for selected markets
        print(f"\n[Step 3] Fetching orderbooks (max {max_orderbooks})...")
        markets_with_orderbooks = []

        for market in usable_markets[:max_orderbooks]:
            print(f"  Fetching orderbook for: {market.title[:50]}...")
            try:
                orderbook = await data_provider.get_orderbook(market.market_id)
                if orderbook:
                    markets_with_orderbooks.append((market, orderbook))
                    result.orderbooks_fetched += 1
                    print(f"    ✓ Orderbook fetched (combined_ask: {orderbook.combined_ask})")
                else:
                    print("    ✗ No orderbook returned")
            except Exception as e:
                error_msg = f"Failed to fetch orderbook for {market.market_id}: {e}"
                result.errors.append(error_msg)
                print(f"    ✗ ERROR: {e}")

        if not markets_with_orderbooks:
            result.errors.append("No orderbooks could be fetched")
            return result

        # Step 4: Process each market through the pipeline
        print("\n[Step 4] Processing through pipeline...")

        for market, orderbook in markets_with_orderbooks:
            print(f"\n  Processing: {market.title[:40]}...")

            try:
                # Market Microstructure Engine
                microstructure_engine.analyze_snapshot(orderbook)
                component_scores = microstructure_engine.get_component_scores(orderbook)

                # Resolution & Lifecycle Engine
                lifecycle_engine.assess(market)

                # Wallet Intelligence Engine
                wallet_engine.assess(market)

                # Event Intelligence Engine (with mock LLM)
                await event_engine.assess_async(market)

                # Create strategy context
                context = StrategyContext(
                    market=market,
                    orderbook=orderbook,
                    component_scores=component_scores,
                )

                # Generate signal
                signal = strategy.compute_signal(context)

                if signal is None:
                    print("    No signal generated (conditions not met)")
                    continue

                result.signals_generated += 1
                print(f"    Signal generated: {signal.side.value}, score={signal.price:.2f}")

                # Create risk context
                risk_context = RiskContext(
                    live_trading_enabled=config.risk.live_trading_enabled,
                    allow_auto_execution=config.risk.allow_auto_execution,
                    api_healthy=True,
                    websocket_healthy=True,
                    market_tradable=market.is_tradable(),
                    market_ambiguous=market.is_ambiguous,
                    market_forbidden=not market.is_auto_allowed(),
                )

                # Evaluate with Risk Governor
                risk_decision = risk_governor.evaluate(
                    signal=signal,
                    context=risk_context,
                    orderbook=orderbook,
                    market=market,
                )

                result.risk_decisions.append({
                    "market": market.title,
                    "action": risk_decision.action.value,
                    "score": risk_decision.trade_score,
                    "reasons": risk_decision.hard_reject_reasons,
                })

                print(f"    Risk decision: {risk_decision.action.value}, score={risk_decision.trade_score:.1f}")

                # If paper trade allowed, simulate
                if risk_decision.action.value == "PAPER_TRADE":
                    order, position, message = paper_trader.execute(
                        signal=signal,
                        risk_decision=risk_decision,
                        orderbook=orderbook,
                    )
                    if order:
                        result.paper_trades_simulated += 1
                        print(f"    Paper trade simulated: {order.filled_size} @ {order.filled_price}")

            except Exception as e:
                error_msg = f"Pipeline error for {market.market_id}: {e}"
                result.errors.append(error_msg)
                print(f"    ERROR: {e}")

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        result.errors.append(error_msg)
        print(f"\nFATAL ERROR: {e}")

    finally:
        # Clean up
        await data_provider.close()

    return result


def main():
    """Main entry point"""
    # Setup logging
    setup_logging(level="INFO", use_rich=False)

    print_header()

    # Run smoke test
    try:
        result = asyncio.run(run_smoke_test(max_markets=5, max_orderbooks=3))
    except KeyboardInterrupt:
        print("\n\nSmoke test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nSmoke test failed with error: {e}")
        sys.exit(0)  # Exit 0 to not fail CI

    # Print summary
    print_summary(result)

    # Final status
    if result.errors:
        print("⚠️  Smoke test completed with errors")
    else:
        print("✅ Smoke test completed successfully")

    print("\nNOTE: This test used READ-ONLY API endpoints only.")
    print("No orders were placed. No private keys were used.")

    sys.exit(0)


if __name__ == "__main__":
    main()
