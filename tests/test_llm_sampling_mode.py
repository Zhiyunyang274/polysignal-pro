"""
Tests for LLM Sampling Mode - Phase 5D.1

Coverage:
- RunConfig has LLM sampling parameters
- RunStatistics tracks LLM sampling statistics
- _select_llm_sampling_candidates selects correct markets
- _perform_llm_sampling returns correct results
- LLM sampling does NOT trigger trading
- Rate limiting is enforced
- Events are logged correctly
- Report includes LLM sampling section
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.models.market import Market
from polysignal.models.orderbook import OrderBookSnapshot
from scripts.run_paper import (
    PaperTradingRunner,
    RunConfig,
    RunStatistics,
)


class TestRunConfigLLMSampling:
    """Test RunConfig LLM sampling parameters"""

    def test_run_config_has_enable_llm_sampling(self):
        """Test RunConfig has enable_llm_sampling field"""
        config = RunConfig()
        assert hasattr(config, "enable_llm_sampling")
        assert config.enable_llm_sampling is False

    def test_run_config_has_llm_sampling_per_scan(self):
        """Test RunConfig has llm_sampling_per_scan field"""
        config = RunConfig()
        assert hasattr(config, "llm_sampling_per_scan")
        assert config.llm_sampling_per_scan == 1

    def test_run_config_has_llm_sampling_min_volume(self):
        """Test RunConfig has llm_sampling_min_volume field"""
        config = RunConfig()
        assert hasattr(config, "llm_sampling_min_volume")
        assert config.llm_sampling_min_volume == 10000.0

    def test_run_config_has_llm_sampling_strategy(self):
        """Test RunConfig has llm_sampling_strategy field"""
        config = RunConfig()
        assert hasattr(config, "llm_sampling_strategy")
        assert config.llm_sampling_strategy == "top_liquidity_or_near_miss"

    def test_run_config_llm_sampling_custom_values(self):
        """Test RunConfig accepts custom LLM sampling values"""
        config = RunConfig(
            enable_llm_sampling=True,
            llm_sampling_per_scan=3,
            llm_sampling_min_volume=50000.0,
            llm_sampling_strategy="top_liquidity",
        )
        assert config.enable_llm_sampling is True
        assert config.llm_sampling_per_scan == 3
        assert config.llm_sampling_min_volume == 50000.0
        assert config.llm_sampling_strategy == "top_liquidity"


class TestRunStatisticsLLMSampling:
    """Test RunStatistics LLM sampling tracking"""

    def test_run_statistics_has_llm_sampling_enabled(self):
        """Test RunStatistics has llm_sampling_enabled field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "llm_sampling_enabled")
        assert stats.llm_sampling_enabled is False

    def test_run_statistics_has_llm_sampling_calls_attempted(self):
        """Test RunStatistics has llm_sampling_calls_attempted field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "llm_sampling_calls_attempted")
        assert stats.llm_sampling_calls_attempted == 0

    def test_run_statistics_has_llm_sampling_calls_succeeded(self):
        """Test RunStatistics has llm_sampling_calls_succeeded field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "llm_sampling_calls_succeeded")
        assert stats.llm_sampling_calls_succeeded == 0

    def test_run_statistics_has_llm_sampling_calls_failed(self):
        """Test RunStatistics has llm_sampling_calls_failed field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "llm_sampling_calls_failed")
        assert stats.llm_sampling_calls_failed == 0

    def test_run_statistics_has_sampled_markets_count(self):
        """Test RunStatistics has sampled_markets_count field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "sampled_markets_count")
        assert stats.sampled_markets_count == 0

    def test_run_statistics_has_sampled_markets_examples(self):
        """Test RunStatistics has sampled_markets_examples field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "sampled_markets_examples")
        assert stats.sampled_markets_examples == []

    def test_to_dict_includes_llm_sampling_statistics(self):
        """Test to_dict includes LLM sampling statistics"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_sampling_enabled = True
        stats.llm_sampling_calls_attempted = 5
        stats.llm_sampling_calls_succeeded = 4
        stats.llm_sampling_calls_failed = 1
        stats.sampled_markets_count = 5

        result = stats.to_dict()

        assert "llm_sampling_enabled" in result
        assert result["llm_sampling_enabled"] is True
        assert result["llm_sampling_calls_attempted"] == 5
        assert result["llm_sampling_calls_succeeded"] == 4
        assert result["llm_sampling_calls_failed"] == 1
        assert result["sampled_markets_count"] == 5


