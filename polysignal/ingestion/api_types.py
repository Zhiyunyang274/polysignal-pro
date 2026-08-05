"""
API Types - Polymarket API Response Types

This module defines the raw API response types from Polymarket APIs.
These are separate from internal models and represent the raw API structure.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Gamma API Response Types
# =============================================================================

class GammaToken(BaseModel):
    """Token from Gamma API response"""
    model_config = ConfigDict(extra="allow")

    token_id: str | None = Field(None, alias="token_id")
    outcome: str | None = Field(None, alias="outcome")
    price: float | None = Field(None, alias="price")

class GammaMarket(BaseModel):
    """Market from Gamma API response"""
    model_config = ConfigDict(extra="allow")

    id: str | None = Field(None, alias="id")
    question: str | None = Field(None, alias="question")
    description: str | None = Field(None, alias="description")
    category: str | None = Field(None, alias="category")
    active: bool | None = Field(None, alias="active")
    closed: bool | None = Field(None, alias="closed")
    resolved: bool | None = Field(None, alias="resolved")
    volume: str | None = Field(None, alias="volume")
    volume_24h: str | None = Field(None, alias="volume_24h")
    end_date: str | None = Field(None, alias="end_date")
    created_at: str | None = Field(None, alias="created_at")
    tokens: list[GammaToken] = Field(default_factory=list, alias="tokens")
    slug: str | None = Field(None, alias="slug")
    resolution_source: str | None = Field(None, alias="resolution_source")

# =============================================================================
# CLOB API Response Types
# =============================================================================

class CLOBPriceLevel(BaseModel):
    """Price level from CLOB API orderbook"""
    model_config = ConfigDict(extra="allow")

    price: str | None = Field(None, alias="price")
    size: str | None = Field(None, alias="size")

class CLOBOrderbook(BaseModel):
    """Orderbook from CLOB API"""
    model_config = ConfigDict(extra="allow")

    market: str | None = Field(None, alias="market")
    asset_id: str | None = Field(None, alias="asset_id")
    bids: list[CLOBPriceLevel] = Field(default_factory=list, alias="bids")
    asks: list[CLOBPriceLevel] = Field(default_factory=list, alias="asks")
    timestamp: str | None = Field(None, alias="timestamp")

class CLOBTicker(BaseModel):
    """Ticker from CLOB API"""
    model_config = ConfigDict(extra="allow")

    market: str | None = Field(None, alias="market")
    asset_id: str | None = Field(None, alias="asset_id")
    price: str | None = Field(None, alias="price")
    timestamp: str | None = Field(None, alias="timestamp")

class CLOBMarket(BaseModel):
    """Market info from CLOB API"""
    model_config = ConfigDict(extra="allow")

    condition_id: str | None = Field(None, alias="condition_id")
    question_id: str | None = Field(None, alias="question_id")
    tokens: list[dict] = Field(default_factory=list, alias="tokens")

# =============================================================================
# WebSocket Message Types (for Phase 4B)
# =============================================================================

class WSOrderbookMessage(BaseModel):
    """WebSocket orderbook update message

    TODO: verify exact WebSocket URL and subscription payload against official docs
    before enabling real websocket mode.
    """
    model_config = ConfigDict(extra="allow")

    event_type: str | None = Field(None, alias="event_type")
    asset_id: str | None = Field(None, alias="asset_id")
    market: str | None = Field(None, alias="market")
    bids: list[CLOBPriceLevel] = Field(default_factory=list, alias="bids")
    asks: list[CLOBPriceLevel] = Field(default_factory=list, alias="asks")
    timestamp: str | None = Field(None, alias="timestamp")
