"""
PolySignal Pro Dashboard - Phase 5G.1

IMPORTANT: This is a READ-ONLY dashboard for monitoring and research.
- Does NOT trigger trades
- Does NOT modify config
- Does NOT write to runs/
- Does NOT call real APIs
- Does NOT import LiveTrader, PaperTrader, or RiskGovernor

Safety constraints:
- live_trading_enabled remains false
- allow_auto_execution remains false
- Dashboard only reads from runs/ and config/
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

# =============================================================================
# SAFETY: Dashboard does NOT import trading modules
# =============================================================================
# The following imports are intentionally NOT done:
# - from polysignal.execution.paper_trader import PaperTrader
# - from polysignal.risk.risk_governor import RiskGovernor
# - from polysignal.execution.live_trader import LiveTrader (stub)
# Dashboard is READ-ONLY and cannot trigger any trading actions.

# =============================================================================
# Constants
# =============================================================================

ALPHA_DISCLAIMER = (
    "⚠️ **DISCLAIMER**: Alpha score is a heuristic research ranking, "
    "NOT a trading signal. Candidates require further paper trading "
    "validation before any execution."
)

AVOID_EXPLANATION = (
    "ℹ️ **Note**: Avoid candidates are research annotations, "
    "NOT hard forbidden. They indicate potential concerns for further review."
)

DEFAULT_RUNS_DIR = Path("runs")
DEFAULT_CONFIG_DIR = Path("config")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RunSummary:
    """Summary of a single run"""

    run_id: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str = "unknown"
    duration_minutes: float = 0.0
    data_mode: str = "unknown"
    llm_provider: str = "unknown"
    websocket_enabled: bool = False
    telegram_enabled: bool = False
    max_markets: int = 0
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
    llm_calls: int = 0
    llm_successes: int = 0
    llm_failures: int = 0
    llm_avg_latency_seconds: Optional[float] = None
    api_errors: int = 0
    websocket_messages: int = 0
    websocket_reconnects: int = 0
    websocket_errors: int = 0
    # LLM Sampling
    llm_sampling_enabled: bool = False
    llm_sampling_calls_attempted: int = 0
    llm_sampling_calls_succeeded: int = 0
    llm_sampling_calls_failed: int = 0
    llm_sampling_avg_latency_seconds: Optional[float] = None
    llm_sampling_p95_latency_seconds: Optional[float] = None
    llm_sampling_timeout_count: int = 0
    llm_sampling_invalid_json_count: int = 0
    llm_sampling_schema_error_count: int = 0
    sampled_markets_count: int = 0
    # Combined ask distribution
    combined_ask_min: Optional[float] = None
    combined_ask_max: Optional[float] = None
    combined_ask_median: Optional[float] = None
    combined_ask_p5: Optional[float] = None
    combined_ask_p95: Optional[float] = None
    combined_ask_observation_count: int = 0
    # API error distribution
    api_error_llm_provider: int = 0
    api_error_clob_rest: int = 0
    api_error_gamma_api: int = 0
    api_error_websocket: int = 0
    # WebSocket stats
    ws_cache_hit_rate: float = 0.0
    ws_rest_fallback_rate: float = 0.0
    # Raw data
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RunSummary":
        """Create RunSummary from JSON data"""
        combined_ask = data.get("combined_ask_distribution", {}) or {}
        api_errors = data.get("api_error_type_distribution", {}) or {}
        ws_summary = data.get("websocket_reconnect_summary", {}) or {}

        return cls(
            run_id=data.get("run_id", "unknown"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            status=data.get("status", "unknown"),
            duration_minutes=data.get("duration_minutes", 0.0),
            data_mode=data.get("data_mode", "unknown"),
            llm_provider=data.get("llm_provider", "unknown"),
            websocket_enabled=data.get("websocket_enabled", False),
            telegram_enabled=data.get("telegram_enabled", False),
            max_markets=data.get("max_markets", 0),
            markets_checked=data.get("markets_checked", 0),
            real_markets_fetched=data.get("real_markets_fetched", 0),
            orderbooks_fetched=data.get("orderbooks_fetched", 0),
            signals_generated=data.get("signals_generated", 0),
            signals_ignored=data.get("signals_ignored", 0),
            signals_log_only=data.get("signals_log_only", 0),
            signals_alert=data.get("signals_alert", 0),
            signals_paper_trade=data.get("signals_paper_trade", 0),
            signals_hard_reject=data.get("signals_hard_reject", 0),
            paper_trades_created=data.get("paper_trades_created", 0),
            paper_trades_filled=data.get("paper_trades_filled", 0),
            llm_calls=data.get("llm_calls", 0),
            llm_successes=data.get("llm_successes", 0),
            llm_failures=data.get("llm_failures", 0),
            llm_avg_latency_seconds=data.get("llm_avg_latency_seconds"),
            api_errors=data.get("api_errors", 0),
            websocket_messages=data.get("websocket_messages", 0),
            websocket_reconnects=data.get("websocket_reconnects", 0),
            websocket_errors=data.get("websocket_errors", 0),
            llm_sampling_enabled=data.get("llm_sampling_enabled", False),
            llm_sampling_calls_attempted=data.get("llm_sampling_calls_attempted", 0),
            llm_sampling_calls_succeeded=data.get("llm_sampling_calls_succeeded", 0),
            llm_sampling_calls_failed=data.get("llm_sampling_calls_failed", 0),
            llm_sampling_avg_latency_seconds=data.get("llm_sampling_avg_latency_seconds"),
            llm_sampling_p95_latency_seconds=data.get("llm_sampling_p95_latency_seconds"),
            llm_sampling_timeout_count=data.get("llm_sampling_timeout_count", 0),
            llm_sampling_invalid_json_count=data.get("llm_sampling_invalid_json_count", 0),
            llm_sampling_schema_error_count=data.get("llm_sampling_schema_error_count", 0),
            sampled_markets_count=data.get("sampled_markets_count", 0),
            combined_ask_min=combined_ask.get("min"),
            combined_ask_max=combined_ask.get("max"),
            combined_ask_median=combined_ask.get("median"),
            combined_ask_p5=combined_ask.get("p5"),
            combined_ask_p95=combined_ask.get("p95"),
            combined_ask_observation_count=combined_ask.get("observation_count", 0),
            api_error_llm_provider=api_errors.get("llm_provider", 0),
            api_error_clob_rest=api_errors.get("clob_rest", 0),
            api_error_gamma_api=api_errors.get("gamma_api", 0),
            api_error_websocket=api_errors.get("websocket", 0),
            ws_cache_hit_rate=ws_summary.get("cache_hit_rate", 0.0),
            ws_rest_fallback_rate=ws_summary.get("rest_fallback_rate", 0.0),
            raw_data=data,
        )


@dataclass
class IntelligenceSummary:
    """Intelligence analysis summary"""

    run_id: str = "unknown"
    analysis_timestamp: Optional[str] = None
    total_markets_analyzed: int = 0
    near_miss_tier_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)
    llm_suggested_mode_distribution: dict[str, int] = field(default_factory=dict)
    top_near_miss_markets: list[dict[str, Any]] = field(default_factory=list)
    top_high_event_score_markets: list[dict[str, Any]] = field(default_factory=list)
    top_high_ambiguity_markets: list[dict[str, Any]] = field(default_factory=list)
    top_research_markets: list[dict[str, Any]] = field(default_factory=list)
    top_avoid_markets: list[dict[str, Any]] = field(default_factory=list)
    top_monitor_markets: list[dict[str, Any]] = field(default_factory=list)
    llm_avg_event_score: Optional[float] = None
    llm_avg_confidence: Optional[float] = None
    llm_avg_latency: Optional[float] = None
    event_score_vs_combined_ask_correlation: Optional[float] = None
    correlation_sample_size: int = 0
    live_trading_enabled: bool = False
    allow_auto_execution: bool = False
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "IntelligenceSummary":
        """Create IntelligenceSummary from JSON data"""
        return cls(
            run_id=data.get("run_id", "unknown"),
            analysis_timestamp=data.get("analysis_timestamp"),
            total_markets_analyzed=data.get("total_observed_markets", 0),
            near_miss_tier_distribution=data.get("near_miss_tier_distribution", {}),
            category_distribution=data.get("category_distribution", {}),
            llm_suggested_mode_distribution=data.get("llm_suggested_mode_distribution", {}),
            top_near_miss_markets=data.get("top_near_miss_markets", []),
            top_high_event_score_markets=data.get("top_high_event_score_markets", []),
            top_high_ambiguity_markets=data.get("top_high_ambiguity_markets", []),
            top_research_markets=data.get("top_research_markets", []),
            top_avoid_markets=data.get("top_avoid_markets", []),
            top_monitor_markets=data.get("top_monitor_markets", []),
            llm_avg_event_score=data.get("llm_avg_event_score"),
            llm_avg_confidence=data.get("llm_avg_confidence"),
            llm_avg_latency=data.get("llm_avg_latency"),
            event_score_vs_combined_ask_correlation=data.get(
                "event_score_vs_combined_ask_correlation"
            ),
            correlation_sample_size=data.get("correlation_sample_size", 0),
            live_trading_enabled=data.get("live_trading_enabled", False),
            allow_auto_execution=data.get("allow_auto_execution", False),
            raw_data=data,
        )


@dataclass
class ComparisonSummary:
    """Multi-run comparison summary"""

    total_runs: int = 0
    run_ids: list[str] = field(default_factory=list)
    unique_markets: int = 0
    total_llm_samples: int = 0
    llm_success_rate: float = 0.0
    persistent_watchlist_count: int = 0
    alpha_candidates_count: int = 0
    avoid_candidates_count: int = 0
    category_analysis: dict[str, Any] = field(default_factory=dict)
    near_miss_distribution: dict[str, int] = field(default_factory=dict)
    all_runs_live_trading_disabled: bool = True
    all_runs_auto_execution_disabled: bool = True
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ComparisonSummary":
        """Create ComparisonSummary from JSON data"""
        run_selection = data.get("run_selection", {}) or {}
        summary_stats = data.get("summary_statistics", {}) or {}
        safety = data.get("safety_verification", {}) or {}

        return cls(
            total_runs=run_selection.get("total_runs", 0),
            run_ids=run_selection.get("run_ids", []),
            unique_markets=summary_stats.get("unique_markets", 0),
            total_llm_samples=summary_stats.get("total_llm_samples", 0),
            llm_success_rate=summary_stats.get("llm_success_rate", 0.0),
            persistent_watchlist_count=data.get("persistent_watchlist_count", 0),
            alpha_candidates_count=data.get("alpha_candidates_count", 0),
            avoid_candidates_count=data.get("avoid_candidates_count", 0),
            category_analysis=data.get("category_analysis", {}),
            near_miss_distribution=summary_stats.get("near_miss_distribution", {}),
            all_runs_live_trading_disabled=safety.get("all_runs_live_trading_disabled", True),
            all_runs_auto_execution_disabled=safety.get("all_runs_auto_execution_disabled", True),
            raw_data=data,
        )


@dataclass
class SafetyStatus:
    """Safety configuration status"""

    live_trading_enabled: bool = False
    allow_auto_execution: bool = False
    paper_trading_enabled: bool = True
    llm_provider: str = "mock"

    @classmethod
    def from_config(cls, config_dir: Path) -> "SafetyStatus":
        """Load safety status from config files"""
        safety = cls()

        # Load risk.yaml
        risk_yaml = config_dir / "risk.yaml"
        if risk_yaml.exists():
            try:
                import yaml

                with open(risk_yaml, "r") as f:
                    risk_config = yaml.safe_load(f) or {}
                safety.live_trading_enabled = risk_config.get("live_trading_enabled", False)
                safety.allow_auto_execution = risk_config.get("allow_auto_execution", False)
                safety.paper_trading_enabled = risk_config.get("paper_trading_enabled", True)
            except Exception:
                pass

        # Load llm.yaml
        llm_yaml = config_dir / "llm.yaml"
        if llm_yaml.exists():
            try:
                import yaml

                with open(llm_yaml, "r") as f:
                    llm_config = yaml.safe_load(f) or {}
                safety.llm_provider = llm_config.get("provider", "mock")
            except Exception:
                pass

        return safety


# =============================================================================
# Data Loader
# =============================================================================


class DashboardDataLoader:
    """
    Load data for dashboard from runs/ directory.

    IMPORTANT: This class is READ-ONLY.
    - Does NOT write any files
    - Does NOT call any APIs
    - Does NOT trigger any trading actions
    """

    def __init__(self, runs_dir: Path = DEFAULT_RUNS_DIR, config_dir: Path = DEFAULT_CONFIG_DIR):
        self.runs_dir = runs_dir
        self.config_dir = config_dir
        self._runs_cache: Optional[dict[str, RunSummary]] = None
        self._comparison_cache: Optional[ComparisonSummary] = None

    def discover_runs(self) -> list[str]:
        """Discover all run directories"""
        if not self.runs_dir.exists():
            return []

        run_ids = []
        for item in self.runs_dir.iterdir():
            if item.is_dir() and item.name.startswith("run_"):
                # Check if summary.json exists
                summary_file = item / "summary.json"
                if summary_file.exists():
                    run_ids.append(item.name)

        # Sort by name (which includes timestamp)
        run_ids.sort(reverse=True)
        return run_ids

    def load_run_summary(self, run_id: str) -> Optional[RunSummary]:
        """Load summary for a specific run"""
        summary_file = self.runs_dir / run_id / "summary.json"
        if not summary_file.exists():
            return None

        try:
            with open(summary_file, "r") as f:
                data = json.load(f)
            return RunSummary.from_json(data)
        except Exception as e:
            st.warning(f"Failed to load {run_id}: {e}")
            return None

    def load_all_runs(self) -> dict[str, RunSummary]:
        """Load all run summaries"""
        if self._runs_cache is not None:
            return self._runs_cache

        runs = {}
        for run_id in self.discover_runs():
            summary = self.load_run_summary(run_id)
            if summary:
                runs[run_id] = summary

        self._runs_cache = runs
        return runs

    def load_intelligence_summary(self, run_id: str) -> Optional[IntelligenceSummary]:
        """Load intelligence summary for a specific run"""
        intel_file = self.runs_dir / run_id / "intelligence_summary.json"
        if not intel_file.exists():
            return None

        try:
            with open(intel_file, "r") as f:
                data = json.load(f)
            return IntelligenceSummary.from_json(data)
        except Exception:
            return None

    def load_comparison_summary(self) -> Optional[ComparisonSummary]:
        """Load multi-run comparison summary"""
        if self._comparison_cache is not None:
            return self._comparison_cache

        comparison_file = self.runs_dir / "intelligence_comparison_summary.json"
        if not comparison_file.exists():
            return None

        try:
            with open(comparison_file, "r") as f:
                data = json.load(f)
            self._comparison_cache = ComparisonSummary.from_json(data)
            return self._comparison_cache
        except Exception:
            return None

    def load_intelligence_report(self, run_id: str) -> Optional[str]:
        """Load intelligence report markdown for a specific run"""
        report_file = self.runs_dir / run_id / "intelligence_report.md"
        if not report_file.exists():
            return None

        try:
            with open(report_file, "r") as f:
                return f.read()
        except Exception:
            return None

    def load_persistent_watchlist(self) -> pd.DataFrame:
        """Load persistent watchlist CSV"""
        watchlist_file = self.runs_dir / "persistent_watchlist.csv"
        if not watchlist_file.exists():
            return pd.DataFrame()

        try:
            return pd.read_csv(watchlist_file)
        except Exception:
            return pd.DataFrame()

    def load_alpha_candidates(self) -> pd.DataFrame:
        """Load alpha candidates CSV"""
        alpha_file = self.runs_dir / "alpha_candidates.csv"
        if not alpha_file.exists():
            return pd.DataFrame()

        try:
            return pd.read_csv(alpha_file)
        except Exception:
            return pd.DataFrame()

    def load_avoid_candidates(self) -> pd.DataFrame:
        """Load avoid candidates CSV"""
        avoid_file = self.runs_dir / "avoid_candidates.csv"
        if not avoid_file.exists():
            return pd.DataFrame()

        try:
            return pd.read_csv(avoid_file)
        except Exception:
            return pd.DataFrame()

    def load_market_trajectories(self) -> dict[str, Any]:
        """Load market trajectories JSON"""
        trajectories_file = self.runs_dir / "market_trajectories.json"
        if not trajectories_file.exists():
            return {}

        try:
            with open(trajectories_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def load_safety_status(self) -> SafetyStatus:
        """Load safety status from config"""
        return SafetyStatus.from_config(self.config_dir)

    def get_aggregated_stats(self) -> dict[str, Any]:
        """Get aggregated statistics across all runs"""
        runs = self.load_all_runs()

        if not runs:
            return {
                "total_runs": 0,
                "total_markets_checked": 0,
                "total_signals_generated": 0,
                "total_paper_trades": 0,
                "total_llm_sampling_calls": 0,
                "total_llm_sampling_successes": 0,
                "total_api_errors": 0,
                "total_websocket_messages": 0,
            }

        return {
            "total_runs": len(runs),
            "total_markets_checked": sum(r.markets_checked for r in runs.values()),
            "total_signals_generated": sum(r.signals_generated for r in runs.values()),
            "total_paper_trades": sum(r.paper_trades_created for r in runs.values()),
            "total_llm_sampling_calls": sum(r.llm_sampling_calls_attempted for r in runs.values()),
            "total_llm_sampling_successes": sum(r.llm_sampling_calls_succeeded for r in runs.values()),
            "total_api_errors": sum(r.api_errors for r in runs.values()),
            "total_websocket_messages": sum(r.websocket_messages for r in runs.values()),
        }


# =============================================================================
# Dashboard Pages
# =============================================================================


def render_overview_page(loader: DashboardDataLoader):
    """Render Overview page"""
    st.header("📊 Overview")

    # Safety status
    safety = loader.load_safety_status()

    # Safety status cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        status_color = "🔴" if safety.live_trading_enabled else "🟢"
        st.metric("Live Trading", f"{status_color} {safety.live_trading_enabled}")
    with col2:
        status_color = "🔴" if safety.allow_auto_execution else "🟢"
        st.metric("Auto Execution", f"{status_color} {safety.allow_auto_execution}")
    with col3:
        st.metric("Paper Trading", f"🟢 {safety.paper_trading_enabled}")
    with col4:
        provider_color = "🟡" if safety.llm_provider == "mock" else "🔵"
        st.metric("LLM Provider", f"{provider_color} {safety.llm_provider}")

    st.divider()

    # Aggregated stats
    stats = loader.get_aggregated_stats()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Runs", stats["total_runs"])
    with col2:
        st.metric("Total Markets Checked", stats["total_markets_checked"])
    with col3:
        st.metric("Total Signals Generated", stats["total_signals_generated"])
    with col4:
        st.metric("Total Paper Trades", stats["total_paper_trades"])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("LLM Sampling Calls", stats["total_llm_sampling_calls"])
    with col2:
        success_rate = (
            stats["total_llm_sampling_successes"] / stats["total_llm_sampling_calls"] * 100
            if stats["total_llm_sampling_calls"] > 0
            else 0
        )
        st.metric("LLM Success Rate", f"{success_rate:.1f}%")
    with col3:
        st.metric("Total API Errors", stats["total_api_errors"])
    with col4:
        st.metric("WebSocket Messages", stats["total_websocket_messages"])

    st.divider()

    # Latest run summary
    runs = loader.load_all_runs()
    if runs:
        latest_run_id = list(runs.keys())[0]
        latest_run = runs[latest_run_id]

        st.subheader("Latest Run")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**Run ID**: {latest_run.run_id}")
            st.write(f"**Status**: {latest_run.status}")
            st.write(f"**Duration**: {latest_run.duration_minutes:.1f} min")
        with col2:
            st.write(f"**Data Mode**: {latest_run.data_mode}")
            st.write(f"**LLM Provider**: {latest_run.llm_provider}")
            st.write(f"**WebSocket**: {'Enabled' if latest_run.websocket_enabled else 'Disabled'}")
        with col3:
            st.write(f"**Markets Checked**: {latest_run.markets_checked}")
            st.write(f"**Signals Generated**: {latest_run.signals_generated}")
            st.write(f"**Paper Trades**: {latest_run.paper_trades_created}")


def render_run_details_page(loader: DashboardDataLoader):
    """Render Run Details page"""
    st.header("📋 Run Details")

    runs = loader.load_all_runs()
    if not runs:
        st.warning("No runs found")
        return

    # Run selector
    run_ids = list(runs.keys())
    selected_run_id = st.selectbox("Select Run", run_ids, index=0)
    selected_run = runs[selected_run_id]

    st.subheader(f"Run: {selected_run.run_id}")

    # Basic info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", selected_run.status)
        st.write(f"**Start**: {selected_run.start_time or 'N/A'}")
        st.write(f"**End**: {selected_run.end_time or 'N/A'}")
    with col2:
        st.metric("Duration (min)", f"{selected_run.duration_minutes:.1f}")
        st.write(f"**Data Mode**: {selected_run.data_mode}")
        st.write(f"**LLM Provider**: {selected_run.llm_provider}")
    with col3:
        st.metric("Markets Checked", selected_run.markets_checked)
        st.write(f"**WebSocket**: {'Enabled' if selected_run.websocket_enabled else 'Disabled'}")
        st.write(f"**Telegram**: {'Enabled' if selected_run.telegram_enabled else 'Disabled'}")

    st.divider()

    # Signal distribution
    st.subheader("Signal Distribution")
    signal_data = {
        "Action": ["Ignored", "Log Only", "Alert", "Paper Trade", "Hard Reject"],
        "Count": [
            selected_run.signals_ignored,
            selected_run.signals_log_only,
            selected_run.signals_alert,
            selected_run.signals_paper_trade,
            selected_run.signals_hard_reject,
        ],
    }
    signal_df = pd.DataFrame(signal_data)
    st.bar_chart(signal_df.set_index("Action"))

    # Combined ask distribution
    if selected_run.combined_ask_observation_count > 0:
        st.subheader("Combined Ask Distribution")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Min", f"{selected_run.combined_ask_min:.4f}" if selected_run.combined_ask_min else "N/A")
        with col2:
            st.metric("P5", f"{selected_run.combined_ask_p5:.4f}" if selected_run.combined_ask_p5 else "N/A")
        with col3:
            st.metric("Median", f"{selected_run.combined_ask_median:.4f}" if selected_run.combined_ask_median else "N/A")
        with col4:
            st.metric("P95", f"{selected_run.combined_ask_p95:.4f}" if selected_run.combined_ask_p95 else "N/A")
        with col5:
            st.metric("Max", f"{selected_run.combined_ask_max:.4f}" if selected_run.combined_ask_max else "N/A")

    st.divider()

    # REST / WebSocket stats
    st.subheader("API & WebSocket Stats")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("API Errors", selected_run.api_errors)
    with col2:
        st.metric("WebSocket Messages", selected_run.websocket_messages)
    with col3:
        st.metric("WebSocket Reconnects", selected_run.websocket_reconnects)
    with col4:
        st.metric("WebSocket Errors", selected_run.websocket_errors)

    # API error distribution
    if selected_run.api_errors > 0:
        st.subheader("API Error Distribution")
        error_data = {
            "Source": ["LLM Provider", "CLOB REST", "Gamma API", "WebSocket"],
            "Count": [
                selected_run.api_error_llm_provider,
                selected_run.api_error_clob_rest,
                selected_run.api_error_gamma_api,
                selected_run.api_error_websocket,
            ],
        }
        error_df = pd.DataFrame(error_data)
        st.bar_chart(error_df.set_index("Source"))

    # WebSocket cache stats
    if selected_run.websocket_enabled:
        st.subheader("WebSocket Cache Stats")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Cache Hit Rate", f"{selected_run.ws_cache_hit_rate * 100:.1f}%")
        with col2:
            st.metric("REST Fallback Rate", f"{selected_run.ws_rest_fallback_rate * 100:.1f}%")


def render_llm_performance_page(loader: DashboardDataLoader):
    """Render LLM Performance page"""
    st.header("🤖 LLM Performance")

    runs = loader.load_all_runs()
    if not runs:
        st.warning("No runs found")
        return

    # Run selector
    run_ids = list(runs.keys())
    selected_run_id = st.selectbox("Select Run", run_ids, index=0, key="llm_run_select")
    selected_run = runs[selected_run_id]

    # LLM Sampling stats
    st.subheader("LLM Sampling Statistics")

    if not selected_run.llm_sampling_enabled:
        st.info("LLM Sampling was not enabled for this run")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Calls Attempted", selected_run.llm_sampling_calls_attempted)
    with col2:
        st.metric("Calls Succeeded", selected_run.llm_sampling_calls_succeeded)
    with col3:
        st.metric("Calls Failed", selected_run.llm_sampling_calls_failed)
    with col4:
        success_rate = (
            selected_run.llm_sampling_calls_succeeded / selected_run.llm_sampling_calls_attempted * 100
            if selected_run.llm_sampling_calls_attempted > 0
            else 0
        )
        st.metric("Success Rate", f"{success_rate:.1f}%")

    st.divider()

    # Latency stats
    st.subheader("Latency Statistics")
    col1, col2 = st.columns(2)
    with col1:
        avg_latency = selected_run.llm_sampling_avg_latency_seconds
        st.metric("Avg Latency", f"{avg_latency:.2f}s" if avg_latency else "N/A")
    with col2:
        p95_latency = selected_run.llm_sampling_p95_latency_seconds
        st.metric("P95 Latency", f"{p95_latency:.2f}s" if p95_latency else "N/A")

    st.divider()

    # Error distribution
    st.subheader("Error Distribution")
    error_data = {
        "Type": ["Timeout", "Invalid JSON", "Schema Error"],
        "Count": [
            selected_run.llm_sampling_timeout_count,
            selected_run.llm_sampling_invalid_json_count,
            selected_run.llm_sampling_schema_error_count,
        ],
    }
    error_df = pd.DataFrame(error_data)
    st.bar_chart(error_df.set_index("Type"))

    st.divider()

    # Sampled markets
    st.subheader("Sampled Markets")
    st.metric("Total Sampled Markets", selected_run.sampled_markets_count)

    # Check for sampled_markets.csv
    sampled_file = loader.runs_dir / selected_run_id / "sampled_markets.csv"
    if sampled_file.exists():
        try:
            sampled_df = pd.read_csv(sampled_file)
            st.dataframe(sampled_df)
        except Exception:
            st.info("Could not load sampled markets data")


def render_intelligence_summary_page(loader: DashboardDataLoader):
    """Render Intelligence Summary page"""
    st.header("🧠 Intelligence Summary")

    # Multi-run comparison
    comparison = loader.load_comparison_summary()
    if comparison:
        st.subheader("Multi-Run Comparison")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Runs", comparison.total_runs)
        with col2:
            st.metric("Unique Markets", comparison.unique_markets)
        with col3:
            st.metric("LLM Samples", comparison.total_llm_samples)
        with col4:
            st.metric("LLM Success Rate", f"{comparison.llm_success_rate * 100:.1f}%")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Persistent Watchlist", comparison.persistent_watchlist_count)
        with col2:
            st.metric("Alpha Candidates", comparison.alpha_candidates_count)
        with col3:
            st.metric("Avoid Candidates", comparison.avoid_candidates_count)

        # Near-miss distribution
        if comparison.near_miss_distribution:
            st.subheader("Near-Miss Tier Distribution")
            tier_data = {
                "Tier": list(comparison.near_miss_distribution.keys()),
                "Count": list(comparison.near_miss_distribution.values()),
            }
            tier_df = pd.DataFrame(tier_data)
            st.bar_chart(tier_df.set_index("Tier"))

        # Category analysis
        if comparison.category_analysis:
            st.subheader("Category Analysis")
            category_df = pd.DataFrame(comparison.category_analysis).T
            st.dataframe(category_df)

        st.divider()

    # Single run intelligence
    runs = loader.load_all_runs()
    if runs:
        run_ids = list(runs.keys())
        selected_run_id = st.selectbox("Select Run for Intelligence Report", run_ids, index=0)

        intel_summary = loader.load_intelligence_summary(selected_run_id)
        if intel_summary:
            st.subheader(f"Intelligence Summary: {selected_run_id}")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Markets Analyzed", intel_summary.total_markets_analyzed)
            with col2:
                st.write(f"**Analysis Time**: {intel_summary.analysis_timestamp or 'N/A'}")
            with col3:
                if intel_summary.llm_avg_event_score is not None:
                    st.metric("Avg Event Score", f"{intel_summary.llm_avg_event_score:.1f}")

            # Safety flags from intelligence data
            col1, col2 = st.columns(2)
            with col1:
                flag = "🟢 OFF" if not intel_summary.live_trading_enabled else "🔴 ON"
                st.write(f"**Live Trading**: {flag}")
            with col2:
                flag = "🟢 OFF" if not intel_summary.allow_auto_execution else "🔴 ON"
                st.write(f"**Auto Execution**: {flag}")

            # Near-miss tiers
            if intel_summary.near_miss_tier_distribution:
                st.subheader("Near-Miss Tier Distribution")
                tier_data = {
                    "Tier": list(intel_summary.near_miss_tier_distribution.keys()),
                    "Count": list(intel_summary.near_miss_tier_distribution.values()),
                }
                st.bar_chart(pd.DataFrame(tier_data).set_index("Tier"))

            # LLM suggested mode distribution
            if intel_summary.llm_suggested_mode_distribution:
                st.subheader("LLM Suggested Mode Distribution")
                mode_data = {
                    "Mode": list(intel_summary.llm_suggested_mode_distribution.keys()),
                    "Count": list(intel_summary.llm_suggested_mode_distribution.values()),
                }
                st.bar_chart(pd.DataFrame(mode_data).set_index("Mode"))

            # Top candidates
            if intel_summary.top_near_miss_markets:
                st.subheader("Top Near-Miss Markets")
                st.dataframe(pd.DataFrame(intel_summary.top_near_miss_markets))

            if intel_summary.top_high_event_score_markets:
                st.subheader("Top High Event Score Markets")
                st.dataframe(pd.DataFrame(intel_summary.top_high_event_score_markets))

        # Intelligence report markdown
        intel_report = loader.load_intelligence_report(selected_run_id)
        if intel_report:
            st.subheader("Intelligence Report")
            st.markdown(intel_report)


def render_watchlist_page(loader: DashboardDataLoader):
    """Render Watchlist / Alpha / Avoid page"""
    st.header("👀 Watchlist / Alpha / Avoid")

    tab1, tab2, tab3, tab4 = st.tabs(["Persistent Watchlist", "Alpha Candidates", "Avoid Candidates", "Market Trajectories"])

    # Persistent Watchlist
    with tab1:
        st.subheader("Persistent Watchlist")
        watchlist_df = loader.load_persistent_watchlist()
        if watchlist_df.empty:
            st.info("No persistent watchlist found")
        else:
            st.dataframe(watchlist_df)

    # Alpha Candidates
    with tab2:
        st.subheader("Alpha Candidates")
        st.warning(ALPHA_DISCLAIMER)

        alpha_df = loader.load_alpha_candidates()
        if alpha_df.empty:
            st.info("No alpha candidates found")
        else:
            st.dataframe(alpha_df)

    # Avoid Candidates
    with tab3:
        st.subheader("Avoid Candidates")
        st.info(AVOID_EXPLANATION)

        avoid_df = loader.load_avoid_candidates()
        if avoid_df.empty:
            st.info("No avoid candidates found")
        else:
            st.dataframe(avoid_df)

    # Market Trajectories
    with tab4:
        st.subheader("Market Trajectories")
        trajectories = loader.load_market_trajectories()
        if not trajectories:
            st.info("No market trajectories found")
        else:
            # Show summary
            st.metric("Total Markets Tracked", len(trajectories))

            # Show as table
            trajectory_summary = []
            for market_id, data in trajectories.items():
                obs_count = len(data.get("observations", []))
                trajectory_summary.append(
                    {
                        "Market ID": market_id,
                        "Question": data.get("normalized_question", "N/A"),
                        "Observations": obs_count,
                    }
                )

            if trajectory_summary:
                st.dataframe(pd.DataFrame(trajectory_summary))


# =============================================================================
# Main Dashboard
# =============================================================================


def main():
    """Main dashboard entry point"""
    st.set_page_config(
        page_title="PolySignal Pro Dashboard",
        page_icon="📊",
        layout="wide",
    )

    st.title("📊 PolySignal Pro Dashboard")
    st.caption("READ-ONLY monitoring dashboard for paper trading research")

    # Initialize data loader
    loader = DashboardDataLoader()

    # Sidebar navigation
    page = st.sidebar.radio(
        "Navigate",
        ["Overview", "Run Details", "LLM Performance", "Intelligence Summary", "Watchlist / Alpha / Avoid"],
    )

    # Safety status in sidebar
    st.sidebar.divider()
    st.sidebar.subheader("Safety Status")
    safety = loader.load_safety_status()

    status_text = f"""
    - Live Trading: {'🔴 ON' if safety.live_trading_enabled else '🟢 OFF'}
    - Auto Execution: {'🔴 ON' if safety.allow_auto_execution else '🟢 OFF'}
    - Paper Trading: {'🟢 ON' if safety.paper_trading_enabled else '🔴 OFF'}
    - LLM Provider: {safety.llm_provider}
    """
    st.sidebar.markdown(status_text)

    # Render selected page
    if page == "Overview":
        render_overview_page(loader)
    elif page == "Run Details":
        render_run_details_page(loader)
    elif page == "LLM Performance":
        render_llm_performance_page(loader)
    elif page == "Intelligence Summary":
        render_intelligence_summary_page(loader)
    elif page == "Watchlist / Alpha / Avoid":
        render_watchlist_page(loader)


if __name__ == "__main__":
    main()
