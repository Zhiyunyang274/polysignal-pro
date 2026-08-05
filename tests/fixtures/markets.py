"""

from __future__ import annotations
Test Fixtures - Mock markets
"""

from datetime import datetime, timedelta
from polysignal.models.market import Market, MarketCategory, MarketStatus


def create_mock_market(
    market_id: str = "test_market_001",
    title: str = "Test Market",
    category: MarketCategory = MarketCategory.CRYPTO,
    status: MarketStatus = MarketStatus.OPEN,
    total_volume_usd: float = 500000,
    volume_24h_usd: float = 200000,
    is_ambiguous: bool = False,
    is_forbidden_auto: bool = False,
) -> Market:
    """Create a mock market for testing"""
    return Market(
        market_id=market_id,
        title=title,
        description=f"Test market: {title}",
        category=category,
        status=status,
        yes_token_address="0x" + "1" * 40,
        no_token_address="0x" + "2" * 40,
        total_volume_usd=total_volume_usd,
        volume_24h_usd=volume_24h_usd,
        created_at=datetime.utcnow() - timedelta(days=10),
        close_time=datetime.utcnow() + timedelta(days=30),
        resolution_source="test_source",
        resolution_criteria="Test criteria",
        is_ambiguous=is_ambiguous,
        is_forbidden_auto=is_forbidden_auto,
    )


def create_mock_markets() -> list[Market]:
    """Create a list of mock markets"""
    return [
        create_mock_market(
            market_id="crypto_001",
            title="Will Bitcoin reach $100,000?",
            category=MarketCategory.CRYPTO,
        ),
        create_mock_market(
            market_id="sports_001",
            title="Will Team A win the championship?",
            category=MarketCategory.SPORTS,
        ),
        create_mock_market(
            market_id="politics_001",
            title="Will Candidate X win election?",
            category=MarketCategory.POLITICS,
            is_forbidden_auto=True,
        ),
        create_mock_market(
            market_id="ambiguous_001",
            title="Will something subjective happen?",
            category=MarketCategory.SUBJECTIVE,
            is_ambiguous=True,
            is_forbidden_auto=True,
        ),
    ]
