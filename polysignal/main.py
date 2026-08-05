"""
PolySignal Pro Main Entry Point

This is the main entry point for PolySignal Pro.
It initializes all components and runs the main loop.

IMPORTANT:
- Default mode: READ-ONLY + PAPER TRADING
- Live trading is DISABLED by default
- All signals must pass through Risk Governor
- Telegram is a monitoring/control panel, NOT a trading system
- Data mode: mock (default), real_readonly, or hybrid
"""

import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from polysignal.config import Config, config, DataMode
from polysignal.logging_config import setup_logging, get_logger, console
from polysignal.ingestion.mock_data_provider import MockDataProvider
from polysignal.ingestion.data_provider_manager import DataProviderManager
from polysignal.engines.market_microstructure import MarketMicrostructureEngine
from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy
from polysignal.strategies.base import StrategyContext
from polysignal.risk.risk_governor import RiskGovernor
from polysignal.execution.paper_trader import PaperTrader
from polysignal.execution.live_trader_stub import LiveTraderStub
from polysignal.storage.database import Database
from polysignal.models.risk import RiskContext, RiskAction
from polysignal.interface.cli import (
    print_header,
    print_config_summary,
    print_summary,
    print_error,
    print_success,
)
from polysignal.interface.telegram_client import TelegramClient


logger = get_logger("polysignal.main")


