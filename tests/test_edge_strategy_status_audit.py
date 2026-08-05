"""Tests for Trading MVP Step 9F edge status audit."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.audit_edge_strategy_status as audit


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def sample_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    runs = tmp_path / "runs"
    shadow = runs / "shadow"
    write_json(runs / "edge_feedback_calibration_summary.json", {
        "trades_analyzed": 10,
        "overall_average_return": -0.24,
        "overall_win_rate": 0.1,
        "expected_edge_realized_return_correlation": -0.17,
        "confidence_win_correlation": -0.01,
        "edge_type_performance": {
            "price_dislocation_probability_v2": {
                "closed_trades": 10,
                "win_rate": 0.1,
                "average_return": -0.24,
            }
        },
    })
    write_json(runs / "edge_feedback_gate_summary.json", {
        "feedback_gates": {
            "price_dislocation_probability_v1": {
                "status": "watch_only",
                "trades_analyzed": 0,
                "win_rate": 0,
                "average_return": 0,
            },
            "price_dislocation_probability_v2": {
                "status": "quarantined",
                "trades_analyzed": 10,
                "win_rate": 0.1,
                "average_return": -0.24,
            },
        }
    })
    write_json(runs / "cross_market_convergence_dataset_summary.json", {
        "total_observations": 352,
        "pairs_analyzed": 16,
        "converging_pairs_count": 0,
        "best_convergence_score": 0.02,
    })
    write_json(shadow / "shadow_performance_review_summary.json", {
        "trades_reviewed": 10,
        "win_rate": 0.0,
        "average_return": -0.24,
        "total_pnl": -2.4,
        "edge_type_performance": {
            "cross_market_consistency_v1": {
                "trades": 10,
                "win_rate": 0.0,
                "average_return": -0.24,
                "total_return": -2.4,
            }
        },
    })
    write_json(runs / "multi_edge_discovery_summary.json", {
        "combined_ask_arbitrage_count": 474,
        "orderbooks_fetched": 948,
    })
    write_json(runs / "executable_edge_discovery_summary.json", {
        "edge_candidates_count": 0,
        "orderbooks_fetched": 948,
    })
    return runs, shadow


def test_can_build_edge_registry(tmp_path: Path):
    runs, shadow = sample_artifacts(tmp_path)

    rows = audit.build_registry(runs, shadow)

    assert {row["edge_type"] for row in rows} == {
        "combined_ask_arbitrage",
        "price_dislocation_probability_v1",
        "price_dislocation_probability_v2",
        "cross_market_consistency_v1",
        "cross_market_convergence",
    }


def test_missing_files_graceful(tmp_path: Path):
    rows = audit.build_registry(tmp_path / "runs", tmp_path / "runs" / "shadow")
    summary = audit.build_summary(rows)

    assert len(rows) == 5
    assert summary["tiny_live_recommendation"] == "NO"


def test_probability_edges_marked_quarantined(tmp_path: Path):
    runs, shadow = sample_artifacts(tmp_path)
    rows = {row["edge_type"]: row for row in audit.build_registry(runs, shadow)}

    assert rows["price_dislocation_probability_v1"]["recommended_status"] == "quarantined"
    assert rows["price_dislocation_probability_v2"]["recommended_status"] == "quarantined"


def test_cross_market_convergence_research_only(tmp_path: Path):
    runs, shadow = sample_artifacts(tmp_path)
    rows = {row["edge_type"]: row for row in audit.build_registry(runs, shadow)}

    assert rows["cross_market_convergence"]["recommended_status"] == "research_only"
    assert rows["cross_market_convergence"]["convergence_score"] == 0.02


def test_combined_ask_enabled_watchable(tmp_path: Path):
    runs, shadow = sample_artifacts(tmp_path)
    rows = {row["edge_type"]: row for row in audit.build_registry(runs, shadow)}

    assert rows["combined_ask_arbitrage"]["recommended_status"] == "enabled"
    assert rows["combined_ask_arbitrage"]["tiny_live_allowed"] is False


def test_summary_tiny_live_no(tmp_path: Path):
    runs, shadow = sample_artifacts(tmp_path)
    summary = audit.build_summary(audit.build_registry(runs, shadow))

    assert summary["tiny_live_recommendation"] == "NO"
    assert summary["any_edge_supports_tiny_live"] is False
    assert summary["recommended_next_edge_source"] == "Crypto Price Threshold Edge"


def test_output_summary_report_csv(tmp_path: Path):
    runs, shadow = sample_artifacts(tmp_path)
    rows = audit.build_registry(runs, shadow)
    summary = audit.build_summary(rows)

    audit.write_registry_csv(tmp_path / "registry.csv", rows)
    audit.write_summary(tmp_path / "summary.json", summary)
    audit.write_report(tmp_path / "report.md", rows, summary)

    assert list(csv.DictReader(open(tmp_path / "registry.csv")))[0]["edge_type"] == "combined_ask_arbitrage"
    assert json.loads((tmp_path / "summary.json").read_text())["recommended_step_10"] == "Trading MVP Step 10 — Crypto Price Threshold Edge v1"
    report = (tmp_path / "report.md").read_text()
    assert "Tiny live recommendation: **NO**" in report
    assert "Crypto Price Threshold Edge v1" in report


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/audit_edge_strategy_status.py").read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = [item for item in imports if any(name in item.lower() for name in ["livetrader", "paper_trader", "risk_governor"])]
    assert forbidden == []


def test_live_trading_enabled_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())
    assert risk["live_trading_enabled"] is False
