"""

Mock Data Provider - Generate mock market and orderbook data for testing

IMPORTANT: This module generates fake data for testing purposes only.
It does NOT connect to real Polymarket APIs.
"""

import random
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from polysignal.models.market import Market, MarketCategory, MarketStatus, MarketList
from polysignal.models.orderbook import (
    OrderBookSnapshot,
    OrderBookUpdate,
    OrderBookSide,
    PriceLevel,
)


class MockDataProvider:
    """
    Generate mock market and orderbook data for testing.

    This provider generates deterministic fake data for testing the system
    without connecting to real Polymarket APIs.
    """

    def __init__(
        self,
        num_markets: int = 10,
        price_range: tuple[float, float] = (0.1, 0.9),
        volume_range_usd: tuple[float, float] = (100000, 1000000),
        seed: Optional[int] = None,
    ):
        """
        Initialize mock data provider.

        Args:
            num_markets: Number of mock markets to generate
            price_range: Price range for mock prices
            volume_range_usd: Volume range in USD
            seed: Random seed for reproducibility
        """
        self.num_markets = num_markets
        self.price_range = price_range
        self.volume_range_usd = volume_range_usd
        self.seed = seed

        if seed is not None:
            random.seed(seed)

        self._markets: list[Market] = []
        self._generate_markets()

    def _generate_markets(self) -> None:
        """Generate mock markets"""
        categories = [
            MarketCategory.CRYPTO,
            MarketCategory.SPORTS,
            MarketCategory.WEATHER,
            MarketCategory.MACRO,
            MarketCategory.POLITICS,  # Will be filtered for auto-execution
        ]

        titles = [
            "Will Bitcoin reach $100,000 by end of 2024?",
            "Will ETH flip BTC in market cap?",
            "Will the Fed cut rates in Q1 2024?",
            "Will it rain in New York on Christmas?",
            "Will Team A win the championship?",
            "Will BTC drop below $30,000?",
            "Will Solana reach $200?",
            "Will inflation be below 3%?",
            "Will the Lakers make the playoffs?",
            "Will temperature exceed 40°C in London?",
        ]

        self._markets = []

        for i in range(self.num_markets):
            category = categories[i % len(categories)]
            title = titles[i % len(titles)]
            volume = random.uniform(*self.volume_range_usd)
            volume_24h = volume * random.uniform(0.3, 0.7)

            market = Market(
                market_id=f"mock_market_{i:03d}",
                title=f"{title} (Mock {i})",
                description=f"Mock market for testing purposes - {title}",
                category=category,
                status=MarketStatus.OPEN,
                yes_token_address=f"0x{'1' * 40}",
                no_token_address=f"0x{'2' * 40}",
                total_volume_usd=volume,
                volume_24h_usd=volume_24h,
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 30)),
                close_time=datetime.utcnow() + timedelta(days=random.randint(1, 90)),
                resolution_source="mock_source",
                resolution_criteria="Mock resolution criteria",
                is_ambiguous=False,
                is_forbidden_auto=category in {
                    MarketCategory.POLITICS,
                    MarketCategory.WAR_GEOPOLITICS,
                    MarketCategory.LEGAL,
                    MarketCategory.CELEBRITY,
                    MarketCategory.SUBJECTIVE,
                },
            )
            self._markets.append(market)

    def get_markets(self) -> MarketList:
        """Get all mock markets"""
        return MarketList(
            markets=self._markets,
            total_count=len(self._markets),
            fetched_at=datetime.utcnow(),
        )

    def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific mock market by ID"""
        for market in self._markets:
            if market.market_id == market_id:
                return market
        return None

    def get_orderbook_snapshot(
        self,
        market_id: str,
        combined_ask_target: Optional[float] = None,
    ) -> OrderBookSnapshot:
        """
        Generate a mock orderbook snapshot.

        Args:
            market_id: Market ID
            combined_ask_target: If set, generate orderbook with this combined ask value
                                (for testing YES/NO mispricing detection)

        Returns:
            Mock orderbook snapshot
        """
        market = self.get_market(market_id)
        if market is None:
            # Create a default market if not found
            market = Market(
                market_id=market_id,
                title=f"Mock Market {market_id}",
                category=MarketCategory.OTHER,
            )

        # Generate prices
        if combined_ask_target is not None:
            # Generate orderbook with specific combined ask
            # Split between YES and NO
            yes_ask = random.uniform(0.3, 0.7)
            no_ask = combined_ask_target - yes_ask
            if no_ask < 0.01:
                no_ask = 0.01
                yes_ask = combined_ask_target - no_ask
            yes_bid = yes_ask - random.uniform(0.01, 0.03)
            no_bid = no_ask - random.uniform(0.01, 0.03)
        else:
            # Normal random orderbook
            yes_mid = random.uniform(*self.price_range)
            spread = random.uniform(0.01, 0.05)
            yes_bid = max(0.01, yes_mid - spread / 2)
            yes_ask = min(0.99, yes_mid + spread / 2)
            no_mid = 1 - yes_mid
            no_bid = max(0.01, no_mid - spread / 2)
            no_ask = min(0.99, no_mid + spread / 2)

        # Generate depth
        yes_bid_depth = random.uniform(50, 500)
        yes_ask_depth = random.uniform(50, 500)
        no_bid_depth = random.uniform(50, 500)
        no_ask_depth = random.uniform(50, 500)

        # Create orderbook
        snapshot = OrderBookSnapshot(
            market_id=market_id,
            timestamp=datetime.utcnow(),
            yes_bids=OrderBookSide(
                levels=[
                    PriceLevel(price=yes_bid, size=yes_bid_depth / yes_bid, total_usd=yes_bid_depth)
                ],
            ),
            yes_asks=OrderBookSide(
                levels=[
                    PriceLevel(price=yes_ask, size=yes_ask_depth / yes_ask, total_usd=yes_ask_depth)
                ],
            ),
            no_bids=OrderBookSide(
                levels=[
                    PriceLevel(price=no_bid, size=no_bid_depth / no_bid, total_usd=no_bid_depth)
                ],
            ),
            no_asks=OrderBookSide(
                levels=[
                    PriceLevel(price=no_ask, size=no_ask_depth / no_ask, total_usd=no_ask_depth)
                ],
            ),
            source="mock",
        )

        # Calculate metrics
        snapshot.calculate_metrics()

        return snapshot

    def get_orderbook_update(
        self,
        market_id: str,
        combined_ask_target: Optional[float] = None,
    ) -> OrderBookUpdate:
        """
        Generate a mock orderbook update (lightweight).

        Args:
            market_id: Market ID
            combined_ask_target: If set, generate update with this combined ask

        Returns:
            Mock orderbook update
        """
        if combined_ask_target is not None:
            yes_ask = random.uniform(0.3, 0.7)
            no_ask = combined_ask_target - yes_ask
            if no_ask < 0.01:
                no_ask = 0.01
                yes_ask = combined_ask_target - no_ask
        else:
            yes_mid = random.uniform(*self.price_range)
            spread = random.uniform(0.01, 0.05)
            yes_ask = min(0.99, yes_mid + spread / 2)
            no_ask = min(0.99, (1 - yes_mid) + spread / 2)

        return OrderBookUpdate(
            market_id=market_id,
            timestamp=datetime.utcnow(),
            yes_best_bid=yes_ask - random.uniform(0.01, 0.03),
            yes_best_ask=yes_ask,
            yes_best_bid_size=random.uniform(100, 1000),
            yes_best_ask_size=random.uniform(100, 1000),
            no_best_bid=no_ask - random.uniform(0.01, 0.03),
            no_best_ask=no_ask,
            no_best_bid_size=random.uniform(100, 1000),
            no_best_ask_size=random.uniform(100, 1000),
            source="mock",
        )

    def create_mispricing_scenario(
        self,
        market_id: str,
        combined_ask: float = 0.975,
    ) -> OrderBookSnapshot:
        """
        Create an orderbook with YES/NO mispricing for testing.

        Args:
            market_id: Market ID
            combined_ask: Target combined ask (default 0.975 for clear mispricing)

        Returns:
            Orderbook with mispricing
        """
        return self.get_orderbook_snapshot(market_id, combined_ask_target=combined_ask)


# Convenience function for testing
def create_mock_provider(seed: int = 42) -> MockDataProvider:
    """Create a mock data provider with fixed seed for reproducibility"""
    return MockDataProvider(
        num_markets=10,
        price_range=(0.1, 0.9),
        volume_range_usd=(100000, 1000000),
        seed=seed,
    )