class TestSelectLLMSamplingCandidates:
    """Test _select_llm_sampling_candidates method"""

    def _create_test_market(
        self,
        market_id: str,
        status: str = "open",  # Use lowercase to match MarketStatus.OPEN.value
        total_volume_usd: float = 50000.0,
        is_auto_allowed: bool = True,
        is_ambiguous: bool = False,
    ) -> Market:
        """Create a test market"""
        market = MagicMock(spec=Market)
        market.market_id = market_id
        market.status = status
        market.total_volume_usd = total_volume_usd
        market.volume_24h_usd = 0  # Often not populated
        market.is_auto_allowed = MagicMock(return_value=is_auto_allowed)
        market.is_ambiguous = is_ambiguous
        market.title = f"Test question for {market_id}"
        return market

    def _create_test_orderbook(
        self,
        combined_ask: float = 0.98,
    ) -> OrderBookSnapshot:
        """Create a test orderbook"""
        orderbook = MagicMock(spec=OrderBookSnapshot)
        orderbook.combined_ask = combined_ask
        orderbook.is_stale = False
        return orderbook

    def test_select_candidates_empty_markets(self):
        """Test with empty market list"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        result = runner._select_llm_sampling_candidates([], {})

        assert result == []

    def test_select_candidates_filters_closed_markets(self):
        """Test that closed markets are filtered out"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        market = self._create_test_market("m1", status="CLOSED")
        orderbook = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates([market], {"m1": orderbook})

        assert result == []

    def test_select_candidates_filters_forbidden_markets(self):
        """Test that forbidden category markets are NOT filtered out for LLM sampling (research only)"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # Note: is_auto_allowed() is no longer checked for LLM sampling
        # So forbidden markets CAN be sampled (since LLM sampling is research only, not trading)
        market = self._create_test_market("m1", is_auto_allowed=False)
        orderbook = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates([market], {"m1": orderbook})

        # Now forbidden markets ARE eligible for LLM sampling (research only)
        assert len(result) == 1

    def test_select_candidates_filters_low_volume(self):
        """Test that low volume markets are filtered out"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_min_volume=100000.0,  # High threshold
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        market = self._create_test_market("m1", total_volume_usd=50000.0)  # Below threshold
        orderbook = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates([market], {"m1": orderbook})

        assert result == []

    def test_select_candidates_filters_ambiguous_markets(self):
        """Test that ambiguous markets are filtered out"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        market = self._create_test_market("m1", is_ambiguous=True)
        orderbook = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates([market], {"m1": orderbook})

        assert result == []

    def test_select_candidates_returns_eligible_markets(self):
        """Test that eligible markets are selected"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_per_scan=2,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        market1 = self._create_test_market("m1", total_volume_usd=100000.0)
        market2 = self._create_test_market("m2", total_volume_usd=200000.0)
        orderbook1 = self._create_test_orderbook()
        orderbook2 = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates(
            [market1, market2],
            {"m1": orderbook1, "m2": orderbook2}
        )

        assert len(result) == 2

    def test_select_candidates_respects_per_scan_limit(self):
        """Test that per_scan limit is respected"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_per_scan=1,  # Only 1 per scan
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        market1 = self._create_test_market("m1", total_volume_usd=100000.0)
        market2 = self._create_test_market("m2", total_volume_usd=200000.0)
        orderbook1 = self._create_test_orderbook()
        orderbook2 = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates(
            [market1, market2],
            {"m1": orderbook1, "m2": orderbook2}
        )

        assert len(result) == 1


class TestPerformLLMSampling:
    """Test _perform_llm_sampling method"""

    def _create_test_market(self) -> Market:
        """Create a test market"""
        market = MagicMock(spec=Market)
        market.market_id = "test_market"
        market.title = "Test question?"
        market.volume_24h_usd = 100000.0
        market.status = "OPEN"
        market.is_auto_allowed = MagicMock(return_value=True)
        market.is_ambiguous = False
        return market

    def _create_test_orderbook(self) -> OrderBookSnapshot:
        """Create a test orderbook"""
        orderbook = MagicMock(spec=OrderBookSnapshot)
        orderbook.combined_ask = 0.98
        orderbook.is_stale = False
        return orderbook

    @pytest.mark.asyncio
    async def test_perform_llm_sampling_mock_provider_returns_error(self):
        """Test that mock provider returns appropriate error"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="mock",  # Mock provider
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        market = self._create_test_market()
        orderbook = self._create_test_orderbook()

        result = await runner._perform_llm_sampling(market, orderbook)

        assert result["success"] is False
        assert result["error"] == "mock_provider_no_real_call"
        assert "llm_mock_provider" in result["risk_flags"]

    @pytest.mark.asyncio
    async def test_perform_llm_sampling_rate_limit_exceeded(self):
        """Test that rate limit is enforced"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=5,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.llm_calls_this_hour = 5  # Already at limit

        market = self._create_test_market()
        orderbook = self._create_test_orderbook()

        result = await runner._perform_llm_sampling(market, orderbook)

        assert result["success"] is False
        assert result["error"] == "rate_limit_exceeded"
        assert "llm_rate_limit_exceeded" in result["risk_flags"]


class TestLLMSamplingNoTrading:
    """Test that LLM sampling does NOT trigger trading"""

    def test_llm_sampling_config_not_in_signal_path(self):
        """Test that LLM sampling config is separate from signal generation"""
        config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            max_signals_per_hour=20,
        )

        # LLM sampling should be independent
        assert config.enable_llm_sampling is True
        assert config.max_signals_per_hour == 20  # Unrelated

    def test_llm_sampling_stats_separate_from_trading_stats(self):
        """Test that LLM sampling statistics are separate from trading statistics"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # Set some trading stats
        stats.signals_generated = 5
        stats.paper_trades_created = 2

        # Set some LLM sampling stats
        stats.llm_sampling_calls_attempted = 10
        stats.llm_sampling_calls_succeeded = 8

        result = stats.to_dict()

        # Both should be present and independent
        assert result["signals_generated"] == 5
        assert result["paper_trades_created"] == 2
        assert result["llm_sampling_calls_attempted"] == 10
        assert result["llm_sampling_calls_succeeded"] == 8


