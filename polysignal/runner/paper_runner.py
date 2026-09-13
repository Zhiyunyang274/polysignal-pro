"""Paper Trading Runner — verbatim extraction (Iteration 019, D6 step 3).

The class body is unchanged; scripts/run_paper.py re-exports it so all
existing imports and call sites keep working.
"""

from __future__ import annotations

import asyncio
import json
import signal
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

# Add project root to path
from polysignal.config import Config
from polysignal.engines.event_intelligence import EventIntelligenceEngine

# Engines
from polysignal.engines.market_microstructure import MarketMicrostructureEngine
from polysignal.engines.resolution_lifecycle import ResolutionLifecycleEngine
from polysignal.engines.wallet_intelligence import WalletIntelligenceEngine

# Paper Trader
from polysignal.execution.paper_trader import PaperTrader

# Data providers
from polysignal.ingestion.data_provider_manager import DataMode, DataProviderManager
from polysignal.ingestion.orderbook_cache import OrderBookCacheManager
from polysignal.ingestion.subscription_manager import SubscriptionManager

# WebSocket
from polysignal.ingestion.websocket_client import CLOBWebSocketClient, WebSocketConfig
from polysignal.ingestion.websocket_message_handler import WSMessage
from polysignal.llm.base import LLMProvider
from polysignal.models.market import Market
from polysignal.models.orderbook import OrderBookSnapshot

# Risk
from polysignal.risk.risk_governor import RiskGovernor

# Decomposed domains (Iteration 007/010): watchlist / llm-sampling /
# control-group / alpha-repeat / run-state moved verbatim to
# polysignal/runner/. Names are re-exported here and the runner inherits
# the mixins, so every existing import and call site is unchanged.
from polysignal.runner.alpha_repeat import AlphaRepeatMixin
from polysignal.runner.control_group import ControlGroupMixin
from polysignal.runner.llm_sampling import LLMSamplingMixin
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
from polysignal.storage.database import Database

# Strategy
from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy
from polysignal.utils.time import utc_now


