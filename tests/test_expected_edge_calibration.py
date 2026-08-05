"""Tests for Trading MVP expected edge v1 calibration."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.calibrate_expected_edge as edge
import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.shadow.entry_filter import EntryDecision, ShadowEntryFilter


def priced_row(**overrides):
    row = {
        "market_id": "m1",
        "question": "Will test happen?",
        "source": "watchlist",
        "combined_ask": "0.97",
        "yes_best_bid": "0.47",
        "yes_best_ask": "0.48",
        "no_best_bid": "0.48",
        "no_best_ask": "0.49",
        "yes_spread": "0.01",
        "no_spread": "0.01",
        "max_spread": "0.01",
        "spread": "0.01",
        "liquidity_score": "3",
        "liquidity_proxy": "20",
        "orderbook_depth": "3",
        "ambiguity_risk": "5",
        "near_miss_tier": "tier2_strong_near_miss",
        "tradable_score": "20",
        "entry_decision_hint": "watch_only",
        "reasons": "non_avoid_watchlist",
        "evidence_level": "strong",
        "alpha_score": "0",
        "is_avoid_candidate": "False",
    }
    row.update(overrides)
    return row


def write_priced(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_combined_ask_gap_calculation():
    row = edge.calibrate_row(priced_row(combined_ask="0.97"), spread_buffer=0.01, min_combined_ask_gap=0.005)

    assert round(row["combined_ask_gap"], 4) == 0.03


def test_executable_edge_formula():
    row = edge.calibrate_row(priced_row(combined_ask="0.97", max_spread="0.01"), 0.01, 0.005)

    assert round(row["executable_edge"], 4) == 0.01
    assert row["expected_edge"] == row["executable_edge"]


def test_combined_ask_at_or_above_one_fails_edge():
    row = edge.calibrate_row(priced_row(combined_ask="1.001"), 0.01, 0.005)

    assert row["edge_pass"] is False
    assert row["expected_edge_status"] == "combined_ask_not_below_one"


def test_spread_too_wide_fails_edge():
    row = edge.calibrate_row(priced_row(combined_ask="0.97", max_spread="0.04"), 0.01, 0.005)

    assert row["edge_pass"] is False
    assert row["expected_edge_status"] == "spread_too_wide"


def test_positive_executable_edge_passes():
    row = edge.calibrate_row(priced_row(combined_ask="0.96", max_spread="0.01"), 0.01, 0.005)

    assert row["edge_pass"] is True
    assert row["expected_edge_status"] == "edge_positive"


def test_control_group_only_defaults_watch_only_even_with_positive_edge():
    row = edge.calibrate_row(
        priced_row(source="control_group", near_miss_tier="", reasons="low_risk_control_group", evidence_level="control_group", combined_ask="0.96"),
        0.01,
        0.005,
    )
    result = ShadowEntryFilter().evaluate(shadow_loop.candidate_from_tradable(row, set()))

    assert row["edge_pass"] is False
    assert row["expected_edge_status"] == "control_group_only_watch"
    assert result.entry_decision == EntryDecision.WATCH_ONLY


def test_tier1_tier2_near_miss_with_edge_can_be_eligible():
    row = edge.calibrate_row(priced_row(near_miss_tier="tier1_mispricing", combined_ask="0.96"), 0.01, 0.005)
    result = ShadowEntryFilter().evaluate(shadow_loop.candidate_from_tradable(row, set()))

    assert row["edge_pass"] is True
    assert result.entry_decision == EntryDecision.ELIGIBLE_SHADOW_ENTRY


def test_tradable_score_only_cannot_be_eligible():
    row = edge.calibrate_row(
        priced_row(near_miss_tier="", reasons="", evidence_level="", tradable_score="99", combined_ask="0.96"),
        0.01,
        0.005,
    )
    result = ShadowEntryFilter().evaluate(shadow_loop.candidate_from_tradable(row, set()))

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "tradable_score_only_not_allowed" in result.watch_reasons


def test_alpha_score_only_cannot_be_eligible():
    candidate = shadow_loop.candidate_from_tradable(
        edge.calibrate_row(priced_row(alpha_score="99", reasons="", near_miss_tier="", combined_ask="0.96"), 0.01, 0.005),
        set(),
    )
    candidate.source = "alpha_score_only"
    result = ShadowEntryFilter().evaluate(candidate)

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "alpha_score_only_not_allowed" in result.reject_reasons


def test_expected_edge_cannot_bypass_quality_gates():
    row = edge.calibrate_row(priced_row(combined_ask="0.96", ambiguity_risk="99"), 0.01, 0.005)
    result = ShadowEntryFilter().evaluate(shadow_loop.candidate_from_tradable(row, set()))

    assert result.entry_decision == EntryDecision.REJECTED
    assert "high_ambiguity" in result.reject_reasons


def test_summary_json_format(tmp_path: Path):
    rows = [edge.calibrate_row(priced_row(), 0.01, 0.005)]
    summary = edge.summarize(rows)
    edge.write_summary(tmp_path / "summary.json", summary)

    payload = json.loads((tmp_path / "summary.json").read_text())
    assert "expected_edge_available_count" in payload
    assert "safety_verification" in payload
    assert payload["tiny_live_recommendation"] == "NO"


def test_script_writes_calibration_outputs(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_priced(runs_dir / "tradable_candidates_priced.csv", [priced_row()])

    rc = edge.main(["--runs_dir", str(runs_dir), "--output_dir", str(runs_dir)])

    assert rc == 0
    assert (runs_dir / "expected_edge_calibration_summary.json").exists()
    assert (runs_dir / "expected_edge_calibration_report.md").exists()
    assert "expected_edge" in list(csv.DictReader(open(runs_dir / "tradable_candidates_priced.csv")))[0]


def test_dry_run_does_not_write_outputs(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_priced(runs_dir / "tradable_candidates_priced.csv", [priced_row()])

    rc = edge.main(["--runs_dir", str(runs_dir), "--output_dir", str(runs_dir), "--dry_run"])

    assert rc == 0
    assert not (runs_dir / "expected_edge_calibration_summary.json").exists()


def test_no_forbidden_trading_imports():
    tree = ast.parse(Path("scripts/calibrate_expected_edge.py").read_text())
    forbidden = {"LiveTrader", "PaperTrader", "RiskGovernor"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)

    assert forbidden.isdisjoint(imported)


def test_live_trading_enabled_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
    assert risk["allow_auto_execution"] is False
    assert risk["paper_trading_enabled"] is True