class TestReportIncludesLLMSampling:
    """Test that report.md includes LLM sampling section"""

    def test_generate_markdown_report_includes_llm_sampling(self):
        """Test _generate_markdown_report includes LLM sampling section"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.llm_sampling_enabled = True
        runner.stats.llm_sampling_calls_attempted = 5
        runner.stats.llm_sampling_calls_succeeded = 4
        runner.stats.llm_sampling_calls_failed = 1
        runner.stats.sampled_markets_count = 5
        runner.stats.llm_latencies = [10.0, 12.0, 11.0, 13.0, 10.5]

        report = runner._generate_markdown_report()

        assert "LLM Sampling" in report
        assert "Research/Intelligence Only" in report
        assert "Calls Attempted" in report

    def test_generate_markdown_report_no_llm_sampling_when_disabled(self):
        """Test _generate_markdown_report does not include LLM sampling when disabled"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        report = runner._generate_markdown_report()

        # Should not include LLM sampling section when disabled
        assert "LLM Sampling (Research/Intelligence Only)" not in report


class TestSafetyChecksLLMSampling:
    """Test safety checks for LLM sampling"""

    def test_safety_check_rejects_llm_sampling_with_mock_provider(self):
        """Test that LLM sampling with mock provider is rejected"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="mock",  # Should be rejected
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)

        # Safety check should fail
        result = runner._safety_checks()
        assert result is False

    def test_safety_check_rejects_llm_sampling_without_rate_limit(self):
        """Test that LLM sampling without rate limit is rejected"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=0,  # Should be rejected
        )

        runner = PaperTradingRunner(mock_config, run_config)

        # Safety check should fail
        result = runner._safety_checks()
        assert result is False


