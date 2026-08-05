#!/usr/bin/env python3
"""
Smoke Test - Real WebSocket Read-only

This script performs a minimal smoke test using real Polymarket WebSocket.
It validates that real WebSocket data can flow through the pipeline.

IMPORTANT:
- This script does NOT place real orders
- This script does NOT require private keys
- This script does NOT call POST/DELETE endpoints
- This script does NOT run live_trader
- This script gracefully exits on WebSocket failure
- This is OPTIONAL - not part of pytest

Usage:
    python scripts/smoke_ws_readonly.py

Environment:
    DATA_MODE=real_readonly (optional, script uses REAL_READONLY by default)
"""

import asyncio
import sys
from datetime import datetime
from typing import Optional

# Add project root to path
sys.path.insert(0, ".")

from polysignal.config import config
from polysignal.logging_config import setup_logging, get_logger
from polysignal.ingestion.websocket_client import CLOBWebSocketClient, WebSocketConfig
from polysignal.ingestion.gamma_client import GammaAPIClient
from polysignal.ingestion.data_converter import DataConverter


logger = get_logger("polysignal.smoke_ws_readonly")


class WSSmokeTestResult:
    """Results from WebSocket smoke test"""
    def __init__(self):
        self.ws_connected: bool = False
        self.ws_messages_received: int = 0
        self.tokens_subscribed: int = 0
        self.orderbooks_cached: int = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "ws_connected": self.ws_connected,
            "ws_messages_received": self.ws_messages_received,
            "tokens_subscribed": self.tokens_subscribed,
            "orderbooks_cached": self.orderbooks_cached,
            "errors": self.errors,
        }


def print_header():
    """Print smoke test header"""
    print("\n" + "=" * 60)
    print("PolySignal Pro - Real WebSocket Read-only Smoke Test")
    print("=" * 60)
    print(f"Started: {datetime.utcnow().isoformat()}")
    print("Mode: REAL_WEBSOCKET_READONLY")
    print("=" * 60 + "\n")


