"""
Tests for Subscription Manager
"""

import asyncio

import pytest

from polysignal.ingestion.subscription_manager import SubscriptionManager


class TestSubscriptionManager:
    """Test subscription manager"""

    def test_initial_state(self):
        """Test initial state"""
        manager = SubscriptionManager()
        assert manager.subscribed_count() == 0
        assert manager.available_slots() == manager.max_subscriptions

    def test_can_subscribe(self):
        """Test can_subscribe logic"""
        manager = SubscriptionManager(max_subscriptions=5)

        # Can subscribe new tokens
        can = manager.can_subscribe(["token_1", "token_2"])
        assert len(can) == 2

    def test_can_subscribe_already_subscribed(self):
        """Test can_subscribe filters already subscribed"""
        manager = SubscriptionManager(max_subscriptions=5)
        manager._subscribed.add("token_1")

        can = manager.can_subscribe(["token_1", "token_2"])
        assert "token_1" not in can
        assert "token_2" in can

    def test_can_subscribe_exceeds_limit(self):
        """Test can_subscribe respects limit"""
        manager = SubscriptionManager(max_subscriptions=3)
        manager._subscribed.add("token_1")

        # Request 5, but only 2 slots available
        can = manager.can_subscribe(["token_2", "token_3", "token_4", "token_5", "token_6"])
        assert len(can) == 2

    def test_is_subscribed(self):
        """Test is_subscribed"""
        manager = SubscriptionManager()
        manager._subscribed.add("token_1")

        assert manager.is_subscribed("token_1") is True
        assert manager.is_subscribed("token_2") is False

    def test_unsubscribe(self):
        """Test unsubscribe"""
        manager = SubscriptionManager()
        manager._subscribed.add("token_1")
        manager._subscribed.add("token_2")

        count = manager.unsubscribe(["token_1", "token_3"])  # token_3 not subscribed
        assert count == 1
        assert not manager.is_subscribed("token_1")
        assert manager.is_subscribed("token_2")

    def test_available_slots(self):
        """Test available slots"""
        manager = SubscriptionManager(max_subscriptions=10)
        assert manager.available_slots() == 10

        manager._subscribed.add("token_1")
        assert manager.available_slots() == 9

    @pytest.mark.asyncio
    async def test_subscribe_batch_success(self):
        """Test subscribe_batch success"""
        manager = SubscriptionManager(max_subscriptions=10, batch_size=3)

        sent_batches = []

        async def send_subscribe(batch):
            sent_batches.append(batch)

        success, failed = await manager.subscribe_batch(
            send_subscribe,
            ["token_1", "token_2", "token_3", "token_4"],
        )

        assert success == 4
        assert failed == 0
        assert manager.subscribed_count() == 4
        # First batch: 3, second batch: 1
        assert len(sent_batches) == 2

    @pytest.mark.asyncio
    async def test_subscribe_batch_with_delay(self):
        """Test subscribe_batch with delay between batches"""
        manager = SubscriptionManager(
            max_subscriptions=10,
            batch_size=2,
            delay_ms=100,  # 100ms delay
        )

        start_time = asyncio.get_event_loop().time()

        async def send_subscribe(batch):
            pass

        # Subscribe 4 tokens in 2 batches = 1 delay
        await manager.subscribe_batch(
            send_subscribe,
            ["token_1", "token_2", "token_3", "token_4"],
        )

        elapsed = asyncio.get_event_loop().time() - start_time
        # Should have at least 100ms delay
        assert elapsed >= 0.1

    @pytest.mark.asyncio
    async def test_subscribe_batch_failure(self):
        """Test subscribe_batch with failure"""
        manager = SubscriptionManager(max_subscriptions=10)

        async def send_subscribe(batch):
            raise Exception("Connection error")

        success, failed = await manager.subscribe_batch(
            send_subscribe,
            ["token_1", "token_2"],
        )

        assert success == 0
        assert failed == 2
        assert manager.subscribed_count() == 0

    @pytest.mark.asyncio
    async def test_subscribe_batch_exceeds_limit(self):
        """Test subscribe_batch respects limit"""
        manager = SubscriptionManager(max_subscriptions=2)

        async def send_subscribe(batch):
            pass

        # Try to subscribe 5 tokens, but limit is 2
        success, failed = await manager.subscribe_batch(
            send_subscribe,
            ["token_1", "token_2", "token_3", "token_4", "token_5"],
        )

        assert success == 2
        assert manager.subscribed_count() == 2

    def test_clear(self):
        """Test clear subscriptions"""
        manager = SubscriptionManager()
        manager._subscribed.add("token_1")
        manager._subscribed.add("token_2")

        manager.clear()

        assert manager.subscribed_count() == 0

    def test_custom_parameters(self):
        """Test custom parameters"""
        manager = SubscriptionManager(
            max_subscriptions=50,
            batch_size=10,
            delay_ms=200,
        )

        assert manager.max_subscriptions == 50
        assert manager.batch_size == 10
        assert manager.delay_ms == 200
