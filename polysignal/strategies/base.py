"""

Strategy Base - Base class for all trading strategies
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from datetime import datetime

from polysignal.models.signal import Signal, ComponentScores
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.market import Market


class StrategyContext:
    """Context passed to strategies"""

    def __init__(
        self,
        market: Optional[Market] = None,
        orderbook: Optional[OrderBookSnapshot] = None,
        component_scores: Optional[ComponentScores] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.market = market
        self.orderbook = orderbook
        self.component_scores = component_scores or ComponentScores()
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow()


class Strategy(ABC):
    """
    Base class for all trading strategies.

    Strategies ONLY produce signals. They do NOT execute trades.
    All signals must pass through Risk Governor.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Strategy description"""
        pass

    @property
    def version(self) -> str:
        """Strategy version"""
        return "0.1.0"

    @property
    def risk_notes(self) -> list[str]:
        """Risk notes for this strategy"""
        return []

    @abstractmethod
    def compute_signal(self, context: StrategyContext) -> Optional[Signal]:
        """
        Compute a trading signal.

        Args:
            context: Strategy context with market data

        Returns:
            Signal if opportunity found, None otherwise
        """
        pass

    def explain_signal(self, signal: Signal) -> str:
        """
        Explain a signal in human-readable format.

        Args:
            signal: Signal to explain

        Returns:
            Human-readable explanation
        """
        return f"Signal from {self.name}: {signal.side.value} @ {signal.price:.4f}"

    def get_inputs(self) -> list[str]:
        """Get list of required inputs"""
        return ["orderbook", "market"]

    def __repr__(self) -> str:
        return f"Strategy({self.name} v{self.version})"