class TestLLMSamplingDiversity:
    """Test LLM sampling diversity features - Phase 5D.2.5"""

    def test_run_config_has_llm_sampling_cooldown_minutes(self):
        """Test RunConfig has llm_sampling_cooldown_minutes field"""
        config = RunConfig()
        assert hasattr(config, "llm_sampling_cooldown_minutes")
        assert config.llm_sampling_cooldown_minutes == 60

    def test_run_config_has_llm_sampling_max_repeats_per_market(self):
        """Test RunConfig has llm_sampling_max_repeats_per_market field"""
        config = RunConfig()
        assert hasattr(config, "llm_sampling_max_repeats_per_market")
        assert config.llm_sampling_max_repeats_per_market == 1

    def test_run_config_has_diversified_strategy(self):
        """Test RunConfig accepts diversified strategy"""
        config = RunConfig(llm_sampling_strategy="diversified")
        assert config.llm_sampling_strategy == "diversified"

    def test_run_statistics_has_sampled_market_history(self):
        """Test RunStatistics has sampled_market_history field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "sampled_market_history")
        assert stats.sampled_market_history == {}

    def test_run_statistics_has_unique_sampled_markets(self):
        """Test RunStatistics has unique_sampled_markets field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "unique_sampled_markets")
        assert stats.unique_sampled_markets == 0

    def test_run_statistics_has_repeated_sampled_markets(self):
        """Test RunStatistics has repeated_sampled_markets field"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "repeated_sampled_markets")
        assert stats.repeated_sampled_markets == 0

    def test_to_dict_includes_diversity_statistics(self):
        """Test to_dict includes diversity statistics"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.unique_sampled_markets = 5
        stats.repeated_sampled_markets = 2
        stats.llm_sampling_strategy = "diversified"
        stats.llm_sampling_cooldown_minutes = 30

        result = stats.to_dict()

        assert "unique_sampled_markets" in result
        assert result["unique_sampled_markets"] == 5
        assert "repeated_sampled_markets" in result
        assert result["repeated_sampled_markets"] == 2
        assert "llm_sampling_strategy" in result
        assert result["llm_sampling_strategy"] == "diversified"
        assert "llm_sampling_cooldown_minutes" in result
        assert result["llm_sampling_cooldown_minutes"] == 30

    def _create_test_market(
        self,
        market_id: str,
        status: str = "open",
        total_volume_usd: float = 50000.0,
        is_auto_allowed: bool = True,
        is_ambiguous: bool = False,
    ) -> Market:
        """Create a test market"""
        market = MagicMock(spec=Market)
        market.market_id = market_id
        market.status = status
        market.total_volume_usd = total_volume_usd
        market.volume_24h_usd = 0
        market.is_auto_allowed = MagicMock(return_value=is_auto_allowed)
        market.is_ambiguous = is_ambiguous
        market.title = f"Test question for {market_id}"
        return market

    def _create_test_orderbook(self, combined_ask: float = 0.98) -> OrderBookSnapshot:
        """Create a test orderbook"""
        orderbook = MagicMock(spec=OrderBookSnapshot)
        orderbook.combined_ask = combined_ask
        orderbook.is_stale = False
        return orderbook

    def test_cooldown_filters_recently_sampled_markets(self):
        """Test that markets in cooldown are filtered out"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_cooldown_minutes=60,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # Add a recent sample to history (within cooldown)
        runner.stats.sampled_market_history["m1"] = [datetime.now(timezone.utc)]

        market1 = self._create_test_market("m1", total_volume_usd=100000.0)
        market2 = self._create_test_market("m2", total_volume_usd=100000.0)
        orderbook1 = self._create_test_orderbook()
        orderbook2 = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates(
            [market1, market2],
            {"m1": orderbook1, "m2": orderbook2}
        )

        # m1 should be filtered due to cooldown, only m2 should be selected
        assert len(result) == 1
        assert result[0][0].market_id == "m2"

    def test_max_repeats_filters_exceeded_markets(self):
        """Test that markets exceeding max repeats are filtered out"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_max_repeats_per_market=1,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # Add a sample from long ago (exceeds max repeats but outside cooldown)
        from datetime import timedelta
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        runner.stats.sampled_market_history["m1"] = [old_time]

        market1 = self._create_test_market("m1", total_volume_usd=100000.0)
        market2 = self._create_test_market("m2", total_volume_usd=100000.0)
        orderbook1 = self._create_test_orderbook()
        orderbook2 = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates(
            [market1, market2],
            {"m1": orderbook1, "m2": orderbook2}
        )

        # m1 should be filtered due to max repeats, only m2 should be selected
        assert len(result) == 1
        assert result[0][0].market_id == "m2"

    def test_diversified_strategy_prioritizes_unsampled_markets(self):
        """Test that diversified strategy prioritizes unsampled markets"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_strategy="diversified",
            llm_sampling_per_scan=1,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # m1 was sampled long ago (outside cooldown)
        from datetime import timedelta
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        runner.stats.sampled_market_history["m1"] = [old_time]

        # m1 has higher volume but was sampled, m2 has lower volume but never sampled
        market1 = self._create_test_market("m1", total_volume_usd=200000.0)
        market2 = self._create_test_market("m2", total_volume_usd=100000.0)
        orderbook1 = self._create_test_orderbook()
        orderbook2 = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates(
            [market1, market2],
            {"m1": orderbook1, "m2": orderbook2}
        )

        # m2 should be selected because it was never sampled (diversified strategy)
        assert len(result) == 1
        assert result[0][0].market_id == "m2"

    def test_no_candidates_when_all_in_cooldown(self):
        """Test that empty list is returned when all candidates are in cooldown"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_cooldown_minutes=60,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # All markets recently sampled
        runner.stats.sampled_market_history["m1"] = [datetime.now(timezone.utc)]
        runner.stats.sampled_market_history["m2"] = [datetime.now(timezone.utc)]

        market1 = self._create_test_market("m1", total_volume_usd=100000.0)
        market2 = self._create_test_market("m2", total_volume_usd=100000.0)
        orderbook1 = self._create_test_orderbook()
        orderbook2 = self._create_test_orderbook()

        result = runner._select_llm_sampling_candidates(
            [market1, market2],
            {"m1": orderbook1, "m2": orderbook2}
        )

        # No candidates should be selected
        assert result == []

    def test_llm_sampling_still_no_trading_with_diversity(self):
        """Test that LLM sampling with diversity features still doesn't trigger trading"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )

        # Simulate diversity tracking
        stats.sampled_market_history["m1"] = [datetime.now(timezone.utc)]
        stats.unique_sampled_markets = 1
        stats.llm_sampling_strategy = "diversified"

        # Trading stats should still be separate
        stats.signals_generated = 0
        stats.paper_trades_created = 0

        result = stats.to_dict()

        # Verify separation
        assert result["unique_sampled_markets"] == 1
        assert result["signals_generated"] == 0
        assert result["paper_trades_created"] == 0

    def test_report_includes_diversity_stats(self):
        """Test that report.md includes diversity statistics"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
            llm_sampling_strategy="diversified",
            llm_sampling_cooldown_minutes=30,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.llm_sampling_enabled = True
        runner.stats.llm_sampling_strategy = "diversified"
        runner.stats.llm_sampling_cooldown_minutes = 30
        runner.stats.unique_sampled_markets = 5
        runner.stats.repeated_sampled_markets = 2
        runner.stats.sampled_markets_count = 7

        report = runner._generate_markdown_report()

        assert "Unique Markets" in report
        assert "Repeated Samples" in report
        assert "Strategy" in report
        assert "Cooldown" in report


