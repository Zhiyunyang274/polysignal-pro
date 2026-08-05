"""Tests for Trading MVP Step 7 edge feedback calibration."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.calibrate_edge_from_shadow_feedback as feedback


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_safe_config(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "risk.yaml").write_text(
        yaml.safe_dump({
            "live_trading_enabled": False,
            "allow_auto_execution": False,
            "paper_trading_enabled": True,
        })
    )
    (config / "llm.yaml").write_text(yaml.safe_dump({"provider": "mock"}))


def sample_workspace(tmp_path: Path) -> tuple[Path, Path]:
    runs = tmp_path / "runs"
    shadow = runs / "shadow"
    write_csv(
        runs / "multi_edge_candidates_v2.csv",
        [
            {
                "market_id": "m1",
                "edge_type": "price_dislocation_probability_v2",
                "side": "YES",
                "calibrated_expected_edge": 0.03,
                "expected_edge": 0.03,
                "confidence": 0.95,
                "exit_bid_penalty": 0.001,
                "adverse_selection_penalty": 0.001,
                "liquidity_penalty": 0.0,
                "entry_yes_best_ask": 0.40,
                "entry_yes_best_bid": 0.39,
                "entry_no_best_ask": 0.61,
                "entry_no_best_bid": 0.60,
                "combined_ask": 1.01,
                "depth": 20,
                "liquidity_score": 500,
            },
            {
                "market_id": "m2",
                "edge_type": "price_dislocation_probability_v2",
                "side": "NO",
                "calibrated_expected_edge": 0.01,
                "expected_edge": 0.01,
                "confidence": 0.65,
                "exit_bid_penalty": 0.02,
                "adverse_selection_penalty": 0.02,
                "liquidity_penalty": 0.0,
                "entry_yes_best_ask": 0.30,
                "entry_yes_best_bid": 0.29,
                "entry_no_best_ask": 0.70,
                "entry_no_best_bid": 0.69,
                "combined_ask": 1.0,
                "depth": 50,
                "liquidity_score": 800,
            },
            {
                "market_id": "m3",
                "edge_type": "price_dislocation_probability_v2",
                "side": "YES",
                "calibrated_expected_edge": 0.04,
                "expected_edge": 0.04,
                "confidence": 0.90,
                "exit_bid_penalty": 0.001,
                "adverse_selection_penalty": 0.001,
                "liquidity_penalty": 0.0,
                "entry_yes_best_ask": 0.20,
                "entry_yes_best_bid": 0.19,
                "entry_no_best_ask": 0.81,
                "entry_no_best_bid": 0.80,
                "combined_ask": 1.01,
                "depth": 15,
                "liquidity_score": 400,
            },
        ],
    )
    write_csv(
        shadow / "updated_shadow_trades.csv",
        [
            {
                "shadow_trade_id": "t1",
                "market_id": "m1",
                "question": "Q1",
                "edge_type": "price_dislocation_probability_v2",
                "side": "YES",
                "expected_edge": 0.03,
                "confidence": 0.95,
                "entry_price": 0.40,
                "entry_side_price": 0.40,
                "exit_price": 0.30,
                "exit_side_price": 0.30,
                "entry_yes_best_ask": 0.40,
                "entry_yes_best_bid": 0.39,
                "entry_no_best_ask": 0.61,
                "entry_no_best_bid": 0.60,
                "combined_ask": 1.01,
                "liquidity_score": 500,
                "orderbook_depth": 20,
                "return_pct": -0.25,
                "pnl": -0.25,
                "status": "closed",
                "exit_reason": "stop_loss",
                "holding_minutes": 0,
            },
            {
                "shadow_trade_id": "t2",
                "market_id": "m2",
                "question": "Q2",
                "edge_type": "price_dislocation_probability_v2",
                "side": "NO",
                "expected_edge": 0.01,
                "confidence": 0.65,
                "entry_price": 0.70,
                "entry_side_price": 0.70,
                "exit_price": 0.72,
                "exit_side_price": 0.72,
                "entry_yes_best_ask": 0.30,
                "entry_yes_best_bid": 0.29,
                "entry_no_best_ask": 0.70,
                "entry_no_best_bid": 0.69,
                "combined_ask": 1.0,
                "liquidity_score": 800,
                "orderbook_depth": 50,
                "return_pct": 0.028571,
                "pnl": 0.028571,
                "status": "closed",
                "exit_reason": "take_profit",
                "holding_minutes": 5,
            },
            {
                "shadow_trade_id": "t3",
                "market_id": "m3",
                "question": "Q3",
                "edge_type": "price_dislocation_probability_v2",
                "side": "YES",
                "expected_edge": 0.04,
                "confidence": 0.90,
                "entry_price": 0.20,
                "entry_side_price": 0.20,
                "exit_price": 0.10,
                "exit_side_price": 0.10,
                "entry_yes_best_ask": 0.20,
                "entry_yes_best_bid": 0.19,
                "entry_no_best_ask": 0.81,
                "entry_no_best_bid": 0.80,
                "combined_ask": 1.01,
                "liquidity_score": 400,
                "orderbook_depth": 15,
                "return_pct": -0.50,
                "pnl": -0.50,
                "status": "closed",
                "exit_reason": "stop_loss",
                "holding_minutes": 0,
            },
        ],
    )
    write_csv(
        shadow / "shadow_trade_diagnostics.csv",
        [
            {"shadow_trade_id": "t1", "diagnosis_flags": "expected_edge_too_optimistic", "primary_loss_driver": "expected_edge_too_optimistic"},
            {"shadow_trade_id": "t2", "diagnosis_flags": "not_losing_trade", "primary_loss_driver": "not_losing_trade"},
            {"shadow_trade_id": "t3", "diagnosis_flags": "expected_edge_too_optimistic", "primary_loss_driver": "expected_edge_too_optimistic"},
        ],
    )
    (shadow / "forward_observations.jsonl").write_text("")
    return runs, shadow


def test_can_merge_candidate_and_realized_pnl(tmp_path: Path):
    runs, shadow = sample_workspace(tmp_path)
    dataset = feedback.build_dataset(runs, shadow)

    assert len(dataset) == 3
    assert dataset[0]["edge_type"] == "price_dislocation_probability_v2"
    assert dataset[0]["realized_return"] == -0.25
    assert dataset[0]["calibrated_expected_edge"] == 0.03


def test_expected_edge_correlation_calculation():
    corr = feedback.pearson([1, 2, 3], [3, 2, 1])
    assert round(corr, 6) == -1.0


def test_confidence_correlation_calculation(tmp_path: Path):
    runs, shadow = sample_workspace(tmp_path)
    summary = feedback.summarize(feedback.build_dataset(runs, shadow), 0.8)

    assert summary["confidence_win_correlation"] is not None
    assert summary["confidence_win_correlation"] < 0


def test_false_positives_and_high_confidence_losses(tmp_path: Path):
    runs, shadow = sample_workspace(tmp_path)
    summary = feedback.summarize(feedback.build_dataset(runs, shadow), 0.8)

    assert summary["false_positive_count"] == 2
    assert summary["high_confidence_loss_count"] == 2


def test_top_loss_patterns_output(tmp_path: Path):
    runs, shadow = sample_workspace(tmp_path)
    summary = feedback.summarize(feedback.build_dataset(runs, shadow), 0.8)
    patterns = {item["pattern"]: item["count"] for item in summary["top_loss_patterns"]}

    assert patterns["expected_edge_false_positive"] == 2
    assert patterns["high_confidence_loss"] == 2
    assert patterns["microstructure_probability_loss"] == 2


def test_missing_files_graceful(tmp_path: Path):
    dataset = feedback.build_dataset(tmp_path / "runs", tmp_path / "runs" / "shadow")
    summary = feedback.summarize(dataset, 0.8)

    assert dataset == []
    assert summary["trades_analyzed"] == 0
    assert summary["tiny_live_recommendation"] == "NO"


def test_report_summary_csv_format(tmp_path: Path, monkeypatch):
    write_safe_config(tmp_path)
    runs, shadow = sample_workspace(tmp_path)
    output = tmp_path / "out"
    monkeypatch.setattr(feedback, "REPO_ROOT", tmp_path)

    rc = feedback.main(["--runs_dir", str(runs), "--shadow_dir", str(shadow), "--output_dir", str(output)])

    assert rc == 0
    assert (output / "edge_feedback_dataset.csv").exists()
    assert (output / "edge_feedback_calibration_summary.json").exists()
    assert (output / "edge_feedback_calibration_report.md").exists()
    summary = json.loads((output / "edge_feedback_calibration_summary.json").read_text())
    assert summary["tiny_live_recommendation"] == "NO"
    assert "tiny live recommendation: NO" in (output / "edge_feedback_calibration_report.md").read_text()


def test_dry_run_does_not_write_files(tmp_path: Path):
    runs, shadow = sample_workspace(tmp_path)
    output = tmp_path / "out"

    rc = feedback.main(["--runs_dir", str(runs), "--shadow_dir", str(shadow), "--output_dir", str(output), "--dry_run"])

    assert rc == 0
    assert not (output / "edge_feedback_dataset.csv").exists()


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/calibrate_edge_from_shadow_feedback.py").read_text())
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
