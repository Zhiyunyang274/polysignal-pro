"""
Test Fixtures - Wallet test data
"""

from __future__ import annotations

from datetime import datetime, timedelta

from polysignal.models.wallet import (
    WalletActivity,
    WalletActivityHistory,
    WalletProfile,
    WalletMarketActivity,
    WalletSpecialization,
    WatchlistEntry,
)
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.ingestion.mock_wallet_provider import MOCK_WALLET_ADDRESSES


def create_mock_watchlist() -> list[WatchlistEntry]:
    """Create mock watchlist for testing"""
    return [
        WatchlistEntry(
            address=MOCK_WALLET_ADDRESSES["whale_1"],
            alias="whale_1",
            category="whale",
            is_active=True,
        ),
        WatchlistEntry(
            address=MOCK_WALLET_ADDRESSES["whale_2"],
            alias="whale_2",
            category="whale",
            is_active=True,
        ),
        WatchlistEntry(
            address=MOCK_WALLET_ADDRESSES["researcher_1"],
            alias="researcher_1",
            category="researcher",
            is_active=True,
        ),
    ]


def create_mock_wallet_profile(
    wallet_address: str = "0x1111111111111111111111111111111111111111",
    alias: str = "test_wallet",
    total_trades: int = 50,
    win_rate: float = 0.65,
    primary_category: WalletSpecialization = WalletSpecialization.CRYPTO,
    copy_ratio: float = 0.2,
    reliability_score: float = 80.0,
    performance_score: float = 75.0,
    specialization_score: float = 70.0,
    discipline_score: float = 85.0,
) -> WalletProfile:
    """Create a mock wallet profile for testing"""
    win_count = int(total_trades * win_rate)
    loss_count = total_trades - win_count

    # Calculate wallet_score using the formula
    wallet_score = (
        0.30 * reliability_score
        + 0.35 * performance_score
        + 0.20 * specialization_score
        + 0.15 * discipline_score
    )

    return WalletProfile(
        wallet_address=wallet_address,
        alias=alias,
        total_trades=total_trades,
        total_volume_usd=total_trades * 100.0,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        total_pnl_usd=(win_count * 50.0) - (loss_count * 30.0),
        avg_trade_size_usd=100.0,
        primary_category=primary_category,
        copy_ratio=copy_ratio,
        reliability_score=reliability_score,
        performance_score=performance_score,
        specialization_score=specialization_score,
        discipline_score=discipline_score,
        wallet_score=wallet_score,
    )


def create_high_quality_wallet() -> WalletProfile:
    """Create a high quality wallet profile"""
    return create_mock_wallet_profile(
        wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
        alias="whale_1",
        total_trades=100,
        win_rate=0.75,
        primary_category=WalletSpecialization.CRYPTO,
        copy_ratio=0.1,
        reliability_score=95.0,
        performance_score=85.0,
        specialization_score=90.0,
        discipline_score=90.0,
    )


def create_medium_quality_wallet() -> WalletProfile:
    """Create a medium quality wallet profile"""
    return create_mock_wallet_profile(
        wallet_address=MOCK_WALLET_ADDRESSES["researcher_1"],
        alias="researcher_1",
        total_trades=50,
        win_rate=0.60,
        primary_category=WalletSpecialization.GENERALIST,
        copy_ratio=0.3,
        reliability_score=70.0,
        performance_score=65.0,
        specialization_score=60.0,
        discipline_score=70.0,
    )


def create_high_copy_risk_wallet() -> WalletProfile:
    """Create a wallet with high copy trading risk"""
    return create_mock_wallet_profile(
        wallet_address=MOCK_WALLET_ADDRESSES["trader_1"],
        alias="trader_1",
        total_trades=30,
        win_rate=0.55,
        primary_category=WalletSpecialization.CRYPTO,
        copy_ratio=0.8,  # High copy ratio
        reliability_score=60.0,
        performance_score=55.0,
        specialization_score=50.0,
        discipline_score=30.0,  # Low discipline due to copy trading
    )


def create_wallet_market_activity(
    wallet_address: str = "0x1111111111111111111111111111111111111111",
    market_id: str = "test_market_001",
    side: str = "yes",
    price: float = 0.5,
    size_usd: float = 100.0,
    wallet_score: float = 80.0,
    timestamp: datetime = None,
) -> WalletMarketActivity:
    """Create a wallet market activity for testing"""
    if timestamp is None:
        timestamp = datetime.utcnow() - timedelta(hours=1)

    return WalletMarketActivity(
        wallet_address=wallet_address,
        market_id=market_id,
        side=side,
        price=price,
        size_usd=size_usd,
        timestamp=timestamp,
        wallet_score=wallet_score,
    )


def create_consensus_activities_yes() -> list[WalletMarketActivity]:
    """Create activities showing YES consensus"""
    now = datetime.utcnow()
    return [
        create_wallet_market_activity(
            wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
            side="yes",
            wallet_score=85.0,
            timestamp=now - timedelta(hours=1),
        ),
        create_wallet_market_activity(
            wallet_address=MOCK_WALLET_ADDRESSES["whale_2"],
            side="yes",
            wallet_score=80.0,
            timestamp=now - timedelta(hours=2),
        ),
        create_wallet_market_activity(
            wallet_address=MOCK_WALLET_ADDRESSES["researcher_1"],
            side="yes",
            wallet_score=70.0,
            timestamp=now - timedelta(hours=3),
        ),
    ]


def create_consensus_activities_mixed() -> list[WalletMarketActivity]:
    """Create activities showing mixed directions"""
    now = datetime.utcnow()
    return [
        create_wallet_market_activity(
            wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
            side="yes",
            wallet_score=85.0,
            timestamp=now - timedelta(hours=1),
        ),
        create_wallet_market_activity(
            wallet_address=MOCK_WALLET_ADDRESSES["whale_2"],
            side="no",
            wallet_score=80.0,
            timestamp=now - timedelta(hours=2),
        ),
    ]


def create_wallet_market() -> Market:
    """Create a test market for wallet testing"""
    return Market(
        market_id="wallet_test_001",
        title="Will Bitcoin reach $100,000?",
        description="Test market for wallet testing",
        category=MarketCategory.CRYPTO,
        status=MarketStatus.OPEN,
        total_volume_usd=500000,
        volume_24h_usd=200000,
        close_time=datetime.utcnow() + timedelta(days=30),
    )


def create_politics_market() -> Market:
    """Create a politics market for specialization testing"""
    return Market(
        market_id="politics_test_001",
        title="Will Candidate X win?",
        description="Test politics market",
        category=MarketCategory.POLITICS,
        status=MarketStatus.OPEN,
        total_volume_usd=500000,
        volume_24h_usd=200000,
        close_time=datetime.utcnow() + timedelta(days=30),
    )


def create_profiles_dict() -> dict[str, WalletProfile]:
    """Create a dictionary of mock profiles"""
    return {
        MOCK_WALLET_ADDRESSES["whale_1"]: create_high_quality_wallet(),
        MOCK_WALLET_ADDRESSES["whale_2"]: create_mock_wallet_profile(
            wallet_address=MOCK_WALLET_ADDRESSES["whale_2"],
            alias="whale_2",
            primary_category=WalletSpecialization.CRYPTO,
            copy_ratio=0.15,
        ),
        MOCK_WALLET_ADDRESSES["researcher_1"]: create_medium_quality_wallet(),
    }