class PaperTradingRunner(LLMSamplingMixin, ControlGroupMixin, AlphaRepeatMixin):
    """
    Paper Trading Runner for Phase 5A.

    IMPORTANT:
    - This is for PAPER TRADING ONLY
    - live_trading_enabled must be false
    - No real orders are placed
    - No private keys are used
    """

    def __init__(self, config: Config, run_config: RunConfig):
        """
        Initialize paper trading runner.

        Args:
            config: Application configuration
            run_config: Run-specific configuration
        """
        self.config = config
        self.run_config = run_config
        # Init-later contract (asserted by tests): these stay None until
        # _initialize_run sets them; consumers guard accordingly.
        self.stats: RunStatistics | None = None  # type: ignore[assignment]
        self.db: Database | None = None
        self.run_dir: Path | None = None
        self.events_file: Any | None = None
        self._shutdown_requested = False
        self._scan_count = 0

        # Data provider
        self.data_provider: DataProviderManager = DataProviderManager()

        # WebSocket components
        self.ws_client: CLOBWebSocketClient | None = None
        self.ws_cache_manager: OrderBookCacheManager | None = None  # type: ignore[assignment]
        self.ws_subscription_manager: SubscriptionManager | None = None
        self._ws_message_count: int = 0
        self._ws_connected: bool = False

        # Engines
        self.microstructure_engine: MarketMicrostructureEngine | None = None
        self.lifecycle_engine: ResolutionLifecycleEngine | None = None
        self.wallet_engine: WalletIntelligenceEngine | None = None
        self.event_engine: EventIntelligenceEngine | None = None

        # Strategy
        self.strategy: YesNoMispricingStrategy = YesNoMispricingStrategy()

        # Risk Governor
        self.risk_governor: RiskGovernor | None = None

        # Paper Trader
        self.paper_trader: PaperTrader | None = None

        # Watchlist-Driven Monitoring (Phase 5F.5)
        # These are for RESEARCH/MONITORING only - do NOT affect trading
        self.watchlist_loader: WatchlistLoader | None = None
        self.market_prioritizer: MarketPrioritizer | None = None
        self.avoid_annotator: AvoidAnnotator | None = None
        self.trajectory_tracker: TrajectoryTracker | None = None
        self.watchlist_stats: WatchlistMonitoringStats | None = None
        self._watchlist_events_file: Any | None = None

        # Phase 6.5A — Control group tracking (RESEARCH only)
        self._control_group_ids: set[str] = set()
        self._control_group_samples: list[dict[str, Any]] = []
        self._avoid_ids: set[str] = set()
        self._alpha_ids: set[str] = set()
        self._watchlist_ids: set[str] = set()

        # Phase 6.5B — Alpha repeat observation tracking (RESEARCH only)
        self._alpha_observation_counts: dict[str, int] = {}  # market_id -> observation count

    async def run(self) -> dict[str, Any]:
        """
        Run paper trading.

        Returns:
            Run statistics
        """
        # Safety checks
        if not self._safety_checks():
            return {"error": "Safety checks failed", "status": "rejected"}

        # Initialize run
        run_id = self._generate_run_id()
        self.stats = RunStatistics(
            run_id=run_id,
            start_time=utc_now(),
            data_mode=self.run_config.data_mode,
            llm_provider=self.run_config.llm_provider,
            websocket_enabled=self.run_config.use_websocket,
            telegram_enabled=self.run_config.telegram_enabled,
            max_markets=self.run_config.max_markets,
            scan_interval_seconds=self.run_config.scan_interval_seconds,
            max_llm_calls_per_hour=self.run_config.max_llm_calls_per_hour,
            max_signals_per_hour=self.run_config.max_signals_per_hour,
            max_telegram_messages_per_hour=self.run_config.max_telegram_messages_per_hour,
        )
        self.stats.duration_minutes = self.run_config.duration_minutes
        self.stats.duration_hours = self.run_config.duration_hours
        self.stats.hour_start = utc_now()
        self.stats.llm_sampling_enabled = self.run_config.enable_llm_sampling
        self.stats.llm_sampling_strategy = self.run_config.llm_sampling_strategy
        self.stats.llm_sampling_cooldown_minutes = self.run_config.llm_sampling_cooldown_minutes

        # Create run directory
        self.run_dir = Path("runs") / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Open events file
        self.events_file = open(self.run_dir / "events.jsonl", "w")  # noqa: SIM115 (long-lived run log, flushed per event)

        # Open watchlist events file (Phase 5F.5)
        if self.run_config.monitor_mode != "default" and (
            self.run_config.watchlist_file or self.run_config.alpha_candidates_file
        ):
            self._watchlist_events_file = open(self.run_dir / "watchlist_events.jsonl", "w")  # noqa: SIM115 (long-lived run log, flushed per event)

        # Connect to database
        self.db = Database()
        await self.db.connect()

        # Initialize components
        await self._initialize_components()

        # Save run to database
        await self._save_run_start()

        # Log start
        self._log_event("run_start", "system", f"Paper trading run started: {run_id}")
        self._print_header()

        # Setup signal handlers
        self._setup_signal_handlers()

        try:
            # Run main loop
            await self._run_loop()

        except Exception as e:
            self._log_event("run_error", "error", f"Run error: {e}")
            self.stats.errors.append({
                "time": utc_now().isoformat(),
                "type": "run_error",
                "message": str(e),
            })

        finally:
            # Cleanup
            await self._cleanup()

        return self.stats.to_dict()

    def _safety_checks(self) -> bool:
        """Perform safety checks before starting"""
        print("\n=== Safety Checks ===")

        # Check live_trading_enabled
        if self.config.env.live_trading_enabled:
            print("❌ FAILED: live_trading_enabled must be false")
            return False
        print("✓ live_trading_enabled: false")

        # Check allow_auto_execution
        if self.config.env.allow_auto_execution:
            print("❌ FAILED: allow_auto_execution must be false")
            return False
        print("✓ allow_auto_execution: false")

        # Check paper_trading_enabled
        if not self.config.env.paper_trading_enabled:
            print("❌ FAILED: paper_trading_enabled must be true")
            return False
        print("✓ paper_trading_enabled: true")

        # Check LLM provider limits
        if self.run_config.llm_provider != "mock":
            if self.run_config.max_llm_calls_per_hour <= 0:
                print(f"❌ FAILED: Real LLM provider '{self.run_config.llm_provider}' requires --max_llm_calls_per_hour > 0")
                return False
            print(f"✓ LLM provider: {self.run_config.llm_provider} (max {self.run_config.max_llm_calls_per_hour} calls/hour)")
        else:
            print("✓ LLM provider: mock (no real API calls)")

        # Check Telegram
        if self.run_config.telegram_enabled:
            print(f"✓ Telegram enabled (max {self.run_config.max_telegram_messages_per_hour} messages/hour)")
        else:
            print("✓ Telegram: disabled")

        # Check LLM Sampling Mode
        if self.run_config.enable_llm_sampling:
            if self.run_config.llm_provider == "mock":
                print("❌ FAILED: LLM sampling requires real LLM provider (not mock)")
                return False
            if self.run_config.max_llm_calls_per_hour <= 0:
                print("❌ FAILED: LLM sampling requires --max_llm_calls_per_hour > 0")
                return False
            print(f"✓ LLM Sampling: enabled (max {self.run_config.max_llm_calls_per_hour} calls/hour)")
            print("  ⚠️  LLM Sampling is for RESEARCH/INTELLIGENCE ONLY - NO TRADING")
        else:
            print("✓ LLM Sampling: disabled")

        print("\n✅ All safety checks passed\n")
        return True

    async def _initialize_components(self) -> None:
        """Initialize all components based on run config"""
        self._log_event("init_start", "system", "Initializing components")

        # Initialize data provider
        data_mode = DataMode(self.run_config.data_mode)
        self.data_provider = DataProviderManager(
            mode=data_mode,
            timeout_seconds=10.0,
            max_retries=3,
        )
        self._log_event("init_data_provider", "init", f"Data provider initialized: {data_mode.value}")

        # Initialize WebSocket components if enabled and using real data
        if self.run_config.use_websocket and self.run_config.data_mode in ("real_readonly", "hybrid"):
            await self._initialize_websocket()

        # Initialize engines
        self.microstructure_engine = MarketMicrostructureEngine()
        self.lifecycle_engine = ResolutionLifecycleEngine()
        self.wallet_engine = WalletIntelligenceEngine()

        # Initialize LLM provider based on run_config
        llm_provider_instance: LLMProvider | None = None
        if self.run_config.llm_provider == "xfyun_anthropic":
            from polysignal.llm.xfyun_anthropic_provider import (
                XFyunAnthropicProvider,
            )
            llm_provider_instance = XFyunAnthropicProvider()
            self._log_event("llm_provider_init", "init", "Initialized XFyunAnthropicProvider")
        elif self.run_config.llm_provider == "sensenova":
            from polysignal.llm.sensenova_provider import (
                SenseNovaProvider,
            )
            llm_provider_instance = SenseNovaProvider()
            self._log_event("llm_provider_init", "init", "Initialized SenseNovaProvider")
        else:
            from polysignal.llm.mock_provider import MockLLMProvider
            llm_provider_instance = MockLLMProvider()
            self._log_event("llm_provider_init", "init", "Initialized MockLLMProvider")

        self.event_engine = EventIntelligenceEngine(llm_provider=llm_provider_instance)

        # Initialize strategy
        self.strategy = YesNoMispricingStrategy()

        # Initialize Risk Governor with config values
        self.risk_governor = RiskGovernor(
            live_trading_enabled=self.config.env.live_trading_enabled,
            allow_auto_execution=self.config.env.allow_auto_execution,
            paper_trading_enabled=self.config.env.paper_trading_enabled,
        )

        # Initialize Paper Trader
        self.paper_trader = PaperTrader()

        # Initialize Watchlist-Driven Monitoring (Phase 5F.5)
        # IMPORTANT: This is for RESEARCH/MONITORING only - does NOT affect trading
        self._initialize_watchlist()

        self._log_event("init_complete", "system", "All components initialized")

    def _initialize_watchlist(self) -> None:
        """
        Initialize watchlist-driven monitoring components.

        IMPORTANT: This is for RESEARCH/MONITORING only.
        - Does NOT affect Risk Governor
        - Does NOT trigger trades
        - Does NOT modify trading decisions
        """
        # Only initialize if watchlist files are provided and monitor_mode is not default
        if self.run_config.monitor_mode == "default":
            self._log_event("watchlist_init", "watchlist", "Monitor mode is default, skipping watchlist initialization")
            return

        if not self.run_config.watchlist_file and not self.run_config.alpha_candidates_file:
            self._log_event("watchlist_init", "watchlist", "No watchlist files provided, skipping watchlist initialization")
            return

        self._log_event("watchlist_init_start", "watchlist", "Initializing watchlist-driven monitoring")

        # Initialize stats
        self.watchlist_stats = WatchlistMonitoringStats()

        # Initialize loader
        self.watchlist_loader = WatchlistLoader(
            logger=lambda msg: self._log_event("watchlist_loader", "watchlist", msg)
        )

        # Load watchlist files
        if self.run_config.watchlist_file:
            count = self.watchlist_loader.load_watchlist(self.run_config.watchlist_file)
            self.watchlist_stats.watchlist_markets_loaded = count

        if self.run_config.alpha_candidates_file:
            count = self.watchlist_loader.load_alpha_candidates(self.run_config.alpha_candidates_file)
            self.watchlist_stats.alpha_candidates_loaded = count

        if self.run_config.avoid_candidates_file:
            count = self.watchlist_loader.load_avoid_candidates(self.run_config.avoid_candidates_file)
            self.watchlist_stats.avoid_candidates_loaded = count

        if self.run_config.trajectories_file:
            count = self.watchlist_loader.load_trajectories(self.run_config.trajectories_file)
            self.watchlist_stats.trajectories_loaded = count

        # Initialize prioritizer
        self.market_prioritizer = MarketPrioritizer(
            watchlist=self.watchlist_loader.watchlist,
            alpha_candidates=self.watchlist_loader.alpha_candidates,
            watchlist_priority_ratio=self.run_config.watchlist_priority_ratio,
            discovery_ratio=self.run_config.discovery_ratio,
            alpha_priority_ratio=self.run_config.alpha_priority_ratio,
            alpha_repeat_target=self.run_config.alpha_repeat_target,
        )

        # Initialize avoid annotator
        self.avoid_annotator = AvoidAnnotator(
            avoid_candidates=self.watchlist_loader.avoid_candidates,
        )

        # Initialize trajectory tracker
        self.trajectory_tracker = TrajectoryTracker(
            trajectories=self.watchlist_loader.trajectories,
            track_enabled=self.run_config.track_trajectory,
        )

        self._log_event("watchlist_init_complete", "watchlist", "Watchlist-driven monitoring initialized", {
            "watchlist_markets": self.watchlist_stats.watchlist_markets_loaded,
            "alpha_candidates": self.watchlist_stats.alpha_candidates_loaded,
            "avoid_candidates": self.watchlist_stats.avoid_candidates_loaded,
            "trajectories": self.watchlist_stats.trajectories_loaded,
        })

        # Phase 6.5A — Extract IDs for control group exclusion
        if self.watchlist_loader:
            self._avoid_ids = set(self.watchlist_loader.avoid_candidates.keys())
            self._alpha_ids = set(self.watchlist_loader.alpha_candidates.keys())
            self._watchlist_ids = set(self.watchlist_loader.watchlist.keys())
            self._log_event("control_group_ids_loaded", "control_group", "Loaded exclusion IDs for control group", {
                "avoid_ids": len(self._avoid_ids),
                "alpha_ids": len(self._alpha_ids),
                "watchlist_ids": len(self._watchlist_ids),
            })

    async def _initialize_websocket(self) -> None:
        """Initialize WebSocket components for real-time data"""
        self._log_event("init_websocket_start", "system", "Initializing WebSocket components")

        # Initialize cache manager
        self.ws_cache_manager = OrderBookCacheManager(
            stale_threshold_seconds=60
        )

        # Initialize subscription manager
        self.ws_subscription_manager = SubscriptionManager(
            max_subscriptions=self.run_config.max_markets * 2,  # YES + NO tokens
            batch_size=5,
            delay_ms=100,
        )

        # Initialize WebSocket client
        ws_config = WebSocketConfig(
            enabled=True,
            max_subscriptions=self.run_config.max_markets * 2,
            stale_threshold_seconds=60,
        )

        # Create WebSocket client with message callback
        self.ws_client = CLOBWebSocketClient(
            config=ws_config,
            on_message=self._on_websocket_message,
            on_connect=self._on_websocket_connect,
            on_disconnect=self._on_websocket_disconnect,
        )

        # Use the client's cache manager
        self.ws_client.cache_manager = self.ws_cache_manager
        self.ws_client.subscription_manager = self.ws_subscription_manager

        self._log_event("init_websocket_complete", "system", "WebSocket components initialized")

    async def _on_websocket_message(self, message: WSMessage) -> None:
        """Callback for WebSocket messages"""
        if self.stats is None:
            return
        self._ws_message_count += 1
        self.stats.websocket_messages += 1

    async def _on_websocket_disconnect(self) -> None:
        """Callback for WebSocket disconnection"""
        if self.stats is None:
            return
        self._ws_connected = False
        self.stats.websocket_disconnects += 1
        self.stats.websocket_reconnects += 1
        # Track reconnect success (will be updated on next connect)
        self._ws_reconnect_pending = True
        self._log_event("websocket_disconnected", "websocket", "WebSocket disconnected")

    async def _on_websocket_connect(self) -> None:
        """Callback for WebSocket connection"""
        if self.stats is None:
            return
        self._ws_connected = True
        # Track reconnect success if this was a reconnect
        if hasattr(self, '_ws_reconnect_pending') and self._ws_reconnect_pending:
            self.stats.websocket_reconnect_successes += 1
            self._ws_reconnect_pending = False
        self._log_event("websocket_connected", "websocket", "WebSocket connected")

    async def _subscribe_markets(self, markets: list[Market]) -> None:
        """Subscribe to WebSocket for current markets"""
        if not self.ws_client or not self._ws_connected:
            return
        if self.stats is None:
            return

        # Extract token IDs
        token_ids = set()
        for market in markets:
            if market.yes_token_address:
                token_ids.add(market.yes_token_address)
            if market.no_token_address:
                token_ids.add(market.no_token_address)

        if not token_ids:
            return

        token_list = list(token_ids)

        # Subscribe
        self.stats.websocket_subscriptions_attempted += len(token_list)
        success, failed = await self.ws_client.subscribe(token_list)
        self.stats.websocket_subscriptions_active += success

        self._log_event("websocket_subscribe", "websocket", f"Subscribed to {success} tokens", {
            "success": success,
            "failed": failed,
            "total_attempted": len(token_list),
        })

    def _generate_run_id(self) -> str:
        """Generate unique run ID"""
        timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"run_{timestamp}_{short_uuid}"

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals"""
        print(f"\n\nReceived signal {signum}, initiating graceful shutdown...")
        self._shutdown_requested = True

    async def _run_loop(self) -> None:
        """Main run loop"""
        if self.stats is None:
            return
        end_time = utc_now() + timedelta(minutes=self.run_config.duration_minutes)

        # Start WebSocket connection if enabled
        if self.ws_client and self.run_config.use_websocket:
            connected = await self.ws_client.connect()
            if connected:
                self._ws_connected = True
                self._log_event("websocket_connected", "websocket", "WebSocket connection established")
            else:
                self._log_event("websocket_connect_failed", "websocket", "WebSocket connection failed, using REST fallback")

        while utc_now() < end_time and not self._shutdown_requested:
            self._scan_count += 1

            # Check hourly rate limits
            self._check_hourly_limits()

            # Run scan
            scan_start = utc_now()
            scan_id = f"{self.stats.run_id}_scan_{self._scan_count}"

            try:
                await self._run_scan(scan_id)
            except Exception as e:
                self._log_event("scan_error", "error", f"Scan error: {e}")
                self.stats.errors.append({
                    "time": utc_now().isoformat(),
                    "type": "scan_error",
                    "message": str(e),
                })

            scan_latency = (utc_now() - scan_start).total_seconds()

            # Print progress
            remaining = (end_time - utc_now()).total_seconds() / 60
            self._print_progress(remaining, scan_latency)

            # Wait for next scan
            if utc_now() < end_time and not self._shutdown_requested:
                await asyncio.sleep(self.run_config.scan_interval_seconds)

        # Set end time
        self.stats.end_time = utc_now()
        self.stats.status = "completed" if not self._shutdown_requested else "shutdown"

    async def _run_scan(self, scan_id: str) -> None:
        """Run a single market scan with real data"""
        if self.stats is None:
            return
        self._log_event("scan_start", "scan", f"Scan #{self._scan_count} started")

        signals_generated = 0
        markets_scanned = 0
        orderbooks_fetched = 0

        # Collect orderbooks for LLM sampling
        orderbooks_by_market: dict[str, OrderBookSnapshot] = {}

        try:
            # Fetch markets from data provider
            market_list = await self.data_provider.get_markets()

            if market_list and market_list.markets:
                # Track real markets fetched
                if self.run_config.data_mode != "mock":
                    self.stats.real_markets_fetched += len(market_list.markets)

                # Apply watchlist prioritization if enabled (Phase 5F.5)
                # IMPORTANT: This only affects scan order, NOT trading decisions
                market_sources: dict[str, str] = {}
                if self.market_prioritizer and self.run_config.monitor_mode != "default":
                    # Phase 6.5B — Update alpha observation counts for deprioritization
                    if self.run_config.alpha_priority_ratio > 0:
                        self.market_prioritizer.update_alpha_observations(
                            self._alpha_observation_counts
                        )
                    markets_to_scan, market_sources = self.market_prioritizer.prioritize(
                        all_markets=market_list.markets,
                        max_markets=self.run_config.max_markets,
                    )
                    # Update watchlist stats
                    if self.watchlist_stats:
                        for _market_id, source in market_sources.items():
                            if source == "watchlist":
                                self.watchlist_stats.watchlist_markets_scanned += 1
                            elif source == "alpha":
                                self.watchlist_stats.alpha_markets_scanned += 1
                            elif source == "discovery":
                                self.watchlist_stats.discovery_markets_scanned += 1
                        self.watchlist_stats.market_sources = market_sources
                else:
                    # Default behavior: limit to max_markets
                    markets_to_scan = market_list.markets[:self.run_config.max_markets]

                markets_scanned = len(markets_to_scan)
                self.stats.markets_checked += markets_scanned

                # Subscribe to WebSocket for current markets (if enabled)
                if self.ws_client and self._ws_connected:
                    await self._subscribe_markets(markets_to_scan)

                # Process each market
                for market in markets_to_scan:
                    try:
                        # Get orderbook
                        orderbook = await self._get_orderbook(market)

                        if orderbook:
                            orderbooks_fetched += 1
                            self.stats.orderbooks_fetched += 1
                            orderbooks_by_market[market.market_id] = orderbook

                            # Phase 6.5B — Track alpha observations (RESEARCH only)
                            if (market_sources.get(market.market_id) == "alpha"
                                    and market.market_id in self._alpha_ids):
                                self._alpha_observation_counts[market.market_id] = \
                                    self._alpha_observation_counts.get(market.market_id, 0) + 1

                            # Apply avoid annotation (Phase 5F.5)
                            # IMPORTANT: This is for RESEARCH LOGGING only
                            # Does NOT affect Risk Governor or trading decisions
                            avoid_annotation = None
                            if self.avoid_annotator:
                                avoid_annotation = self.avoid_annotator.annotate(market.market_id)
                                if avoid_annotation and self.watchlist_stats:
                                    self.watchlist_stats.avoid_annotations_count += 1
                                    self.watchlist_stats.avoid_annotations.append({
                                        "market_id": market.market_id,
                                        "question": market.title[:100] if market.title else None,
                                        "avoid_score": avoid_annotation.get("avoid_score"),
                                        "category_risk": avoid_annotation.get("category_risk"),
                                        "avoid_reasons": avoid_annotation.get("avoid_reasons", []),
                                    })

                            # Log watchlist event (Phase 5F.5)
                            if market_sources.get(market.market_id) and self.watchlist_stats:
                                self._log_watchlist_event(
                                    market=market,
                                    orderbook=orderbook,
                                    source=market_sources[market.market_id],
                                    avoid_annotation=avoid_annotation,
                                )

                            # Run through pipeline
                            signal = await self._process_market(market, orderbook)

                            # Track trajectory for watchlist markets (Phase 5F.5)
                            # IMPORTANT: This is for RESEARCH TRACKING only
                            if self.trajectory_tracker and market.market_id in market_sources:
                                # Get event_score from signal if available
                                event_score = None
                                if signal and signal.component_scores:
                                    event_score = signal.component_scores.event_score

                                # Track observation
                                change = self.trajectory_tracker.track(
                                    market_id=market.market_id,
                                    combined_ask=orderbook.combined_ask,
                                    event_score=event_score,
                                    liquidity_score=orderbook.liquidity_score if hasattr(orderbook, 'liquidity_score') else None,
                                )

                                if change and self.watchlist_stats:
                                    self.watchlist_stats.trajectory_changes_count += 1
                                    self.watchlist_stats.trajectory_changes.append(change)

                            if signal:
                                signals_generated += 1
                                self.stats.signals_generated += 1
                                self.stats.signals_this_hour += 1

                                # Process signal through Risk Governor
                                await self._process_signal(signal, market, orderbook)

                    except Exception as e:
                        error_str = str(e).lower()
                        self._log_event("market_error", "error", f"Error processing market {market.market_id}: {e}")
                        self.stats.api_errors += 1

                        # Classify error source
                        if "xfyun" in error_str or "llm" in error_str or "anthropic" in error_str:
                            self.stats.api_error_llm_provider += 1
                        elif "websocket" in error_str or "server disconnected" in error_str:
                            self.stats.api_error_websocket += 1
                        elif "clob" in error_str or "orderbook" in error_str:
                            self.stats.api_error_clob_rest += 1
                        elif "gamma" in error_str or "market" in error_str:
                            self.stats.api_error_gamma_api += 1
                        else:
                            # Default to LLM provider for sampling errors
                            self.stats.api_error_llm_provider += 1

                # LLM Sampling Mode (research/intelligence only, no trading)
                if self.run_config.enable_llm_sampling and self.run_config.llm_provider != "mock":
                    await self._run_llm_sampling(markets_to_scan, orderbooks_by_market)

                # Phase 6.5A — Control group sampling (research only, no trading)
                if (self.run_config.control_group_sampling_ratio > 0
                        and self.run_config.llm_provider != "mock"):
                    await self._run_control_group_sampling(markets_to_scan, orderbooks_by_market)

            else:
                # No markets returned - this could be an API error or fallback
                if self.run_config.data_mode == "hybrid":
                    self.stats.api_fallbacks += 1
                    self._log_event("api_fallback", "api", "No markets returned, using fallback")

        except Exception as e:
            self._log_event("scan_api_error", "error", f"API error during scan: {e}")
            self.stats.api_errors += 1

            # In hybrid mode, this is a fallback situation
            if self.run_config.data_mode == "hybrid":
                self.stats.api_fallbacks += 1

        # Save scan to database
        await self._save_scan(scan_id, markets_scanned, signals_generated, orderbooks_fetched)

        self._log_event("scan_end", "scan", f"Scan #{self._scan_count} completed", {
            "markets_scanned": markets_scanned,
            "signals_generated": signals_generated,
            "orderbooks_fetched": orderbooks_fetched,
        })

    def _log_watchlist_event(
        self,
        market: Market,
        orderbook: OrderBookSnapshot,
        source: str,
        avoid_annotation: dict[str, Any] | None,
    ) -> None:
        """
        Log watchlist monitoring event.

        IMPORTANT: This is for RESEARCH LOGGING only.
        Does NOT affect trading decisions.
        """
        if not self._watchlist_events_file:
            return

        event = {
            "event_time": utc_now().isoformat(),
            "event_type": "watchlist_scan",
            "market_id": market.market_id,
            "question": market.title[:200] if market.title else None,
            "source": source,  # "watchlist", "alpha", or "discovery"
            "combined_ask": orderbook.combined_ask,
            "spread": orderbook.spread_yes,
            "total_volume": market.total_volume_usd,
            "avoid_annotation": avoid_annotation,
        }

        self._watchlist_events_file.write(json.dumps(event) + "\n")
        self._watchlist_events_file.flush()

    def _check_hourly_limits(self) -> None:
        """Check and reset hourly rate limits"""
        if self.stats is None:
            return
        if self.stats.hour_start:
            hour_elapsed = (utc_now() - self.stats.hour_start).total_seconds() >= 3600
            if hour_elapsed:
                self.stats.llm_calls_this_hour = 0
                self.stats.signals_this_hour = 0
                self.stats.telegram_messages_this_hour = 0
                self.stats.hour_start = utc_now()
                self._log_event("hour_reset", "rate_limit", "Hourly rate limits reset")

    async def _save_run_start(self) -> None:
        """Save run start to database"""
        if not self.db or not self.stats:
            return

        await self.db.require_connection().execute(
            """
            INSERT INTO paper_runs (
                run_id, start_time, status, data_mode, llm_provider,
                websocket_enabled, telegram_enabled, max_markets, scan_interval_seconds,
                max_llm_calls_per_hour, max_signals_per_hour, max_telegram_messages_per_hour,
                duration_minutes, duration_hours
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.stats.run_id,
                self.stats.start_time.isoformat(),
                self.stats.status,
                self.stats.data_mode,
                self.stats.llm_provider,
                1 if self.stats.websocket_enabled else 0,
                1 if self.stats.telegram_enabled else 0,
                self.stats.max_markets,
                self.stats.scan_interval_seconds,
                self.stats.max_llm_calls_per_hour,
                self.stats.max_signals_per_hour,
                self.stats.max_telegram_messages_per_hour,
                self.stats.duration_minutes,
                self.stats.duration_hours,
            ),
        )
        await self.db.require_connection().commit()

    async def _save_scan(self, scan_id: str, markets_scanned: int, signals_generated: int, orderbooks_fetched: int) -> None:
        """Save scan to database"""
        if not self.db or not self.stats:
            return

        await self.db.require_connection().execute(
            """
            INSERT INTO paper_run_scans (
                scan_id, run_id, scan_time, markets_scanned, signals_generated,
                data_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                self.stats.run_id,
                utc_now().isoformat(),
                markets_scanned,
                signals_generated,
                self.run_config.data_mode,
            ),
        )
        await self.db.require_connection().commit()

    async def _save_run_end(self) -> None:
        """Save run end to database"""
        if not self.db or not self.stats:
            return

        await self.db.require_connection().execute(
            """
            UPDATE paper_runs SET
                end_time = ?, status = ?,
                markets_checked = ?, real_markets_fetched = ?, orderbooks_fetched = ?,
                signals_generated = ?,
                signals_ignored = ?, signals_log_only = ?,
                signals_alert = ?, signals_paper_trade = ?,
                signals_hard_reject = ?, paper_trades_created = ?,
                paper_trades_filled = ?, llm_calls = ?,
                llm_successes = ?, llm_failures = ?,
                api_errors = ?, api_fallbacks = ?,
                websocket_messages = ?, websocket_reconnects = ?,
                websocket_errors = ?, telegram_messages_sent = ?,
                telegram_errors = ?, hard_reject_reasons = ?,
                error_summary = ?, simulated_pnl_usd = ?
            WHERE run_id = ?
            """,
            (
                self.stats.end_time.isoformat() if self.stats.end_time else None,
                self.stats.status,
                self.stats.markets_checked,
                self.stats.real_markets_fetched,
                self.stats.orderbooks_fetched,
                self.stats.signals_generated,
                self.stats.signals_ignored,
                self.stats.signals_log_only,
                self.stats.signals_alert,
                self.stats.signals_paper_trade,
                self.stats.signals_hard_reject,
                self.stats.paper_trades_created,
                self.stats.paper_trades_filled,
                self.stats.llm_calls,
                self.stats.llm_successes,
                self.stats.llm_failures,
                self.stats.api_errors,
                self.stats.api_fallbacks,
                self.stats.websocket_messages,
                self.stats.websocket_reconnects,
                self.stats.websocket_errors,
                self.stats.telegram_messages_sent,
                self.stats.telegram_errors,
                json.dumps(self.stats.hard_reject_reasons),
                json.dumps(self.stats.errors[-10:]),
                self.stats.simulated_pnl_usd,
                self.stats.run_id,
            ),
        )
        await self.db.require_connection().commit()

    def _log_event(self, event_type: str, event_category: str, description: str, details: dict | None = None) -> None:
        """Log event to file and database"""
        if not self.stats:
            return

        event = {
            "event_id": f"{self.stats.run_id}_event_{uuid.uuid4().hex[:8]}",
            "run_id": self.stats.run_id,
            "event_time": utc_now().isoformat(),
            "event_type": event_type,
            "event_category": event_category,
            "description": description,
            "details": details,
        }

        # Write to events file
        if self.events_file:
            self.events_file.write(json.dumps(event) + "\n")
            self.events_file.flush()

        # Save to database
        if self.db:
            asyncio.create_task(self._save_event(event))

    async def _save_event(self, event: dict) -> None:
        """Save event to database"""
        if not self.db:
            return

        try:
            await self.db.require_connection().execute(
                """
                INSERT INTO paper_run_events (
                    event_id, run_id, event_time, event_type, event_category,
                    description, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["run_id"],
                    event["event_time"],
                    event["event_type"],
                    event["event_category"],
                    event["description"],
                    json.dumps(event.get("details")),
                ),
            )
            await self.db.require_connection().commit()
        except Exception:
            pass  # Don't fail run on event save error

    async def _cleanup(self) -> None:
        """Cleanup resources"""
        print("\n=== Shutting Down ===")

        # Disconnect WebSocket
        if self.ws_client:
            await self.ws_client.disconnect()
            self._log_event("websocket_disconnected", "websocket", "WebSocket disconnected")

        # Close data provider
        if self.data_provider:
            await self.data_provider.close()

        # Save run end to database
        await self._save_run_end()

        # Generate reports (before closing events file, since report generation may log)
        self._generate_reports()

        # Generate watchlist reports (Phase 5F.5)
        self._generate_watchlist_reports()

        # Generate control group reports (Phase 6.5A)
        self._generate_control_group_reports()

        # Generate alpha repeat observation reports (Phase 6.5B)
        self._generate_alpha_repeat_reports()

        # Close events file
        if self.events_file:
            self.events_file.close()

        # Close watchlist events file (Phase 5F.5)
        if self._watchlist_events_file:
            self._watchlist_events_file.close()

        # Close database
        if self.db:
            await self.db.close()

        print("✓ Cleanup complete")

    def _generate_watchlist_reports(self) -> None:
        """
        Generate watchlist monitoring reports (Phase 5F.5).

        IMPORTANT: These are for RESEARCH/MONITORING only.
        Output is written to current run directory only.
        """
        if not self.run_dir or not self.watchlist_stats:
            return

        # Only generate if watchlist was enabled
        if self.run_config.monitor_mode == "default":
            return

        # Generate watchlist monitoring summary JSON
        summary_path = self.run_dir / "watchlist_monitoring_summary.json"
        summary_data = self.watchlist_stats.to_dict()

        # Add trajectory updates if available
        if self.trajectory_tracker:
            trajectory_update = self.trajectory_tracker.to_trajectory_update_json()
            summary_data["trajectory_updates"] = trajectory_update

        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)

        # Generate watchlist monitoring report markdown
        report_path = self.run_dir / "watchlist_monitoring_report.md"
        with open(report_path, "w") as f:
            f.write(self._generate_watchlist_markdown_report())

        # Generate trajectory update JSON
        if self.trajectory_tracker:
            trajectory_path = self.run_dir / "watchlist_trajectory_update.json"
            with open(trajectory_path, "w") as f:
                json.dump(self.trajectory_tracker.to_trajectory_update_json(), f, indent=2)

        print("\n=== Watchlist Reports Generated ===")
        print(f"  {summary_path}")
        print(f"  {report_path}")
        if self.trajectory_tracker:
            print(f"  {self.run_dir / 'watchlist_trajectory_update.json'}")
        if self._watchlist_events_file:
            print(f"  {self.run_dir / 'watchlist_events.jsonl'}")

    def _generate_watchlist_markdown_report(self) -> str:
        """Generate watchlist monitoring markdown report"""
        if not self.watchlist_stats:
            return ""

        lines = [
            "# Watchlist Monitoring Report",
            "",
            f"## Run ID: {self.stats.run_id if self.stats else 'unknown'}",
            "",
            "## Summary",
            "",
            f"- **Monitor Mode**: {self.run_config.monitor_mode}",
            f"- **Watchlist Markets Loaded**: {self.watchlist_stats.watchlist_markets_loaded}",
            f"- **Alpha Candidates Loaded**: {self.watchlist_stats.alpha_candidates_loaded}",
            f"- **Avoid Candidates Loaded**: {self.watchlist_stats.avoid_candidates_loaded}",
            f"- **Trajectories Loaded**: {self.watchlist_stats.trajectories_loaded}",
            "",
            "## Scan Statistics",
            "",
            f"- **Watchlist Markets Scanned**: {self.watchlist_stats.watchlist_markets_scanned}",
            f"- **Alpha Candidates Scanned**: {self.watchlist_stats.alpha_markets_scanned}",
            f"- **Discovery Markets Scanned**: {self.watchlist_stats.discovery_markets_scanned}",
            f"- **Avoid Annotations**: {self.watchlist_stats.avoid_annotations_count}",
            "",
            "## Trajectory Tracking",
            "",
            f"- **Trajectory Updates**: {self.watchlist_stats.trajectory_updates_count}",
            f"- **Changes Detected**: {self.watchlist_stats.trajectory_changes_count}",
        ]

        # Add trajectory changes
        if self.watchlist_stats.trajectory_changes:
            lines.extend([
                "",
                "### Trajectory Changes",
                "",
            ])
            for change in self.watchlist_stats.trajectory_changes[:10]:
                lines.append(f"- **{change.get('market_id', 'unknown')}**")
                for c in change.get("changes", []):
                    if c.get("type") == "combined_ask_change":
                        lines.append(f"  - Combined Ask: {c.get('from'):.4f} → {c.get('to'):.4f} (Δ {c.get('delta', 0):.4f})")
                    elif c.get("type") == "tier_change":
                        lines.append(f"  - Tier: {c.get('from')} → {c.get('to')}")
                    elif c.get("type") == "mode_change":
                        lines.append(f"  - Mode: {c.get('from')} → {c.get('to')}")

        # Add avoid annotations
        if self.watchlist_stats.avoid_annotations:
            lines.extend([
                "",
                "## Avoid Candidates Status",
                "",
                "**Note**: Avoid candidates are for RESEARCH ANNOTATION only. They do NOT affect Risk Governor or trading decisions.",
                "",
            ])
            for ann in self.watchlist_stats.avoid_annotations[:10]:
                lines.append(f"- **{ann.get('market_id', 'unknown')}**")
                if ann.get("question"):
                    lines.append(f"  - Question: {(ann.get('question') or '')[:80]}...")
                lines.append(f"  - Avoid Score: {ann.get('avoid_score', 0)}")
                lines.append(f"  - Category Risk: {ann.get('category_risk', 'unknown')}")
                if ann.get("avoid_reasons"):
                    lines.append(f"  - Reasons: {', '.join(ann.get('avoid_reasons', []))}")

        lines.extend([
            "",
            "## Safety Verification",
            "",
            "- ✅ Watchlist monitoring is for RESEARCH only",
            "- ✅ Does NOT affect Risk Governor score",
            "- ✅ Does NOT add hard_reject reasons",
            "- ✅ Does NOT block paper trades",
            "- ✅ Does NOT change signal actions",
            "- ✅ Avoid candidates are NOT hard forbidden",
            "",
            "---",
            "",
            "*Generated by PolySignal Pro Watchlist-Driven Monitoring (Phase 5F.5)*",
        ])

        return "\n".join(lines)

    def _generate_reports(self) -> None:
        """Generate summary reports"""
        if not self.stats or not self.run_dir:
            return

        # JSON summary
        summary_path = self.run_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(self.stats.to_dict(), f, indent=2)

        # Markdown report
        report_path = self.run_dir / "report.md"
        with open(report_path, "w") as f:
            f.write(self._generate_markdown_report())

        print("\n=== Reports Generated ===")
        print(f"  {summary_path}")
        print(f"  {report_path}")
        print(f"  {self.run_dir / 'events.jsonl'}")

    def _generate_markdown_report(self) -> str:
        """Generate markdown report"""
        if not self.stats:
            return ""

        duration_actual = (
            (self.stats.end_time - self.stats.start_time).total_seconds() / 60
            if self.stats.end_time
            else 0
        )

        lines = [
            "# Paper Trading Run Report",
            "",
            f"## Run ID: {self.stats.run_id}",
            "",
            "## Summary",
            "",
            f"- **Status**: {self.stats.status}",
            f"- **Duration**: {duration_actual:.1f} minutes (planned: {self.stats.duration_minutes})",
            f"- **Start Time**: {self.stats.start_time.isoformat()}",
            f"- **End Time**: {self.stats.end_time.isoformat() if self.stats.end_time else 'N/A'}",
            "",
            "## Configuration",
            "",
            f"- **Data Mode**: {self.stats.data_mode}",
            f"- **LLM Provider**: {self.stats.llm_provider}",
            f"- **WebSocket**: {'enabled' if self.stats.websocket_enabled else 'disabled'}",
            f"- **Telegram**: {'enabled' if self.stats.telegram_enabled else 'disabled'}",
            f"- **Max Markets**: {self.stats.max_markets}",
            f"- **Scan Interval**: {self.stats.scan_interval_seconds}s",
            "",
            "## Statistics",
            "",
            f"- **Markets Checked**: {self.stats.markets_checked}",
            f"- **Real Markets Fetched**: {self.stats.real_markets_fetched}",
            f"- **Orderbooks Fetched**: {self.stats.orderbooks_fetched}",
            f"- **Signals Generated**: {self.stats.signals_generated}",
            f"  - Ignored: {self.stats.signals_ignored}",
            f"  - Log Only: {self.stats.signals_log_only}",
            f"  - Alert: {self.stats.signals_alert}",
            f"  - Paper Trade: {self.stats.signals_paper_trade}",
            f"  - Hard Reject: {self.stats.signals_hard_reject}",
            "",
            f"- **Paper Trades Created**: {self.stats.paper_trades_created}",
            f"- **Paper Trades Filled**: {self.stats.paper_trades_filled}",
            "",
            "## LLM Performance",
            "",
            f"- **Provider**: {self.stats.llm_provider}",
            f"- **Calls**: {self.stats.llm_calls}",
            f"- **Successes**: {self.stats.llm_successes}",
            f"- **Failures**: {self.stats.llm_failures}",
        ]

        if self.stats.llm_latencies:
            avg_latency = sum(self.stats.llm_latencies) / len(self.stats.llm_latencies)
            lines.append(f"- **Avg Latency**: {avg_latency:.2f}s")

        lines.extend([
            "",
            "## API/WebSocket",
            "",
            f"- **API Errors**: {self.stats.api_errors}",
            f"- **API Fallbacks**: {self.stats.api_fallbacks}",
            f"- **WebSocket Messages**: {self.stats.websocket_messages}",
            f"- **WebSocket Reconnects**: {self.stats.websocket_reconnects}",
            f"- **WebSocket Errors**: {self.stats.websocket_errors}",
        ])

        # Add WebSocket subscription stats if enabled
        if self.stats.websocket_enabled:
            ws_summary = self.stats._get_websocket_reconnect_summary()
            lines.extend([
                "",
                "## WebSocket Subscriptions",
                "",
                f"- **Subscriptions Attempted**: {self.stats.websocket_subscriptions_attempted}",
                f"- **Subscriptions Active**: {self.stats.websocket_subscriptions_active}",
                f"- **Cache Hits**: {self.stats.websocket_cache_hits}",
                f"- **Cache Misses**: {self.stats.websocket_cache_misses}",
                f"- **Stale Fallbacks**: {self.stats.websocket_stale_fallbacks}",
                f"- **REST Fallbacks**: {self.stats.rest_fallbacks}",
                "",
                "### WebSocket Reconnect Summary",
                "",
                f"- **Disconnects**: {ws_summary['disconnects']}",
                f"- **Reconnects**: {ws_summary['reconnects']}",
                f"- **Reconnect Successes**: {ws_summary['reconnect_successes']}",
                f"- **Reconnect Failures**: {ws_summary['reconnect_failures']}",
                f"- **Cache Hit Rate**: {ws_summary['cache_hit_rate']:.2%}",
                f"- **REST Fallback Rate**: {ws_summary['rest_fallback_rate']:.2%}",
            ])

        lines.extend([
            "",
            "## Hard Reject Reasons",
            "",
        ])

        for reason, count in self.stats.hard_reject_reasons.items():
            lines.append(f"- {reason}: {count}")

        # Add API Error Distribution
        api_error_dist = self.stats._get_api_error_type_distribution()
        if api_error_dist["total"] > 0:
            lines.extend([
                "",
                "## API Error Distribution",
                "",
                f"- **LLM Provider**: {api_error_dist['llm_provider']}",
                f"- **CLOB REST**: {api_error_dist['clob_rest']}",
                f"- **Gamma API**: {api_error_dist['gamma_api']}",
                f"- **WebSocket**: {api_error_dist['websocket']}",
                f"- **Database**: {api_error_dist['database']}",
                f"- **Total**: {api_error_dist['total']}",
            ])

        # Add combined_ask distribution
        combined_ask = self.stats._calculate_combined_ask_distribution()
        if combined_ask["observation_count"] > 0:
            lines.extend([
                "",
                "## Combined Ask Distribution",
                "",
                f"- **Observations**: {combined_ask['observation_count']}",
                f"- **Min**: {combined_ask['min']:.4f}" if combined_ask['min'] else "- **Min**: N/A",
                f"- **Max**: {combined_ask['max']:.4f}" if combined_ask['max'] else "- **Max**: N/A",
                f"- **Median**: {combined_ask['median']:.4f}" if combined_ask['median'] else "- **Median**: N/A",
                f"- **P5**: {combined_ask['p5']:.4f}" if combined_ask['p5'] else "- **P5**: N/A",
                f"- **P95**: {combined_ask['p95']:.4f}" if combined_ask['p95'] else "- **P95**: N/A",
                f"- **Sample Lowest**: {combined_ask['sample_lowest']}",
                f"- **Sample Highest**: {combined_ask['sample_highest']}",
            ])

        # Add LLM Sampling section
        if self.stats.llm_sampling_enabled:
            lines.extend([
                "",
                "## LLM Sampling (Research/Intelligence Only)",
                "",
                "- **Enabled**: true",
                f"- **Provider**: {self.stats.llm_provider}",
                f"- **Strategy**: {self.stats.llm_sampling_strategy}",
                f"- **Cooldown**: {self.stats.llm_sampling_cooldown_minutes} minutes",
                f"- **Calls Attempted**: {self.stats.llm_sampling_calls_attempted}",
                f"- **Calls Succeeded**: {self.stats.llm_sampling_calls_succeeded}",
                f"- **Calls Failed**: {self.stats.llm_sampling_calls_failed}",
                f"- **Sampled Markets**: {self.stats.sampled_markets_count}",
                f"- **Unique Markets**: {self.stats.unique_sampled_markets}",
                f"- **Repeated Samples**: {self.stats.repeated_sampled_markets}",
            ])

            if self.stats.llm_latencies:
                llm_avg_latency: float | None = self.stats._calculate_avg_latency()
                llm_p95_latency: float | None = self.stats._calculate_p95_latency()
                lines.append(f"- **Avg Latency**: {llm_avg_latency:.2f}s" if llm_avg_latency else "- **Avg Latency**: N/A")
                lines.append(f"- **P95 Latency**: {llm_p95_latency:.2f}s" if llm_p95_latency else "- **P95 Latency**: N/A")

            # LLM Error Type Distribution
            error_dist = self.stats._get_llm_error_type_distribution()
            if error_dist["total"] > 0:
                lines.extend([
                    "",
                    "### LLM Error Type Distribution",
                    "",
                    f"- **Timeout**: {error_dist['timeout']}",
                    f"- **Invalid JSON**: {error_dist['invalid_json']}",
                    f"- **Schema Error**: {error_dist['schema_error']}",
                    f"- **Server Error (500)**: {error_dist['server_error']}",
                    f"- **Connection Error**: {error_dist['connection_error']}",
                    f"- **Rate Limit**: {error_dist['rate_limit']}",
                    f"- **Total Errors**: {error_dist['total']}",
                ])

            if self.stats.sampled_markets_examples:
                lines.extend([
                    "",
                    "### Sampled Markets Examples",
                    "",
                ])
                for example in self.stats.sampled_markets_examples[:5]:
                    status = "✅" if example.get("success") else "❌"
                    lines.append(f"- {status} **{example.get('market_id', 'unknown')}**")
                    if example.get("question"):
                        lines.append(f"  - Question: {example['question'][:80]}...")
                    if example.get("event_score") is not None:
                        lines.append(f"  - Event Score: {example['event_score']}")
                    if example.get("latency_seconds") is not None:
                        lines.append(f"  - Latency: {example['latency_seconds']:.2f}s")

            lines.extend([
                "",
                "**Note**: LLM Sampling is for research/intelligence logging only. No trading signals generated.",
            ])

        if self.stats.errors:
            lines.extend([
                "",
                "## Errors",
                "",
            ])
            for error in self.stats.errors[-10:]:
                lines.append(f"- [{error['time']}] {error['type']}: {error['message']}")

        lines.extend([
            "",
            "## Safety Verification",
            "",
            "- ✅ live_trading_enabled: false",
            "- ✅ allow_auto_execution: false",
            "- ✅ paper_trading_enabled: true",
            "- ✅ No real orders placed",
            "- ✅ No private keys used",
            "",
            "---",
            "",
            "*Generated by PolySignal Pro Paper Trading Runner*",
        ])

        return "\n".join(lines)

    def _print_header(self) -> None:
        """Print run header"""
        if self.stats is None:
            return
        print("=" * 60)
        print("PolySignal Pro - Paper Trading Runner")
        print("=" * 60)
        print(f"Run ID: {self.stats.run_id}")
        print(f"Duration: {self.run_config.duration_minutes} minutes")
        print(f"Data Mode: {self.run_config.data_mode}")
        print(f"LLM Provider: {self.run_config.llm_provider}")
        print(f"WebSocket: {'enabled' if self.run_config.use_websocket else 'disabled'}")
        print(f"Telegram: {'enabled' if self.run_config.telegram_enabled else 'disabled'}")
        print(f"Max Markets: {self.run_config.max_markets}")
        print(f"Scan Interval: {self.run_config.scan_interval_seconds}s")
        print(f"Max Signals/Hour: {self.run_config.max_signals_per_hour}")
        if self.run_config.enable_llm_sampling:
            print(f"LLM Sampling: enabled ({self.run_config.llm_sampling_per_scan}/scan, max {self.run_config.max_llm_calls_per_hour}/hour)")
        print("=" * 60)
        print()

    def _print_progress(self, remaining_minutes: float, scan_latency: float) -> None:
        """Print progress update"""
        if not self.stats:
            return

        ws_status = ""
        if self.run_config.use_websocket:
            ws_status = f"WS: {self.stats.websocket_messages} | "

        print(f"\r[{utc_now().strftime('%H:%M:%S')}] "
              f"Scan #{self._scan_count} | "
              f"Markets: {self.stats.markets_checked} | "
              f"OBs: {self.stats.orderbooks_fetched} | "
              f"{ws_status}"
              f"Signals: {self.stats.signals_generated} | "
              f"Remaining: {remaining_minutes:.1f}m | "
              f"Latency: {scan_latency:.1f}s",
              end="", flush=True)


