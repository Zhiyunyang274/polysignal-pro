"""

YES/NO Mispricing Strategy - Detect arbitrage opportunities in YES/NO combined pricing

Strategy Logic:
- combined_ask = yes_best_ask + no_best_ask
- If combined_ask < 1.0, there's potential arbitrage
- Signal threshold: combined_ask <= 0.985

IMPORTANT:
- SignalSide.BOTH is ONLY used for YES/NO mispricing paper trading
- This strategy does NOT trigger live execution by default
- All signals must pass through Risk Governor
"""

from typing import Optional, Union, Any
from datetime import datetime

from polysignal.models.signal import Signal, SignalSide, ComponentScores
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.market import Market, MarketCategory
from polysignal.strategies.base import Strategy, StrategyContext


class YesNoMispricingStrategy(Strategy):
    """
    YES/NO Combined Mispricing Strategy.

    Detects when the combined ask of YES and NO tokens is below 1.0,
    indicating a potential arbitrage opportunity.

    This strategy operates in the ULTRA-FAST path:
    - No LLM calls
    - No slow API calls
    - Only orderbook calculations

    Risk Notes:
    - Both sides may not fill simultaneously
    - Partial fill risk
    - Orderbook may change before execution
    - Resolution risk if market is ambiguous
    """

    # Default thresholds
    DEFAULT_COMBINED_ASK_THRESHOLD = 0.985
    DEFAULT_MIN_DEPTH_USD = 20.0
    DEFAULT_MIN_VOLUME_USD = 100000.0
    DEFAULT_MAX_SPREAD_PCT = 0.05

    def __init__(
        self,
        combined_ask_threshold: float = DEFAULT_COMBINED_ASK_THRESHOLD,
        min_depth_usd: float = DEFAULT_MIN_DEPTH_USD,
        min_volume_usd: float = DEFAULT_MIN_VOLUME_USD,
        max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT,
    ):
        """
        Initialize YES/NO mispricing strategy.

        Args:
            combined_ask_threshold: Signal threshold (default 0.985)
            min_depth_usd: Minimum depth required
            min_volume_usd: Minimum market volume required
            max_spread_pct: Maximum spread allowed
        """
        self.combined_ask_threshold = combined_ask_threshold
        self.min_depth_usd = min_depth_usd
        self.min_volume_usd = min_volume_usd
        self.max_spread_pct = max_spread_pct

    @property
    def name(self) -> str:
        return "yes_no_mispricing"

    @property
    def description(self) -> str:
        return (
            "Detects YES/NO combined mispricing opportunities. "
            f"Signals when combined_ask <= {self.combined_ask_threshold}"
        )

    @property
    def risk_notes(self) -> list[str]:
        return [
            "Both sides may not fill simultaneously",
            "Partial fill risk exists",
            "Orderbook may change before execution",
            "Resolution risk if market is ambiguous",
            "Transaction costs may eliminate profit",
        ]

    def compute_signal(self, context: StrategyContext) -> Optional[Signal]:
        """
        Compute YES/NO mispricing signal.

        Args:
            context: Strategy context with orderbook and market data

        Returns:
            Signal if mispricing detected, None otherwise
        """
        orderbook = context.orderbook
        market = context.market

        # Validate inputs
        if orderbook is None:
            return None

        # Ensure metrics are calculated
        orderbook.calculate_metrics()

        # Check combined ask
        combined_ask = orderbook.combined_ask
        if combined_ask is None:
            return None

        # Check if mispricing exists
        if combined_ask > self.combined_ask_threshold:
            return None

        # Check depth requirements
        yes_depth = orderbook.yes_asks.total_depth_usd
        no_depth = orderbook.no_asks.total_depth_usd

        if yes_depth < self.min_depth_usd or no_depth < self.min_depth_usd:
            return None

        # Check spread
        spread_pct = orderbook.spread_pct_yes
        if spread_pct is not None and spread_pct > self.max_spread_pct:
            return None

        # Check market volume if available
        if market is not None:
            if market.total_volume_usd < self.min_volume_usd:
                return None

            # Check if market is forbidden for auto-execution
            if not market.is_auto_allowed():
                # Still generate signal but add risk flag
                pass

        # Calculate signal score
        raw_score = self._calculate_score(combined_ask, yes_depth, no_depth)

        # Get component scores
        component_scores = context.component_scores or ComponentScores()
        component_scores.microstructure_score = raw_score
        component_scores.liquidity_score = self._calculate_liquidity_score(yes_depth, no_depth)

        # Create signal
        signal = Signal(
            market_id=orderbook.market_id,
            market_title=market.title if market else f"Market {orderbook.market_id}",
            market_category=market.category.value if market else "other",
            strategy_name=self.name,
            strategy_version=self.version,
            side=SignalSide.BOTH,  # ONLY for YES/NO mispricing
            price=combined_ask,
            target_price=1.0,  # Target is to hold to resolution
            component_scores=component_scores,
            raw_score=raw_score,
            reason=f"Combined ask {combined_ask:.4f} < threshold {self.combined_ask_threshold}",
            explanation=self._generate_explanation(combined_ask, yes_depth, no_depth),
            path_type="ultra_fast",
            data_source=orderbook.source,
        )

        # Add risk flags
        if market and not market.is_auto_allowed():
            signal.add_risk_flag("forbidden_auto_category")
        if market and market.is_ambiguous:
            signal.add_risk_flag("ambiguous_market")

        return signal

    def _calculate_score(
        self,
        combined_ask: float,
        yes_depth: float,
        no_depth: float,
    ) -> float:
        """
        Calculate signal score (0-100).

        Higher score = better opportunity.
        """
        # Base score from mispricing magnitude
        # The lower combined_ask, the higher the score
        mispricing_gap = 1.0 - combined_ask
        base_score = min(100, mispricing_gap * 1000)  # 0.01 gap = 10 points

        # Depth bonus
        min_depth = min(yes_depth, no_depth)
        if min_depth >= 100:
            depth_bonus = 10
        elif min_depth >= 50:
            depth_bonus = 5
        else:
            depth_bonus = 0

        score = base_score + depth_bonus

        return max(0, min(100, score))

    def _calculate_liquidity_score(
        self,
        yes_depth: float,
        no_depth: float,
    ) -> float:
        """Calculate liquidity score based on depth"""
        min_depth = min(yes_depth, no_depth)
        avg_depth = (yes_depth + no_depth) / 2

        # Score based on minimum depth
        if min_depth >= 100:
            score = 90
        elif min_depth >= 50:
            score = 80
        elif min_depth >= 20:
            score = 70
        else:
            score = 50

        return score

    def _generate_explanation(
        self,
        combined_ask: float,
        yes_depth: float,
        no_depth: float,
    ) -> str:
        """Generate human-readable explanation"""
        gap = 1.0 - combined_ask
        gap_pct = gap * 100

        return (
            f"YES/NO Mispricing detected: combined_ask={combined_ask:.4f} "
            f"(gap={gap_pct:.2f}%). "
            f"YES ask depth: ${yes_depth:.0f}, NO ask depth: ${no_depth:.0f}. "
            f"Potential profit if both sides fill and market resolves correctly."
        )
