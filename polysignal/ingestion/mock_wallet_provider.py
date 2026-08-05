"""
Mock Wallet Provider - Generate mock wallet activity data for testing

This module provides mock wallet data for development and testing.
Does NOT connect to real Polymarket API.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional

from polysignal.models.wallet import (
    WalletActivity,
    WalletActivityHistory,
    WalletProfile,
    WalletSpecialization,
    WatchlistEntry,
)
from polysignal.models.market import MarketCategory


# Mock wallet addresses
MOCK_WALLET_ADDRESSES = {
    "whale_1": "0x1111111111111111111111111111111111111111",
    "whale_2": "0x2222222222222222222222222222222222222222",
    "researcher_1": "0x3333333333333333333333333333333333333333",
    "trader_1": "0x4444444444444444444444444444444444444444",
    "trader_2": "0x5555555555555555555555555555555555555555",
}

# Mock market IDs for different categories
MOCK_MARKET_IDS = {
    MarketCategory.CRYPTO: [
        "crypto_btc_100k",
        "crypto_eth_5k",
        "crypto_sol_200",
    ],
    MarketCategory.SPORTS: [
        "sports_nba_finals",
        "sports_super_bowl",
        "sports_world_cup",
    ],
    MarketCategory.POLITICS: [
        "politics_election_2024",
        "politics_senate",
    ],
}


def generate_mock_watchlist() -> list[WatchlistEntry]:
    """Generate mock watchlist entries"""
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
        WatchlistEntry(
            address=MOCK_WALLET_ADDRESSES["trader_1"],
            alias="trader_1",
            category="trader",
            is_active=True,
        ),
        WatchlistEntry(
            address=MOCK_WALLET_ADDRESSES["trader_2"],
            alias="trader_2",
            category="trader",
            is_active=False,  # Inactive wallet
        ),
    ]


def generate_mock_wallet_activity(
    wallet_address: str,
    market_id: str,
    market_category: str,
    side: str = "yes",
    price: float = 0.5,
    size_usd: float = 100.0,
    timestamp: Optional[datetime] = None,
    pnl_usd: Optional[float] = None,
) -> WalletActivity:
    """Generate a single mock wallet activity"""
    if timestamp is None:
        timestamp = datetime.utcnow() - timedelta(hours=random.randint(1, 48))

    return WalletActivity(
        wallet_address=wallet_address,
        market_id=market_id,
        market_category=market_category,
        side=side,
        price=price,
        size_usd=size_usd,
        timestamp=timestamp,
        tx_hash=f"0x{random.randint(0, 999999):06x}",
        pnl_usd=pnl_usd,
    )


def generate_mock_wallet_history(
    wallet_address: str,
    num_trades: int = 50,
    win_rate: float = 0.6,
    primary_category: WalletSpecialization = WalletSpecialization.CRYPTO,
) -> WalletActivityHistory:
    """Generate mock wallet activity history"""
    activities = []
    now = datetime.utcnow()

    # Determine category distribution
    categories = [MarketCategory.CRYPTO, MarketCategory.SPORTS, MarketCategory.POLITICS]
    category_weights = {
        primary_category.value: 0.6,  # 60% in primary category
    }
    # Distribute remaining 40% among other categories
    other_categories = [c.value for c in categories if c.value != primary_category.value]
    for cat in other_categories:
        category_weights[cat] = 0.2

    total_volume = 0.0
    total_pnl = 0.0
    win_count = 0
    loss_count = 0

    for i in range(num_trades):
        # Select category based on weights
        rand = random.random()
        cumulative = 0.0
        selected_category = MarketCategory.CRYPTO.value
        for cat, weight in category_weights.items():
            cumulative += weight
            if rand < cumulative:
                selected_category = cat
                break

        # Get market ID for category
        market_ids = MOCK_MARKET_IDS.get(MarketCategory(selected_category), ["generic_market"])
        market_id = random.choice(market_ids)

        # Generate trade parameters
        side = random.choice(["yes", "no"])
        price = random.uniform(0.2, 0.8)
        size_usd = random.uniform(50, 500)

        # Timestamp (spread over last 60 days)
        days_ago = random.uniform(0, 60)
        timestamp = now - timedelta(days=days_ago)

        # PnL (based on win_rate)
        is_win = random.random() < win_rate
        if is_win:
            pnl = size_usd * random.uniform(0.1, 0.5)  # 10-50% gain
            win_count += 1
        else:
            pnl = -size_usd * random.uniform(0.1, 0.3)  # 10-30% loss
            loss_count += 1

        activity = WalletActivity(
            wallet_address=wallet_address,
            market_id=market_id,
            market_category=selected_category,
            side=side,
            price=price,
            size_usd=size_usd,
            timestamp=timestamp,
            tx_hash=f"0x{random.randint(0, 999999):06x}",
            pnl_usd=pnl,
        )
        activities.append(activity)
        total_volume += size_usd
        total_pnl += pnl

    # Sort by timestamp
    activities.sort(key=lambda x: x.timestamp, reverse=True)

    return WalletActivityHistory(
        wallet_address=wallet_address,
        activities=activities,
        total_trades=num_trades,
        total_volume_usd=total_volume,
        win_count=win_count,
        loss_count=loss_count,
        total_pnl_usd=total_pnl,
        first_activity=activities[-1].timestamp if activities else None,
        last_activity=activities[0].timestamp if activities else None,
    )


def generate_mock_wallet_profile(
    wallet_address: str,
    alias: Optional[str] = None,
    history: Optional[WalletActivityHistory] = None,
    primary_category: WalletSpecialization = WalletSpecialization.CRYPTO,
    copy_ratio: float = 0.2,
) -> WalletProfile:
    """Generate mock wallet profile from history"""
    if history is None:
        history = generate_mock_wallet_history(
            wallet_address=wallet_address,
            primary_category=primary_category,
        )

    # Calculate metrics
    win_rate = history.get_win_rate()
    avg_trade_size = history.total_volume_usd / history.total_trades if history.total_trades > 0 else 0

    # Calculate category distribution
    category_dist: dict[str, int] = {}
    for activity in history.activities:
        cat = activity.market_category
        category_dist[cat] = category_dist.get(cat, 0) + 1

    # Calculate component scores

    # Reliability score: based on trade count and data freshness
    reliability_score = min(100, history.total_trades * 2)  # 50 trades = 100

    # Performance score: based on win rate and PnL
    performance_score = win_rate * 100

    # Specialization score: based on category concentration
    if primary_category.value in category_dist:
        concentration = category_dist[primary_category.value] / history.total_trades
        specialization_score = 50 + concentration * 50  # 50-100
    else:
        specialization_score = 50  # Generalist

    # Discipline score: based on copy ratio and consistency
    discipline_score = (1 - copy_ratio) * 100

    # Calculate final wallet_score
    # wallet_score = 0.30 * reliability + 0.35 * performance + 0.20 * specialization + 0.15 * discipline
    wallet_score = (
        0.30 * reliability_score
        + 0.35 * performance_score
        + 0.20 * specialization_score
        + 0.15 * discipline_score
    )

    return WalletProfile(
        wallet_address=wallet_address,
        alias=alias,
        total_trades=history.total_trades,
        total_volume_usd=history.total_volume_usd,
        win_count=history.win_count,
        loss_count=history.loss_count,
        win_rate=win_rate,
        total_pnl_usd=history.total_pnl_usd,
        avg_trade_size_usd=avg_trade_size,
        primary_category=primary_category,
        category_distribution=category_dist,
        copy_ratio=copy_ratio,
        reliability_score=reliability_score,
        performance_score=performance_score,
        specialization_score=specialization_score,
        discipline_score=discipline_score,
        wallet_score=wallet_score,
    )


def generate_mock_profiles_for_watchlist(
    watchlist: list[WatchlistEntry],
) -> dict[str, WalletProfile]:
    """Generate mock profiles for all wallets in watchlist"""
    profiles = {}

    # Define specializations for each wallet type
    specializations = {
        "whale_1": WalletSpecialization.CRYPTO,
        "whale_2": WalletSpecialization.CRYPTO,
        "researcher_1": WalletSpecialization.GENERALIST,
        "trader_1": WalletSpecialization.SPORTS,
        "trader_2": WalletSpecialization.POLITICS,
    }

    copy_ratios = {
        "whale_1": 0.1,  # Low copy ratio
        "whale_2": 0.15,
        "researcher_1": 0.2,
        "trader_1": 0.4,  # Higher copy ratio
        "trader_2": 0.6,  # High copy ratio
    }

    for entry in watchlist:
        # Find the alias key
        alias_key = entry.alias if entry.alias else entry.address[:8]
        specialization = specializations.get(alias_key, WalletSpecialization.GENERALIST)
        copy_ratio = copy_ratios.get(alias_key, 0.3)

        profile = generate_mock_wallet_profile(
            wallet_address=entry.address,
            alias=entry.alias,
            primary_category=specialization,
            copy_ratio=copy_ratio,
        )
        profiles[entry.address] = profile

    return profiles
