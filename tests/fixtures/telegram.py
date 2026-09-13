"""
Test fixtures for Telegram module
"""


from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.risk import RiskAction, RiskDecision
from polysignal.models.signal import ComponentScores, Signal, SignalSide


def create_test_signal(
    signal_id: str = "test_signal_001",
    market_id: str = "test_market_001",
    market_title: str = "Test Market",
    strategy_name: str = "test_strategy",
    side: SignalSide = SignalSide.YES,
    price: float = 0.5,
    microstructure_score: float = 70.0,
    liquidity_score: float = 70.0,
    event_score: float = 70.0,
    wallet_score: float = 70.0,
    lifecycle_score: float = 70.0,
    risk_flags: list[str] = None,
) -> Signal:
    """Create a test signal"""
    if risk_flags is None:
        risk_flags = []
    return Signal(
        signal_id=signal_id,
        market_id=market_id,
        market_title=market_title,
        market_category="crypto",
        strategy_name=strategy_name,
        side=side,
        price=price,
        component_scores=ComponentScores(
            microstructure_score=microstructure_score,
            liquidity_score=liquidity_score,
            event_score=event_score,
            wallet_score=wallet_score,
            lifecycle_score=lifecycle_score,
        ),
        risk_flags=risk_flags,
    )


def create_test_risk_decision(
    signal_id: str = "test_signal_001",
    action: RiskAction = RiskAction.PAPER_TRADE,
    trade_score: float = 85.0,
    hard_reject_reasons: list[str] = None,
    explanation: str = "Test explanation",
) -> RiskDecision:
    """Create a test risk decision"""
    if hard_reject_reasons is None:
        hard_reject_reasons = []
    return RiskDecision(
        signal_id=signal_id,
        action=action,
        trade_score=trade_score,
        hard_reject_reasons=hard_reject_reasons,
        explanation=explanation,
    )


def create_test_market(
    market_id: str = "test_market_001",
    title: str = "Test Market",
    category: MarketCategory = MarketCategory.CRYPTO,
    status: MarketStatus = MarketStatus.OPEN,
) -> Market:
    """Create a test market"""
    return Market(
        market_id=market_id,
        title=title,
        description="Test market description",
        category=category,
        status=status,
        total_volume_usd=500000,
        volume_24h_usd=200000,
    )
