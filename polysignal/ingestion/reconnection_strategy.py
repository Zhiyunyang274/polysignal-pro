"""
Reconnection Strategy - Exponential backoff for WebSocket reconnection

This module provides reconnection logic with exponential backoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReconnectionStrategy:
    """
    Exponential backoff reconnection strategy.

    Usage:
        strategy = ReconnectionStrategy()
        while True:
            delay = strategy.next_delay()
            if delay is None:
                break  # Max attempts reached
            await asyncio.sleep(delay)
            if await connect():
                strategy.reset()
                break
    """

    max_attempts: int = 5
    initial_delay: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay: float = 60.0

    _attempt: int = field(default=0, repr=False)
    _current_delay: float = field(default=1.0, repr=False)

    def __post_init__(self) -> None:
        self._current_delay = self.initial_delay

    def next_delay(self) -> Optional[float]:
        """
        Get next reconnection delay.

        Returns:
            Delay in seconds, or None if max attempts reached
        """
        if self._attempt >= self.max_attempts:
            return None

        delay = min(self._current_delay, self.max_delay)
        self._attempt += 1
        self._current_delay *= self.backoff_multiplier

        return delay

    def reset(self) -> None:
        """Reset after successful connection."""
        self._attempt = 0
        self._current_delay = self.initial_delay

    @property
    def attempt(self) -> int:
        """Current attempt number (1-indexed after first next_delay call)."""
        return self._attempt

    @property
    def is_exhausted(self) -> bool:
        """Check if max attempts have been reached."""
        return self._attempt >= self.max_attempts
