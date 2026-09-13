"""
Risk Models - Risk Governor decision models

IMPORTANT: RiskAction is the action to take, RiskDecision is the decision result.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class RiskAction(StrEnum):
    """Risk Governor action decision"""
    IGNORE = "ignore"                    # score < 70
    LOG_ONLY = "log_only"               # 70 <= score < 80
    ALERT = "alert"                     # 80 <= score < 90
    PAPER_TRADE = "paper_trade"         # 90 <= score < 95
    MANUAL_REVIEW = "manual_review"     # 90 <= score < 95 (with flags)
    LIVE_EXECUTE = "live_execute"       # score >= 95 AND explicitly enabled
    HARD_REJECT = "hard_reject"         # Hard rejection conditions met


class RiskContext(BaseModel):
    """Risk Governor context - system and account state"""
    # System state
    live_trading_enabled: bool = Field(False, description="Live trading is enabled")
    allow_auto_execution: bool = Field(False, description="Auto execution allowed")
    api_healthy: bool = Field(True, description="API is healthy")
    websocket_healthy: bool = Field(True, description="WebSocket is healthy")

    # Account state
    account_balance_usd: float = Field(100.0, ge=0)
    daily_pnl_usd: float = Field(0.0)
    weekly_pnl_usd: float = Field(0.0)
    consecutive_losses: int = Field(0, ge=0)

    # Exposure state
    current_market_exposure_usd: float = Field(0.0, ge=0)
    current_strategy_exposure_usd: float = Field(0.0, ge=0)

    # Market state
    market_tradable: bool = Field(True)
    market_ambiguous: bool = Field(False)
    market_forbidden: bool = Field(False)
    price_stale: bool = Field(False)


class RiskDecision(BaseModel):
    """Risk Governor decision result"""
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    signal_id: str

    # Decision
    action: RiskAction = Field(RiskAction.IGNORE)
    trade_score: float = Field(0.0, ge=0, le=100)

    # Hard rejection reasons
    hard_reject_reasons: list[str] = Field(default_factory=list)

    # Score breakdown
    component_scores: dict[str, float] = Field(default_factory=dict)

    # Penalties
    ambiguity_penalty: float = Field(0.0, ge=0)
    slippage_penalty: float = Field(0.0, ge=0)
    concentration_penalty: float = Field(0.0, ge=0)
    copy_risk_penalty: float = Field(0.0, ge=0)
    chase_risk_penalty: float = Field(0.0, ge=0)
    timing_risk_penalty: float = Field(0.0, ge=0)
    event_ambiguity_penalty: float = Field(0.0, ge=0)
    event_weak_evidence_penalty: float = Field(0.0, ge=0)
    llm_failure_penalty: float = Field(0.0, ge=0)

    # Allowed actions
    allowed_actions: list[RiskAction] = Field(default_factory=list)

    # Explanation
    explanation: str = Field("")

    # Risk flags
    risk_flags: list[str] = Field(default_factory=list)

    def is_hard_rejected(self) -> bool:
        """Check if hard rejected"""
        return self.action == RiskAction.HARD_REJECT

    def allows_paper_trade(self) -> bool:
        """Check if paper trade is allowed"""
        return RiskAction.PAPER_TRADE in self.allowed_actions

    def allows_live_execute(self) -> bool:
        """Check if live execution is allowed"""
        return RiskAction.LIVE_EXECUTE in self.allowed_actions

    def get_summary(self) -> str:
        """Get decision summary"""
        return (
            f"RiskDecision({self.decision_id[:8]}): {self.action.value} "
            f"| Score: {self.trade_score:.1f} "
            f"| Rejects: {len(self.hard_reject_reasons)}"
        )
