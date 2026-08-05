"""

from __future__ import annotations
Test Fixtures - Mock orderbooks
"""

from polysignal.models.orderbook import (
    OrderBookSnapshot,
    OrderBookUpdate,
    OrderBookSide,
    PriceLevel,
)


def create_mock_orderbook(
    market_id: str = "test_market_001",
    yes_bid: float = 0.45,
    yes_ask: float = 0.47,
    no_bid: float = 0.53,
    no_ask: float = 0.55,
    yes_depth_usd: float = 100,
    no_depth_usd: float = 100,
    is_stale: bool = False,
) -> OrderBookSnapshot:
    """Create a mock orderbook for testing"""
    snapshot = OrderBookSnapshot(
        market_id=market_id,
        yes_bids=OrderBookSide(
            levels=[
                PriceLevel(price=yes_bid, size=yes_depth_usd / yes_bid, total_usd=yes_depth_usd)
            ]
        ),
        yes_asks=OrderBookSide(
            levels=[
                PriceLevel(price=yes_ask, size=yes_depth_usd / yes_ask, total_usd=yes_depth_usd)
            ]
        ),
        no_bids=OrderBookSide(
            levels=[
                PriceLevel(price=no_bid, size=no_depth_usd / no_bid, total_usd=no_depth_usd)
            ]
        ),
        no_asks=OrderBookSide(
            levels=[
                PriceLevel(price=no_ask, size=no_depth_usd / no_ask, total_usd=no_depth_usd)
            ]
        ),
        is_stale=is_stale,
        source="test",
    )
    snapshot.calculate_metrics()
    return snapshot


def create_mispricing_orderbook(
    market_id: str = "test_market_001",
    combined_ask: float = 0.975,
) -> OrderBookSnapshot:
    """Create an orderbook with YES/NO mispricing"""
    # Split combined ask between YES and NO
    yes_ask = 0.48
    no_ask = combined_ask - yes_ask
    if no_ask < 0.01:
        no_ask = 0.01
        yes_ask = combined_ask - no_ask

    yes_bid = yes_ask - 0.02
    no_bid = no_ask - 0.02

    return create_mock_orderbook(
        market_id=market_id,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
    )


def create_wide_spread_orderbook(
    market_id: str = "test_market_001",
    spread_pct: float = 0.10,  # 10% spread
) -> OrderBookSnapshot:
    """Create an orderbook with wide spread"""
    mid = 0.50
    half_spread = spread_pct / 2

    return create_mock_orderbook(
        market_id=market_id,
        yes_bid=mid - half_spread,
        yes_ask=mid + half_spread,
        no_bid=1 - mid - half_spread,
        no_ask=1 - mid + half_spread,
    )


def create_thin_depth_orderbook(
    market_id: str = "test_market_001",
    depth_usd: float = 10,  # Very thin
) -> OrderBookSnapshot:
    """Create an orderbook with thin depth"""
    return create_mock_orderbook(
        market_id=market_id,
        yes_depth_usd=depth_usd,
        no_depth_usd=depth_usd,
    )