class TestP95LatencyCalculation:
    """Test p95 latency calculation - Phase 5D.3"""

    def test_calculate_p95_latency_empty_list(self):
        """Test p95 with empty latency list"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert stats._calculate_p95_latency() is None

    def test_calculate_p95_latency_single_value(self):
        """Test p95 with single latency value"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_latencies = [10.0]
        # For n < 20, should return max (the only value)
        assert stats._calculate_p95_latency() == 10.0

    def test_calculate_p95_latency_small_sample(self):
        """Test p95 with small sample (n < 20)"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_latencies = [10.0, 20.0, 30.0, 15.0, 25.0]
        # For n < 20, should return max (sorted max = 30.0)
        assert stats._calculate_p95_latency() == 30.0

    def test_calculate_p95_latency_18_samples(self):
        """Test p95 with 18 samples (actual Phase 5D.3 case)"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        # Actual latencies from Phase 5D.3 run
        stats.llm_latencies = [
            14.43, 15.49, 15.84, 17.27, 17.42, 18.09, 18.24, 18.73,
            20.22, 21.16, 21.61, 23.99, 26.82, 27.21, 46.26, 46.63,
            48.10, 53.95
        ]
        # For n < 20, should return max = 53.95
        assert stats._calculate_p95_latency() == 53.95

    def test_calculate_p95_latency_20_samples(self):
        """Test p95 with exactly 20 samples"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_latencies = list(range(1, 21))  # 1, 2, 3, ..., 20
        # For n = 20, p95 index = int(20 * 0.95) = 19
        # sorted[19] = 20
        assert stats._calculate_p95_latency() == 20

    def test_calculate_p95_latency_100_samples(self):
        """Test p95 with 100 samples"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_latencies = list(range(1, 101))  # 1, 2, 3, ..., 100
        # For n = 100, p95 index = int(100 * 0.95) = 95
        # sorted[95] = 96
        assert stats._calculate_p95_latency() == 96

    def test_calculate_p95_latency_unsorted_input(self):
        """Test p95 with unsorted input"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_latencies = [30.0, 10.0, 50.0, 20.0, 40.0]
        # Should sort first, then return max = 50.0
        assert stats._calculate_p95_latency() == 50.0

    def test_p95_in_to_dict(self):
        """Test p95 is included in to_dict output"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_latencies = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = stats.to_dict()
        assert "llm_sampling_p95_latency_seconds" in result
        assert result["llm_sampling_p95_latency_seconds"] == 50.0


