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
import csv
import json
import os
import signal
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.config import Config
from polysignal.storage.database import Database
from polysignal.models.signal import Signal, SignalSide, ComponentScores
from polysignal.models.risk import RiskAction, RiskDecision, RiskContext
from polysignal.models.market import Market
from polysignal.models.orderbook import OrderBookSnapshot

# Data providers
from polysignal.ingestion.data_provider_manager import DataProviderManager, DataMode

# WebSocket
from polysignal.ingestion.websocket_client import CLOBWebSocketClient, WebSocketConfig
from polysignal.ingestion.orderbook_cache import OrderBookCacheManager
from polysignal.ingestion.subscription_manager import SubscriptionManager
from polysignal.ingestion.websocket_message_handler import WSMessage

# Engines
from polysignal.engines.market_microstructure import MarketMicrostructureEngine
from polysignal.engines.resolution_lifecycle import ResolutionLifecycleEngine
from polysignal.engines.wallet_intelligence import WalletIntelligenceEngine
from polysignal.engines.event_intelligence import EventIntelligenceEngine

# Strategy
from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy
from polysignal.strategies.base import StrategyContext

# Risk
from polysignal.risk.risk_governor import RiskGovernor

# Paper Trader
from polysignal.execution.paper_trader import PaperTrader


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
    watchlist_file: Optional[str] = None  # Path to persistent_watchlist.csv
    alpha_candidates_file: Optional[str] = None  # Path to alpha_candidates.csv
    avoid_candidates_file: Optional[str] = None  # Path to avoid_candidates.csv
    trajectories_file: Optional[str] = None  # Path to market_trajectories.json
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
    end_time: Optional[datetime] = None
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
    hour_start: Optional[datetime] = None

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

    def _calculate_avg_latency(self) -> Optional[float]:
        """Calculate average LLM latency"""
        if not self.llm_latencies:
            return None
        return sum(self.llm_latencies) / len(self.llm_latencies)

    def _calculate_p95_latency(self) -> Optional[float]:
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


# =============================================================================
# Phase 5F.5 — Watchlist-Driven Monitoring
# =============================================================================

@dataclass
class WatchlistEntry:
    """Entry from persistent_watchlist.csv"""
    market_id: str
    normalized_question: str
    evidence_level: str  # strong, moderate, weak
    appearance_count: int
    avg_combined_ask: Optional[float]
    category: Optional[str]


@dataclass
class AlphaCandidate:
    """Entry from alpha_candidates.csv"""
    market_id: str
    normalized_question: str
    alpha_score: float
    category: Optional[str]
    combined_ask: Optional[float]
    event_score: Optional[float]
    near_miss_tier: Optional[str]


@dataclass
class AvoidCandidate:
    """Entry from avoid_candidates.csv"""
    market_id: str
    normalized_question: str
    avoid_score: float
    category: Optional[str]
    category_risk: Optional[str]
    avoid_reasons: list[str] = field(default_factory=list)


@dataclass
class TrajectoryObservation:
    """Single observation in market trajectory"""
    timestamp: str
    combined_ask: Optional[float] = None
    event_score: Optional[float] = None
    near_miss_tier: Optional[str] = None
    liquidity_score: Optional[float] = None
    suggested_mode: Optional[str] = None
    ambiguity_risk: Optional[float] = None
    source: str = "watchlist_monitoring"


@dataclass
class MarketTrajectory:
    """Market trajectory from market_trajectories.json"""
    market_id: str
    normalized_question: str
    observations: list[TrajectoryObservation] = field(default_factory=list)


