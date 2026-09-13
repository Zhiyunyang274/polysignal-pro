"""

Market Microstructure Engine - Analyze orderbook microstructure

This engine operates in the ULTRA-FAST path and does NOT call LLM.

Responsibilities:
- Calculate spread, depth, imbalance
- Detect YES/NO combined ask mispricing
- Calculate microstructure_score
"""

from typing import Any

from polysignal.models.orderbook import OrderBookSnapshot, OrderBookUpdate
from polysignal.models.signal import ComponentScores
from polysignal.utils.time import utc_now


class MicrostructureResult:
    """Result of microstructure analysis"""

    def __init__(
        self,
        spread_pct: float = 0.0,
        total_depth_usd: float = 0.0,
        imbalance_ratio: float = 0.5,
        combined_ask: float | None = None,
        is_mispriced: bool = False,
        microstructure_score: float = 0.0,
        liquidity_score: float = 0.0,
    ):
        self.spread_pct = spread_pct
        self.total_depth_usd = total_depth_usd
        self.imbalance_ratio = imbalance_ratio
        self.combined_ask = combined_ask
        self.is_mispriced = is_mispriced
        self.microstructure_score = microstructure_score
        self.liquidity_score = liquidity_score
        self.timestamp = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "spread_pct": self.spread_pct,
            "total_depth_usd": self.total_depth_usd,
            "imbalance_ratio": self.imbalance_ratio,
            "combined_ask": self.combined_ask,
            "is_mispriced": self.is_mispriced,
            "microstructure_score": self.microstructure_score,
            "liquidity_score": self.liquidity_score,
            "timestamp": self.timestamp.isoformat(),
        }