class TestLLMErrorTypeDistribution:
    """Test LLM error type distribution - Phase 5D.3"""

    def test_run_statistics_has_llm_error_type_fields(self):
        """Test RunStatistics has LLM error type fields"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "llm_sampling_server_error_count")
        assert hasattr(stats, "llm_sampling_connection_error_count")
        assert hasattr(stats, "llm_sampling_rate_limit_count")

    def test_get_llm_error_type_distribution_empty(self):
        """Test error distribution with no errors"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        dist = stats._get_llm_error_type_distribution()
        assert dist["timeout"] == 0
        assert dist["invalid_json"] == 0
        assert dist["schema_error"] == 0
        assert dist["server_error"] == 0
        assert dist["connection_error"] == 0
        assert dist["rate_limit"] == 0
        assert dist["total"] == 0

    def test_get_llm_error_type_distribution_with_errors(self):
        """Test error distribution with various errors"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_sampling_timeout_count = 3
        stats.llm_sampling_invalid_json_count = 2
        stats.llm_sampling_server_error_count = 5
        stats.llm_sampling_connection_error_count = 1

        dist = stats._get_llm_error_type_distribution()
        assert dist["timeout"] == 3
        assert dist["invalid_json"] == 2
        assert dist["server_error"] == 5
        assert dist["connection_error"] == 1
        assert dist["total"] == 11

    def test_error_distribution_in_to_dict(self):
        """Test error distribution is included in to_dict"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.llm_sampling_server_error_count = 2

        result = stats.to_dict()
        assert "llm_sampling_error_type_distribution" in result
        assert result["llm_sampling_error_type_distribution"]["server_error"] == 2


class TestAPIErrorDistribution:
    """Test API error source distribution - Phase 5D.3"""

    def test_run_statistics_has_api_error_source_fields(self):
        """Test RunStatistics has API error source fields"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "api_error_llm_provider")
        assert hasattr(stats, "api_error_clob_rest")
        assert hasattr(stats, "api_error_gamma_api")
        assert hasattr(stats, "api_error_websocket")
        assert hasattr(stats, "api_error_database")

    def test_get_api_error_type_distribution_empty(self):
        """Test API error distribution with no errors"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        dist = stats._get_api_error_type_distribution()
        assert dist["llm_provider"] == 0
        assert dist["clob_rest"] == 0
        assert dist["gamma_api"] == 0
        assert dist["websocket"] == 0
        assert dist["database"] == 0
        assert dist["total"] == 0

    def test_get_api_error_type_distribution_with_errors(self):
        """Test API error distribution with various sources"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.api_error_llm_provider = 42
        stats.api_error_clob_rest = 2

        dist = stats._get_api_error_type_distribution()
        assert dist["llm_provider"] == 42
        assert dist["clob_rest"] == 2
        assert dist["total"] == 44

    def test_api_error_distribution_in_to_dict(self):
        """Test API error distribution is included in to_dict"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.api_error_llm_provider = 42
        stats.api_error_clob_rest = 2

        result = stats.to_dict()
        assert "api_error_type_distribution" in result
        assert result["api_error_type_distribution"]["llm_provider"] == 42