class WatchlistLoader:
    """
    Load watchlist files for Phase 5F.5.

    IMPORTANT: This is for RESEARCH/MONITORING only.
    - Does NOT affect trading decisions
    - Does NOT modify Risk Governor
    - Does NOT trigger trades
    """

    def __init__(self, logger: Optional[Any] = None):
        self.logger = logger
        self._watchlist: dict[str, WatchlistEntry] = {}
        self._alpha_candidates: dict[str, AlphaCandidate] = {}
        self._avoid_candidates: dict[str, AvoidCandidate] = {}
        self._trajectories: dict[str, MarketTrajectory] = {}

    def load_watchlist(self, filepath: str) -> int:
        """Load persistent_watchlist.csv"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Watchlist file not found: {filepath}")
            return 0

        count = 0
        with open(filepath, "r") as f:
            # Skip header
            header = f.readline().strip().split(",")
            header_map = {h.strip(): i for i, h in enumerate(header)}

            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue

                try:
                    market_id = parts[0].strip()

                    # Get question
                    if "question" in header_map:
                        question = parts[header_map["question"]].strip() if len(parts) > header_map["question"] else ""
                    else:
                        question = ""

                    # Get evidence_level
                    if "evidence_level" in header_map:
                        evidence_level = parts[header_map["evidence_level"]].strip() if len(parts) > header_map["evidence_level"] else "weak"
                    else:
                        evidence_level = "weak"

                    # Get appearances
                    if "appearances" in header_map:
                        appearance_count = int(parts[header_map["appearances"]]) if parts[header_map["appearances"]].strip().isdigit() else 1
                    else:
                        appearance_count = 1

                    # Get avg_combined_ask
                    if "avg_combined_ask" in header_map:
                        avg_combined_ask = float(parts[header_map["avg_combined_ask"]]) if parts[header_map["avg_combined_ask"]].strip() else None
                    else:
                        avg_combined_ask = None

                    # Get category
                    if "category" in header_map:
                        category = parts[header_map["category"]].strip() if len(parts) > header_map["category"] else None
                    else:
                        category = None

                    entry = WatchlistEntry(
                        market_id=market_id,
                        normalized_question=question,
                        evidence_level=evidence_level,
                        appearance_count=appearance_count,
                        avg_combined_ask=avg_combined_ask,
                        category=category,
                    )
                    self._watchlist[entry.market_id] = entry
                    count += 1
                except (ValueError, IndexError) as e:
                    if self.logger:
                        self.logger(f"Skipping invalid watchlist line: {line[:50]}...")
                    continue

        if self.logger:
            self.logger(f"Loaded {count} watchlist entries from {filepath}")
        return count

    def load_alpha_candidates(self, filepath: str) -> int:
        """Load alpha_candidates.csv"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Alpha candidates file not found: {filepath}")
            return 0

        count = 0
        with open(filepath, "r") as f:
            header = f.readline().strip().split(",")
            header_map = {h.strip(): i for i, h in enumerate(header)}

            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue

                # Handle different CSV formats
                # Format 1: market_id,normalized_question,alpha_score,category,combined_ask,event_score,near_miss_tier
                # Format 2: market_id,matched_by,question,category,appearances,avg_combined_ask,avg_event_score,avg_ambiguity_risk,avg_volume,alpha_score,evidence_level,run_ids
                try:
                    market_id = parts[0].strip()

                    # Try to get alpha_score from different positions
                    if "alpha_score" in header_map:
                        alpha_score = float(parts[header_map["alpha_score"]]) if parts[header_map["alpha_score"]].strip() else 0.0
                    elif len(parts) > 2 and parts[2].strip().replace(".", "").replace("-", "").isdigit():
                        alpha_score = float(parts[2])
                    else:
                        alpha_score = 0.0

                    # Get question
                    if "question" in header_map:
                        question = parts[header_map["question"]].strip() if len(parts) > header_map["question"] else ""
                    else:
                        question = parts[1].strip() if len(parts) > 1 else ""

                    # Get category
                    if "category" in header_map:
                        category = parts[header_map["category"]].strip() if len(parts) > header_map["category"] else None
                    else:
                        category = parts[3].strip() if len(parts) > 3 else None

                    # Get combined_ask
                    if "avg_combined_ask" in header_map:
                        combined_ask = float(parts[header_map["avg_combined_ask"]]) if parts[header_map["avg_combined_ask"]].strip() else None
                    elif len(parts) > 4 and parts[4].strip():
                        combined_ask = float(parts[4]) if parts[4].strip().replace(".", "").isdigit() else None
                    else:
                        combined_ask = None

                    # Get event_score
                    if "avg_event_score" in header_map:
                        event_score = float(parts[header_map["avg_event_score"]]) if parts[header_map["avg_event_score"]].strip() else None
                    elif len(parts) > 5 and parts[5].strip():
                        event_score = float(parts[5]) if parts[5].strip().replace(".", "").isdigit() else None
                    else:
                        event_score = None

                    entry = AlphaCandidate(
                        market_id=market_id,
                        normalized_question=question,
                        alpha_score=alpha_score,
                        category=category,
                        combined_ask=combined_ask,
                        event_score=event_score,
                        near_miss_tier=None,  # Not in this format
                    )
                    self._alpha_candidates[entry.market_id] = entry
                    count += 1
                except (ValueError, IndexError) as e:
                    if self.logger:
                        self.logger(f"Skipping invalid alpha candidate line: {line[:50]}...")
                    continue

        if self.logger:
            self.logger(f"Loaded {count} alpha candidates from {filepath}")
        return count

    def load_avoid_candidates(self, filepath: str) -> int:
        """Load avoid_candidates.csv"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Avoid candidates file not found: {filepath}")
            return 0

        count = 0
        with open(filepath, "r") as f:
            header = f.readline().strip().split(",")
            header_map = {h.strip(): i for i, h in enumerate(header)}

            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue

                try:
                    market_id = parts[0].strip()

                    # Get question
                    if "question" in header_map:
                        question = parts[header_map["question"]].strip() if len(parts) > header_map["question"] else ""
                    else:
                        question = ""

                    # Get avoid_score
                    if "avoid_score" in header_map:
                        avoid_score = float(parts[header_map["avoid_score"]]) if parts[header_map["avoid_score"]].strip() else 0.0
                    else:
                        avoid_score = 0.0

                    # Get category
                    if "category" in header_map:
                        category = parts[header_map["category"]].strip() if len(parts) > header_map["category"] else None
                    else:
                        category = None

                    # Get reasons
                    avoid_reasons = []
                    if "reasons" in header_map:
                        reasons_str = parts[header_map["reasons"]].strip().strip('"').strip("'") if len(parts) > header_map["reasons"] else ""
                        avoid_reasons = [r.strip() for r in reasons_str.split("|") if r.strip()]

                    # Determine category_risk from reasons
                    category_risk = "medium"
                    if "high_ambiguity" in avoid_reasons or "forbidden_category" in avoid_reasons:
                        category_risk = "high"

                    entry = AvoidCandidate(
                        market_id=market_id,
                        normalized_question=question,
                        avoid_score=avoid_score,
                        category=category,
                        category_risk=category_risk,
                        avoid_reasons=avoid_reasons,
                    )
                    self._avoid_candidates[entry.market_id] = entry
                    count += 1
                except (ValueError, IndexError) as e:
                    if self.logger:
                        self.logger(f"Skipping invalid avoid candidate line: {line[:50]}...")
                    continue

        if self.logger:
            self.logger(f"Loaded {count} avoid candidates from {filepath}")
        return count

    def load_trajectories(self, filepath: str) -> int:
        """Load market_trajectories.json"""
        if not Path(filepath).exists():
            if self.logger:
                self.logger(f"Trajectories file not found: {filepath}")
            return 0

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            count = 0
            for market_id, traj_data in data.items():
                observations = []
                for obs_data in traj_data.get("observations", []):
                    obs = TrajectoryObservation(
                        timestamp=obs_data.get("timestamp", ""),
                        combined_ask=obs_data.get("combined_ask"),
                        event_score=obs_data.get("event_score"),
                        near_miss_tier=obs_data.get("near_miss_tier"),
                        liquidity_score=obs_data.get("liquidity_score"),
                        suggested_mode=obs_data.get("suggested_mode"),
                        ambiguity_risk=obs_data.get("ambiguity_risk"),
                        source=obs_data.get("source", "watchlist_monitoring"),
                    )
                    observations.append(obs)

                trajectory = MarketTrajectory(
                    market_id=market_id,
                    normalized_question=traj_data.get("normalized_question", ""),
                    observations=observations,
                )
                self._trajectories[market_id] = trajectory
                count += 1

            if self.logger:
                self.logger(f"Loaded {count} trajectories from {filepath}")
            return count

        except Exception as e:
            if self.logger:
                self.logger(f"Error loading trajectories: {e}")
            return 0

    @property
    def watchlist(self) -> dict[str, WatchlistEntry]:
        return self._watchlist

    @property
    def alpha_candidates(self) -> dict[str, AlphaCandidate]:
        return self._alpha_candidates

    @property
    def avoid_candidates(self) -> dict[str, AvoidCandidate]:
        return self._avoid_candidates

    @property
    def trajectories(self) -> dict[str, MarketTrajectory]:
        return self._trajectories


class MarketPrioritizer:
    """
    Prioritize markets for scanning based on watchlist.

    IMPORTANT: This affects scan order ONLY.
    - Does NOT affect trading decisions
    - Does NOT modify Risk Governor
    - Does NOT trigger trades
    """

    MIN_DISCOVERY_RATIO = 0.1  # Minimum 10% new market discovery

    def __init__(
        self,
        watchlist: dict[str, WatchlistEntry],
        alpha_candidates: dict[str, AlphaCandidate],
        watchlist_priority_ratio: float = 0.6,
        discovery_ratio: float = 0.2,
        alpha_priority_ratio: float = 0.0,
        alpha_repeat_target: int = 3,
    ):
        self.watchlist = watchlist
        self.alpha_candidates = alpha_candidates
        self.watchlist_priority_ratio = watchlist_priority_ratio
        self.discovery_ratio = max(discovery_ratio, self.MIN_DISCOVERY_RATIO)
        self.alpha_priority_ratio = max(0.0, min(alpha_priority_ratio, 0.8))
        self.alpha_repeat_target = alpha_repeat_target
        self._alpha_observation_counts: dict[str, int] = {}

    def update_alpha_observations(self, observation_counts: dict[str, int]) -> None:
        """Update alpha observation counts for deprioritization logic."""
        self._alpha_observation_counts = dict(observation_counts)

    def prioritize(
        self,
        all_markets: list[Market],
        max_markets: int,
    ) -> tuple[list[Market], dict[str, str]]:
        """
        Prioritize markets for scanning.

        Returns:
            Tuple of (prioritized_markets, market_sources)
            where market_sources[market_id] = "watchlist" | "alpha" | "discovery"
        """
        market_sources: dict[str, str] = {}

        # Calculate target counts with alpha priority.
        # IMPORTANT: priority ratios only affect scan order. They do not create
        # signals, alter Risk Governor inputs, or trigger PaperTrader.
        if self.alpha_priority_ratio > 0:
            alpha_slot_target = int(max_markets * self.alpha_priority_ratio)
            alphas_needing_obs = self._count_alphas_needing_observations(all_markets)
            alpha_count = min(alpha_slot_target, alphas_needing_obs)
            alpha_count = max(0, alpha_count)

            watchlist_count = int(max_markets * self.watchlist_priority_ratio)
            min_discovery_count = max(1, int(max_markets * self.MIN_DISCOVERY_RATIO))
            remaining_after_alpha = max_markets - alpha_count
            discovery_count = min(min_discovery_count, remaining_after_alpha)
            watchlist_count = max(0, max_markets - alpha_count - discovery_count)
            watchlist_count = min(watchlist_count, int(max_markets * self.watchlist_priority_ratio))

            # Any extra capacity after capped watchlist slots goes to discovery.
            discovery_count = max_markets - alpha_count - watchlist_count
        else:
            # Original behavior: no alpha priority
            watchlist_count = int(max_markets * self.watchlist_priority_ratio)
            alpha_count = int(max_markets * (1 - self.watchlist_priority_ratio - self.discovery_ratio))
            discovery_count = max_markets - watchlist_count - alpha_count

            # Ensure minimum discovery
            if discovery_count < int(max_markets * self.MIN_DISCOVERY_RATIO):
                discovery_count = int(max_markets * self.MIN_DISCOVERY_RATIO)
                remaining = max_markets - discovery_count
                watchlist_count = int(remaining * 0.7)
                alpha_count = remaining - watchlist_count

        prioritized: list[Market] = []

        # 1. Add watchlist markets (by evidence level)
        watchlist_markets = []
        for market in all_markets:
            if market.market_id in self.watchlist:
                entry = self.watchlist[market.market_id]
                priority = self._evidence_priority(entry.evidence_level)
                watchlist_markets.append((market, priority))

        # Sort by priority (higher first)
        watchlist_markets.sort(key=lambda x: x[1], reverse=True)
        for market, _ in watchlist_markets[:watchlist_count]:
            prioritized.append(market)
            market_sources[market.market_id] = "watchlist"

        # 2. Add alpha candidates (not already in watchlist)
        # When alpha_priority_ratio > 0, prioritize alphas that still need observations
        alpha_markets = []
        for market in all_markets:
            if market.market_id not in market_sources and market.market_id in self.alpha_candidates:
                candidate = self.alpha_candidates[market.market_id]
                obs_count = self._alpha_observation_counts.get(market.market_id, 0)

                # Skip alphas that have reached the repeat target (deprioritize)
                if self.alpha_priority_ratio > 0 and obs_count >= self.alpha_repeat_target:
                    continue

                priority = self._tier_priority(candidate.near_miss_tier)
                # Boost priority for alphas with fewer observations (need more data)
                if self.alpha_priority_ratio > 0 and obs_count < self.alpha_repeat_target:
                    priority += (self.alpha_repeat_target - obs_count) * 10
                alpha_markets.append((market, priority))

        alpha_markets.sort(key=lambda x: x[1], reverse=True)
        for market, _ in alpha_markets[:alpha_count]:
            prioritized.append(market)
            market_sources[market.market_id] = "alpha"

        # 3. Add discovery markets (not already prioritized)
        discovery_markets = [m for m in all_markets if m.market_id not in market_sources]
        # Shuffle for diversity
        import random
        random.shuffle(discovery_markets)

        for market in discovery_markets[:discovery_count]:
            prioritized.append(market)
            market_sources[market.market_id] = "discovery"

        # 4. Fill remaining with any markets
        remaining_count = max_markets - len(prioritized)
        if remaining_count > 0:
            remaining_markets = [m for m in all_markets if m.market_id not in market_sources]
            for market in remaining_markets[:remaining_count]:
                prioritized.append(market)
                market_sources[market.market_id] = "discovery"

        return prioritized, market_sources

    def _count_alphas_needing_observations(self, markets: Optional[list[Market]] = None) -> int:
        """Count alpha candidates that haven't reached the repeat target."""
        available_ids = {m.market_id for m in markets} if markets is not None else None
        count = 0
        for market_id in self.alpha_candidates:
            if available_ids is not None and market_id not in available_ids:
                continue
            obs_count = self._alpha_observation_counts.get(market_id, 0)
            if obs_count < self.alpha_repeat_target:
                count += 1
        return count

    def _evidence_priority(self, evidence_level: str) -> int:
        """Convert evidence level to priority score"""
        priorities = {"strong": 100, "moderate": 70, "weak": 40}
        return priorities.get(evidence_level.lower(), 30)

    def _tier_priority(self, tier: Optional[str]) -> int:
        """Convert near_miss_tier to priority score"""
        if not tier:
            return 20
        priorities = {"Tier1": 90, "Tier2": 70, "Tier3": 50, "Tier4": 30}
        return priorities.get(tier, 20)


