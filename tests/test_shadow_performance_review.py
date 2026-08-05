"""Tests for Phase 8H shadow performance review."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.review_shadow_performance as review
from polysignal.shadow.models import SHADOW_TRADE_FIELDS


def write_trade(path: Path, **overrides) -> dict[str, str]:
    row = {
        "shadow_trade_id": "shadow_1",
        "market_id": "m1",
        "question": "Will test happen?",
        "side": "YES",
        "entry_time": "2026-05-11T00:00:00",
        "entry_price": "1.001",
        "entry_reason": "tradable_candidate_evidence_passed",
        "expected_edge": "0.03",
        "confidence": "0.95",
        "edge_type": "price_dislocation_probability_v1",
        "evidence": "microstructure_probability_edge",
        "tradable_score": "16.4",
        "alpha_score": "0",
        "combined_ask": "1.001",
        "liquidity_score": "2",
        "ambiguity_risk": "5",
        "risk_decision": "allow_shadow",
        "yes_token_id": "yes1",
        "no_token_id": "no1",
        "exit_time": "2026-05-11T01:00:00",
        "exit_price": "0.10",
        "exit_reason": "stop_loss",
        "pnl": "-0.90",
        "return_pct": "-0.90",
        "status": "closed",
        "run_id": "",
        "category": "Sports",
        "source": "control_group",
        "evidence_level": "control_group",
        "near_miss_tier": "",
        "orderbook_spread": "0.02",
        "orderbook_depth": "2",
        "max_adverse_excursion": "-0.90",
        "max_favorable_excursion": "-0.90",
        "holding_minutes": "60",
    }
    row.update(overrides)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHADOW_TRADE_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return row


def setup_review_dir(tmp_path: Path, **trade_overrides) -> tuple[Path, Path]:
    runs_dir = tmp_path / "runs"
    shadow_dir = runs_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    trade = write_trade(shadow_dir / "updated_shadow_trades.csv", **trade_overrides)
    (shadow_dir / "updated_shadow_positions.json").write_text(json.dumps({
        "generated_at": "2026-05-11T01:00:00",
        "open_positions": [],
        "closed_positions": [trade],
        "insufficient_forward_data_positions": [],
    }))
    (shadow_dir / "forward_observations.jsonl").write_text(json.dumps({
        "shadow_trade_id": "shadow_1",
        "market_id": "m1",
        "timestamp": "2026-05-11T01:00:00",
        "observed_price": 0.10,
        "yes_best_bid": 0.10,
        "yes_best_ask": 0.12,
        "no_best_bid": 0.88,
        "no_best_ask": 0.89,
        "combined_ask": 1.01,
        "spread": 0.02,
        "liquidity": 10,
        "source": "clob_rest_readonly",
        "stale": False,
    }) + "\n")
    (shadow_dir / "paper_performance_summary.json").write_text(json.dumps({
        "total_pnl": -0.90,
        "win_rate": 0.0,
        "max_drawdown": -0.90,
    }))
    (runs_dir / "tradable_candidates_with_tokens.csv").write_text(
        "market_id,source,tradable_score,evidence_level,near_miss_tier,reasons\n"
        "m1,control_group,16.4,control_group,,control_group_low_risk\n"
    )
    return runs_dir, shadow_dir


def test_can_read_updated_shadow_trades_csv(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    summary, diagnostics, _ = review.build_review(args)

    assert summary["trades_reviewed"] == 1
    assert diagnostics[0]["shadow_trade_id"] == "shadow_1"


def test_can_read_updated_shadow_positions_json(tmp_path: Path):
    _, shadow_dir = setup_review_dir(tmp_path)

    positions = review.load_position_rows(shadow_dir / "updated_shadow_positions.json")

    assert positions["shadow_1"]["status"] == "closed"


def test_can_read_forward_observations_jsonl(tmp_path: Path):
    _, shadow_dir = setup_review_dir(tmp_path)

    observations = review.load_forward_observations(shadow_dir / "forward_observations.jsonl")

    assert observations["shadow_1"][0]["observed_price"] == 0.10


def test_missing_files_graceful_handling(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    shadow_dir = runs_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    summary, diagnostics, _ = review.build_review(args)

    assert summary["trades_reviewed"] == 0
    assert diagnostics == []


def test_losing_trade_generates_diagnosis(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    _, diagnostics, _ = review.build_review(args)

    assert diagnostics[0]["pnl"] < 0
    assert diagnostics[0]["primary_loss_driver"]


def test_spread_drag_flag(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    _, diagnostics, _ = review.build_review(args)

    assert "spread_drag" in diagnostics[0]["diagnosis_flags"]


def test_weak_evidence_flag(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    _, diagnostics, _ = review.build_review(args)

    assert "weak_tradable_evidence" in diagnostics[0]["diagnosis_flags"]


def test_control_group_source_risk_flag(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    _, diagnostics, _ = review.build_review(args)

    assert "control_group_source_risk" in diagnostics[0]["diagnosis_flags"]


def test_insufficient_expected_edge_flag(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    _, diagnostics, _ = review.build_review(args)

    assert "insufficient_expected_edge" in diagnostics[0]["diagnosis_flags"]


def test_aggregate_loss_attribution_correct(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    summary, _, _ = review.build_review(args)

    assert summary["losing_trades"] == 1
    assert summary["primary_loss_drivers"]["legacy_invalid_price_model"] == 1


def test_review_tracks_edge_type_performance(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(
        tmp_path,
        entry_price="0.50",
        entry_side_price="0.50",
        exit_price="0.45",
        exit_side_price="0.45",
        combined_ask="1.01",
        pnl="-0.1",
        return_pct="-0.1",
    )
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    summary, diagnostics, _ = review.build_review(args)

    assert diagnostics[0]["edge_type"] == "price_dislocation_probability_v1"
    assert "probability_model_bias" in diagnostics[0]["diagnosis_flags"]
    assert summary["edge_type_performance"]["price_dislocation_probability_v1"]["trades"] == 1
    assert summary["probability_model_bias_count"] == 1


def test_review_tracks_cross_market_relationship_performance(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(
        tmp_path,
        entry_price="0.30",
        entry_side_price="0.30",
        exit_price="0.36",
        exit_side_price="0.36",
        combined_ask="1.00",
        pnl="0.2",
        return_pct="0.2",
        edge_type="cross_market_consistency_v1",
        relationship_status="high_confidence_duplicate",
        relationship_confidence="0.86",
        price_gap="0.22",
        reference_market_id="ref1",
        reference_price="0.55",
        source="cross_market_discovery",
        evidence_level="cross_market_consistency",
        near_miss_tier="tier1_mispricing",
    )
    args = review.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    summary, diagnostics, _ = review.build_review(args)

    assert diagnostics[0]["edge_type"] == "cross_market_consistency_v1"
    assert diagnostics[0]["relationship_status"] == "high_confidence_duplicate"
    assert summary["edge_type_performance"]["cross_market_consistency_v1"]["trades"] == 1
    assert summary["relationship_status_performance"]["high_confidence_duplicate"]["trades"] == 1
    assert summary["price_gap_bucket_performance"]["0.10-0.25"]["trades"] == 1


def test_summary_json_format(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)

    rc = review.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])

    payload = json.loads((shadow_dir / "shadow_performance_review_summary.json").read_text())
    assert rc == 0
    assert "recommended_filter_adjustments" in payload
    assert payload["tiny_live_recommendation"] == "NO"


def test_diagnostics_csv_format(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)

    review.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])
    rows = list(csv.DictReader(open(shadow_dir / "shadow_trade_diagnostics.csv")))

    assert rows[0]["shadow_trade_id"] == "shadow_1"
    assert "diagnosis_flags" in rows[0]


def test_markdown_report_contains_tiny_live_no(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)

    review.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir)])
    text = (shadow_dir / "shadow_performance_review.md").read_text()

    assert "Tiny live recommendation: **NO**" in text
    assert "当前是否应该进入 tiny live" in text


def test_dry_run_does_not_write_files(tmp_path: Path):
    runs_dir, shadow_dir = setup_review_dir(tmp_path)

    rc = review.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--output_dir", str(shadow_dir), "--dry_run"])

    assert rc == 0
    assert not (shadow_dir / "shadow_performance_review.md").exists()
    assert not (shadow_dir / "shadow_performance_review_summary.json").exists()
    assert not (shadow_dir / "shadow_trade_diagnostics.csv").exists()


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/review_shadow_performance.py").read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")

    assert not any("live_trader" in name.lower() for name in imports)
    assert not any("paper_trader" in name.lower() for name in imports)
    assert not any("risk_governor" in name.lower() for name in imports)


def test_no_real_api_or_llm_flags():
    safety = review.verify_safety()

    assert safety["real_api_calls"] is False
    assert safety["llm_calls"] is False
    assert safety["run_paper_invoked"] is False


def test_live_trading_enabled_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
