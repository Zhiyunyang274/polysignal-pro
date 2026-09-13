"""
Test fixtures for Polymarket API responses

These fixtures provide mock API responses for testing without
connecting to real Polymarket APIs.
"""

from datetime import datetime

# =============================================================================
# Gamma API Fixtures
# =============================================================================

def create_gamma_market_response(
    market_id: str = "test_market_001",
    question: str = "Will BTC reach $100k?",
    category: str = "crypto",
    active: bool = True,
    closed: bool = False,
    resolved: bool = False,
    volume: str = "5000000.00",
    volume_24h: str = "200000.00",
    yes_token_id: str = "token_yes_001",
    no_token_id: str = "token_no_001",
    end_date: str = "2024-12-31T23:59:59Z",
    created_at: str = "2024-01-01T00:00:00Z",
) -> dict:
    """Create a mock Gamma API market response"""
    return {
        "id": market_id,
        "question": question,
        "description": f"Market description for {question}",
        "category": category,
        "active": active,
        "closed": closed,
        "resolved": resolved,
        "volume": volume,
        "volume_24h": volume_24h,
        "end_date": end_date,
        "created_at": created_at,
        "slug": f"{market_id}-slug",
        "resolution_source": "polymarket",
        "tokens": [
            {
                "token_id": yes_token_id,
                "outcome": "Yes",
                "price": "0.45",
            },
            {
                "token_id": no_token_id,
                "outcome": "No",
                "price": "0.55",
            },
        ],
    }


def create_gamma_markets_list_response(count: int = 3) -> list[dict]:
    """Create a list of mock Gamma API market responses"""
    markets = []
    categories = ["crypto", "sports", "weather", "politics", "finance"]

    for i in range(count):
        markets.append(
            create_gamma_market_response(
                market_id=f"test_market_{i:03d}",
                question=f"Test Market {i}?",
                category=categories[i % len(categories)],
                volume=f"{(i + 1) * 1000000:.2f}",
                volume_24h=f"{(i + 1) * 100000:.2f}",
                yes_token_id=f"token_yes_{i:03d}",
                no_token_id=f"token_no_{i:03d}",
            )
        )

    return markets


def create_gamma_market_missing_tokens() -> dict:
    """Create a Gamma market response with missing tokens"""
    return {
        "id": "market_no_tokens",
        "question": "Market without tokens",
        "category": "crypto",
        "active": True,
        "closed": False,
        "resolved": False,
        "volume": "1000000.00",
        "tokens": [],  # Missing tokens
    }


def create_gamma_market_missing_id() -> dict:
    """Create a Gamma market response with missing ID"""
    return {
        "question": "Market without ID",
        "category": "crypto",
        "active": True,
        "tokens": [
            {"token_id": "token_yes", "outcome": "Yes", "price": "0.5"},
            {"token_id": "token_no", "outcome": "No", "price": "0.5"},
        ],
    }


def create_gamma_market_invalid_volume() -> dict:
    """Create a Gamma market response with invalid volume"""
    return {
        "id": "market_invalid_volume",
        "question": "Market with invalid volume",
        "category": "crypto",
        "active": True,
        "volume": "not_a_number",
        "volume_24h": None,
        "tokens": [
            {"token_id": "token_yes", "outcome": "Yes", "price": "0.5"},
            {"token_id": "token_no", "outcome": "No", "price": "0.5"},
        ],
    }


def create_gamma_market_politics() -> dict:
    """Create a Gamma market response for politics category"""
    return create_gamma_market_response(
        market_id="politics_market_001",
        question="Will candidate X win the election?",
        category="politics",
    )


def create_gamma_market_closed() -> dict:
    """Create a Gamma market response for closed market"""
    return create_gamma_market_response(
        market_id="closed_market_001",
        question="This market is closed",
        category="crypto",
        active=False,
        closed=True,
    )


