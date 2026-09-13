"""

Market Maker - Dual-side quoting around a fair value estimate

IMPORTANT:
- This module generates bid/ask quotes and tracks inventory. It does NOT
  submit orders or interact with any exchange API.
- Deterministic by construction: same inputs produce same quotes.
- Inventory skew: when holding too much of one side, quotes are shifted to
  attract inventory-reducing flow. This is the core mechanism that keeps
  the market maker direction-neutral.
- All prices are in [0, 1] (Polymarket outcome token convention).

Design (ADR-030):
- Fair value is the mid-price of the current orderbook (first iteration).
  Later iterations may use an external-signal-informed model.
- Quotes are placed at fair_value ± half_spread, further skewed by inventory.
- Each fill updates inventory; the quote engine reacts on the next call.
"""

from __future__ import annotations

from math import isfinite

from pydantic import BaseModel, Field


class MarketMakerConfig(BaseModel):
    """Quoting and inventory parameters."""

    half_spread_pct: float = Field(0.02, description="Half-spread as fraction of fair value")
    inventory_limit: float = Field(100.0, description="Max absolute inventory (shares)", gt=0)
    skew_factor: float = Field(
        0.5, description="How aggressively to skew quotes per unit of inventory", gt=0
    )
    max_inventory_skew: float = Field(
        0.05, description="Max price skew from inventory (fraction)", ge=0
    )
    order_size: float = Field(10.0, description="Quote size per side (shares)", gt=0)
    min_half_spread_pct: float = Field(0.005, description="Floor for half-spread", gt=0)
    vol_multiplier: float = Field(
        1.0, description="Volatility multiplier: spread widens proportionally", ge=0
    )

    def validate_params(self) -> None:
        if not isfinite(self.half_spread_pct) or self.half_spread_pct <= 0:
            raise ValueError("half_spread_pct must be positive")
        if not isfinite(self.skew_factor) or self.skew_factor <= 0:
            raise ValueError("skew_factor must be positive")
        if not isfinite(self.max_inventory_skew) or self.max_inventory_skew < 0:
            raise ValueError("max_inventory_skew must be non-negative")


class QuotePair(BaseModel):
    """A pair of bid and ask quotes."""

    bid_price: float = Field(..., ge=0, le=1)
    ask_price: float = Field(..., ge=0, le=1)
    bid_size: float = Field(..., ge=0)
    ask_size: float = Field(..., ge=0)
    fair_value: float = Field(..., ge=0, le=1)
    inventory_skew: float = Field(0.0)
    skipped: bool = Field(False, description="True when quoting is suppressed")
    skip_reason: str = Field("")


