"""
Run state domain: RunConfig and RunStatistics.

Verbatim extraction from scripts/run_paper.py (Iteration 010) — the dataclasses
are unchanged; scripts/run_paper.py re-exports them so every existing import
(including tests importing from scripts.run_paper) keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RunConfig:
    """Configuration for paper trading run"""

    # Duration
    duration_minutes: int = 30
    duration_hours: float = 0.5

    # Market scanning
    max_markets: int = 10
    scan_interval_seconds: int = 120

    # Data mode
    data_mode: str = "hybrid"
    use_websocket: bool = True

    # LLM
    llm_provider: str = "mock"
    max_llm_calls_per_hour: int = 0

    # LLM Sampling Mode (research/intelligence only, no trading)
    enable_llm_sampling: bool = False
    llm_sampling_per_scan: int = 1
    llm_sampling_min_volume: float = 10000.0  # Minimum 24h volume for sampling
    llm_sampling_strategy: str = "top_liquidity_or_near_miss"
    llm_sampling_cooldown_minutes: int = 60  # Cooldown before re-sampling same market
    llm_sampling_max_repeats_per_market: int = 1  # Max times to sample same market per run

    # Signals
    max_signals_per_hour: int = 20

    # Telegram
    telegram_enabled: bool = False
    max_telegram_messages_per_hour: int = 0

    # Watchlist-Driven Monitoring (Phase 5F.5)
    # All watchlist features are OPTIONAL and do not affect trading decisions
    watchlist_file: str | None = None  # Path to persistent_watchlist.csv
    alpha_candidates_file: str | None = None  # Path to alpha_candidates.csv
    avoid_candidates_file: str | None = None  # Path to avoid_candidates.csv
    trajectories_file: str | None = None  # Path to market_trajectories.json
    monitor_mode: str = "default"  # "default", "hybrid", "watchlist"
    watchlist_priority_ratio: float = 0.6  # Ratio of watchlist markets in hybrid mode
    discovery_ratio: float = 0.2  # Minimum ratio for new market discovery
    track_trajectory: bool = True  # Track trajectory changes for watchlist markets

    # Phase 6.5A — Control Group Sampling
    control_group_sampling_ratio: float = 0.0  # Ratio of markets for control group (0.0-0.5)
    exclude_avoid_from_control_group: bool = True  # Exclude avoid candidates from control group

    # Phase 6.5B — Alpha Repeated Observation
    alpha_priority_ratio: float = 0.0  # Ratio of scan slots reserved for alpha candidates (0.0-0.8)
    alpha_repeat_target: int = 3  # Target observations per alpha candidate before deprioritizing


@dataclass
class RunStatistics:
    """Statistics for a paper trading run"""

    run_id: str
    start_time: datetime
    end_time: datetime | None = None
    status: str = "running"

    # Configuration
    data_mode: str = "hybrid"
    llm_provider: str = "mock"
    websocket_enabled: bool = True
    telegram_enabled: bool = False
    max_markets: int = 10
    scan_interval_seconds: int = 120
    max_llm_calls_per_hour: int = 0
    max_signals_per_hour: int = 20
    max_telegram_messages_per_hour: int = 0

    # Statistics
    markets_checked: int = 0
    real_markets_fetched: int = 0
    orderbooks_fetched: int = 0
    signals_generated: int = 0
    signals_ignored: int = 0
    signals_log_only: int = 0
    signals_alert: int = 0
    signals_paper_trade: int = 0
    signals_hard_reject: int = 0
    paper_trades_created: int = 0
    paper_trades_filled: int = 0

    # LLM statistics
    llm_calls: int = 0
    llm_successes: int = 0
    llm_failures: int = 0
    llm_latencies: list[float] = field(default_factory=list)

    # LLM Sampling statistics (research/intelligence only)
    llm_sampling_enabled: bool = False
    llm_sampling_calls_attempted: int = 0
    llm_sampling_calls_succeeded: int = 0
    llm_sampling_calls_failed: int = 0
    llm_sampling_fallback_count: int = 0
    llm_sampling_timeout_count: int = 0
    llm_sampling_invalid_json_count: int = 0
    llm_sampling_schema_error_count: int = 0
    sampled_markets_count: int = 0
    sampled_markets_examples: list[dict[str, Any]] = field(default_factory=list)

    # LLM Sampling diversity tracking
    sampled_market_history: dict[str, list[datetime]] = field(default_factory=dict)  # market_id -> list of sample times
    unique_sampled_markets: int = 0
    repeated_sampled_markets: int = 0
    llm_sampling_strategy: str = "top_liquidity_or_near_miss"
    llm_sampling_cooldown_minutes: int = 60

    # API/WebSocket statistics
    api_errors: int = 0
    api_fallbacks: int = 0
    websocket_messages: int = 0
    websocket_reconnects: int = 0
    websocket_errors: int = 0

    # WebSocket subscription statistics
    websocket_subscriptions_attempted: int = 0
    websocket_subscriptions_active: int = 0
    websocket_cache_hits: int = 0
    websocket_cache_misses: int = 0
    websocket_stale_fallbacks: int = 0
    rest_fallbacks: int = 0

    # Telegram statistics
    telegram_messages_sent: int = 0
    telegram_errors: int = 0

    # LLM error type distribution
    llm_sampling_server_error_count: int = 0
    llm_sampling_connection_error_count: int = 0
    llm_sampling_rate_limit_count: int = 0

    # API error type distribution
    api_error_llm_provider: int = 0
    api_error_clob_rest: int = 0
    api_error_gamma_api: int = 0
    api_error_websocket: int = 0
    api_error_database: int = 0

    # WebSocket reconnect details
    websocket_disconnects: int = 0
    websocket_reconnect_successes: int = 0
    websocket_reconnect_failures: int = 0

    # Rate limit tracking
    llm_calls_this_hour: int = 0
    signals_this_hour: int = 0
    telegram_messages_this_hour: int = 0
    hour_start: datetime | None = None

    # Error tracking
    hard_reject_reasons: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # PnL
    simulated_pnl_usd: float = 0.0

    # Duration (set dynamically)
    duration_minutes: int = 30
    duration_hours: float = 0.5

    # Combined ask distribution tracking
    combined_ask_observations: list[float] = field(default_factory=list)

    # Phase 6.5A — Control group statistics
    control_group_samples: int = 0
    control_group_unique_markets: int = 0
    control_group_llm_calls: int = 0
    control_group_categories: dict[str, int] = field(default_factory=dict)

    # Phase 6.5B — Alpha repeat observation statistics
    alpha_priority_ratio: float = 0.0
    alpha_repeat_target: int = 3
    alpha_slots_assigned: int = 0
    alpha_observations_total: int = 0
    alpha_markets_at_target: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        # Calculate combined_ask distribution
        combined_ask_distribution = self._calculate_combined_ask_distribution()

        return {
            "run_id": self.run_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "duration_minutes": self.duration_minutes,
            "duration_hours": self.duration_hours,
            "data_mode": self.data_mode,
            "llm_provider": self.llm_provider,
            "websocket_enabled": self.websocket_enabled,
            "telegram_enabled": self.telegram_enabled,
            "max_markets": self.max_markets,
            "scan_interval_seconds": self.scan_interval_seconds,
            "max_llm_calls_per_hour": self.max_llm_calls_per_hour,
            "max_signals_per_hour": self.max_signals_per_hour,
            "max_telegram_messages_per_hour": self.max_telegram_messages_per_hour,
            "markets_checked": self.markets_checked,
            "real_markets_fetched": self.real_markets_fetched,
            "orderbooks_fetched": self.orderbooks_fetched,
            "signals_generated": self.signals_generated,
            "signals_ignored": self.signals_ignored,
            "signals_log_only": self.signals_log_only,
            "signals_alert": self.signals_alert,
            "signals_paper_trade": self.signals_paper_trade,
            "signals_hard_reject": self.signals_hard_reject,
            "paper_trades_created": self.paper_trades_created,
            "paper_trades_filled": self.paper_trades_filled,
            "llm_calls": self.llm_calls,
            "llm_successes": self.llm_successes,
            "llm_failures": self.llm_failures,
            "llm_avg_latency_seconds": sum(self.llm_latencies) / len(self.llm_latencies) if self.llm_latencies else None,
            "api_errors": self.api_errors,
            "api_fallbacks": self.api_fallbacks,
            "websocket_messages": self.websocket_messages,
            "websocket_reconnects": self.websocket_reconnects,
            "websocket_errors": self.websocket_errors,
            "websocket_subscriptions_attempted": self.websocket_subscriptions_attempted,
            "websocket_subscriptions_active": self.websocket_subscriptions_active,
            "websocket_cache_hits": self.websocket_cache_hits,
            "websocket_cache_misses": self.websocket_cache_misses,
            "websocket_stale_fallbacks": self.websocket_stale_fallbacks,
            "rest_fallbacks": self.rest_fallbacks,
            "telegram_messages_sent": self.telegram_messages_sent,
            "telegram_errors": self.telegram_errors,
            "hard_reject_reasons": self.hard_reject_reasons,
            "error_summary": self.errors[-10:] if self.errors else [],
            "simulated_pnl_usd": self.simulated_pnl_usd,
            "combined_ask_distribution": combined_ask_distribution,
            # LLM Sampling statistics
            "llm_sampling_enabled": self.llm_sampling_enabled,
            "llm_sampling_calls_attempted": self.llm_sampling_calls_attempted,
            "llm_sampling_calls_succeeded": self.llm_sampling_calls_succeeded,
            "llm_sampling_calls_failed": self.llm_sampling_calls_failed,
            "llm_sampling_fallback_count": self.llm_sampling_fallback_count,
            "llm_sampling_avg_latency_seconds": self._calculate_avg_latency(),
            "llm_sampling_p95_latency_seconds": self._calculate_p95_latency(),
            "llm_sampling_timeout_count": self.llm_sampling_timeout_count,
            "llm_sampling_invalid_json_count": self.llm_sampling_invalid_json_count,
            "llm_sampling_schema_error_count": self.llm_sampling_schema_error_count,
            "llm_sampling_error_type_distribution": self._get_llm_error_type_distribution(),
            "sampled_markets_count": self.sampled_markets_count,
            "sampled_markets_examples": self.sampled_markets_examples[:5],
            # LLM Sampling diversity statistics
            "unique_sampled_markets": self.unique_sampled_markets,
            "repeated_sampled_markets": self.repeated_sampled_markets,
            "llm_sampling_strategy": self.llm_sampling_strategy,
            "llm_sampling_cooldown_minutes": self.llm_sampling_cooldown_minutes,
            "top_sampled_markets": self._get_top_sampled_markets(),
            # API error distribution
            "api_error_type_distribution": self._get_api_error_type_distribution(),
            # WebSocket reconnect summary
            "websocket_reconnect_summary": self._get_websocket_reconnect_summary(),
            # Phase 6.5A — Control group statistics
            "control_group_samples": self.control_group_samples,
            "control_group_unique_markets": self.control_group_unique_markets,
            "control_group_llm_calls": self.control_group_llm_calls,
            "control_group_categories": self.control_group_categories,
            # Phase 6.5B — Alpha repeat observation statistics
            "alpha_priority_ratio": self.alpha_priority_ratio,
            "alpha_repeat_target": self.alpha_repeat_target,
            "alpha_slots_assigned": self.alpha_slots_assigned,
            "alpha_observations_total": self.alpha_observations_total,
            "alpha_markets_at_target": self.alpha_markets_at_target,
        }

    def _calculate_avg_latency(self) -> float | None:
        """Calculate average LLM latency"""
        if not self.llm_latencies:
            return None
        return sum(self.llm_latencies) / len(self.llm_latencies)

    def _calculate_p95_latency(self) -> float | None:
        """
        Calculate p95 LLM latency.

        Uses proper percentile calculation on sorted latencies.
        For small samples, uses the maximum value as a conservative estimate.
        """
        if not self.llm_latencies:
            return None

        sorted_latencies = sorted(self.llm_latencies)
        n = len(sorted_latencies)

        # For small samples, return the maximum (conservative estimate)
        if n < 20:
            return sorted_latencies[-1]

        # For 20+ samples, calculate true p95
        idx = int(n * 0.95)
        idx = min(idx, n - 1)  # Ensure we don't go out of bounds
        return sorted_latencies[idx]

    def _get_llm_error_type_distribution(self) -> dict[str, int]:
        """Get LLM error type distribution"""
        return {
            "timeout": self.llm_sampling_timeout_count,
            "invalid_json": self.llm_sampling_invalid_json_count,
            "schema_error": self.llm_sampling_schema_error_count,
            "server_error": self.llm_sampling_server_error_count,
            "connection_error": self.llm_sampling_connection_error_count,
            "rate_limit": self.llm_sampling_rate_limit_count,
            "total": (self.llm_sampling_timeout_count +
                      self.llm_sampling_invalid_json_count +
                      self.llm_sampling_schema_error_count +
                      self.llm_sampling_server_error_count +
                      self.llm_sampling_connection_error_count +
                      self.llm_sampling_rate_limit_count),
        }

    def _get_api_error_type_distribution(self) -> dict[str, int]:
        """Get API error type distribution by source"""
        return {
            "llm_provider": self.api_error_llm_provider,
            "clob_rest": self.api_error_clob_rest,
            "gamma_api": self.api_error_gamma_api,
            "websocket": self.api_error_websocket,
            "database": self.api_error_database,
            "total": (self.api_error_llm_provider +
                      self.api_error_clob_rest +
                      self.api_error_gamma_api +
                      self.api_error_websocket +
                      self.api_error_database),
        }

    def _get_websocket_reconnect_summary(self) -> dict[str, Any]:
        """Get WebSocket reconnect summary with rates"""
        total_orderbooks = self.websocket_cache_hits + self.websocket_cache_misses + self.websocket_stale_fallbacks + self.rest_fallbacks
        cache_hit_rate = self.websocket_cache_hits / total_orderbooks if total_orderbooks > 0 else 0.0
        rest_fallback_rate = self.rest_fallbacks / total_orderbooks if total_orderbooks > 0 else 0.0

        return {
            "disconnects": self.websocket_disconnects,
            "reconnects": self.websocket_reconnects,
            "reconnect_successes": self.websocket_reconnect_successes,
            "reconnect_failures": self.websocket_reconnect_failures,
            "cache_hit_rate": round(cache_hit_rate, 4),
            "rest_fallback_rate": round(rest_fallback_rate, 4),
        }

    def _calculate_combined_ask_distribution(self) -> dict[str, Any]:
        """Calculate combined_ask distribution statistics"""
        if not self.combined_ask_observations:
            return {
                "min": None,
                "max": None,
                "median": None,
                "p5": None,
                "p95": None,
                "sample_lowest": [],
                "sample_highest": [],
                "observation_count": 0,
            }

        observations = sorted(self.combined_ask_observations)
        count = len(observations)

        # Calculate percentiles
        def percentile(p: float) -> float:
            idx = int(count * p / 100)
            idx = max(0, min(idx, count - 1))
            return observations[idx]

        return {
            "min": observations[0],
            "max": observations[-1],
            "median": percentile(50),
            "p5": percentile(5),
            "p95": percentile(95),
            "sample_lowest": observations[:5],
            "sample_highest": observations[-5:],
            "observation_count": count,
        }

    def _get_top_sampled_markets(self) -> list[dict[str, Any]]:
        """Get top sampled markets by sample count"""
        if not self.sampled_market_history:
            return []

        # Sort by sample count descending
        sorted_markets = sorted(
            self.sampled_market_history.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )

        return [
            {
                "market_id": market_id,
                "sample_count": len(times),
            }
            for market_id, times in sorted_markets[:5]
        ]