class MarketMicrostructureEngine:
    """
    Market Microstructure Engine - Analyzes orderbook microstructure.

    This engine operates in the ULTRA-FAST path:
    - No LLM calls
    - No slow API calls
    - Only in-memory calculations
    - Target latency: 0.1-2 seconds
    """

    # Thresholds for scoring
    SPREAD_GOOD_THRESHOLD = 0.02  # 2% spread is good
    SPREAD_BAD_THRESHOLD = 0.05   # 5% spread is bad

    DEPTH_GOOD_THRESHOLD = 1000   # $1000 depth is good
    DEPTH_BAD_THRESHOLD = 50      # $50 depth is bad

    COMBINED_ASK_THRESHOLD = 0.985  # Below this = potential mispricing

    def __init__(
        self,
        spread_good_threshold: float = SPREAD_GOOD_THRESHOLD,
        spread_bad_threshold: float = SPREAD_BAD_THRESHOLD,
        depth_good_threshold: float = DEPTH_GOOD_THRESHOLD,
        depth_bad_threshold: float = DEPTH_BAD_THRESHOLD,
        combined_ask_threshold: float = COMBINED_ASK_THRESHOLD,
    ):
        """Initialize engine with thresholds"""
        self.spread_good_threshold = spread_good_threshold
        self.spread_bad_threshold = spread_bad_threshold
        self.depth_good_threshold = depth_good_threshold
        self.depth_bad_threshold = depth_bad_threshold
        self.combined_ask_threshold = combined_ask_threshold

    def analyze_snapshot(self, snapshot: OrderBookSnapshot) -> MicrostructureResult:
        """
        Analyze an orderbook snapshot.

        Args:
            snapshot: Orderbook snapshot to analyze

        Returns:
            MicrostructureResult with analysis
        """
        # Ensure metrics are calculated
        snapshot.calculate_metrics()

        # Calculate spread percentage
        spread_pct = snapshot.spread_pct_yes or 0.0

        # Calculate total depth
        total_depth_usd = snapshot.get_total_depth_usd()

        # Calculate imbalance (bid vs ask depth)
        yes_bid_depth = snapshot.yes_bids.total_depth_usd
        yes_ask_depth = snapshot.yes_asks.total_depth_usd
        total_yes_depth = yes_bid_depth + yes_ask_depth

        imbalance_ratio = yes_bid_depth / total_yes_depth if total_yes_depth > 0 else 0.5

        # Get combined ask
        combined_ask = snapshot.combined_ask

        # Detect mispricing
        is_mispriced = (
            combined_ask is not None
            and combined_ask < self.combined_ask_threshold
            and total_depth_usd >= self.depth_bad_threshold
        )

        # Calculate scores
        microstructure_score = self._calculate_microstructure_score(
            spread_pct=spread_pct,
            imbalance_ratio=imbalance_ratio,
            is_mispriced=is_mispriced,
        )

        liquidity_score = self._calculate_liquidity_score(
            spread_pct=spread_pct,
            total_depth_usd=total_depth_usd,
        )

        return MicrostructureResult(
            spread_pct=spread_pct,
            total_depth_usd=total_depth_usd,
            imbalance_ratio=imbalance_ratio,
            combined_ask=combined_ask,
            is_mispriced=is_mispriced,
            microstructure_score=microstructure_score,
            liquidity_score=liquidity_score,
        )

    def analyze_update(self, update: OrderBookUpdate) -> MicrostructureResult:
        """
        Analyze an orderbook update (lightweight).

        Args:
            update: Orderbook update to analyze

        Returns:
            MicrostructureResult with analysis
        """
        # Get combined ask
        combined_ask = update.get_combined_ask()

        # Detect mispricing
        is_mispriced = combined_ask is not None and combined_ask < self.combined_ask_threshold

        # For updates, we have less data, so scores are simpler
        if is_mispriced:
            microstructure_score = 80.0
            liquidity_score = 70.0
        else:
            microstructure_score = 50.0
            liquidity_score = 50.0

        return MicrostructureResult(
            combined_ask=combined_ask,
            is_mispriced=is_mispriced,
            microstructure_score=microstructure_score,
            liquidity_score=liquidity_score,
        )

    def _calculate_microstructure_score(
        self,
        spread_pct: float,
        imbalance_ratio: float,
        is_mispriced: bool,
    ) -> float:
        """
        Calculate microstructure score (0-100).

        Higher score = better trading opportunity.
        """
        score = 50.0  # Base score

        # Spread component (tighter is better)
        if spread_pct <= self.spread_good_threshold:
            score += 20
        elif spread_pct >= self.spread_bad_threshold:
            score -= 20
        else:
            # Linear interpolation
            spread_score = 20 * (1 - (spread_pct - self.spread_good_threshold) /
                                 (self.spread_bad_threshold - self.spread_good_threshold))
            score += spread_score

        # Imbalance component (extreme imbalance may indicate opportunity)
        imbalance_deviation = abs(imbalance_ratio - 0.5)
        if imbalance_deviation > 0.3:
            score += 10  # Significant imbalance

        # Mispricing bonus
        if is_mispriced:
            score += 25

        return max(0, min(100, score))

    def _calculate_liquidity_score(
        self,
        spread_pct: float,
        total_depth_usd: float,
    ) -> float:
        """
        Calculate liquidity score (0-100).

        Higher score = better liquidity.
        """
        score = 50.0  # Base score

        # Depth component
        if total_depth_usd >= self.depth_good_threshold:
            score += 25
        elif total_depth_usd <= self.depth_bad_threshold:
            score -= 25
        else:
            # Linear interpolation
            depth_score = 25 * (total_depth_usd - self.depth_bad_threshold) / \
                         (self.depth_good_threshold - self.depth_bad_threshold)
            score += depth_score

        # Spread component
        if spread_pct <= self.spread_good_threshold:
            score += 25
        elif spread_pct >= self.spread_bad_threshold:
            score -= 25
        else:
            spread_score = 25 * (1 - (spread_pct - self.spread_good_threshold) /
                                 (self.spread_bad_threshold - self.spread_good_threshold))
            score += spread_score

        return max(0, min(100, score))

    def get_component_scores(self, snapshot: OrderBookSnapshot) -> ComponentScores:
        """
        Get component scores for a snapshot.

        This is used by strategies to get pre-calculated scores.
        """
        result = self.analyze_snapshot(snapshot)

        return ComponentScores(
            microstructure_score=result.microstructure_score,
            liquidity_score=result.liquidity_score,
            event_score=50.0,  # Default neutral (calculated by other engines)
            wallet_score=50.0,  # Default neutral
            lifecycle_score=50.0,  # Default neutral
        )