def print_summary(result: WSSmokeTestResult):
    """Print smoke test summary"""
    print("\n" + "=" * 60)
    print("WebSocket Smoke Test Summary")
    print("=" * 60)
    print(f"WebSocket Connected:    {result.ws_connected}")
    print(f"Messages Received:      {result.ws_messages_received}")
    print(f"Tokens Subscribed:      {result.tokens_subscribed}")
    print(f"Orderbooks Cached:      {result.orderbooks_cached}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors[:5]:
            print(f"  - {error[:100]}")

    print("=" * 60)

    print("\n" + "=" * 60)
    print("SAFETY CHECK: Live Trading Status")
    print("=" * 60)
    print(f"live_trading_enabled: {config.risk.live_trading_enabled}")
    print(f"allow_auto_execution: {config.risk.allow_auto_execution}")
    print(f"paper_trading_enabled: {config.risk.paper_trading_enabled}")

    if config.risk.live_trading_enabled:
        print("\n⚠️  WARNING: live_trading_enabled is TRUE!")
    else:
        print("\n✅ Safe: live_trading is DISABLED")

    print("=" * 60 + "\n")


async def run_smoke_test(
    max_tokens: int = 4,  # 2 markets (YES + NO each)
    timeout_seconds: int = 30,
) -> WSSmokeTestResult:
    """
    Run smoke test with real WebSocket.

    Args:
        max_tokens: Maximum tokens to subscribe
        timeout_seconds: Timeout for receiving messages

    Returns:
        WSSmokeTestResult with test results
    """
    result = WSSmokeTestResult()

    # Get WebSocket config
    ws_config = WebSocketConfig(
        enabled=True,
        url=config.websocket.url,
        max_subscriptions=max_tokens,
        ping_interval_seconds=config.websocket.ping_interval_seconds,
        pong_timeout_seconds=config.websocket.pong_timeout_seconds,
    )

    # Create client
    messages_received = 0

    async def on_message(msg):
        nonlocal messages_received
        messages_received += 1
        if messages_received <= 5:
            print(f"  Received message {messages_received}: type={msg.message_type}, token={msg.token_id[:20]}...")

    client = CLOBWebSocketClient(
        config=ws_config,
        on_message=on_message,
    )

    try:
        # Step 1: Fetch markets from Gamma API to get token IDs
        print("[Step 1] Fetching markets from Gamma API...")
        gamma_client = GammaAPIClient()
        try:
            markets = await gamma_client.get_markets(limit=10)
            # get_markets returns a list, not MarketsList
            print(f"  Fetched {len(markets)} markets")
        except Exception as e:
            result.errors.append(f"Failed to fetch markets: {e}")
            print(f"  ERROR: {e}")
            return result
        finally:
            await gamma_client.close()

        # Step 2: Extract token IDs
        print("\n[Step 2] Extracting token IDs...")
        token_pairs = []  # [(market_id, yes_token, no_token), ...]
        for gamma_market in markets:  # markets is a list
            market = DataConverter.gamma_to_market(gamma_market)
            if market and market.yes_token_address and market.no_token_address:
                token_pairs.append((market.market_id, market.yes_token_address, market.no_token_address))
                if len(token_pairs) >= max_tokens // 2:
                    break

        if not token_pairs:
            result.errors.append("No markets with valid token IDs found")
            return result

        # Flatten token IDs
        token_ids = []
        for market_id, yes_token, no_token in token_pairs:
            token_ids.extend([yes_token, no_token])

        print(f"  Found {len(token_ids)} tokens from {len(token_pairs)} markets")

        # Step 3: Connect to WebSocket
        print("\n[Step 3] Connecting to WebSocket...")
        print(f"  URL: {ws_config.url}")

        connected = await client.connect()
        if not connected:
            result.errors.append("Failed to connect to WebSocket")
            return result

        result.ws_connected = True
        print("  ✓ Connected")

        # Step 4: Subscribe to tokens
        print(f"\n[Step 4] Subscribing to {len(token_ids)} tokens...")
        success, failed = await client.subscribe(token_ids)
        result.tokens_subscribed = success
        print(f"  Subscribed: {success}, Failed: {failed}")

        # Step 5: Wait for messages
        print(f"\n[Step 5] Waiting for messages (timeout: {timeout_seconds}s)...")
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout_seconds:
                break

            # Check if we have orderbooks cached
            cached = client.cache_manager.subscribed_count()
            if cached > 0:
                result.orderbooks_cached = cached

            await asyncio.sleep(1)

        result.ws_messages_received = messages_received
        print(f"  Received {messages_received} messages")
        print(f"  Cached {result.orderbooks_cached} orderbooks")

        # Step 6: Check cache
        print("\n[Step 6] Checking cache...")
        for market_id, yes_token, no_token in token_pairs[:2]:
            snapshot = await client.get_orderbook(market_id, yes_token, no_token)
            if snapshot:
                print(f"  Market: {market_id}")
                print(f"    YES bids: {len(snapshot.yes_bids.levels)}, asks: {len(snapshot.yes_asks.levels)}")
                print(f"    NO bids: {len(snapshot.no_bids.levels)}, asks: {len(snapshot.no_asks.levels)}")
                print(f"    Is stale: {snapshot.is_stale}")

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        result.errors.append(error_msg)
        print(f"\nFATAL ERROR: {e}")

    finally:
        # Disconnect
        await client.disconnect()

    return result


def main():
    """Main entry point"""
    # Setup logging
    setup_logging(level="INFO", use_rich=False)

    print_header()

    # Run smoke test
    try:
        result = asyncio.run(run_smoke_test(max_tokens=4, timeout_seconds=30))
    except KeyboardInterrupt:
        print("\n\nSmoke test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nSmoke test failed with error: {e}")
        sys.exit(0)  # Exit 0 to not fail CI

    # Print summary
    print_summary(result)

    # Final status
    if result.errors:
        print("⚠️  Smoke test completed with errors")
    elif result.ws_messages_received > 0:
        print("✅ Smoke test completed successfully")
    else:
        print("⚠️  Smoke test completed but no messages received")

    print("\nNOTE: This test used READ-ONLY WebSocket.")
    print("No orders were placed. No private keys were used.")

    sys.exit(0)


if __name__ == "__main__":
    main()
