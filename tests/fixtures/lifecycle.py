"""
Test Fixtures - Lifecycle test markets
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from polysignal.models.market import Market, MarketCategory, MarketStatus


def create_lifecycle_market(
    market_id: str = "lifecycle_test_001",
    title: str = "Test Lifecycle Market",
    category: MarketCategory = MarketCategory.CRYPTO,
    status: MarketStatus = MarketStatus.OPEN,
    close_time: datetime = None,
    created_at: datetime = None,
    resolution_source: str = "polymarket",
    resolution_criteria: str = "This market will resolve based on the official announcement.",
    is_ambiguous: bool = False,
    is_forbidden_auto: bool = False,
) -> Market:
    """Create a market for lifecycle testing"""
    now = datetime.now(timezone.utc)

    if created_at is None:
        created_at = now - timedelta(days=10)

    if close_time is None:
        close_time = now + timedelta(days=30)

    return Market(
        market_id=market_id,
        title=title,
        description=f"Test market: {title}",
        category=category,
        status=status,
        yes_token_address="0x" + "1" * 40,
        no_token_address="0x" + "2" * 40,
        total_volume_usd=500000,
        volume_24h_usd=200000,
        created_at=created_at,
        close_time=close_time,
        resolution_source=resolution_source,
        resolution_criteria=resolution_criteria,
        is_ambiguous=is_ambiguous,
        is_forbidden_auto=is_forbidden_auto,
    )


def create_early_phase_market() -> Market:
    """Create a market in EARLY phase (< 10% time elapsed)"""
    now = datetime.now(timezone.utc)
    return create_lifecycle_market(
        market_id="early_phase_001",
        title="Will Bitcoin reach $150,000 by end of year?",
        created_at=now - timedelta(hours=1),
        close_time=now + timedelta(days=30),
    )


def create_mid_phase_market() -> Market:
    """Create a market in MID phase (10-80% time elapsed)"""
    now = datetime.now(timezone.utc)
    return create_lifecycle_market(
        market_id="mid_phase_001",
        title="Will ETH price exceed $5000 this month?",
        created_at=now - timedelta(days=10),
        close_time=now + timedelta(days=20),
    )


def create_late_phase_market() -> Market:
    """Create a market in LATE phase (80-95% time elapsed)"""
    now = datetime.now(timezone.utc)
    return create_lifecycle_market(
        market_id="late_phase_001",
        title="Will the Fed raise rates next week?",
        created_at=now - timedelta(days=28),
        close_time=now + timedelta(days=2),
    )


def create_closing_phase_market() -> Market:
    """Create a market in CLOSING phase (> 95% time elapsed)"""
    now = datetime.now(timezone.utc)
    return create_lifecycle_market(
        market_id="closing_phase_001",
        title="Will the game end in 5 minutes?",
        created_at=now - timedelta(hours=2),
        close_time=now + timedelta(minutes=5),
    )


def create_closed_market() -> Market:
    """Create a CLOSED market"""
    return create_lifecycle_market(
        market_id="closed_001",
        title="Will Team A win yesterday?",
        status=MarketStatus.CLOSED,
    )


def create_resolved_market() -> Market:
    """Create a RESOLVED market"""
    return create_lifecycle_market(
        market_id="resolved_001",
        title="Did Bitcoin reach $100k?",
        status=MarketStatus.RESOLVED,
    )


def create_ambiguous_market() -> Market:
    """Create an ambiguous market"""
    return create_lifecycle_market(
        market_id="ambiguous_001",
        title="Will something subjective happen?",
        is_ambiguous=True,
    )


def create_ambiguous_keyword_market() -> Market:
    """Create a market with ambiguous keywords in title"""
    return create_lifecycle_market(
        market_id="ambiguous_keyword_001",
        title="Will maybe something possibly happen?",
        resolution_source="TBD",
    )


def create_no_resolution_source_market() -> Market:
    """Create a market without resolution source"""
    return create_lifecycle_market(
        market_id="no_source_001",
        title="Will this market resolve correctly?",
        resolution_source=None,
    )


def create_forbidden_category_market() -> Market:
    """Create a market in forbidden category"""
    return create_lifecycle_market(
        market_id="forbidden_001",
        title="Will Candidate X win the election?",
        category=MarketCategory.POLITICS,
    )


def create_no_close_time_market() -> Market:
    """Create a market without close_time"""
    now = datetime.now(timezone.utc)
    return Market(
        market_id="no_close_time_001",
        title="Will this ever happen?",
        description="Test market",
        category=MarketCategory.CRYPTO,
        status=MarketStatus.OPEN,
        yes_token_address="0x" + "1" * 40,
        no_token_address="0x" + "2" * 40,
        total_volume_usd=500000,
        volume_24h_usd=200000,
        created_at=now - timedelta(days=10),
        close_time=None,  # Explicitly None
        resolution_source="polymarket",
        resolution_criteria="This market will resolve based on the official announcement.",
        is_ambiguous=False,
        is_forbidden_auto=False,
    )


def create_no_created_at_market() -> Market:
    """Create a market without created_at"""
    now = datetime.now(timezone.utc)
    return Market(
        market_id="no_created_at_001",
        title="Will this market work?",
        description="Test market",
        category=MarketCategory.CRYPTO,
        status=MarketStatus.OPEN,
        yes_token_address="0x" + "1" * 40,
        no_token_address="0x" + "2" * 40,
        total_volume_usd=500000,
        volume_24h_usd=200000,
        created_at=None,  # Explicitly None
        close_time=now + timedelta(days=5),
        resolution_source="polymarket",
        resolution_criteria="This market will resolve based on the official announcement.",
        is_ambiguous=False,
        is_forbidden_auto=False,
    )