class MarketMaker:
    """Dual-side quoting with inventory skew.

    Given a fair value estimate and current inventory, produces bid/ask quotes.
    Quotes shift to attract inventory-reducing flow when position is unbalanced.
    """

    def __init__(self, config: MarketMakerConfig):
        config.validate_params()
        self.config = config

    def compute_quotes(
        self,
        fair_value: float,
        inventory: float = 0.0,
        volatility: float = 0.0,
        external_signal: float | None = None,
        signal_weight: float = 0.3,
    ) -> QuotePair:
        """Generate bid/ask quotes.

        Args:
            fair_value: Best estimate of the true probability (0-1).
            inventory: Current YES inventory in shares (positive = long YES,
                       negative = long NO via YES convention).

        Returns:
            QuotePair with bid/ask prices and sizes.
        """
        cfg = self.config

        if not isfinite(fair_value) or fair_value <= 0 or fair_value >= 1:
            return QuotePair(
                bid_price=0, ask_price=0, bid_size=0, ask_size=0,
                fair_value=max(0, min(1, fair_value)) if isfinite(fair_value) else 0,
                skipped=True, skip_reason="invalid_fair_value",
            )

        half_spread = cfg.half_spread_pct * fair_value
        half_spread = max(half_spread, cfg.min_half_spread_pct)
        # Dynamic spread widening: high volatility → wider spread to mitigate
        # adverse selection (ADR-030 / Iteration 031). Volatility is the caller-
        # measured recent price std as a fraction (e.g. 0.03 = 3% per step).
        vol_adj = cfg.vol_multiplier * max(0.0, volatility)
        half_spread *= 1.0 + vol_adj

        # External signal blending (Iteration 034): when RealTimeMonitor detects
        # a lag, the external-signal probability is more accurate than the
        # orderbook mid. Blend it into the fair value to correct quotes.
        if external_signal is not None and isfinite(external_signal) and 0 <= external_signal <= 1:
            fair_value = fair_value * (1 - signal_weight) + external_signal * signal_weight

        # Inventory skew: positive inventory (long YES) → shift quotes DOWN
        # to make bids less attractive and asks more attractive, encouraging
        # inventory reduction. Negative inventory (short YES / long NO) → shift UP.
        inventory_ratio = inventory / cfg.inventory_limit if cfg.inventory_limit > 0 else 0.0
        inventory_ratio = max(-1.0, min(1.0, inventory_ratio))
        skew = -inventory_ratio * cfg.skew_factor * cfg.max_inventory_skew

        bid_price = fair_value - half_spread + skew
        ask_price = fair_value + half_spread + skew

        # Clamp to valid price range and ensure bid < ask
        bid_price = max(0.01, min(0.99, bid_price))
        ask_price = max(0.01, min(0.99, ask_price))

        if bid_price >= ask_price:
            bid_price = fair_value - half_spread
            ask_price = fair_value + half_spread
            bid_price = max(0.01, min(0.99, bid_price))
            ask_price = max(0.01, min(0.99, ask_price))
            if bid_price >= ask_price:
                return QuotePair(
                    bid_price=0, ask_price=0, bid_size=0, ask_size=0,
                    fair_value=fair_value, inventory_skew=skew,
                    skipped=True, skip_reason="quotes_crossed_after_clamping",
                )

        # Suppress quoting when inventory is at the limit
        if abs(inventory) >= cfg.inventory_limit:
            return QuotePair(
                bid_price=0, ask_price=0, bid_size=0, ask_size=0,
                fair_value=fair_value, inventory_skew=skew,
                skipped=True, skip_reason="inventory_limit_reached",
            )

        return QuotePair(
            bid_price=round(bid_price, 4),
            ask_price=round(ask_price, 4),
            bid_size=cfg.order_size,
            ask_size=cfg.order_size,
            fair_value=round(fair_value, 4),
            inventory_skew=round(skew, 6),
        )


class InventoryTracker:
    """Tracks YES-side inventory from fills.

    Positive inventory = long YES (bought YES).
    Negative inventory = effectively long NO (sold YES short or bought NO).
    """

    def __init__(self):
        self.inventory: float = 0.0
        self.cash_flow: float = 0.0  # positive = received cash (sold), negative = paid (bought)
        self.fill_count: int = 0
        self.realized_pnl: float = 0.0
        self._last_prices: list[float] = []

    def on_buy_fill(self, price: float, size: float) -> None:
        if not isfinite(price) or not isfinite(size) or price <= 0 or size <= 0:
            raise ValueError(f"invalid fill: price={price}, size={size}")
        self.inventory += size
        self.cash_flow -= price * size
        self.fill_count += 1
        self._last_prices.append(price)

    def on_sell_fill(self, price: float, size: float) -> None:
        if not isfinite(price) or not isfinite(size) or price <= 0 or size <= 0:
            raise ValueError(f"invalid fill: price={price}, size={size}")
        self.inventory -= size
        self.cash_flow += price * size
        self.fill_count += 1
        self._last_prices.append(price)

    @property
    def is_flat(self) -> bool:
        return abs(self.inventory) < 1e-9

    @property
    def average_entry_price(self) -> float | None:
        if not self._last_prices or self.inventory <= 0:
            return None
        return sum(self._last_prices) / len(self._last_prices)