def create_gamma_market_resolved() -> dict:
    """Create a Gamma market response for resolved market"""
    return create_gamma_market_response(
        market_id="resolved_market_001",
        question="This market is resolved",
        category="crypto",
        active=False,
        closed=True,
        resolved=True,
    )


# =============================================================================
# CLOB API Fixtures
# =============================================================================

def create_clob_orderbook_response(
    market: str = "test_market_001",
    asset_id: str = "token_yes_001",
    bid_prices: list[str] = None,
    ask_prices: list[str] = None,
) -> dict:
    """Create a mock CLOB API orderbook response"""
    if bid_prices is None:
        bid_prices = ["0.44", "0.43", "0.42"]
    if ask_prices is None:
        ask_prices = ["0.46", "0.47", "0.48"]

    bids = []
    for i, price in enumerate(bid_prices):
        bids.append({
            "price": price,
            "size": str(1000 * (i + 1)),
        })

    asks = []
    for i, price in enumerate(ask_prices):
        asks.append({
            "price": price,
            "size": str(1000 * (i + 1)),
        })

    return {
        "market": market,
        "asset_id": asset_id,
        "bids": bids,
        "asks": asks,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def create_clob_orderbook_mispricing(
    yes_ask: str = "0.48",
    no_ask: str = "0.48",
) -> tuple[dict, dict]:
    """
    Create CLOB orderbooks with YES/NO mispricing.

    combined_ask = yes_ask + no_ask
    For mispricing, combined_ask < 1.0 (e.g., 0.96)
    """
    yes_orderbook = create_clob_orderbook_response(
        market="mispricing_market",
        asset_id="token_yes",
        bid_prices=[str(float(yes_ask) - 0.02)],
        ask_prices=[yes_ask],
    )

    no_orderbook = create_clob_orderbook_response(
        market="mispricing_market",
        asset_id="token_no",
        bid_prices=[str(float(no_ask) - 0.02)],
        ask_prices=[no_ask],
    )

    return yes_orderbook, no_orderbook


def create_clob_ticker_response(
    market: str = "test_market_001",
    asset_id: str = "token_yes_001",
    price: str = "0.45",
) -> dict:
    """Create a mock CLOB API ticker response"""
    return {
        "market": market,
        "asset_id": asset_id,
        "price": price,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def create_clob_tickers_list_response(count: int = 3) -> list[dict]:
    """Create a list of mock CLOB API ticker responses"""
    tickers = []
    for i in range(count):
        tickers.append(
            create_clob_ticker_response(
                market=f"test_market_{i:03d}",
                asset_id=f"token_{i:03d}",
                price=f"{0.3 + i * 0.1:.2f}",
            )
        )
    return tickers


def create_clob_orderbook_empty() -> dict:
    """Create an empty CLOB orderbook response"""
    return {
        "market": "empty_market",
        "asset_id": "empty_token",
        "bids": [],
        "asks": [],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def create_clob_orderbook_invalid_prices() -> dict:
    """Create a CLOB orderbook with invalid prices"""
    return {
        "market": "invalid_market",
        "asset_id": "invalid_token",
        "bids": [
            {"price": "invalid", "size": "1000"},
            {"price": "-0.5", "size": "1000"},  # Negative price
            {"price": "1.5", "size": "1000"},   # Price > 1
        ],
        "asks": [
            {"price": "0.5", "size": "invalid"},
            {"price": "0.5", "size": "-100"},   # Negative size
        ],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# =============================================================================
# WebSocket Message Fixtures (Phase 4B)
# =============================================================================

def create_ws_orderbook_message(
    asset_id: str = "token_yes_001",
    market: str = "test_market_001",
) -> dict:
    """
    Create a mock WebSocket orderbook message.

    TODO: verify exact WebSocket URL and subscription payload against official docs
    before enabling real websocket mode.
    """
    return {
        "event_type": "book",
        "asset_id": asset_id,
        "market": market,
        "bids": [
            {"price": "0.44", "size": "1000"},
        ],
        "asks": [
            {"price": "0.46", "size": "1000"},
        ],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
