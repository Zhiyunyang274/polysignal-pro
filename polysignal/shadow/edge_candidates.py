"""Unified edge candidate models for shadow-only discovery.

Edge candidates are research/shadow inputs. They are not trading signals and
must never bypass risk, liquidity, ambiguity, or execution gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EdgeType(str, Enum):
    COMBINED_ASK_ARBITRAGE = "combined_ask_arbitrage"
    PRICE_DISLOCATION_PROBABILITY_V1 = "price_dislocation_probability_v1"
    PRICE_DISLOCATION_PROBABILITY_V2 = "price_dislocation_probability_v2"
    STALE_PRICE_LAG = "stale_price_lag"
    CLOSING_MARKET_CONVERGENCE = "closing_market_convergence"
    CROSS_MARKET_CONSISTENCY = "cross_market_consistency"
    CROSS_MARKET_CONSISTENCY_V1 = "cross_market_consistency_v1"
    SPREAD_CAPTURE_PASSIVE = "spread_capture_passive"
    CRYPTO_PRICE_THRESHOLD_V1 = "crypto_price_threshold_v1"


class EdgeAction(str, Enum):
    WATCH_ONLY = "watch_only"
    SHADOW_ENTRY = "shadow_entry"
    REJECT = "reject"


@dataclass
class EdgeCandidate:
    """A unified shadow-only candidate emitted by an edge detector."""

    edge_type: EdgeType
    market_id: str
    question: str
    side: str
    yes_token_id: str
    no_token_id: str
    entry_price: float
    estimated_probability: float
    expected_edge: float
    confidence: float
    liquidity_score: float
    depth: float
    spread: float
    risk_flags: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    recommended_action: EdgeAction = EdgeAction.WATCH_ONLY
    yes_best_bid: float = 0.0
    yes_best_ask: float = 0.0
    no_best_bid: float = 0.0
    no_best_ask: float = 0.0
    combined_ask: float = 0.0
    combined_ask_gap: float = 0.0
    executable_edge: float = 0.0
    timestamp: str = ""
    source: str = "multi_edge_discovery"
    category: str = ""
    volume: float = 0.0
    raw_estimated_probability: float = 0.0
    calibrated_estimated_probability: float = 0.0
    probability_adjustment: float = 0.0
    exit_bid_penalty: float = 0.0
    adverse_selection_penalty: float = 0.0
    liquidity_penalty: float = 0.0
    confidence_penalty: float = 0.0
    calibrated_expected_edge: float = 0.0
    calibration_version: str = ""
    feedback_gate_status: str = ""
    feedback_gate_reason: str = ""
    gate_passed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["edge_type"] = self.edge_type.value
        payload["recommended_action"] = self.recommended_action.value
        payload["risk_flags"] = "|".join(self.risk_flags)
        payload["evidence"] = "|".join(self.evidence)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EdgeCandidate:
        payload = dict(data)
        payload["edge_type"] = EdgeType(payload.get("edge_type", EdgeType.PRICE_DISLOCATION_PROBABILITY_V1.value))
        payload["recommended_action"] = EdgeAction(payload.get("recommended_action", EdgeAction.WATCH_ONLY.value))
        for field_name in ("risk_flags", "evidence"):
            value = payload.get(field_name, [])
            if isinstance(value, str):
                payload[field_name] = [part.strip() for part in value.split("|") if part.strip()]
        return cls(**payload)


EDGE_CANDIDATE_FIELDS = [
    "edge_type",
    "market_id",
    "question",
    "side",
    "yes_token_id",
    "no_token_id",
    "entry_price",
    "estimated_probability",
    "expected_edge",
    "confidence",
    "liquidity_score",
    "depth",
    "spread",
    "risk_flags",
    "evidence",
    "recommended_action",
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "combined_ask",
    "combined_ask_gap",
    "executable_edge",
    "timestamp",
    "source",
    "category",
    "volume",
    "raw_estimated_probability",
    "calibrated_estimated_probability",
    "probability_adjustment",
    "exit_bid_penalty",
    "adverse_selection_penalty",
    "liquidity_penalty",
    "confidence_penalty",
    "calibrated_expected_edge",
    "calibration_version",
    "feedback_gate_status",
    "feedback_gate_reason",
    "gate_passed",
]
