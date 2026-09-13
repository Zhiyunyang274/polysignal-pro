"""
Tests for Reconnection Strategy
"""


from polysignal.ingestion.reconnection_strategy import ReconnectionStrategy


class TestReconnectionStrategy:
    """Test reconnection strategy with exponential backoff"""

    def test_initial_state(self):
        """Test initial state"""
        strategy = ReconnectionStrategy()
        assert strategy.attempt == 0
        assert not strategy.is_exhausted

    def test_first_delay(self):
        """Test first delay is initial_delay"""
        strategy = ReconnectionStrategy(initial_delay=1.0)
        delay = strategy.next_delay()
        assert delay == 1.0
        assert strategy.attempt == 1

    def test_exponential_backoff(self):
        """Test exponential backoff"""
        strategy = ReconnectionStrategy(
            initial_delay=1.0,
            backoff_multiplier=2.0,
        )

        delays = []
        while not strategy.is_exhausted:
            delay = strategy.next_delay()
            if delay is not None:
                delays.append(delay)

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_max_delay_cap(self):
        """Test delay is capped at max_delay"""
        strategy = ReconnectionStrategy(
            initial_delay=10.0,
            backoff_multiplier=10.0,
            max_delay=30.0,
        )

        delays = []
        while not strategy.is_exhausted:
            delay = strategy.next_delay()
            if delay is not None:
                delays.append(delay)

        # 10, 100 (capped to 30), 1000 (capped to 30), ...
        assert delays[0] == 10.0
        assert all(d == 30.0 for d in delays[1:])

    def test_max_attempts_reached(self):
        """Test max attempts reached"""
        strategy = ReconnectionStrategy(max_attempts=3)

        delays = []
        while not strategy.is_exhausted:
            delay = strategy.next_delay()
            if delay is not None:
                delays.append(delay)

        assert len(delays) == 3
        assert strategy.is_exhausted
        assert strategy.next_delay() is None

    def test_reset(self):
        """Test reset after successful connection"""
        strategy = ReconnectionStrategy(max_attempts=5)

        # Use some attempts
        strategy.next_delay()
        strategy.next_delay()
        assert strategy.attempt == 2

        # Reset
        strategy.reset()
        assert strategy.attempt == 0
        assert not strategy.is_exhausted

        # Can start again
        delay = strategy.next_delay()
        assert delay == strategy.initial_delay

    def test_custom_parameters(self):
        """Test custom parameters"""
        strategy = ReconnectionStrategy(
            max_attempts=10,
            initial_delay=0.5,
            backoff_multiplier=1.5,
            max_delay=100.0,
        )

        assert strategy.max_attempts == 10
        assert strategy.initial_delay == 0.5
        assert strategy.backoff_multiplier == 1.5
        assert strategy.max_delay == 100.0

    def test_zero_initial_delay(self):
        """Test zero initial delay"""
        strategy = ReconnectionStrategy(initial_delay=0.0)
        delay = strategy.next_delay()
        assert delay == 0.0

    def test_single_attempt(self):
        """Test single attempt strategy"""
        strategy = ReconnectionStrategy(max_attempts=1)
        delay = strategy.next_delay()
        assert delay is not None
        assert strategy.is_exhausted
        assert strategy.next_delay() is None