"""Data models for offline shadow paper trading."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class ShadowSide(str, Enum):
    YES = "YES"
    NO = "NO"


class ShadowTradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    REJECTED = "rejected"
    INSUFFICIENT_FORWARD_DATA = "insufficient_forward_data"


class ExitReason(str, Enum):
    FIXED_HORIZON = "fixed_horizon"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STALE_DATA = "stale_data"
    MARKET_CLOSE = "market_close"
    OPEN = "open"


@dataclass
class CandidateSnapshot:
    """Offline candidate data used to decide whether to create a shadow entry."""

    market_id: str
    question: str
    side: ShadowSide = ShadowSide.YES
    run_id: str = ""
    category: str = ""
    entry_time: str = ""
    alpha_score: float = 0.0
    expected_edge: float = 0.0
    executable_edge: float = 0.0
    combined_ask_gap: float = 0.0
    expected_edge_source: str = ""
    expected_edge_status: str = ""
    edge_pass: Optional[bool] = None
    edge_failure_reason: str = ""
    edge_notes: str = ""
    confidence: float = 0.0
    edge_type: str = ""
    evidence: str = ""
    relationship_status: str = ""
    relationship_confidence: float = 0.0
    price_gap: float = 0.0
    reference_market_id: str = ""
    reference_question: str = ""
    reference_price: float = 0.0
    convergence_gate_passed: Optional[bool] = None
    convergence_score: float = 0.0
    convergence_status: str = ""
    convergence_reason: str = ""
    convergence_observation_count: int = 0
    initial_price_gap: float = 0.0
    final_price_gap: float = 0.0
    gap_change: float = 0.0
    feedback_gate_status: str = ""
    feedback_gate_reason: str = ""
    gate_passed: Optional[bool] = None
    entry_yes_best_ask: float = 0.0
    entry_no_best_ask: float = 0.0
    entry_yes_best_bid: float = 0.0
    entry_no_best_bid: float = 0.0
    entry_side_price: float = 0.0
    entry_price_source: str = ""
    price_model_status: str = ""
    price_model_notes: str = ""
    # combined_ask is a market-level feature only, not a side-specific entry price.
    combined_ask: float = 1.0
    liquidity_score: float = 0.0
    ambiguity_risk: float = 0.0
    near_miss_tier: str = ""
    orderbook_spread: float = 0.0
    orderbook_depth: float = 0.0
    risk_decision: str = "allow_shadow"
    is_avoid_candidate: bool = False
    is_stale: bool = False
    is_llm_only: bool = False
    source: str = ""
    entry_decision_hint: str = ""
    tradable_score: float = 0.0
    tradable_source: str = ""
    tradable_reasons: list[str] = field(default_factory=list)
    evidence_level: str = ""
    yes_token_id: str = ""
    no_token_id: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ShadowTrade:
    """Hypothetical shadow trade record for paper performance validation."""

    shadow_trade_id: str
    market_id: str
    question: str
    side: ShadowSide
    entry_time: str
    entry_price: float
    entry_reason: str
    alpha_score: float
    combined_ask: float
    liquidity_score: float
    ambiguity_risk: float
    risk_decision: str
    expected_edge: float = 0.0
    confidence: float = 0.0
    edge_type: str = ""
    evidence: str = ""
    relationship_status: str = ""
    relationship_confidence: float = 0.0
    price_gap: float = 0.0
    reference_market_id: str = ""
    reference_question: str = ""
    reference_price: float = 0.0
    convergence_gate_passed: Optional[bool] = None
    convergence_score: float = 0.0
    convergence_status: str = ""
    convergence_reason: str = ""
    convergence_observation_count: int = 0
    initial_price_gap: float = 0.0
    final_price_gap: float = 0.0
    gap_change: float = 0.0
    entry_yes_best_ask: float = 0.0
    entry_no_best_ask: float = 0.0
    entry_yes_best_bid: float = 0.0
    entry_no_best_bid: float = 0.0
    entry_side_price: float = 0.0
    exit_side_price: Optional[float] = None
    entry_price_source: str = ""
    exit_price_source: str = ""
    price_model_status: str = ""
    price_model_notes: str = ""
    tradable_score: float = 0.0
    yes_token_id: str = ""
    no_token_id: str = ""
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: ExitReason = ExitReason.OPEN
    pnl: float = 0.0
    return_pct: float = 0.0
    status: ShadowTradeStatus = ShadowTradeStatus.OPEN
    run_id: str = ""
    category: str = ""
    source: str = ""
    evidence_level: str = ""
    near_miss_tier: str = ""
    orderbook_spread: float = 0.0
    orderbook_depth: float = 0.0
    max_adverse_excursion: float = 0.0
    max_favorable_excursion: float = 0.0
    holding_minutes: float = 0.0

    @classmethod
    def from_candidate(cls, candidate: CandidateSnapshot, entry_reason: str) -> "ShadowTrade":
        entry_side_price = candidate.entry_side_price or candidate.side_entry_ask()
        return cls(
            shadow_trade_id=f"shadow_{uuid4().hex[:12]}",
            market_id=candidate.market_id,
            question=candidate.question,
            side=candidate.side,
            entry_time=candidate.entry_time or datetime.utcnow().isoformat(),
            entry_price=entry_side_price,
            entry_reason=entry_reason,
            expected_edge=candidate.expected_edge,
            confidence=candidate.confidence,
            edge_type=candidate.edge_type,
            evidence=candidate.evidence or "|".join(candidate.tradable_reasons),
            relationship_status=candidate.relationship_status,
            relationship_confidence=candidate.relationship_confidence,
            price_gap=candidate.price_gap,
            reference_market_id=candidate.reference_market_id,
            reference_question=candidate.reference_question,
            reference_price=candidate.reference_price,
            convergence_gate_passed=candidate.convergence_gate_passed,
            convergence_score=candidate.convergence_score,
            convergence_status=candidate.convergence_status,
            convergence_reason=candidate.convergence_reason,
            convergence_observation_count=candidate.convergence_observation_count,
            initial_price_gap=candidate.initial_price_gap,
            final_price_gap=candidate.final_price_gap,
            gap_change=candidate.gap_change,
            entry_yes_best_ask=candidate.entry_yes_best_ask,
            entry_no_best_ask=candidate.entry_no_best_ask,
            entry_yes_best_bid=candidate.entry_yes_best_bid,
            entry_no_best_bid=candidate.entry_no_best_bid,
            entry_side_price=entry_side_price,
            entry_price_source=candidate.entry_price_source or f"{candidate.side.value.lower()}_best_ask",
            price_model_status=candidate.price_model_status or "side_specific_entry",
            price_model_notes=candidate.price_model_notes,
            tradable_score=candidate.tradable_score,
            alpha_score=candidate.alpha_score,
            combined_ask=candidate.combined_ask,
            liquidity_score=candidate.liquidity_score,
            ambiguity_risk=candidate.ambiguity_risk,
            risk_decision=candidate.risk_decision,
            run_id=candidate.run_id,
            category=candidate.category,
            source=candidate.tradable_source or candidate.source,
            evidence_level=candidate.evidence_level,
            yes_token_id=candidate.yes_token_id,
            no_token_id=candidate.no_token_id,
            near_miss_tier=candidate.near_miss_tier,
            orderbook_spread=candidate.orderbook_spread,
            orderbook_depth=candidate.orderbook_depth,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value
        payload["exit_reason"] = self.exit_reason.value
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShadowTrade":
        payload = dict(data)
        payload["side"] = ShadowSide(payload.get("side", ShadowSide.YES.value))
        payload["exit_reason"] = ExitReason(payload.get("exit_reason", ExitReason.OPEN.value))
        payload["status"] = ShadowTradeStatus(payload.get("status", ShadowTradeStatus.OPEN.value))
        return cls(**payload)

    def effective_entry_price(self) -> float:
        return self.entry_side_price or self.entry_price

    def set_exit_side_price(self, value: float, source: str) -> None:
        self.exit_side_price = value
        self.exit_price = value
        self.exit_price_source = source


def _side_entry_ask(candidate: CandidateSnapshot) -> float:
    if candidate.side == ShadowSide.NO:
        return candidate.entry_no_best_ask
    return candidate.entry_yes_best_ask


def _side_entry_bid(candidate: CandidateSnapshot) -> float:
    if candidate.side == ShadowSide.NO:
        return candidate.entry_no_best_bid
    return candidate.entry_yes_best_bid


CandidateSnapshot.side_entry_ask = _side_entry_ask  # type: ignore[attr-defined]
CandidateSnapshot.side_entry_bid = _side_entry_bid  # type: ignore[attr-defined]


SHADOW_TRADE_FIELDS = [
    "shadow_trade_id",
    "market_id",
    "question",
    "side",
    "entry_time",
    "entry_price",
    "entry_reason",
    "expected_edge",
    "confidence",
    "edge_type",
    "evidence",
    "relationship_status",
    "relationship_confidence",
    "price_gap",
    "reference_market_id",
    "reference_question",
    "reference_price",
    "convergence_gate_passed",
    "convergence_score",
    "convergence_status",
    "convergence_reason",
    "convergence_observation_count",
    "initial_price_gap",
    "final_price_gap",
    "gap_change",
    "entry_yes_best_ask",
    "entry_no_best_ask",
    "entry_yes_best_bid",
    "entry_no_best_bid",
    "entry_side_price",
    "exit_side_price",
    "entry_price_source",
    "exit_price_source",
    "price_model_status",
    "price_model_notes",
    "tradable_score",
    "alpha_score",
    "combined_ask",
    "liquidity_score",
    "ambiguity_risk",
    "risk_decision",
    "yes_token_id",
    "no_token_id",
    "exit_time",
    "exit_price",
    "exit_reason",
    "pnl",
    "return_pct",
    "status",
    "run_id",
    "category",
    "source",
    "evidence_level",
    "near_miss_tier",
    "orderbook_spread",
    "orderbook_depth",
    "max_adverse_excursion",
    "max_favorable_excursion",
    "holding_minutes",
]