class TestWebSocketReconnectSummary:
    """Test WebSocket reconnect summary - Phase 5D.3"""

    def test_run_statistics_has_websocket_reconnect_fields(self):
        """Test RunStatistics has WebSocket reconnect detail fields"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        assert hasattr(stats, "websocket_disconnects")
        assert hasattr(stats, "websocket_reconnect_successes")
        assert hasattr(stats, "websocket_reconnect_failures")

    def test_get_websocket_reconnect_summary(self):
        """Test WebSocket reconnect summary calculation"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.websocket_disconnects = 15
        stats.websocket_reconnects = 14
        stats.websocket_reconnect_successes = 14
        stats.websocket_reconnect_failures = 0
        stats.websocket_cache_hits = 7
        stats.websocket_cache_misses = 314
        stats.websocket_stale_fallbacks = 96
        stats.rest_fallbacks = 413

        summary = stats._get_websocket_reconnect_summary()
        assert summary["disconnects"] == 15
        assert summary["reconnects"] == 14
        assert summary["reconnect_successes"] == 14
        assert summary["reconnect_failures"] == 0
        # Cache hit rate = 7 / (7 + 314 + 96 + 413) = 7 / 830 = 0.0084
        assert summary["cache_hit_rate"] < 0.01
        # REST fallback rate = 413 / 830 = 0.497
        assert summary["rest_fallback_rate"] > 0.49

    def test_websocket_reconnect_summary_in_to_dict(self):
        """Test WebSocket reconnect summary is included in to_dict"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        stats.websocket_enabled = True
        stats.websocket_disconnects = 15

        result = stats.to_dict()
        assert "websocket_reconnect_summary" in result
        assert result["websocket_reconnect_summary"]["disconnects"] == 15


class TestReportIncludesNewMetrics:
    """Test that report.md includes new metrics - Phase 5D.3"""

    def test_report_includes_llm_error_distribution(self):
        """Test report includes LLM error type distribution"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
            enable_llm_sampling=True,
            llm_provider="xfyun_anthropic",
            max_llm_calls_per_hour=10,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.llm_sampling_enabled = True
        runner.stats.llm_sampling_server_error_count = 2
        runner.stats.llm_sampling_calls_failed = 2

        report = runner._generate_markdown_report()

        assert "LLM Error Type Distribution" in report
        assert "Server Error (500)" in report

    def test_report_includes_api_error_distribution(self):
        """Test report includes API error distribution"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=False,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.api_error_llm_provider = 42
        runner.stats.api_error_clob_rest = 2

        report = runner._generate_markdown_report()

        assert "API Error Distribution" in report
        assert "LLM Provider" in report

    def test_report_includes_websocket_reconnect_summary(self):
        """Test report includes WebSocket reconnect summary"""
        mock_config = MagicMock()
        mock_config.env = MagicMock()
        mock_config.env.live_trading_enabled = False
        mock_config.env.allow_auto_execution = False
        mock_config.env.paper_trading_enabled = True

        run_config = RunConfig(
            duration_minutes=5,
            data_mode="real_readonly",
            use_websocket=True,
        )

        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.now(timezone.utc),
        )
        runner.stats.websocket_enabled = True
        runner.stats.websocket_disconnects = 15
        runner.stats.websocket_reconnects = 14
        runner.stats.websocket_reconnect_successes = 14
        runner.stats.websocket_cache_hits = 7
        runner.stats.websocket_cache_misses = 314
        runner.stats.rest_fallbacks = 413

        report = runner._generate_markdown_report()

        assert "WebSocket Reconnect Summary" in report
        assert "Cache Hit Rate" in report
        assert "REST Fallback Rate" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
