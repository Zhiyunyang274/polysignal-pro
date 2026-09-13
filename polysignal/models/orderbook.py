"""
Orderbook Models - Polymarket CLOB orderbook data
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class PriceLevel(BaseModel):
    """Orderbook price level"""
    price: float = Field(..., ge=0, le=1, description="Price (0-1)")
    size: float = Field(..., ge=0, description="Size")
    total_usd: float = Field(..., ge=0, description="Total USD value")


class OrderBookSide(BaseModel):
    """One side of the orderbook"""
    levels: list[PriceLevel] = Field(default_factory=list)
    best_price: float | None = None
    best_size: float | None = None
    total_depth_usd: float = Field(0.0, ge=0)

    def calculate_best_bid(self) -> None:
        """Calculate best bid price (highest buy price) from levels"""
        if self.levels:
            # For bids, best price is the HIGHEST price (buyers want to buy low)
            best_level = max(self.levels, key=lambda x: x.price)
            self.best_price = best_level.price
            self.best_size = best_level.size
            self.total_depth_usd = sum(level.total_usd for level in self.levels)

    def calculate_best_ask(self) -> None:
        """Calculate best ask price (lowest sell price) from levels"""
        if self.levels:
            # For asks, best price is the LOWEST price (sellers want to sell high)
            best_level = min(self.levels, key=lambda x: x.price)
            self.best_price = best_level.price
            self.best_size = best_level.size
            self.total_depth_usd = sum(level.total_usd for level in self.levels)

    def calculate_best(self, is_bid: bool = True) -> None:
        """
        Calculate best price and size from levels.

        DEPRECATED: Use calculate_best_bid() or calculate_best_ask() instead.

        Args:
            is_bid: If True, calculate best bid (highest price).
                    If False, calculate best ask (lowest price).
        """
        if is_bid:
            self.calculate_best_bid()
        else:
            self.calculate_best_ask()


class OrderBookSnapshot(BaseModel):
    """Complete orderbook snapshot"""
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    market_id: str = Field(..., description="Market ID")
    timestamp: datetime = Field(default_factory=utc_now)

    # YES side
    yes_bids: OrderBookSide = Field(default_factory=OrderBookSide)  # Buy YES
    yes_asks: OrderBookSide = Field(default_factory=OrderBookSide)  # Sell YES

    # NO side
    no_bids: OrderBookSide = Field(default_factory=OrderBookSide)   # Buy NO
    no_asks: OrderBookSide = Field(default_factory=OrderBookSide)   # Sell NO

    # Calculated fields
    mid_price_yes: float | None = Field(None, description="YES mid price")
    spread_yes: float | None = Field(None, description="YES spread")
    spread_pct_yes: float | None = Field(None, description="YES spread percentage")

    # Combined ask for YES/NO mispricing detection
    combined_ask: float | None = Field(None, description="YES best ask + NO best ask")

    # Data quality
    is_stale: bool = Field(False, description="Data is stale")
    source: str = Field("mock", description="Data source")

    def calculate_metrics(self) -> None:
        """Calculate all orderbook metrics"""
        # Calculate best for each side
        # For bids, best price is highest (buyers want to buy at highest they're willing to pay)
        # For asks, best price is lowest (sellers want to sell at lowest they're willing to accept)
        self.yes_bids.calculate_best_bid()
        self.yes_asks.calculate_best_ask()
        self.no_bids.calculate_best_bid()
        self.no_asks.calculate_best_ask()

        # Calculate YES mid price and spread
        if self.yes_bids.best_price is not None and self.yes_asks.best_price is not None:
            self.mid_price_yes = (self.yes_bids.best_price + self.yes_asks.best_price) / 2
            self.spread_yes = self.yes_asks.best_price - self.yes_bids.best_price
            if self.mid_price_yes > 0:
                self.spread_pct_yes = self.spread_yes / self.mid_price_yes

        # Calculate combined ask for YES/NO mispricing
        # combined_ask = YES best ask + NO best ask
        # If combined_ask < 1.0, there's an arbitrage opportunity
        if self.yes_asks.best_price is not None and self.no_asks.best_price is not None:
            self.combined_ask = self.yes_asks.best_price + self.no_asks.best_price

    def get_yes_depth_usd(self) -> float:
        """Get total YES side depth in USD"""
        return self.yes_bids.total_depth_usd + self.yes_asks.total_depth_usd

    def get_no_depth_usd(self) -> float:
        """Get total NO side depth in USD"""
        return self.no_bids.total_depth_usd + self.no_asks.total_depth_usd

    def get_total_depth_usd(self) -> float:
        """Get total depth in USD"""
        return self.get_yes_depth_usd() + self.get_no_depth_usd()


class OrderBookUpdate(BaseModel):
    """WebSocket orderbook update (lightweight)"""
    market_id: str
    timestamp: datetime = Field(default_factory=utc_now)

    # Best prices only
    yes_best_bid: float | None = None
    yes_best_ask: float | None = None
    yes_best_bid_size: float | None = None
    yes_best_ask_size: float | None = None

    no_best_bid: float | None = None
    no_best_ask: float | None = None
    no_best_bid_size: float | None = None
    no_best_ask_size: float | None = None

    source: str = Field("mock", description="Data source")

    def get_combined_ask(self) -> float | None:
        """Calculate combined ask for YES/NO mispricing"""
        if self.yes_best_ask is not None and self.no_best_ask is not None:
            return self.yes_best_ask + self.no_best_ask
        return None
