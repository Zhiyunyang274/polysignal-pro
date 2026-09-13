"""
PolySignal Pro - Polymarket Prediction Market Intelligence System

A research-first, paper trading, risk-controlled system for analyzing
Polymarket prediction markets.

IMPORTANT: This system is designed for RESEARCH purposes only.
- Default mode: READ-ONLY + PAPER TRADING
- Live trading is DISABLED by default
- LLM cannot directly place orders
- All signals must pass through Risk Governor
"""

__version__ = "0.1.0"
__author__ = "PolySignal Pro Team"

# Import key models for convenience
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.orderbook import OrderBookSnapshot, OrderBookUpdate
from polysignal.models.paper_trade import OrderSide, OrderStatus, PaperOrder, PaperPosition
from polysignal.models.risk import RiskAction, RiskContext, RiskDecision
from polysignal.models.signal import ComponentScores, Signal, SignalSide

__all__ = [
    # Version
    "__version__",
    "__author__",
    # Market
    "Market",
    "MarketCategory",
    "MarketStatus",
    # Orderbook
    "OrderBookSnapshot",
    "OrderBookUpdate",
    # Signal
    "Signal",
    "SignalSide",
    "ComponentScores",
    # Risk
    "RiskAction",
    "RiskDecision",
    "RiskContext",
    # Paper Trade
    "PaperOrder",
    "PaperPosition",
    "OrderSide",
    "OrderStatus",
]
