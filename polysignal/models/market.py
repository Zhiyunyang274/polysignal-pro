"""
Market Models - Polymarket market information
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MarketCategory(str, Enum):
    """Market category classification"""
    CRYPTO = "crypto"
    SPORTS = "sports"
    POLITICS = "politics"
    WAR_GEOPOLITICS = "war_geopolitics"
    LEGAL = "legal"
    CELEBRITY = "celebrity"
    WEATHER = "weather"
    MACRO = "macro"
    SUBJECTIVE = "subjective"
    OTHER = "other"


class MarketStatus(str, Enum):
    """Market status"""
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class Market(BaseModel):
    """Polymarket market information"""
    market_id: str = Field(..., description="Polymarket market ID")
    title: str = Field(..., description="Market title")
    description: Optional[str] = Field(None, description="Market description")
    category: MarketCategory = Field(default=MarketCategory.OTHER, description="Market category")
    status: MarketStatus = Field(default=MarketStatus.OPEN)

    # Token addresses
    yes_token_address: Optional[str] = None
    no_token_address: Optional[str] = None

    # Volume information
    total_volume_usd: float = Field(0.0, ge=0)
    volume_24h_usd: float = Field(0.0, ge=0)

    # Time information
    created_at: Optional[datetime] = None
    close_time: Optional[datetime] = None
    resolution_time: Optional[datetime] = None

    # Resolution information
    resolution_source: Optional[str] = Field(None, description="Resolution source")
    resolution_criteria: Optional[str] = Field(None, description="Resolution criteria")

    # Risk flags
    is_ambiguous: bool = Field(False, description="Has ambiguous rules")
    is_forbidden_auto: bool = Field(False, description="Forbidden for auto execution")

    # Metadata
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    def is_tradable(self) -> bool:
        """Check if market is tradable"""
        return (
            self.status == MarketStatus.OPEN
            and not self.is_ambiguous
            and self.total_volume_usd >= 100000
        )

    def is_auto_allowed(self) -> bool:
        """Check if auto execution is allowed for this market"""
        forbidden_categories = {
            MarketCategory.POLITICS,
            MarketCategory.WAR_GEOPOLITICS,
            MarketCategory.LEGAL,
            MarketCategory.CELEBRITY,
            MarketCategory.SUBJECTIVE,
        }
        return self.category not in forbidden_categories and not self.is_forbidden_auto


class MarketList(BaseModel):
    """List of markets"""
    markets: list[Market] = Field(default_factory=list)
    total_count: int = Field(0, ge=0)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
