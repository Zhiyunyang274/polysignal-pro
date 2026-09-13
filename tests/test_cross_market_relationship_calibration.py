"""Tests for Trading MVP Step 9B cross-market relationship calibration."""

from __future__ import annotations
from datetime import timezone

import argparse
import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.calibrate_cross_market_relationships as rel
import scripts.run_shadow_paper_loop as shadow_loop


def args(tmp_path: Path, **overrides):
    payload = {
        "runs_dir": str(tmp_path / "runs"),
        "output_dir": str(tmp_path / "runs"),
        "min_price_gap": 0.05,
        "min_relationship_confidence": 0.75,
        "max_spread": 0.05,
        "min_depth": 1.0,
        "min_liquidity": 1.0,
        "dry_run": False,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def candidate(**overrides):
    row = {
        "edge_type": "cross_market_consistency_v1",
        "group_id": "g1",
        "relationship_type": "same_event_duplicate",
        "market_id": "m1",
        "question": "Will Alice win the 2026 election?",
        "reference_market_id": "m2",
        "reference_question": "Will Alice win the 2026 election?",
        "side": "YES",
        "price_gap": "0.20",
        "entry_price": "0.30",
        "expected_edge": "0.19",
        "spread": "0.01",
        "liquidity_score": "10",
        "orderbook_depth": "2",
        "recommended_action": "watch_only",
        "evidence": "cross_market_consistency_v1|same_event_duplicate|cross_market_price_gap",
        "reasons": "cross_market_consistency_v1|same_event_duplicate|cross_market_price_gap",
        "yes_token_id": "yes",
        "no_token_id": "no",
        "yes_best_ask": "0.30",
        "yes_best_bid": "0.29",
        "no_best_ask": "0.70",
        "no_best_bid": "0.69",
        "entry_yes_best_ask": "0.30",
        "entry_yes_best_bid": "0.29",
        "entry_no_best_ask": "0.70",
        "entry_no_best_bid": "0.69",
        "combined_ask": "1.0",
        "source": "cross_market_discovery",
        "feedback_gate_status": "enabled",
        "gate_passed": "True",
    }
    row.update(overrides)
    return row


def write_input(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_exact_duplicate_question_gives_high_confidence(tmp_path: Path):
    row = rel.calibrate_row(candidate(), args(tmp_path))

    assert row["relationship_status"] == "high_confidence_duplicate"
    assert row["relationship_confidence"] >= 0.75


def test_near_duplicate_with_shared_entity_date_gives_high_confidence(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(reference_question="Alice wins the 2026 election?"),
        args(tmp_path),
    )

    assert row["relationship_status"] == "high_confidence_duplicate"


def test_same_category_but_different_entity_gives_low_confidence(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(reference_question="Will Bob win the 2026 election?"),
        args(tmp_path),
    )

    assert row["relationship_status"] == "likely_false_match"
    assert row["recommended_action"] == "reject"


def test_conditional_wording_lowers_confidence(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(
            question="Will Alice win if Bob drops out?",
            reference_question="Will Alice win the 2026 election?",
        ),
        args(tmp_path),
    )

    assert row["conditional_language_penalty"] > 0
    assert row["relationship_status"] in {"ambiguous_relationship", "medium_confidence_related", "likely_false_match"}
    assert row["recommended_action"] != "shadow_entry"


def test_mutually_exclusive_defaults_watch_only(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(
            relationship_type="mutually_exclusive_group",
            question="Will Alice win the 2026 election?",
            reference_question="Will Bob win the 2026 election?",
        ),
        args(tmp_path),
    )

    assert row["relationship_status"] == "mutually_exclusive_watch"
    assert row["recommended_action"] == "watch_only"


def test_price_gap_alone_cannot_create_shadow_entry(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(
            question="Will Alice win the 2026 election?",
            reference_question="Will Bob win the 2026 election?",
            price_gap="0.90",
        ),
        args(tmp_path),
    )

    assert row["relationship_status"] == "likely_false_match"
    assert row["recommended_action"] == "reject"


def test_high_confidence_duplicate_plus_price_gap_can_shadow_entry(tmp_path: Path):
    row = rel.calibrate_row(candidate(price_gap="0.20"), args(tmp_path))

    assert row["relationship_status"] == "high_confidence_duplicate"
    assert row["recommended_action"] == "shadow_entry"
    assert row["near_miss_tier"] == "tier1_mispricing"


def test_ambiguous_stays_watch_only(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(
            relationship_type="near_duplicate",
            question="Will Alice win if Bob drops out?",
            reference_question="Will Alice win the 2026 election?",
            price_gap="0.20",
        ),
        args(tmp_path, min_relationship_confidence=0.9),
    )

    assert row["relationship_status"] == "ambiguous_relationship"
    assert row["recommended_action"] == "watch_only"


def test_likely_false_match_rejected(tmp_path: Path):
    row = rel.calibrate_row(
        candidate(question="Will Alice win?", reference_question="Will Ethereum hit $5,000?"),
        args(tmp_path),
    )

    assert row["relationship_status"] == "likely_false_match"
    assert row["recommended_action"] == "reject"


def test_output_csv_json_summary_report_format(tmp_path: Path):
    rows = [rel.calibrate_row(candidate(), args(tmp_path))]
    summary = rel.summarize(__import__("datetime").datetime.now(__import__("datetime").timezone.utc), rows)
    output = tmp_path / "runs"

    rel.write_csv(output / "cross_market_edge_candidates_calibrated.csv", rows, rel.FIELDS)
    rel.write_json(output / "cross_market_edge_candidates_calibrated.json", rows)
    rel.write_summary(output / "cross_market_relationship_calibration_summary.json", summary)
    rel.write_report(output / "cross_market_relationship_calibration_report.md", summary)

    assert list(csv.DictReader(open(output / "cross_market_edge_candidates_calibrated.csv")))[0]["relationship_status"]
    assert json.loads((output / "cross_market_edge_candidates_calibrated.json").read_text())["cross_market_edge_candidates_calibrated"]
    assert json.loads((output / "cross_market_relationship_calibration_summary.json").read_text())["tiny_live_recommendation"] == "NO"
    assert "Cross-Market Relationship Calibration Report" in (output / "cross_market_relationship_calibration_report.md").read_text()


def test_shadow_loop_prefers_calibrated_candidates(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    rows = [
        rel.calibrate_row(candidate(market_id="raw", question="Will Raw win?", reference_question="Will Raw win?"), args(tmp_path)),
    ]
    raw = candidate(market_id="raw_source", question="Will Raw Source win?", reference_question="Will Raw Source win?")
    write_input(runs_dir / "cross_market_edge_candidates.csv", [raw])
    rel.write_csv(runs_dir / "cross_market_edge_candidates_calibrated.csv", rows, rel.FIELDS)

    loaded = shadow_loop.load_candidates(runs_dir)

    assert loaded[0].market_id == "raw"


def test_shadow_entry_filter_reports_relationship_reasons(tmp_path: Path):
    mutex = rel.calibrate_row(
        candidate(
            relationship_type="mutually_exclusive_group",
            question="Will Alice win the 2026 election?",
            reference_question="Will Bob win the 2026 election?",
            combined_ask="0",
        ),
        args(tmp_path),
    )
    false_match = rel.calibrate_row(
        candidate(
            market_id="false",
            question="Will Alice win the 2026 election?",
            reference_question="Will Ethereum hit $5,000?",
            combined_ask="1.0",
        ),
        args(tmp_path),
    )
    runs_dir = tmp_path / "runs"
    rel.write_csv(runs_dir / "cross_market_edge_candidates_calibrated.csv", [mutex, false_match], rel.FIELDS)

    candidates = shadow_loop.load_candidates(runs_dir)
    results = [shadow_loop.ShadowEntryFilter().evaluate(candidate) for candidate in candidates]

    assert any("mutually_exclusive_watch" in result.watch_reasons for result in results)
    assert any("likely_false_match" in result.reject_reasons for result in results)


def test_only_high_confidence_shadow_entry_candidates_generate_trades(tmp_path: Path):
    high = rel.calibrate_row(candidate(market_id="high"), args(tmp_path))
    high.update({
        "convergence_gate_passed": "True",
        "convergence_score": "0.75",
        "convergence_status": "convergence_gate_passed",
        "convergence_reason": "convergence_gate_passed",
        "convergence_observation_count": "3",
        "initial_price_gap": "0.20",
        "final_price_gap": "0.05",
        "gap_change": "-0.15",
        "reasons": f"{high.get('reasons')}|cross_market_convergence_observed|convergence_gate_passed",
    })
    mutex = rel.calibrate_row(
        candidate(
            market_id="mutex",
            relationship_type="mutually_exclusive_group",
            question="Will Alice win the 2026 election?",
            reference_question="Will Bob win the 2026 election?",
        ),
        args(tmp_path),
    )
    false_match = rel.calibrate_row(
        candidate(
            market_id="false",
            question="Will Alice win the 2026 election?",
            reference_question="Will Ethereum hit $5,000?",
        ),
        args(tmp_path),
    )
    runs_dir = tmp_path / "runs"
    write_input(runs_dir / "cross_market_edge_candidates_convergence_gated.csv", [high, mutex, false_match])

    candidates = shadow_loop.load_candidates(runs_dir)
    trades = shadow_loop.build_shadow_trades(
        candidates,
        shadow_loop.EntryFilterConfig(),
        shadow_loop.ExitRuleConfig(),
    )

    assert len(trades) == 1
    assert trades[0].market_id == "high"
    assert trades[0].relationship_status == "high_confidence_duplicate"
    assert trades[0].entry_price == float(high["yes_best_ask"])
    assert trades[0].entry_price != float(high["combined_ask"])


def test_dry_run_does_not_write_files(tmp_path: Path, monkeypatch):
    input_path = tmp_path / "runs" / "cross_market_edge_candidates.csv"
    write_input(input_path, [candidate()])

    rc = rel.main(["--runs_dir", str(tmp_path / "runs"), "--output_dir", str(tmp_path / "runs"), "--dry_run"])

    assert rc == 0
    assert not (tmp_path / "runs" / "cross_market_edge_candidates_calibrated.csv").exists()


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/calibrate_cross_market_relationships.py").read_text())
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
