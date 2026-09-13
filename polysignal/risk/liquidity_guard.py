"""
Liquidity Guard - Spread and depth liquidity gates.

IMPORTANT:
- Wired into Risk Governor's hard-rejection chain (Iteration 006). This module
  is now the single source of truth for the side-aware liquidity checks that
  previously lived inline in RiskGovernor._check_hard_rejections; the Governor
  delegates to it, so behaviour is unchanged by construction.
- `orderbook_stale` (freshness) and `volume_too_low` (market-level liquidity)
  remain in Risk Governor: they are not orderbook-depth concerns.
"""

from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.signal import SignalSide

SPREAD_TOO_WIDE = "spread_too_wide"
DEPTH_TOO_THIN = "depth_too_thin"


class LiquidityGuard:
    """Spread and side-aware best-level depth gates on one orderbook."""

    def __init__(self, min_depth_usd: float = 20.0, max_spread_pct: float = 0.05):
        if min_depth_usd <= 0:
            raise ValueError("min_depth_usd must be positive")
        if not 0 < max_spread_pct <= 1:
            raise ValueError("max_spread_pct must be in (0, 1]")

        self.min_depth_usd = min_depth_usd
        self.max_spread_pct = max_spread_pct

    def check_liquidity(
        self,
        orderbook: OrderBookSnapshot,
        signal_side: SignalSide,
    ) -> list[str]:
        """Return hard-reject reasons for spread/depth violations.

        Depth is checked on the side(s) the signal would consume: the ask
        side for an entry (YES/NO/BOTH), mirroring the original inline checks.
        """
        orderbook.calculate_metrics()
        reasons: list[str] = []

        if (
            orderbook.spread_pct_yes is not None
            and orderbook.spread_pct_yes > self.max_spread_pct
        ):
            reasons.append(SPREAD_TOO_WIDE)

        if signal_side == SignalSide.BOTH:
            if (
                orderbook.yes_asks.total_depth_usd < self.min_depth_usd
                or orderbook.no_asks.total_depth_usd < self.min_depth_usd
            ):
                reasons.append(DEPTH_TOO_THIN)
        elif signal_side == SignalSide.YES:
            if orderbook.yes_asks.total_depth_usd < self.min_depth_usd:
                reasons.append(DEPTH_TOO_THIN)
        elif signal_side == SignalSide.NO:
            if orderbook.no_asks.total_depth_usd < self.min_depth_usd:
                reasons.append(DEPTH_TOO_THIN)

        return reasons