class AvoidAnnotator:
    """
    Annotate markets with avoid information.

    IMPORTANT: This is for RESEARCH ANNOTATION ONLY.
    - Does NOT affect Risk Governor score
    - Does NOT add hard_reject reasons
    - Does NOT block paper trades
    - Does NOT change signal action
    - Avoid candidates are NOT hard forbidden
    """

    def __init__(self, avoid_candidates: dict[str, AvoidCandidate]):
        self.avoid_candidates = avoid_candidates

    def annotate(self, market_id: str) -> Optional[dict[str, Any]]:
        """
        Get avoid annotation for a market.

        Returns:
            Annotation dict if market is in avoid list, None otherwise.
            The annotation is for logging/reporting only.
        """
        if market_id not in self.avoid_candidates:
            return None

        candidate = self.avoid_candidates[market_id]
        return {
            "is_avoid_candidate": True,
            "avoid_score": candidate.avoid_score,
            "category_risk": candidate.category_risk,
            "avoid_reasons": candidate.avoid_reasons,
            # Explicitly state this is NOT a block
            "is_hard_forbidden": False,  # Always False - avoid is NOT hard forbidden
            "annotation_type": "research_only",
        }


class TrajectoryTracker:
    """
    Track market trajectory changes during monitoring.

    IMPORTANT: This is for RESEARCH/TRACKING only.
    - Does NOT affect trading decisions
    - Output is written to current run directory only
    """

    def __init__(
        self,
        trajectories: dict[str, MarketTrajectory],
        track_enabled: bool = True,
    ):
        self.trajectories = trajectories
        self.track_enabled = track_enabled
        self._updates: dict[str, TrajectoryObservation] = {}
        self._changes: list[dict[str, Any]] = []

    def track(
        self,
        market_id: str,
        combined_ask: Optional[float] = None,
        event_score: Optional[float] = None,
        near_miss_tier: Optional[str] = None,
        liquidity_score: Optional[float] = None,
        suggested_mode: Optional[str] = None,
        ambiguity_risk: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Track observation for a market.

        Returns:
            Change dict if significant change detected, None otherwise.
        """
        if not self.track_enabled:
            return None

        now = datetime.utcnow().isoformat()

        # Create observation
        observation = TrajectoryObservation(
            timestamp=now,
            combined_ask=combined_ask,
            event_score=event_score,
            near_miss_tier=near_miss_tier,
            liquidity_score=liquidity_score,
            suggested_mode=suggested_mode,
            ambiguity_risk=ambiguity_risk,
            source="watchlist_monitoring",
        )

        # Store update
        self._updates[market_id] = observation

        # Detect changes
        change = self._detect_change(market_id, observation)
        if change:
            self._changes.append(change)

        return change

    def _detect_change(
        self,
        market_id: str,
        current: TrajectoryObservation,
    ) -> Optional[dict[str, Any]]:
        """Detect significant changes from previous observation"""
        if market_id not in self.trajectories:
            return None

        trajectory = self.trajectories[market_id]
        if not trajectory.observations:
            return None

        prev = trajectory.observations[-1]
        changes = []

        # combined_ask change (> 1%)
        if prev.combined_ask is not None and current.combined_ask is not None:
            delta = current.combined_ask - prev.combined_ask
            if abs(delta) > 0.01:
                changes.append({
                    "type": "combined_ask_change",
                    "from": prev.combined_ask,
                    "to": current.combined_ask,
                    "delta": round(delta, 4),
                })

        # near_miss_tier change
        if prev.near_miss_tier != current.near_miss_tier:
            changes.append({
                "type": "tier_change",
                "from": prev.near_miss_tier,
                "to": current.near_miss_tier,
            })

        # suggested_mode change
        if prev.suggested_mode != current.suggested_mode:
            changes.append({
                "type": "mode_change",
                "from": prev.suggested_mode,
                "to": current.suggested_mode,
            })

        if not changes:
            return None

        return {
            "market_id": market_id,
            "timestamp": current.timestamp,
            "changes": changes,
        }

    def get_updates(self) -> dict[str, TrajectoryObservation]:
        """Get all trajectory updates"""
        return self._updates

    def get_changes(self) -> list[dict[str, Any]]:
        """Get all detected changes"""
        return self._changes

    def to_trajectory_update_json(self) -> dict[str, Any]:
        """Convert updates to JSON-serializable dict for output"""
        trajectories_out = {}
        for market_id, obs in self._updates.items():
            trajectories_out[market_id] = {
                "market_id": market_id,
                "observation": {
                    "timestamp": obs.timestamp,
                    "combined_ask": obs.combined_ask,
                    "event_score": obs.event_score,
                    "near_miss_tier": obs.near_miss_tier,
                    "liquidity_score": obs.liquidity_score,
                    "suggested_mode": obs.suggested_mode,
                    "ambiguity_risk": obs.ambiguity_risk,
                    "source": obs.source,
                },
            }

        return {
            "updated_at": datetime.utcnow().isoformat(),
            "markets_updated": list(self._updates.keys()),
            "new_observations_count": len(self._updates),
            "changes_detected": len(self._changes),
            "changes": self._changes,
            "trajectories": trajectories_out,
        }


class WatchlistMonitoringStats:
    """Statistics for watchlist-driven monitoring"""

    def __init__(self):
        self.watchlist_markets_loaded: int = 0
        self.alpha_candidates_loaded: int = 0
        self.avoid_candidates_loaded: int = 0
        self.trajectories_loaded: int = 0

        self.watchlist_markets_scanned: int = 0
        self.alpha_markets_scanned: int = 0
        self.discovery_markets_scanned: int = 0

        self.avoid_annotations_count: int = 0
        self.trajectory_updates_count: int = 0
        self.trajectory_changes_count: int = 0

        self.market_sources: dict[str, str] = {}  # market_id -> source
        self.avoid_annotations: list[dict[str, Any]] = []
        self.trajectory_changes: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output"""
        return {
            "watchlist_stats": {
                "total_watchlist_markets": self.watchlist_markets_loaded,
                "watchlist_markets_scanned": self.watchlist_markets_scanned,
                "alpha_candidates_scanned": self.alpha_markets_scanned,
                "avoid_candidates_annotated": self.avoid_annotations_count,
                "discovery_markets_scanned": self.discovery_markets_scanned,
            },
            "trajectory_stats": {
                "trajectories_loaded": self.trajectories_loaded,
                "updates_count": self.trajectory_updates_count,
                "changes_count": self.trajectory_changes_count,
            },
            "top_changes": self.trajectory_changes[:10],
            "avoid_annotations": self.avoid_annotations[:10],
        }


class PaperTradingRunner:
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
        self.stats: Optional[RunStatistics] = None
        self.db: Optional[Database] = None
        self.run_dir: Optional[Path] = None
        self.events_file: Optional[Any] = None
        self._shutdown_requested = False
        self._scan_count = 0

        # Data provider
        self.data_provider: Optional[DataProviderManager] = None

        # WebSocket components
        self.ws_client: Optional[CLOBWebSocketClient] = None
        self.ws_cache_manager: Optional[OrderBookCacheManager] = None
        self.ws_subscription_manager: Optional[SubscriptionManager] = None
        self._ws_message_count: int = 0
        self._ws_connected: bool = False

        # Engines
        self.microstructure_engine: Optional[MarketMicrostructureEngine] = None
        self.lifecycle_engine: Optional[ResolutionLifecycleEngine] = None
        self.wallet_engine: Optional[WalletIntelligenceEngine] = None
        self.event_engine: Optional[EventIntelligenceEngine] = None

        # Strategy
        self.strategy: Optional[YesNoMispricingStrategy] = None

        # Risk Governor
        self.risk_governor: Optional[RiskGovernor] = None

        # Paper Trader
        self.paper_trader: Optional[PaperTrader] = None

        # Watchlist-Driven Monitoring (Phase 5F.5)
        # These are for RESEARCH/MONITORING only - do NOT affect trading
        self.watchlist_loader: Optional[WatchlistLoader] = None
        self.market_prioritizer: Optional[MarketPrioritizer] = None
        self.avoid_annotator: Optional[AvoidAnnotator] = None
        self.trajectory_tracker: Optional[TrajectoryTracker] = None
        self.watchlist_stats: Optional[WatchlistMonitoringStats] = None
        self._watchlist_events_file: Optional[Any] = None

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
            start_time=datetime.utcnow(),
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
        self.stats.hour_start = datetime.utcnow()
        self.stats.llm_sampling_enabled = self.run_config.enable_llm_sampling
        self.stats.llm_sampling_strategy = self.run_config.llm_sampling_strategy
        self.stats.llm_sampling_cooldown_minutes = self.run_config.llm_sampling_cooldown_minutes

        # Create run directory
        self.run_dir = Path("runs") / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Open events file
        self.events_file = open(self.run_dir / "events.jsonl", "w")

        # Open watchlist events file (Phase 5F.5)
        if self.run_config.monitor_mode != "default" and (
            self.run_config.watchlist_file or self.run_config.alpha_candidates_file
        ):
            self._watchlist_events_file = open(self.run_dir / "watchlist_events.jsonl", "w")

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
                "time": datetime.utcnow().isoformat(),
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
        llm_provider_instance = None
        if self.run_config.llm_provider == "xfyun_anthropic":
            from polysignal.llm.xfyun_anthropic_provider import (
                XFyunAnthropicProvider,
                XFyunAnthropicConfig,
            )
            llm_provider_instance = XFyunAnthropicProvider()
            self._log_event("llm_provider_init", "init", f"Initialized XFyunAnthropicProvider")
        elif self.run_config.llm_provider == "sensenova":
            from polysignal.llm.sensenova_provider import (
                SenseNovaProvider,
                SenseNovaConfig,
            )
            llm_provider_instance = SenseNovaProvider()
            self._log_event("llm_provider_init", "init", f"Initialized SenseNovaProvider")
        else:
            from polysignal.llm.mock_provider import MockLLMProvider
            llm_provider_instance = MockLLMProvider()
            self._log_event("llm_provider_init", "init", f"Initialized MockLLMProvider")

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
        self._ws_message_count += 1
        self.stats.websocket_messages += 1

    async def _on_websocket_disconnect(self) -> None:
        """Callback for WebSocket disconnection"""
        self._ws_connected = False
        self.stats.websocket_disconnects += 1
        self.stats.websocket_reconnects += 1
        # Track reconnect success (will be updated on next connect)
        self._ws_reconnect_pending = True
        self._log_event("websocket_disconnected", "websocket", "WebSocket disconnected")

    async def _on_websocket_connect(self) -> None:
        """Callback for WebSocket connection"""
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
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
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
        end_time = datetime.utcnow() + timedelta(minutes=self.run_config.duration_minutes)

        # Start WebSocket connection if enabled
        if self.ws_client and self.run_config.use_websocket:
            connected = await self.ws_client.connect()
            if connected:
                self._ws_connected = True
                self._log_event("websocket_connected", "websocket", "WebSocket connection established")
            else:
                self._log_event("websocket_connect_failed", "websocket", "WebSocket connection failed, using REST fallback")

        while datetime.utcnow() < end_time and not self._shutdown_requested:
            self._scan_count += 1

            # Check hourly rate limits
            self._check_hourly_limits()

            # Run scan
            scan_start = datetime.utcnow()
            scan_id = f"{self.stats.run_id}_scan_{self._scan_count}"

            try:
                await self._run_scan(scan_id)
            except Exception as e:
                self._log_event("scan_error", "error", f"Scan error: {e}")
                self.stats.errors.append({
                    "time": datetime.utcnow().isoformat(),
                    "type": "scan_error",
                    "message": str(e),
                })

            scan_latency = (datetime.utcnow() - scan_start).total_seconds()

            # Print progress
            remaining = (end_time - datetime.utcnow()).total_seconds() / 60
            self._print_progress(remaining, scan_latency)

            # Wait for next scan
            if datetime.utcnow() < end_time and not self._shutdown_requested:
                await asyncio.sleep(self.run_config.scan_interval_seconds)

        # Set end time
        self.stats.end_time = datetime.utcnow()
        self.stats.status = "completed" if not self._shutdown_requested else "shutdown"

    async def _run_scan(self, scan_id: str) -> None:
        """Run a single market scan with real data"""
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
                        for market_id, source in market_sources.items():
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
        avoid_annotation: Optional[dict[str, Any]],
    ) -> None:
        """
        Log watchlist monitoring event.

        IMPORTANT: This is for RESEARCH LOGGING only.
        Does NOT affect trading decisions.
        """
        if not self._watchlist_events_file:
            return

        event = {
            "event_time": datetime.utcnow().isoformat(),
            "event_type": "watchlist_scan",
            "market_id": market.market_id,
            "question": market.title[:200] if market.title else None,
            "source": source,  # "watchlist", "alpha", or "discovery"
            "combined_ask": orderbook.combined_ask,
            "spread": orderbook.spread,
            "total_volume": market.total_volume_usd,
            "avoid_annotation": avoid_annotation,
        }

        self._watchlist_events_file.write(json.dumps(event) + "\n")
        self._watchlist_events_file.flush()

    async def _run_llm_sampling(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> None:
        """
        Run LLM sampling for selected markets.

        This is research/intelligence logging only - NO TRADING.
        """
        # Select candidates
        candidates = self._select_llm_sampling_candidates(markets, orderbooks)

        if not candidates:
            self._log_event("llm_sampling_no_candidates", "llm_sampling", "No eligible candidates for LLM sampling")
            return

        self._log_event("llm_sampling_start", "llm_sampling", f"Starting LLM sampling for {len(candidates)} markets")

        for market, orderbook in candidates:
            # Check if this is a repeated sample
            is_repeated = market.market_id in self.stats.sampled_market_history

            # Perform LLM sampling
            result = await self._perform_llm_sampling(market, orderbook)

            # Update sampling history
            now = datetime.utcnow()
            if market.market_id not in self.stats.sampled_market_history:
                self.stats.sampled_market_history[market.market_id] = []
                self.stats.unique_sampled_markets += 1
            else:
                self.stats.repeated_sampled_markets += 1
            self.stats.sampled_market_history[market.market_id].append(now)

            # Track sampled markets
            self.stats.sampled_markets_count += 1
            if len(self.stats.sampled_markets_examples) < 5:
                self.stats.sampled_markets_examples.append({
                    "market_id": result["market_id"],
                    "question": result["question"][:100] if result["question"] else None,
                    "success": result["success"],
                    "event_score": result["event_score"],
                    "latency_seconds": result["latency_seconds"],
                    "repeated_market": is_repeated,
                    "market_sample_count": len(self.stats.sampled_market_history[market.market_id]),
                })

            # Log event with diversity fields
            self._log_event(
                "llm_sampling_assessment",
                "llm_sampling",
                f"LLM sampling for {market.market_id}: {'success' if result['success'] else 'failed'}",
                {
                    "market_id": result["market_id"],
                    "question": result["question"],
                    "combined_ask": result["combined_ask"],
                    "volume_24h": result["volume_24h"],
                    "success": result["success"],
                    "latency_seconds": result["latency_seconds"],
                    "event_score": result["event_score"],
                    "confidence": result["confidence"],
                    "suggested_mode": result["suggested_mode"],
                    "evidence_strength": result["evidence_strength"],
                    "market_relevance": result["market_relevance"],
                    "ambiguity_risk": result["ambiguity_risk"],
                    "risk_flags": result["risk_flags"],
                    "error": result["error"],
                    # Diversity fields
                    "sampling_strategy": self.run_config.llm_sampling_strategy,
                    "repeated_market": is_repeated,
                    "market_sample_count": len(self.stats.sampled_market_history[market.market_id]),
                    "cooldown_applied": False,  # Already filtered by cooldown in selection
                }
            )

    async def _get_orderbook(self, market: Market) -> Optional[OrderBookSnapshot]:
        """Get orderbook for a market, with WebSocket cache and fallback logic"""

        # Try WebSocket cache first (if enabled and connected)
        if self.ws_client and self._ws_connected and self.ws_cache_manager:
            if market.yes_token_address and market.no_token_address:
                cached_orderbook = self.ws_cache_manager.get_market_orderbook(
                    market_id=market.market_id,
                    yes_token_id=market.yes_token_address,
                    no_token_id=market.no_token_address,
                )

                if cached_orderbook and not cached_orderbook.is_stale:
                    # Cache hit - use WebSocket data
                    self.stats.websocket_cache_hits += 1
                    self._log_event("websocket_cache_hit", "websocket", f"Cache hit for {market.market_id}")
                    return cached_orderbook
                elif cached_orderbook and cached_orderbook.is_stale:
                    # Cache stale - fallback to REST
                    self.stats.websocket_stale_fallbacks += 1
                    self._log_event("websocket_cache_stale", "websocket", f"Cache stale for {market.market_id}")
                else:
                    # Cache miss - fallback to REST
                    self.stats.websocket_cache_misses += 1

        # Fallback to REST API
        try:
            orderbook = await self.data_provider.get_orderbook(market.market_id)
            if orderbook:
                self.stats.rest_fallbacks += 1
            return orderbook
        except Exception as e:
            self._log_event("orderbook_error", "error", f"Orderbook fetch error for {market.market_id}: {e}")
            self.stats.api_errors += 1

            if self.run_config.data_mode == "hybrid":
                self.stats.api_fallbacks += 1

            return None

    async def _process_market(self, market: Market, orderbook: OrderBookSnapshot) -> Optional[Signal]:
        """Process a market through the intelligence pipeline using YesNoMispricingStrategy"""
        # Ensure orderbook metrics are calculated
        orderbook.calculate_metrics()

        # Record combined_ask for distribution tracking
        if orderbook.combined_ask is not None:
            self.stats.combined_ask_observations.append(orderbook.combined_ask)

        # Run through Market Microstructure Engine for component scores
        micro_result = self.microstructure_engine.analyze_snapshot(orderbook)

        # Run through Resolution & Lifecycle Engine
        lifecycle_result = self.lifecycle_engine.assess(market)

        # Run through Wallet Intelligence Engine (mock for now)
        wallet_result = self.wallet_engine.assess(market, [])

        # Run through Event Intelligence Engine (mock LLM)
        event_result = await self.event_engine.assess_async(market)

        # Build component scores
        component_scores = ComponentScores(
            microstructure_score=micro_result.microstructure_score,
            liquidity_score=micro_result.liquidity_score,
            lifecycle_score=lifecycle_result.lifecycle_score,
            wallet_score=wallet_result.wallet_score,
            event_score=event_result.event_score,
        )

        # Create strategy context
        context = StrategyContext(
            market=market,
            orderbook=orderbook,
            component_scores=component_scores,
        )

        # Use YesNoMispricingStrategy to compute signal
        signal = self.strategy.compute_signal(context)

        return signal

    def _select_llm_sampling_candidates(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> list[tuple[Market, OrderBookSnapshot]]:
        """
        Select candidate markets for LLM sampling.

        Selection criteria:
        - Market status is OPEN
        - Not in forbidden category
        - Not ambiguous
        - Sufficient liquidity (volume >= llm_sampling_min_volume)
        - Orderbook available

        Strategy:
        - top_liquidity: Select markets with highest volume
        - top_liquidity_or_near_miss: Prefer markets close to mispricing threshold
        - random: Random selection from eligible markets
        - diversified: Prioritize unsampled markets, spread across categories

        Diversity features:
        - Cooldown: Markets sampled within cooldown period are skipped
        - Max repeats: Markets exceeding max_repeats_per_market are skipped
        - Fallback: If no candidates, allow random selection from all eligible

        Returns:
            List of (market, orderbook) tuples for LLM sampling
        """
        candidates = []
        now = datetime.utcnow()
        cooldown_delta = timedelta(minutes=self.run_config.llm_sampling_cooldown_minutes)

        for market in markets:
            # Check market eligibility
            # Note: For LLM sampling, we don't require is_auto_allowed() since we're not trading
            # We only check: OPEN status, not ambiguous, has orderbook
            # Use lowercase comparison since MarketStatus.OPEN.value == "open"
            status_ok = market.status == "open" or (hasattr(market.status, 'value') and market.status.value == "open")
            if not status_ok:
                continue
            if market.is_ambiguous:
                continue

            # Check volume (use total_volume_usd since volume_24h_usd is often not populated)
            volume = market.total_volume_usd or market.volume_24h_usd or 0
            if volume < self.run_config.llm_sampling_min_volume:
                continue

            # Get orderbook
            orderbook = orderbooks.get(market.market_id)
            if not orderbook:
                continue

            # Check cooldown and max repeats
            sample_history = self.stats.sampled_market_history.get(market.market_id, [])
            sample_count = len(sample_history)

            # Check if market exceeds max repeats
            if sample_count >= self.run_config.llm_sampling_max_repeats_per_market:
                continue

            # Check if market is in cooldown
            if sample_history:
                last_sample = sample_history[-1]
                if now - last_sample < cooldown_delta:
                    continue

            candidates.append((market, orderbook, volume))

        if not candidates:
            return []

        # Apply selection strategy
        if self.run_config.llm_sampling_strategy == "top_liquidity":
            # Sort by volume descending
            candidates.sort(key=lambda x: x[2], reverse=True)
            selected = candidates[:self.run_config.llm_sampling_per_scan]

        elif self.run_config.llm_sampling_strategy == "top_liquidity_or_near_miss":
            # Prefer markets close to mispricing threshold (combined_ask near 0.985)
            def near_miss_score(item):
                market, orderbook, volume = item
                if orderbook.combined_ask is None:
                    return (0, 0)  # No score, low priority
                # Score based on distance from 0.985 (mispricing threshold)
                # Closer to threshold = higher priority
                distance = abs(orderbook.combined_ask - 0.985)
                # Also consider volume for tie-breaking
                return (1.0 - distance, volume)

            candidates.sort(key=near_miss_score, reverse=True)
            selected = candidates[:self.run_config.llm_sampling_per_scan]

        elif self.run_config.llm_sampling_strategy == "diversified":
            # Prioritize unsampled markets, then by category spread
            def diversified_score(item):
                market, orderbook, volume = item
                # Check if never sampled
                sample_count = len(self.stats.sampled_market_history.get(market.market_id, []))
                never_sampled = sample_count == 0

                # Get category for spreading (use market.category if available)
                category = getattr(market, 'category', 'unknown') or 'unknown'

                # Score: never sampled first, then by volume
                return (never_sampled, volume)

            candidates.sort(key=diversified_score, reverse=True)
            selected = candidates[:self.run_config.llm_sampling_per_scan]

        else:  # random
            import random
            selected = random.sample(
                candidates,
                min(self.run_config.llm_sampling_per_scan, len(candidates))
            )

        return [(m, o) for m, o, _ in selected]

    async def _perform_llm_sampling(
        self,
        market: Market,
        orderbook: OrderBookSnapshot,
    ) -> dict[str, Any]:
        """
        Perform LLM sampling for a single market.

        This is research/intelligence logging only - NO TRADING.

        Returns:
            Sampling result dict with event analysis data
        """
        import time

        result = {
            "market_id": market.market_id,
            "question": market.title,
            "combined_ask": orderbook.combined_ask,
            "volume_24h": market.volume_24h_usd,
            "success": False,
            "latency_seconds": None,
            "event_score": None,
            "confidence": None,
            "suggested_mode": None,
            "evidence_strength": None,
            "market_relevance": None,
            "ambiguity_risk": None,
            "risk_flags": [],
            "error": None,
        }

        # Check rate limit
        if self.stats.llm_calls_this_hour >= self.run_config.max_llm_calls_per_hour:
            result["error"] = "rate_limit_exceeded"
            result["risk_flags"] = ["llm_rate_limit_exceeded"]
            self.stats.llm_sampling_fallback_count += 1
            return result

        # Check LLM provider
        if self.run_config.llm_provider == "mock":
            result["error"] = "mock_provider_no_real_call"
            result["risk_flags"] = ["llm_mock_provider"]
            return result

        try:
            self.stats.llm_sampling_calls_attempted += 1
            self.stats.llm_calls_this_hour += 1

            start_time = time.time()

            # Call EventIntelligenceEngine for LLM assessment
            event_result = await self.event_engine.assess_async(market)

            latency = time.time() - start_time
            result["latency_seconds"] = latency
            self.stats.llm_latencies.append(latency)

            # Extract results
            result["event_score"] = event_result.event_score
            result["confidence"] = event_result.confidence
            result["suggested_mode"] = event_result.suggested_mode
            result["evidence_strength"] = event_result.evidence_strength
            result["market_relevance"] = event_result.market_relevance
            result["ambiguity_risk"] = event_result.ambiguity_risk
            result["risk_flags"] = list(event_result.risk_flags)

            # Check for forbidden trading fields in LLM output
            forbidden_fields = {"side", "size", "order", "position", "buy", "sell", "action"}
            if hasattr(event_result, "raw_response") and event_result.raw_response:
                raw = event_result.raw_response.lower() if isinstance(event_result.raw_response, str) else ""
                for field in forbidden_fields:
                    if field in raw:
                        result["risk_flags"].append("llm_forbidden_trading_instruction")

            # Track success/failure
            if event_result.confidence > 0:
                result["success"] = True
                self.stats.llm_sampling_calls_succeeded += 1
                self.stats.llm_successes += 1
            else:
                result["error"] = "low_confidence"
                self.stats.llm_sampling_calls_failed += 1
                self.stats.llm_failures += 1

        except asyncio.TimeoutError:
            result["error"] = "timeout"
            result["risk_flags"] = ["llm_timeout"]
            self.stats.llm_sampling_timeout_count += 1
            self.stats.llm_sampling_calls_failed += 1
            self.stats.llm_failures += 1

        except json.JSONDecodeError as e:
            result["error"] = f"invalid_json: {str(e)[:50]}"
            result["risk_flags"] = ["llm_invalid_json"]
            self.stats.llm_sampling_invalid_json_count += 1
            self.stats.llm_sampling_calls_failed += 1
            self.stats.llm_failures += 1

        except Exception as e:
            error_str = str(e).lower()
            result["error"] = f"error: {str(e)[:100]}"
            result["risk_flags"] = ["llm_error"]
            self.stats.llm_sampling_calls_failed += 1
            self.stats.llm_failures += 1

            # Classify error type
            if "server error: 500" in error_str or "500" in error_str:
                self.stats.llm_sampling_server_error_count += 1
            elif "connection" in error_str or "connect" in error_str:
                self.stats.llm_sampling_connection_error_count += 1
            elif "rate limit" in error_str or "429" in error_str:
                self.stats.llm_sampling_rate_limit_count += 1

        return result

    def _select_control_group_candidates(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> list[tuple[Market, OrderBookSnapshot]]:
        """
        Select control group markets for non-avoid comparison.

        IMPORTANT: This is for RESEARCH only - NO TRADING.

        Selection criteria:
        - Market status is OPEN
        - Not in forbidden category
        - Not ambiguous
        - Has valid orderbook
        - NOT in avoid_candidates (if exclude_avoid_from_control_group)
        - NOT in alpha_candidates
        - NOT in persistent_watchlist
        - Sufficient volume

        Category diversity:
        - Try to cover multiple categories
        - At least 1 market per category if available
        """
        if self.run_config.control_group_sampling_ratio <= 0:
            return []

        # Determine max control group size
        max_cg = max(1, int(self.run_config.max_markets * self.run_config.control_group_sampling_ratio))

        candidates: list[tuple[Market, OrderBookSnapshot, str]] = []

        for market in markets:
            # Check market eligibility
            status_ok = market.status == "open" or (hasattr(market.status, 'value') and market.status.value == "open")
            if not status_ok:
                continue
            if market.is_ambiguous:
                continue

            # Check forbidden
            if not market.is_auto_allowed():
                continue

            # Check orderbook
            orderbook = orderbooks.get(market.market_id)
            if not orderbook:
                continue

            # Check exclusions
            if self.run_config.exclude_avoid_from_control_group and market.market_id in self._avoid_ids:
                continue
            if market.market_id in self._alpha_ids:
                continue
            if market.market_id in self._watchlist_ids:
                continue

            # Skip if already in control group (avoid duplicates across scans)
            if market.market_id in self._control_group_ids:
                continue

            # Get category
            category = getattr(market, 'category', None) or 'Other'
            candidates.append((market, orderbook, category))

        if not candidates:
            return []

        # Group by category for diversity
        by_category: dict[str, list[tuple[Market, OrderBookSnapshot, str]]] = {}
        for item in candidates:
            cat = item[2]
            by_category.setdefault(cat, []).append(item)

        # Select diverse candidates: 1 per category first, then fill remaining
        selected: list[tuple[Market, OrderBookSnapshot]] = []
        categories_used: list[str] = []

        # Round-robin: one from each category
        for cat in sorted(by_category.keys()):
            if len(selected) >= max_cg:
                break
            items = by_category[cat]
            selected.append((items[0][0], items[0][1]))
            categories_used.append(cat)

        # Fill remaining from any category
        for cat in sorted(by_category.keys()):
            for item in by_category[cat][1:]:
                if len(selected) >= max_cg:
                    break
                selected.append((item[0], item[1]))
                if cat not in categories_used:
                    categories_used.append(cat)

        return selected[:max_cg]

    async def _run_control_group_sampling(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> None:
        """
        Run control group sampling for Phase 6.5A.

        This is research/intelligence logging only - NO TRADING.
        Uses the same LLM provider as regular sampling, subject to rate limits.
        """
        candidates = self._select_control_group_candidates(markets, orderbooks)

        if not candidates:
            return

        self._log_event("control_group_sampling_start", "control_group",
                        f"Starting control group sampling for {len(candidates)} markets")

        for market, orderbook in candidates:
            # Check rate limit
            if self.stats.llm_calls_this_hour >= self.run_config.max_llm_calls_per_hour:
                self._log_event("control_group_rate_limit", "control_group",
                                "Rate limit reached, stopping control group sampling")
                break

            # Use the same _perform_llm_sampling method (same rate limit, same provider)
            result = await self._perform_llm_sampling(market, orderbook)

            # Track control group
            self._control_group_ids.add(market.market_id)
            category = getattr(market, 'category', None) or 'Other'

            # Store sample
            sample = {
                "market_id": market.market_id,
                "question": market.title[:200] if market.title else "",
                "category": category,
                "combined_ask": orderbook.combined_ask,
                "event_score": result.get("event_score"),
                "ambiguity_risk": result.get("ambiguity_risk"),
                "suggested_mode": result.get("suggested_mode"),
                "confidence": result.get("confidence"),
                "success": result.get("success", False),
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._control_group_samples.append(sample)

            # Update stats
            self.stats.control_group_samples += 1
            self.stats.control_group_unique_markets = len(self._control_group_ids)
            self.stats.control_group_llm_calls += 1
            self.stats.control_group_categories[category] = \
                self.stats.control_group_categories.get(category, 0) + 1

            # Log event
            self._log_event(
                "control_group_assessment",
                "control_group",
                f"Control group assessment for {market.market_id}: {'success' if result.get('success') else 'failed'}",
                {
                    "market_id": market.market_id,
                    "question": market.title[:200] if market.title else "",
                    "category": category,
                    "combined_ask": orderbook.combined_ask,
                    "event_score": result.get("event_score"),
                    "ambiguity_risk": result.get("ambiguity_risk"),
                    "suggested_mode": result.get("suggested_mode"),
                    "confidence": result.get("confidence"),
                    "success": result.get("success", False),
                    "latency_seconds": result.get("latency_seconds"),
                    "group": "control",
                }
            )

        self._log_event("control_group_sampling_complete", "control_group",
                        f"Control group sampling complete: {len(self._control_group_samples)} samples, "
                        f"{len(self._control_group_ids)} unique markets")

    def _generate_control_group_reports(self) -> None:
        """
        Generate control group output files.

        IMPORTANT: This is for RESEARCH only.
        """
        if not self.run_dir:
            return

        if not self._control_group_samples:
            self._log_event("control_group_report_skip", "control_group", "No control group samples to report")
            return

        # Write control_group_samples.csv
        csv_path = self.run_dir / "control_group_samples.csv"
        fields = [
            "market_id", "question", "category", "combined_ask",
            "event_score", "ambiguity_risk", "suggested_mode",
            "confidence", "success", "timestamp",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for sample in self._control_group_samples:
                writer.writerow({k: sample.get(k) for k in fields})

        # Write validation_loop_summary.json
        summary_path = self.run_dir / "validation_loop_summary.json"
        summary = {
            "run_id": self.stats.run_id if self.stats else "unknown",
            "phase": "6.5A",
            "control_group_samples": len(self._control_group_samples),
            "unique_control_group_markets": len(self._control_group_ids),
            "control_group_categories": dict(self.stats.control_group_categories) if self.stats else {},
            "llm_calls_used_for_control_group": self.stats.control_group_llm_calls if self.stats else 0,
            "safety_verification": {
                "live_trading_enabled": False,
                "allow_auto_execution": False,
                "real_api_calls": False,
                "trading_actions": False,
            },
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        print(f"\n=== Control Group Reports Generated ===")
        print(f"  {csv_path}")
        print(f"  {summary_path}")

    def _generate_alpha_repeat_reports(self) -> None:
        """
        Generate alpha repeat observation output files.

        IMPORTANT: This is for RESEARCH only.
        """
        if not self.run_dir:
            return

        if self.run_config.alpha_priority_ratio <= 0:
            return

        alpha_candidates_loaded = (
            self.watchlist_stats.alpha_candidates_loaded
            if self.watchlist_stats
            else len(self._alpha_ids)
        )

        if not self._alpha_observation_counts and alpha_candidates_loaded == 0:
            self._log_event("alpha_repeat_report_skip", "alpha_repeat",
                            "No alpha observations to report")
            return

        alpha_ids = set(self._alpha_ids)
        if self.watchlist_loader:
            alpha_ids.update(self.watchlist_loader.alpha_candidates.keys())
        alpha_ids.update(self._alpha_observation_counts.keys())

        alpha_counts = {
            market_id: self._alpha_observation_counts.get(market_id, 0)
            for market_id in sorted(alpha_ids)
        }

        # Count alpha observation distribution
        obs_distribution: dict[int, int] = {}
        for market_id, count in alpha_counts.items():
            obs_distribution[count] = obs_distribution.get(count, 0) + 1

        # Count alphas at or above target
        at_target = sum(1 for c in alpha_counts.values()
                        if c >= self.run_config.alpha_repeat_target)
        with_1 = sum(1 for c in alpha_counts.values() if c == 1)
        with_2 = sum(1 for c in alpha_counts.values() if c == 2)
        with_3_or_more = sum(1 for c in alpha_counts.values() if c >= 3)
        with_5_or_more = sum(1 for c in alpha_counts.values() if c >= 5)
        alpha_candidates_scanned = (
            self.watchlist_stats.alpha_markets_scanned
            if self.watchlist_stats
            else sum(alpha_counts.values())
        )

        # Update stats
        if self.stats:
            self.stats.alpha_priority_ratio = self.run_config.alpha_priority_ratio
            self.stats.alpha_repeat_target = self.run_config.alpha_repeat_target
            self.stats.alpha_observations_total = sum(alpha_counts.values())
            self.stats.alpha_markets_at_target = at_target

        # Write alpha_repeat_observation_summary.json
        summary_path = self.run_dir / "alpha_repeat_observation_summary.json"
        summary = {
            "run_id": self.stats.run_id if self.stats else "unknown",
            "phase": "6.5B",
            "alpha_candidates_loaded": alpha_candidates_loaded,
            "alpha_candidates_scanned": alpha_candidates_scanned,
            "alpha_candidates_with_1_observation": with_1,
            "alpha_candidates_with_2_observations": with_2,
            "alpha_candidates_with_3_or_more_observations": with_3_or_more,
            "alpha_candidates_with_5_or_more_observations": with_5_or_more,
            "alpha_priority_ratio": self.run_config.alpha_priority_ratio,
            "alpha_repeat_target": self.run_config.alpha_repeat_target,
            "alpha_markets_tracked": len(alpha_counts),
            "alpha_observations_total": sum(alpha_counts.values()),
            "alpha_markets_at_target": at_target,
            "observation_distribution": {
                str(k): v for k, v in sorted(obs_distribution.items())
            },
            "per_market_observations": {
                mid: count for mid, count in sorted(
                    alpha_counts.items(),
                    key=lambda x: x[1], reverse=True
                )
            },
            "safety_verification": {
                "live_trading_enabled": self.config.env.live_trading_enabled if self.config else False,
                "allow_auto_execution": self.config.env.allow_auto_execution if self.config else False,
                "paper_trading_enabled": self.config.env.paper_trading_enabled if self.config else True,
                "real_api_calls": False,
                "trading_actions": False,
                "alpha_score_triggers_trade": False,
                "alpha_score_changes_risk_governor_score": False,
                "alpha_score_adds_hard_reject_reason": False,
            },
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # Write alpha_repeat_observation_report.md
        report_path = self.run_dir / "alpha_repeat_observation_report.md"
        with open(report_path, "w") as f:
            f.write("# Alpha Repeated Observation Report\n\n")
            f.write(f"**Phase:** 6.5B\n")
            f.write(f"**Run ID:** {self.stats.run_id if self.stats else 'unknown'}\n\n")
            f.write("## Configuration\n\n")
            f.write(f"- **Alpha Priority Ratio:** {self.run_config.alpha_priority_ratio}\n")
            f.write(f"- **Alpha Repeat Target:** {self.run_config.alpha_repeat_target}\n\n")
            f.write("## Results\n\n")
            f.write(f"- **Alpha Candidates Loaded:** {alpha_candidates_loaded}\n")
            f.write(f"- **Alpha Candidates Scanned:** {alpha_candidates_scanned}\n")
            f.write(f"- **Alpha Markets Tracked:** {len(alpha_counts)}\n")
            f.write(f"- **Total Alpha Observations:** {sum(alpha_counts.values())}\n")
            f.write(f"- **Markets at Target (>= {self.run_config.alpha_repeat_target}):** {at_target}\n\n")

            f.write("## Observation Distribution\n\n")
            f.write("| Observations | Markets |\n")
            f.write("|---|---|\n")
            for obs_count in sorted(obs_distribution.keys()):
                market_count = obs_distribution[obs_count]
                f.write(f"| {obs_count} | {market_count} |\n")

            f.write("\n## Per-Market Observations\n\n")
            f.write("| Market ID | Observations |\n")
            f.write("|---|---|\n")
            for mid, count in sorted(alpha_counts.items(),
                                     key=lambda x: x[1], reverse=True):
                f.write(f"| {mid} | {count} |\n")

            f.write("\n## Safety Verification\n\n")
            f.write("- alpha_score does NOT trigger trades\n")
            f.write("- alpha_score does NOT affect Risk Governor\n")
            f.write("- alpha candidates are monitoring priority ONLY\n")
            f.write("- live_trading_enabled remains false\n")

        print(f"\n=== Alpha Repeat Observation Reports Generated ===")
        print(f"  {summary_path}")
        print(f"  {report_path}")

    async def _process_signal(self, signal: Signal, market: Optional[Market], orderbook: Optional[OrderBookSnapshot]) -> None:
        """Process signal through Risk Governor"""
        # Construct RiskContext with current system state
        context = RiskContext(
            live_trading_enabled=self.config.env.live_trading_enabled,
            allow_auto_execution=self.config.env.allow_auto_execution,
            api_healthy=True,
            websocket_healthy=self._ws_connected,
            price_stale=orderbook.is_stale if orderbook else True,
            market_tradable=market.is_tradable() if market else False,
            market_ambiguous=market.is_ambiguous if market else False,
            market_forbidden=not market.is_auto_allowed() if market else True,
        )

        # Run through Risk Governor (synchronous call - no await)
        decision = self.risk_governor.evaluate(
            signal=signal,
            context=context,
            orderbook=orderbook,
            market=market,
        )

        # Track decision using enum comparison (not string comparison)
        if decision.action == RiskAction.IGNORE:
            self.stats.signals_ignored += 1
        elif decision.action == RiskAction.LOG_ONLY:
            self.stats.signals_log_only += 1
        elif decision.action == RiskAction.ALERT:
            self.stats.signals_alert += 1
        elif decision.action == RiskAction.PAPER_TRADE:
            self.stats.signals_paper_trade += 1

            # Execute paper trade
            await self._execute_paper_trade(signal, decision, orderbook)

        elif decision.action == RiskAction.HARD_REJECT:
            self.stats.signals_hard_reject += 1

            # Track reject reasons
            for reason in decision.hard_reject_reasons:
                self.stats.hard_reject_reasons[reason] = self.stats.hard_reject_reasons.get(reason, 0) + 1

        # Save signal and decision to database
        await self.db.save_signal(signal)
        await self.db.save_risk_decision(decision)

    async def _execute_paper_trade(self, signal: Signal, decision: RiskDecision, orderbook: Optional[OrderBookSnapshot]) -> None:
        """Execute a paper trade"""
        try:
            if not orderbook:
                self._log_event("paper_trade_error", "error", f"No orderbook for {signal.market_id}")
                return

            # Execute paper trade
            order, position, message = self.paper_trader.execute(
                signal=signal,
                risk_decision=decision,
                orderbook=orderbook,
            )

            if order:
                self.stats.paper_trades_created += 1
                self._log_event("paper_trade", "trade", f"Paper trade created: {order.order_id}", {
                    "order_id": order.order_id,
                    "market_id": signal.market_id,
                    "side": signal.side.value,
                    "price": signal.price,
                    "message": message,
                })

                # Save order to database
                await self.db.save_paper_order(order)

        except Exception as e:
            self._log_event("paper_trade_error", "error", f"Paper trade error: {e}")
            self.stats.errors.append({
                "time": datetime.utcnow().isoformat(),
                "type": "paper_trade_error",
                "message": str(e),
            })

    def _check_hourly_limits(self) -> None:
        """Check and reset hourly rate limits"""
        if self.stats.hour_start:
            hour_elapsed = (datetime.utcnow() - self.stats.hour_start).total_seconds() >= 3600
            if hour_elapsed:
                self.stats.llm_calls_this_hour = 0
                self.stats.signals_this_hour = 0
                self.stats.telegram_messages_this_hour = 0
                self.stats.hour_start = datetime.utcnow()
                self._log_event("hour_reset", "rate_limit", "Hourly rate limits reset")

    async def _save_run_start(self) -> None:
        """Save run start to database"""
        if not self.db or not self.stats:
            return

        await self.db._db.execute(
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
        await self.db._db.commit()

    async def _save_scan(self, scan_id: str, markets_scanned: int, signals_generated: int, orderbooks_fetched: int) -> None:
        """Save scan to database"""
        if not self.db or not self.stats:
            return

        await self.db._db.execute(
            """
            INSERT INTO paper_run_scans (
                scan_id, run_id, scan_time, markets_scanned, signals_generated,
                data_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                self.stats.run_id,
                datetime.utcnow().isoformat(),
                markets_scanned,
                signals_generated,
                self.run_config.data_mode,
            ),
        )
        await self.db._db.commit()

    async def _save_run_end(self) -> None:
        """Save run end to database"""
        if not self.db or not self.stats:
            return

        await self.db._db.execute(
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
        await self.db._db.commit()

    def _log_event(self, event_type: str, event_category: str, description: str, details: Optional[dict] = None) -> None:
        """Log event to file and database"""
        if not self.stats:
            return

        event = {
            "event_id": f"{self.stats.run_id}_event_{uuid.uuid4().hex[:8]}",
            "run_id": self.stats.run_id,
            "event_time": datetime.utcnow().isoformat(),
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
            await self.db._db.execute(
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
            await self.db._db.commit()
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

        print(f"\n=== Watchlist Reports Generated ===")
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
                    lines.append(f"  - Question: {ann.get('question')[:80]}...")
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

        print(f"\n=== Reports Generated ===")
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
            f"# Paper Trading Run Report",
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
                f"- **Enabled**: true",
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
                avg_latency = self.stats._calculate_avg_latency()
                p95_latency = self.stats._calculate_p95_latency()
                lines.append(f"- **Avg Latency**: {avg_latency:.2f}s" if avg_latency else "- **Avg Latency**: N/A")
                lines.append(f"- **P95 Latency**: {p95_latency:.2f}s" if p95_latency else "- **P95 Latency**: N/A")

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

        print(f"\r[{datetime.utcnow().strftime('%H:%M:%S')}] "
              f"Scan #{self._scan_count} | "
              f"Markets: {self.stats.markets_checked} | "
              f"OBs: {self.stats.orderbooks_fetched} | "
              f"{ws_status}"
              f"Signals: {self.stats.signals_generated} | "
              f"Remaining: {remaining_minutes:.1f}m | "
              f"Latency: {scan_latency:.1f}s",
              end="", flush=True)


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
