"""Tests for Trading MVP Step 8 feedback-gated shadow entry."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml

from polysignal.shadow.entry_filter import EntryDecision, EntryFilterConfig, ShadowEntryFilter
from polysignal.shadow.feedback_gate import evaluate_edge_type_gate
from polysignal.shadow.models import CandidateSnapshot, ShadowSide

NEGATIVE_SUMMARY = {
    "edge_types_analyzed": ["price_dislocation_probability_v2"],
    "trades_analyzed": 10,
    "overall_win_rate": 0.1,
    "overall_average_return": -0.2469158035079444,
    "expected_edge_realized_return_correlation": -0.1784870086432687,
    "confidence_win_correlation": -0.009224758324091477,
    "false_positive_count": 9,
    "high_confidence_loss_count": 9,
    "edge_type_performance": {
        "price_dislocation_probability_v2": {
            "trades": 10,
            "closed_trades": 10,
            "win_rate": 0.1,
            "average_return": -0.2469158035079444,
        }
    },
}


POSITIVE_SUMMARY = {
    "edge_types_analyzed": ["price_dislocation_probability_v2"],
    "trades_analyzed": 40,
    "overall_win_rate": 0.58,
    "overall_average_return": 0.025,
    "expected_edge_realized_return_correlation": 0.22,
    "confidence_win_correlation": 0.12,
    "false_positive_count": 8,
    "high_confidence_loss_count": 7,
    "edge_type_performance": {
        "price_dislocation_probability_v2": {
            "trades": 40,
            "closed_trades": 40,
            "win_rate": 0.58,
            "average_return": 0.025,
        }
    },
}


def edge_candidate(**overrides) -> CandidateSnapshot:
    payload = {
        "market_id": "m1",
        "question": "Q?",
        "side": ShadowSide.YES,
        "expected_edge": 0.08,
        "confidence": 0.9,
        "edge_type": "price_dislocation_probability_v2",
        "evidence": "probability_edge_v2|calibrated_microstructure_probability_edge",
        "feedback_gate_status": "quarantined",
        "feedback_gate_reason": (
            "expected_edge_negative_correlation|confidence_not_predictive|"
            "false_positive_rate_too_high"
        ),
        "gate_passed": False,
        "entry_yes_best_ask": 0.2,
        "entry_yes_best_bid": 0.19,
        "entry_no_best_ask": 0.79,
        "entry_no_best_bid": 0.78,
        "combined_ask": 0.99,
        "liquidity_score": 10,
        "ambiguity_risk": 0,
        "near_miss_tier": "tier1_mispricing",
        "orderbook_spread": 0.01,
        "orderbook_depth": 4,
        "risk_decision": "allow_shadow",
        "source": "tradable_candidate",
        "tradable_source": "multi_edge_discovery",
        "tradable_reasons": ["probability_edge_v2", "calibrated_microstructure_probability_edge"],
        "edge_pass": True,
    }
    payload.update(overrides)
    return CandidateSnapshot(**payload)


def test_negative_feedback_quarantines_probability_edge():
    gate = evaluate_edge_type_gate("price_dislocation_probability_v2", NEGATIVE_SUMMARY)

    assert gate.status == "quarantined"
    assert gate.gate_passed is False
    assert "expected_edge_negative_correlation" in gate.gate_reason
    assert "confidence_not_predictive" in gate.gate_reason


def test_quarantined_probability_edge_cannot_generate_shadow_entry():
    result = ShadowEntryFilter(EntryFilterConfig()).evaluate(edge_candidate())

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "edge_type_quarantined" in result.watch_reasons
    assert "feedback_gate_failed" in result.watch_reasons


def test_insufficient_feedback_data_is_watch_only():
    gate = evaluate_edge_type_gate("price_dislocation_probability_v1", {})

    assert gate.status == "watch_only"
    assert gate.gate_passed is False
    assert "insufficient_feedback_data" in gate.gate_reason


def test_positive_feedback_data_allows_probability_edge():
    gate = evaluate_edge_type_gate("price_dislocation_probability_v2", POSITIVE_SUMMARY)

    assert gate.status == "enabled"
    assert gate.gate_passed is True


def test_combined_ask_arbitrage_not_probability_gated():
    gate = evaluate_edge_type_gate("combined_ask_arbitrage", NEGATIVE_SUMMARY)

    assert gate.status == "enabled"
    assert gate.gate_passed is True


def test_diagnostics_include_feedback_gate_reasons():
    result = ShadowEntryFilter().evaluate(edge_candidate())

    assert result.reason == "edge_type_quarantined"
    assert "expected_edge_negative_correlation" in result.watch_reasons
    assert "confidence_not_predictive" in result.watch_reasons


def test_no_forbidden_imports():
    for path in [
        Path("polysignal/shadow/feedback_gate.py"),
        Path("polysignal/shadow/entry_filter.py"),
    ]:
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not any("live_trader" in name.lower() for name in imports)
        assert not any("paper_trader" in name.lower() for name in imports)
        assert not any("risk_governor" in name.lower() for name in imports)


def test_live_trading_enabled_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
    assert risk["allow_auto_execution"] is False
    assert risk["paper_trading_enabled"] is True


class TestCryptoPriceThresholdGate:
    """Iteration 026: crypto_price_threshold_v1 joins the gated set after the
    v7+v10+v11 merged evidence (16 closed, 1 win, all cohorts negative)."""

    def test_crypto_threshold_edge_is_gated(self):
        from polysignal.shadow.feedback_gate import (
            CRYPTO_PRICE_THRESHOLD_EDGE_TYPES,
            GATED_EDGE_TYPES,
        )

        assert "crypto_price_threshold_v1" in GATED_EDGE_TYPES
        assert "crypto_price_threshold_v1" in CRYPTO_PRICE_THRESHOLD_EDGE_TYPES

    def test_real_calibration_metrics_quarantine(self):
        summary = json.load(
            open("runs/crypto_threshold_feedback_calibration_summary.json", encoding="utf-8")
        )
        gate = evaluate_edge_type_gate("crypto_price_threshold_v1", summary)
        assert gate.status == "quarantined"
        assert gate.gate_passed is False
        assert gate.trades_analyzed == 16
        assert gate.win_rate == pytest.approx(0.0625)

    def test_uncorrelated_summary_quarantines_too(self):
        summary = {
            "edge_type_performance": {
                "crypto_price_threshold_v1": {
                    "trades": 16,
                    "closed_trades": 16,
                    "win_rate": 0.0625,
                    "average_return": -0.14,
                }
            },
            "edge_types_analyzed": ["crypto_price_threshold_v1"],
            "false_positive_count": 15,
            "high_confidence_loss_count": 15,
        }
        gate = evaluate_edge_type_gate("crypto_price_threshold_v1", summary)
        assert gate.status == "quarantined"
