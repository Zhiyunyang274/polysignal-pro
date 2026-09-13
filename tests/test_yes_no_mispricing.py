"""
Tests for YES/NO Mispricing Strategy
"""

import pytest

from polysignal.models.market import MarketCategory
from polysignal.models.signal import SignalSide
from polysignal.strategies.base import StrategyContext
from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy
from tests.fixtures.markets import create_mock_market
from tests.fixtures.orderbooks import (
    create_mispricing_orderbook,
    create_mock_orderbook,
    create_thin_depth_orderbook,
    create_wide_spread_orderbook,
)


class TestYesNoMispricingStrategy:
    """Test YES/NO mispricing strategy"""

    @pytest.fixture
    def strategy(self) -> YesNoMispricingStrategy:
        """Create strategy with default settings"""
        return YesNoMispricingStrategy(
            combined_ask_threshold=0.985,
            min_depth_usd=20,
            min_volume_usd=100000,
            max_spread_pct=0.05,
        )

    def test_strategy_properties(self, strategy: YesNoMispricingStrategy):
        """Test strategy properties"""
        assert strategy.name == "yes_no_mispricing"
        assert "mispricing" in strategy.description.lower()
        assert len(strategy.risk_notes) > 0

    def test_no_signal_without_mispricing(self, strategy: YesNoMispricingStrategy):
        """Test no signal when combined_ask is above threshold"""
        orderbook = create_mock_orderbook(
            yes_ask=0.50,
            no_ask=0.50,  # combined_ask = 1.0, no mispricing
        )
        market = create_mock_market()

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should not generate signal
        assert signal is None

    def test_signal_with_mispricing(self, strategy: YesNoMispricingStrategy):
        """Test signal generation with mispricing"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market()

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should generate signal
        assert signal is not None
        assert signal.side == SignalSide.BOTH
        assert signal.price < 0.985
        assert signal.strategy_name == "yes_no_mispricing"

    def test_signal_score_increases_with_gap(self, strategy: YesNoMispricingStrategy):
        """Test that score increases with mispricing gap"""
        market = create_mock_market()

        # Small gap
        orderbook_small = create_mispricing_orderbook(combined_ask=0.980)
        context_small = StrategyContext(market=market, orderbook=orderbook_small)
        signal_small = strategy.compute_signal(context_small)

        # Large gap
        orderbook_large = create_mispricing_orderbook(combined_ask=0.950)
        context_large = StrategyContext(market=market, orderbook=orderbook_large)
        signal_large = strategy.compute_signal(context_large)

        if signal_small and signal_large:
            assert signal_large.raw_score > signal_small.raw_score

    def test_no_signal_with_wide_spread(self, strategy: YesNoMispricingStrategy):
        """Test no signal with wide spread"""
        orderbook = create_wide_spread_orderbook(spread_pct=0.10)
        market = create_mock_market()

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should not generate signal due to wide spread
        assert signal is None

    def test_no_signal_with_thin_depth(self, strategy: YesNoMispricingStrategy):
        """Test no signal with thin depth"""
        orderbook = create_thin_depth_orderbook(depth_usd=10)
        market = create_mock_market()

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should not generate signal due to thin depth
        assert signal is None

    def test_no_signal_with_low_volume(self, strategy: YesNoMispricingStrategy):
        """Test no signal with low volume market"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market(total_volume_usd=50000)  # Below threshold

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should not generate signal due to low volume
        assert signal is None

    def test_signal_for_forbidden_category(self, strategy: YesNoMispricingStrategy):
        """Test signal for forbidden category still generates but with flag"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market(category=MarketCategory.POLITICS, is_forbidden_auto=True)

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should generate signal but with risk flag
        assert signal is not None
        assert "forbidden_auto_category" in signal.risk_flags

    def test_signal_for_ambiguous_market(self, strategy: YesNoMispricingStrategy):
        """Test signal for ambiguous market has risk flag"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market(is_ambiguous=True)

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Should generate signal but with risk flag
        assert signal is not None
        assert "ambiguous_market" in signal.risk_flags

    def test_explain_signal(self, strategy: YesNoMispricingStrategy):
        """Test signal explanation"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market()

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        if signal:
            explanation = strategy.explain_signal(signal)
            assert "yes_no_mispricing" in explanation.lower()

    def test_both_side_only_for_mispricing(self, strategy: YesNoMispricingStrategy):
        """Test that BOTH side is only used for YES/NO mispricing"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market()

        context = StrategyContext(
            market=market,
            orderbook=orderbook,
        )

        signal = strategy.compute_signal(context)

        # Signal should use BOTH side
        assert signal is not None
        assert signal.side == SignalSide.BOTH
