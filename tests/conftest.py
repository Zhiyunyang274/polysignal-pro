"""
Test Configuration
"""

import asyncio

# Add project root to path
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_config() -> dict[str, Any]:
    """Mock configuration"""
    return {
        "live_trading_enabled": False,
        "allow_auto_execution": False,
        "paper_trading_enabled": True,
        "max_account_capital_usd": 100.0,
        "max_position_pct": 0.01,
        "max_market_exposure_pct": 0.03,
        "max_strategy_exposure_pct": 0.08,
        "daily_max_loss_pct": 0.03,
        "weekly_max_loss_pct": 0.08,
        "max_consecutive_losses": 3,
        "min_total_volume_usd": 100000,
        "min_depth_usd": 20,
        "max_spread_pct": 0.05,
    }


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
