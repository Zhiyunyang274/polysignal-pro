"""

Real-Time Monitor - Continuous spot + orderbook polling for information lag detection

IMPORTANT:
- Research tool: detects when Polymarket market prices lag behind external
  spot prices. Does NOT place orders or call an LLM.
- Core hypothesis: when the external spot moves sharply toward/away from a
  barrier, the Polymarket market should reprice immediately. A lag window is
  the arbitrage opportunity.
- This module polls Binance (primary) and Coinbase (fallback) tickers plus
  CLOB orderbooks, computes the model-implied probability, and records
  observations where |model_prob - market_prob| exceeds a threshold.
- Read-only: no orders, no keys, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from polysignal.utils.time import utc_now


@dataclass
class LagObservation:
    """One real-time lag detection observation."""

    timestamp: str
    market_id: str
    asset: str
    threshold_price: float
    barrier_direction: str  # "up" / "down"
    spot_price: float
    spot_source: str
    market_yes_bid: float
    market_yes_ask: float
    market_mid: float
    model_probability: float
    edge: float  # model_probability - market_mid
    edge_bps: int  # edge in basis points of market_mid
    is_significant: bool


@dataclass
class RealTimeMonitorConfig:
    """Monitoring parameters."""

    assets: list[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    poll_interval_seconds: float = 5.0
    edge_threshold_bps: int = 50  # minimum edge in bps to record
    lookback_minutes: int = 5  # spot move detection window
    max_observations: int = 1000


class RealTimeMonitor:
    """
    Polls spot and market prices, detects lag.

    The detection logic:
    1. Poll spot price from Binance/Coinbase ticker
    2. Poll Polymarket CLOB orderbook for the same asset's threshold market
    3. Compute model probability of barrier touch using distance/time/vol
    4. Compare model probability with market implied probability (mid)
    5. Record observation if edge > threshold

    This is the real-time counterpart to the batch discovery: instead of
    scanning once and waiting 240 minutes, it monitors continuously and
    catches the brief windows when the market lags the spot.
    """

    def __init__(self, config: RealTimeMonitorConfig):
        self.config = config
        self.observations: list[LagObservation] = []
        self._last_spot: dict[str, float] = {}
        self._spot_change_rate: dict[str, float] = {}

    def compute_model_probability(
        self,
        spot: float,
        threshold: float,
        barrier_direction: str,
        time_to_expiry_hours: float,
        annual_vol: float,
    ) -> float:
        """
        Compute the model-implied probability of barrier touch.

        Uses a simplified one-touch barrier model:
        P(touch) ≈ 2 * N(-|ln(S/K)| / (σ√T))

        where S = spot, K = threshold, σ = annualized vol, T = time to expiry.
        """
        import math

        if spot <= 0 or threshold <= 0 or time_to_expiry_hours <= 0:
            return 0.5

        T = time_to_expiry_hours / (365 * 24)  # years
        if T <= 0:
            return 0.5

        sigma_T = annual_vol * math.sqrt(T)
        if sigma_T <= 0:
            return 0.5

        log_ratio = math.log(threshold / spot)

        if barrier_direction == "up":
            # One-touch reflection principle approximation (discrete-adjusted)
            z = log_ratio / sigma_T
            prob = min(1.0, 2 * _norm_cdf(-z) * 0.85)  # 0.85 factor for discrete-time discount
        elif barrier_direction == "down":
            z = -log_ratio / sigma_T
            prob = min(1.0, 2 * _norm_cdf(-z) * 0.85)
        else:
            prob = 0.5

        return max(0.0, min(0.98, prob))

    def detect_lag(
        self,
        market_id: str,
        asset: str,
        threshold_price: float,
        barrier_direction: str,
        spot_price: float,
        spot_source: str,
        market_yes_bid: float,
        market_yes_ask: float,
        time_to_expiry_hours: float,
        annual_vol: float = 0.75,
        now: datetime | None = None,
    ) -> LagObservation:
        """One detection cycle: compare model probability with market mid."""
        now_dt = now or utc_now()
        market_mid = (market_yes_bid + market_yes_ask) / 2

        model_prob = self.compute_model_probability(
            spot=spot_price,
            threshold=threshold_price,
            barrier_direction=barrier_direction,
            time_to_expiry_hours=time_to_expiry_hours,
            annual_vol=annual_vol,
        )

        edge = model_prob - market_mid
        edge_bps = int(abs(edge) / max(market_mid, 0.001) * 10_000)
        is_significant = edge_bps >= self.config.edge_threshold_bps

        obs = LagObservation(
            timestamp=now_dt.isoformat(),
            market_id=market_id,
            asset=asset,
            threshold_price=threshold_price,
            barrier_direction=barrier_direction,
            spot_price=spot_price,
            spot_source=spot_source,
            market_yes_bid=market_yes_bid,
            market_yes_ask=market_yes_ask,
            market_mid=round(market_mid, 4),
            model_probability=round(model_prob, 4),
            edge=round(edge, 4),
            edge_bps=edge_bps,
            is_significant=is_significant,
        )

        self.observations.append(obs)
        if len(self.observations) > self.config.max_observations:
            self.observations = self.observations[-self.config.max_observations // 2:]

        return obs

    def get_significant_observations(self) -> list[LagObservation]:
        return [obs for obs in self.observations if obs.is_significant]


def _norm_cdf(x: float) -> float:
    """Standard normal CDF (Abramowitz & Stegun approximation)."""
    import math
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