class PolySignalPro:
    """
    PolySignal Pro Main Application.

    Orchestrates all components:
    - Data Provider Manager (mock / real_readonly / hybrid)
    - Market Microstructure Engine
    - Strategies
    - Risk Governor
    - Paper Trader
    - Telegram Signal Cockpit
    - Storage
    """

    def __init__(self, config: Config):
        """Initialize PolySignal Pro"""
        self.config = config

        # Get data mode from config
        data_mode = config.get_data_mode()
        api_config = config.get_api_config()

        # Initialize data provider manager
        self.data_provider = DataProviderManager(
            mode=data_mode,
            gamma_base_url=api_config.gamma_base_url,
            clob_base_url=api_config.clob_base_url,
            timeout_seconds=api_config.timeout_seconds,
            max_retries=api_config.max_retries,
            mock_provider=MockDataProvider(
                num_markets=config.markets.mock.num_markets,
                price_range=tuple(config.markets.mock.price_range),
                volume_range_usd=tuple(config.markets.mock.volume_range_usd),
                seed=42,  # Reproducible for testing
            ),
        )

        self.microstructure_engine = MarketMicrostructureEngine()

        self.strategy = YesNoMispricingStrategy(
            combined_ask_threshold=config.risk.scoring_weights.microstructure * 3.3,  # ~0.99
        )

        self.risk_governor = RiskGovernor(
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

        self.paper_trader = PaperTrader(
            default_order_size_usd=config.risk.default_order_size_usd,
            slippage_assumption_pct=config.risk.slippage_assumption_pct,
            order_timeout_seconds=config.risk.order_timeout_seconds,
        )

        self.live_trader = LiveTraderStub(
            live_trading_enabled=config.risk.live_trading_enabled
        )

        self.database = Database(db_path=config.env.database_path)

        # Telegram client (lazy loading, graceful fallback)
        self.telegram_client = TelegramClient()

        # State
        self._running = False
        self._signals: list[Any] = []
        self._orders: list[Any] = []
        self._positions: list[Any] = []

    async def start(self) -> None:
        """Start PolySignal Pro"""
        logger.info("Starting PolySignal Pro...")

        # Connect to database
        await self.database.connect()
        logger.info("Database connected")

        # Log configuration
        config_summary = self.config.get_summary()
        data_mode = self.config.get_data_mode()
        logger.info(
            "Configuration loaded",
            data_mode=data_mode.value,
            **config_summary,
        )

        self._running = True
        logger.info("PolySignal Pro started")

    async def stop(self) -> None:
        """Stop PolySignal Pro"""
        logger.info("Stopping PolySignal Pro...")
        self._running = False
        await self.database.close()
        await self.data_provider.close()
        logger.info("PolySignal Pro stopped")

    async def run_cycle(self) -> dict[str, Any]:
        """
        Run one analysis cycle.

        This is the main processing loop:
        1. Get markets
        2. Get orderbooks
        3. Analyze with microstructure engine
        4. Generate signals with strategy
        5. Evaluate with Risk Governor
        6. Process signal based on decision (auto paper trade if allowed)
        7. Send Telegram notifications
        8. Store results
        """
        cycle_start = datetime.utcnow()
        cycle_results = {
            "markets_checked": 0,
            "signals_generated": 0,
            "signals_ignored": 0,
            "signals_rejected": 0,
            "paper_trades": 0,
            "telegram_alerts": 0,
            "errors": [],
        }

        # Check if signals are paused
        if self.telegram_client.are_signals_paused():
            logger.info("Signal generation paused, skipping cycle")
            return cycle_results

        try:
            # Step 1: Get markets (async for real API support)
            markets = await self.data_provider.get_markets()
            cycle_results["markets_checked"] = markets.total_count

            # Step 2-6: Process each market
            for market in markets.markets:
                try:
                    # Skip non-tradable markets
                    if not market.is_tradable():
                        continue

                    # Get orderbook (async for real API support)
                    orderbook = await self.data_provider.get_orderbook(market.market_id)

                    if orderbook is None:
                        continue

                    # Analyze with microstructure engine
                    micro_result = self.microstructure_engine.analyze_snapshot(orderbook)

                    # Get component scores
                    component_scores = self.microstructure_engine.get_component_scores(orderbook)

                    # Create strategy context
                    context = StrategyContext(
                        market=market,
                        orderbook=orderbook,
                        component_scores=component_scores,
                    )

                    # Generate signal
                    signal = self.strategy.compute_signal(context)

                    if signal is None:
                        continue

                    cycle_results["signals_generated"] += 1

                    # Create risk context
                    risk_context = RiskContext(
                        live_trading_enabled=self.config.risk.live_trading_enabled,
                        allow_auto_execution=self.config.risk.allow_auto_execution,
                        api_healthy=True,
                        websocket_healthy=True,
                        market_tradable=market.is_tradable(),
                        market_ambiguous=market.is_ambiguous,
                        market_forbidden=not market.is_auto_allowed(),
                    )

                    # Evaluate with Risk Governor
                    risk_decision = self.risk_governor.evaluate(
                        signal=signal,
                        context=risk_context,
                        orderbook=orderbook,
                        market=market,
                    )

                    # Store signal and decision
                    await self.database.save_signal(signal)
                    await self.database.save_risk_decision(risk_decision)

                    self._signals.append(signal)

                    # Process signal based on Risk Governor decision
                    await self._process_signal(
                        signal=signal,
                        decision=risk_decision,
                        orderbook=orderbook,
                        market=market,
                        cycle_results=cycle_results,
                    )

                except Exception as e:
                    cycle_results["errors"].append(str(e))
                    logger.error(f"Error processing market {market.market_id}: {e}")

        except Exception as e:
            cycle_results["errors"].append(str(e))
            logger.error(f"Cycle error: {e}")

        # Log cycle summary
        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
        logger.info(
            "Cycle completed",
            duration_seconds=cycle_duration,
            **cycle_results,
        )

        return cycle_results

    async def _process_signal(
        self,
        signal: Any,
        decision: Any,
        orderbook: Any,
        market: Any,
        cycle_results: dict[str, Any],
    ) -> None:
        """
        Process signal based on Risk Governor decision.

        This implements the automatic signal processing:
        - IGNORE: Record minimal audit log, no Telegram
        - LOG_ONLY: Record to SQLite/log
        - ALERT: Send Telegram alert
        - PAPER_TRADE: Auto-execute paper trade + send Telegram notification
        - MANUAL_REVIEW: Send Telegram review request
        - HARD_REJECT: Send Telegram notification (high score or system error only)
        """
        action = decision.action

        # IGNORE: Record minimal audit log, no Telegram
        if action == RiskAction.IGNORE:
            cycle_results["signals_ignored"] += 1
            logger.debug(
                "Signal ignored",
                signal_id=signal.signal_id,
                trade_score=decision.trade_score,
            )
            return

        # HARD_REJECT: Check if should send Telegram
        if action == RiskAction.HARD_REJECT:
            cycle_results["signals_rejected"] += 1
            logger.warning(
                "Signal hard rejected",
                signal_id=signal.signal_id,
                reasons=decision.hard_reject_reasons,
            )

            # Only send Telegram for high-score rejects or system errors
            should_notify = self._should_notify_hard_reject(decision)
            if should_notify and not self.telegram_client.are_alerts_paused():
                await self.telegram_client.send_reject_notification(signal, decision)
                cycle_results["telegram_alerts"] += 1
            return

        # LOG_ONLY: Record to SQLite, no Telegram
        if action == RiskAction.LOG_ONLY:
            logger.info(
                "Signal logged only",
                signal_id=signal.signal_id,
                trade_score=decision.trade_score,
            )
            return

        # ALERT: Send Telegram alert
        if action == RiskAction.ALERT:
            if not self.telegram_client.are_alerts_paused():
                await self.telegram_client.send_alert(signal, decision)
                cycle_results["telegram_alerts"] += 1
            logger.info(
                "Signal alert sent",
                signal_id=signal.signal_id,
                trade_score=decision.trade_score,
            )
            return

        # PAPER_TRADE: Auto-execute paper trade + send Telegram notification
        if action == RiskAction.PAPER_TRADE:
            # Execute paper trade automatically
            order, position, message = self.paper_trader.execute(
                signal=signal,
                risk_decision=decision,
                orderbook=orderbook,
            )

            if order:
                cycle_results["paper_trades"] += 1
                await self.database.save_paper_order(order)
                self._orders.append(order)

                if position:
                    await self.database.save_paper_position(position)
                    self._positions.append(position)

                logger.info(
                    "Paper trade executed",
                    order_id=order.order_id,
                    market=market.title[:30],
                    size=order.filled_size,
                    price=order.filled_price,
                )

            # Send Telegram notification (even if order failed)
            if not self.telegram_client.are_alerts_paused():
                await self.telegram_client.send_paper_trade_notification(
                    signal, decision, order
                )
                cycle_results["telegram_alerts"] += 1
            return

        # MANUAL_REVIEW: Send Telegram review request
        if action == RiskAction.MANUAL_REVIEW:
            if not self.telegram_client.are_alerts_paused():
                await self.telegram_client.send_review_request(signal, decision)
                cycle_results["telegram_alerts"] += 1
            logger.info(
                "Signal marked for manual review",
                signal_id=signal.signal_id,
                trade_score=decision.trade_score,
            )
            return

    def _should_notify_hard_reject(self, decision: Any) -> bool:
        """
        Determine if hard reject should send Telegram notification.

        Notify if:
        - High score (>= 80) but hard rejected
        - System error (api_unhealthy, websocket_unhealthy, circuit_breaker)
        """
        # High score hard reject
        if decision.trade_score >= 80:
            return True

        # System error hard reject
        system_error_reasons = {
            "api_unhealthy",
            "websocket_unhealthy",
            "circuit_breaker",
            "price_stale",
        }
        for reason in decision.hard_reject_reasons:
            if reason in system_error_reasons:
                return True

        return False

    async def run(self, interval_seconds: int = 10, max_cycles: Optional[int] = None) -> None:
        """
        Run main loop.

        Args:
            interval_seconds: Interval between cycles
            max_cycles: Maximum number of cycles (None for infinite)
        """
        await self.start()

        cycle_count = 0

        try:
            while self._running:
                cycle_count += 1

                # Run cycle
                results = await self.run_cycle()

                # Print summary
                if cycle_count % 5 == 0:  # Every 5 cycles
                    await self.print_summary()

                # Check max cycles
                if max_cycles and cycle_count >= max_cycles:
                    break

                # Wait for next cycle
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        finally:
            await self.stop()

    async def print_summary(self) -> None:
        """Print current summary"""
        health = await self.database.get_health_status()
        signals = await self.database.get_recent_signals(limit=10)
        orders = await self.database.get_recent_orders(limit=10)
        positions = await self.database.get_all_positions()
        stats = self.paper_trader.get_stats()

        print_summary(
            health=health,
            signals=signals,
            orders=orders,
            positions=positions,
            stats=stats,
        )


def main() -> None:
    """Main entry point"""
    # Setup logging
    setup_logging(
        level=config.env.log_level,
        log_file=config.env.log_file,
        use_rich=True,
    )

    logger.info("PolySignal Pro initializing...")

    # Print header
    print_header()
    print_config_summary(config.get_summary())

    # Safety checks
    if config.is_live_trading_enabled():
        print_error("LIVE TRADING IS ENABLED! This should not happen in MVP.")
        sys.exit(1)

    print_success("Running in READ-ONLY + PAPER TRADING mode")

    # Show Telegram status
    telegram_client = TelegramClient()
    if telegram_client.enabled:
        print_success("Telegram Signal Cockpit enabled")
    else:
        print_success("Telegram not configured, using CLI/log mode")

    # Create application
    app = PolySignalPro(config)

    # Setup signal handlers
    def handle_shutdown(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        app._running = False

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Run
    try:
        asyncio.run(app.run(interval_seconds=10, max_cycles=None))
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        print_success("PolySignal Pro exited cleanly")


if __name__ == "__main__":
    main()
