"""Tests for Phase 8C tradable candidate pool construction."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.build_tradable_candidates as build_script
import scripts.run_shadow_paper_loop as shadow_script
from polysignal.shadow.tradable_candidates import (
    TRADABLE_SCORE_DISCLAIMER,
    TradableCandidate,
    TradableCandidateBuilder,
    TradableCandidateBuilderConfig,
    TradableCandidateScorer,
)


def watchlist_row(**overrides):
    row = {
        "market_id": "m_watch",
        "question": "Watchlist market?",
        "category": "Sports",
        "appearances": "3",
        "avg_combined_ask": "1.01",
        "avg_ambiguity_risk": "10",
        "near_miss_tier_mode": "tier2",
        "evidence_level": "moderate",
        "run_ids": "run_a",
    }
    row.update(overrides)
    return row


def alpha_row(**overrides):
    row = {
        "market_id": "m_alpha",
        "question": "Alpha market?",
        "category": "Politics",
        "appearances": "3",
        "avg_combined_ask": "1.01",
        "avg_ambiguity_risk": "10",
        "avg_volume": "3",
        "alpha_score": "45",
        "evidence_level": "moderate",
        "run_ids": "run_a",
    }
    row.update(overrides)
    return row


def avoid_row(market_id="m_bad"):
    return {"market_id": market_id, "question": "Avoid?", "reasons": "high_ambiguity"}


def build_pool(
    watchlist_rows=None,
    alpha_rows=None,
    avoid_rows=None,
    trajectory_items=None,
    control_group_rows=None,
    config=None,
):
    builder = TradableCandidateBuilder(config or TradableCandidateBuilderConfig())
    candidates = builder.build(
        watchlist_rows=watchlist_rows or [],
        alpha_rows=alpha_rows or [],
        avoid_rows=avoid_rows or [],
        trajectory_items=trajectory_items or [],
        control_group_rows=control_group_rows or [],
    )
    return candidates, builder


def test_avoid_candidates_excluded():
    candidates, builder = build_pool(
        watchlist_rows=[watchlist_row(market_id="m_bad")],
        avoid_rows=[avoid_row("m_bad")],
    )

    assert candidates == []
    assert builder.exclusion_summary["avoid_candidate"] == 1


def test_non_avoid_watchlist_market_enters_candidate_pool():
    candidates, _ = build_pool(watchlist_rows=[watchlist_row()])

    assert len(candidates) == 1
    assert candidates[0].market_id == "m_watch"
    assert "non_avoid_watchlist" in candidates[0].reasons


def test_tier1_tier2_near_miss_can_enter():
    candidates, _ = build_pool(watchlist_rows=[
        watchlist_row(market_id="m1", near_miss_tier_mode="tier1"),
        watchlist_row(market_id="m2", near_miss_tier_mode="tier2"),
    ])

    assert {candidate.near_miss_tier for candidate in candidates} == {
        "tier1_mispricing",
        "tier2_strong_near_miss",
    }


def test_tier3_improving_market_marked_watch_only():
    trajectory = {
        "market_id": "m_t3",
        "question": "Tier 3?",
        "category": "Sports",
        "trajectory": [
            {"combined_ask": 1.02, "ambiguity_risk": 10, "near_miss_tier": "tier3"},
            {"combined_ask": 1.01, "ambiguity_risk": 10, "near_miss_tier": "tier3"},
        ],
    }
    candidates, _ = build_pool(trajectory_items=[trajectory])

    assert len(candidates) == 1
    assert candidates[0].entry_decision_hint == "watch_only"
    assert "tier3_improving_watch_only" in candidates[0].reasons


def test_high_ambiguity_excluded():
    candidates, builder = build_pool(watchlist_rows=[watchlist_row(avg_ambiguity_risk="50")])

    assert candidates == []
    assert builder.exclusion_summary["high_ambiguity"] == 1


def test_low_liquidity_excluded():
    candidates, builder = build_pool(watchlist_rows=[watchlist_row(appearances="0")])

    assert candidates == []
    assert builder.exclusion_summary["low_liquidity"] == 1


def test_missing_combined_ask_excluded():
    candidates, builder = build_pool(watchlist_rows=[watchlist_row(avg_combined_ask="")])

    assert candidates == []
    assert builder.exclusion_summary["missing_combined_ask"] == 1


def test_score_components_correct():
    scorer = TradableCandidateScorer()
    candidate = scorer.score(TradableCandidate(
        market_id="m1",
        question="Question?",
        combined_ask=1.01,
        ambiguity_risk=10,
        liquidity_score=2,
        spread=0.01,
        orderbook_depth=2,
        near_miss_tier="tier2_strong_near_miss",
        appearances=3,
        evidence_level="moderate",
    ))

    assert candidate.near_miss_score == 25.0
    assert candidate.liquidity_score_component == 10.0
    assert candidate.ambiguity_penalty == 5.0
    assert candidate.spread_penalty == 1.0
    assert candidate.tradable_score == 43.0


def test_tradable_score_sorting():
    candidates, _ = build_pool(watchlist_rows=[
        watchlist_row(market_id="m_low", near_miss_tier_mode="tier3", evidence_level="weak"),
        watchlist_row(market_id="m_high", near_miss_tier_mode="tier1", evidence_level="strong"),
    ])

    assert candidates[0].market_id == "m_high"


def test_csv_output_format(tmp_path: Path):
    candidate = TradableCandidate(market_id="m1", question="Question?", reasons=["reason"])
    path = tmp_path / "tradable_candidates.csv"

    build_script.write_candidates_csv(path, [candidate])
    text = path.read_text()

    assert "market_id,question,category,source" in text
    assert "tradable_score" in text


def test_json_output_format(tmp_path: Path):
    candidate = TradableCandidate(market_id="m1", question="Question?", reasons=["reason"])
    path = tmp_path / "tradable_candidates.json"

    build_script.write_candidates_json(path, [candidate], {"generated_at": "now"})
    payload = json.loads(path.read_text())

    assert payload["disclaimer"] == TRADABLE_SCORE_DISCLAIMER
    assert payload["tradable_candidates"][0]["market_id"] == "m1"


def test_markdown_report_contains_exclusion_summary(tmp_path: Path):
    path = tmp_path / "tradable_candidate_report.md"

    build_script.write_report(path, [], {
        "generated_at": "now",
        "candidates_considered": 1,
        "tradable_candidates": 0,
        "excluded_avoid_candidates": 1,
        "exclusion_summary": {"avoid_candidate": 1},
    })
    text = path.read_text()

    assert "Exclusion Summary" in text
    assert "avoid_candidate: 1" in text
    assert TRADABLE_SCORE_DISCLAIMER in text


def test_alpha_candidate_if_avoid_must_be_excluded():
    candidates, builder = build_pool(
        alpha_rows=[alpha_row(market_id="m_alpha")],
        avoid_rows=[avoid_row("m_alpha")],
    )

    assert candidates == []
    assert builder.exclusion_summary["avoid_candidate"] == 1


def test_alpha_score_only_not_tradable_reason():
    candidates, _ = build_pool(alpha_rows=[alpha_row()])

    assert len(candidates) == 1
    assert "alpha_score" not in "|".join(candidates[0].reasons)
    assert "alpha_quality_passed" in candidates[0].reasons


def test_run_shadow_loop_prefers_tradable_candidates_csv(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    with open(runs_dir / "tradable_candidates.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=build_script.TRADABLE_CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerow({
            "market_id": "m_trade",
            "question": "Tradable?",
            "source": "control_group",
            "combined_ask": "1.01",
            "ambiguity_risk": "10",
            "liquidity_score": "2",
            "spread": "0.01",
            "orderbook_depth": "2",
            "near_miss_tier": "tier2_strong_near_miss",
            "entry_decision_hint": "eligible_shadow_entry",
            "tradable_score": "20",
            "evidence_level": "control_group",
            "reasons": "low_risk_control_group",
        })
    (runs_dir / "alpha_candidates.csv").write_text(
        "market_id,question,category,appearances,avg_combined_ask,avg_ambiguity_risk,alpha_score,run_ids\n"
        "m_alpha,Alpha?,Sports,3,1.01,10,40,run_a\n"
    )

    candidates = shadow_script.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].market_id == "m_trade"
    assert candidates[0].source == "tradable_candidate"
    assert candidates[0].tradable_source == "control_group"
    assert candidates[0].tradable_score == 20
    assert candidates[0].tradable_reasons == ["low_risk_control_group"]
    assert candidates[0].evidence_level == "control_group"


def test_shadow_dry_run_tradable_diagnostics_not_missing_alpha(tmp_path: Path, capsys):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    with open(runs_dir / "tradable_candidates.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=build_script.TRADABLE_CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerow({
            "market_id": "m_trade",
            "question": "Tradable?",
            "source": "control_group",
            "combined_ask": "1.01",
            "ambiguity_risk": "10",
            "liquidity_score": "1",
            "spread": "0.01",
            "orderbook_depth": "1",
            "near_miss_tier": "",
            "entry_decision_hint": "watch_only",
            "tradable_score": "4",
            "evidence_level": "control_group",
            "reasons": "low_risk_control_group",
        })

    rc = shadow_script.main([
        "--runs_dir",
        str(runs_dir),
        "--output_dir",
        str(tmp_path / "shadow"),
        "--dry_run",
        "--diagnostics",
    ])
    output = capsys.readouterr().out

    assert rc == 0
    assert "missing_alpha_score_but_not_required" in output
    assert "top_rejection_reasons: {'missing_alpha_score'" not in output


def test_run_shadow_loop_fallback_logic_retained(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "alpha_candidates.csv").write_text(
        "market_id,question,category,appearances,avg_combined_ask,avg_ambiguity_risk,alpha_score,run_ids\n"
        "m_alpha,Alpha?,Sports,3,1.01,10,40,run_a\n"
    )

    candidates = shadow_script.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].market_id == "m_alpha"
    assert candidates[0].source == "alpha_candidate"


def test_no_forbidden_trading_imports():
    files = [
        Path("polysignal/shadow/tradable_candidates.py"),
        Path("scripts/build_tradable_candidates.py"),
        Path("scripts/run_shadow_paper_loop.py"),
    ]
    forbidden = {"LiveTrader", "PaperTrader", "RiskGovernor"}

    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[-1] not in forbidden
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not any(name in node.module for name in forbidden)
                for alias in node.names:
                    assert alias.name not in forbidden


def test_live_trading_enabled_still_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
