"""Feedback gates for shadow-only edge candidates.

The gate is deliberately conservative: it only decides whether an edge type is
allowed to create shadow entries. It is not a live trading permission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PROBABILITY_EDGE_TYPES = {
    "price_dislocation_probability_v1",
    "price_dislocation_probability_v2",
}

# Iteration 026: crypto_price_threshold_v1 joins the feedback-gated set after
# 16 closed trades across 6 independent clusters produced 1 win (6.2%) and
# negative average returns in every cohort (v7_reeval/v10/v11).
CRYPTO_PRICE_THRESHOLD_EDGE_TYPES = {
    "crypto_price_threshold_v1",
}
GATED_EDGE_TYPES = PROBABILITY_EDGE_TYPES | CRYPTO_PRICE_THRESHOLD_EDGE_TYPES


@dataclass
class FeedbackGateConfig:
    min_required_trades: int = 30
    min_win_rate: float = 0.52
    min_average_return: float = 0.01
    min_expected_edge_correlation: float = 0.1
    min_confidence_correlation: float = 0.05
    max_high_confidence_loss_rate: float = 0.35
    max_false_positive_rate: float = 0.45


@dataclass
class EdgeTypeGate:
    edge_type: str
    status: str
    trades_analyzed: int
    min_required_trades: int
    win_rate: float
    average_return: float
    expected_edge_realized_return_correlation: float
    confidence_win_correlation: float
    false_positive_rate: float
    high_confidence_loss_rate: float
    gate_passed: bool
    gate_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _edge_type_metrics(edge_type: str, feedback_summary: dict[str, Any]) -> dict[str, Any]:
    performance = feedback_summary.get("edge_type_performance") or {}
    metrics = performance.get(edge_type) if isinstance(performance, dict) else None
    analyzed = feedback_summary.get("edge_types_analyzed") or []
    if metrics:
        trades = _safe_int(metrics.get("closed_trades"), _safe_int(metrics.get("trades")))
        return {
            "trades_analyzed": trades,
            "win_rate": _safe_float(metrics.get("win_rate")),
            "average_return": _safe_float(metrics.get("average_return")),
        }
    if edge_type in analyzed or not performance:
        return {
            "trades_analyzed": _safe_int(feedback_summary.get("trades_analyzed")),
            "win_rate": _safe_float(feedback_summary.get("overall_win_rate")),
            "average_return": _safe_float(feedback_summary.get("overall_average_return")),
        }
    return {"trades_analyzed": 0, "win_rate": 0.0, "average_return": 0.0}


def evaluate_edge_type_gate(
    edge_type: str,
    feedback_summary: dict[str, Any] | None,
    config: FeedbackGateConfig | None = None,
) -> EdgeTypeGate:
    """Evaluate whether an edge type may emit executable shadow entries."""

    cfg = config or FeedbackGateConfig()
    if edge_type not in GATED_EDGE_TYPES:
        return EdgeTypeGate(
            edge_type=edge_type,
            status="enabled",
            trades_analyzed=0,
            min_required_trades=cfg.min_required_trades,
            win_rate=0.0,
            average_return=0.0,
            expected_edge_realized_return_correlation=0.0,
            confidence_win_correlation=0.0,
            false_positive_rate=0.0,
            high_confidence_loss_rate=0.0,
            gate_passed=True,
            gate_reason="edge_type_not_probability_gated",
        )

    summary = feedback_summary or {}
    metrics = _edge_type_metrics(edge_type, summary)
    trades = _safe_int(metrics.get("trades_analyzed"))
    win_rate = _safe_float(metrics.get("win_rate"))
    average_return = _safe_float(metrics.get("average_return"))
    expected_corr = _safe_float(
        summary.get(
            "expected_edge_realized_return_correlation",
            summary.get("calibrated_edge_realized_return_correlation"),
        )
    )
    confidence_corr = _safe_float(summary.get("confidence_win_correlation"))
    false_positive_count = _safe_int(summary.get("false_positive_count"))
    high_confidence_loss_count = _safe_int(summary.get("high_confidence_loss_count"))
    false_positive_rate = false_positive_count / trades if trades else 0.0
    high_confidence_loss_rate = high_confidence_loss_count / trades if trades else 0.0

    reasons: list[str] = []
    hard_fail = False
    if trades < cfg.min_required_trades:
        reasons.append("insufficient_feedback_data")
    if average_return <= 0:
        reasons.append("average_return_non_positive")
        hard_fail = trades > 0
    if expected_corr <= 0:
        reasons.append("expected_edge_negative_correlation")
        hard_fail = trades > 0
    if confidence_corr <= 0:
        reasons.append("confidence_not_predictive")
        hard_fail = trades > 0
    if high_confidence_loss_rate > cfg.max_high_confidence_loss_rate:
        reasons.append("high_confidence_loss_rate_too_high")
        hard_fail = trades > 0
    if false_positive_rate > cfg.max_false_positive_rate:
        reasons.append("false_positive_rate_too_high")
        hard_fail = trades > 0
    if win_rate < cfg.min_win_rate:
        reasons.append("win_rate_below_threshold")
        hard_fail = trades > 0 and average_return <= 0

    if hard_fail:
        status = "quarantined"
        passed = False
    elif reasons:
        status = "watch_only"
        passed = False
    else:
        status = "enabled"
        passed = True
        reasons.append("feedback_gate_passed")

    return EdgeTypeGate(
        edge_type=edge_type,
        status=status,
        trades_analyzed=trades,
        min_required_trades=cfg.min_required_trades,
        win_rate=win_rate,
        average_return=average_return,
        expected_edge_realized_return_correlation=expected_corr,
        confidence_win_correlation=confidence_corr,
        false_positive_rate=false_positive_rate,
        high_confidence_loss_rate=high_confidence_loss_rate,
        gate_passed=passed,
        gate_reason="|".join(reasons),
    )
