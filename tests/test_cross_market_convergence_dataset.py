"""Tests for Trading MVP Step 9E cross-market convergence dataset analysis."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.analyze_cross_market_convergence_dataset as analyzer
import scripts.monitor_cross_market_convergence as monitor
from polysignal.shadow.cross_market_convergence import CrossMarketConvergenceObservation


def obs(
    market_id: str,
    gap: float,
    idx: int,
    *,
    group_id: str = "g1",
    ref: str = "r1",
    stale: bool = False,
) -> CrossMarketConvergenceObservation:
    return CrossMarketConvergenceObservation(
        timestamp=f"2026-05-15T00:0{idx}:00",
        group_id=group_id,
        market_id=market_id,
        reference_market_id=ref,
        question="Will Alice win?",
        reference_question="Will Alice win?",
        side="YES",
        entry_price=0.3,
        reference_price=0.5,
        price_gap=gap,
        spread=0.01,
        depth=5,
        liquidity=100,
        relationship_confidence=0.9,
        relationship_status="high_confidence_duplicate",
        observation_index=idx,
        stale=stale,
        error="stale_orderbook" if stale else "",
        run_id="test_run",
    )


def test_compute_gap_change_and_pct():
    row = analyzer.compute_pair_features([obs("m1", 0.4, 0), obs("m1", 0.2, 1)], min_observations=2)

    assert row["gap_change"] == -0.2
    assert row["gap_change_pct"] == -0.5


def test_compute_gap_volatility():
    row = analyzer.compute_pair_features([obs("m1", 0.4, 0), obs("m1", 0.2, 1), obs("m1", 0.3, 2)], min_observations=2)

    assert row["gap_volatility"] > 0


def test_compute_convergence_score():
    row = analyzer.compute_pair_features([obs("m1", 0.4, 0), obs("m1", 0.1, 1)], min_observations=2, min_convergence_score=0.5)

    assert round(row["convergence_score"], 6) == 0.75
    assert row["future_shadow_candidate"] is True


def test_detect_converging_pair():
    row = analyzer.compute_pair_features([obs("m1", 0.4, 0), obs("m1", 0.1, 1)], min_observations=2, min_convergence_score=0.5)

    assert row["convergence_status"] == "converging_gap"
    assert row["future_recommendation"] == "future_shadow_candidate"


def test_detect_non_converging_pair():
    row = analyzer.compute_pair_features([obs("m1", 0.4, 0), obs("m1", 0.39, 1)], min_observations=2, min_convergence_score=0.5)

    assert row["convergence_status"] == "weak_convergence"
    assert row["future_recommendation"] == "watch_only"


def test_detect_widening_pair():
    row = analyzer.compute_pair_features([obs("m1", 0.2, 0), obs("m1", 0.4, 1)], min_observations=2)

    assert row["convergence_status"] == "widening_gap"
    assert row["future_recommendation"] == "long_term_watch_or_reject"


def test_stable_gap_not_convergence():
    row = analyzer.compute_pair_features([obs("m1", 0.2, 0), obs("m1", 0.2, 1)], min_observations=2)

    assert row["convergence_status"] == "stable_gap"
    assert row["future_shadow_candidate"] is False


def test_insufficient_observations_watch_only():
    row = analyzer.compute_pair_features([obs("m1", 0.2, 0)], min_observations=5)

    assert row["convergence_status"] == "insufficient_observations"
    assert row["future_recommendation"] == "watch_only"


def test_output_summary_report_features(tmp_path: Path):
    features = [
        analyzer.compute_pair_features([obs("m1", 0.4, 0), obs("m1", 0.1, 1)], min_observations=2, min_convergence_score=0.5)
    ]
    summary = analyzer.build_summary(features, total_observations=2)

    analyzer.write_features_csv(tmp_path / "features.csv", features)
    analyzer.write_summary(tmp_path / "summary.json", summary)
    analyzer.write_report(tmp_path / "report.md", summary, features)

    assert list(csv.DictReader(open(tmp_path / "features.csv")))[0]["convergence_status"] == "converging_gap"
    assert json.loads((tmp_path / "summary.json").read_text())["tiny_live_recommendation"] == "NO"
    assert "Cross-Market Convergence Dataset Report" in (tmp_path / "report.md").read_text()


def test_dry_run_does_not_write(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    monitor.write_jsonl(runs / "cross_market_convergence_observations.jsonl", [obs("m1", 0.4, 0), obs("m1", 0.1, 1)])

    args = analyzer.parse_args(["--runs_dir", str(runs), "--output_dir", str(runs), "--dry_run"])
    features, summary = analyzer.analyze_dataset(args)

    assert features
    assert summary["tiny_live_recommendation"] == "NO"
    assert not (runs / "cross_market_convergence_features.csv").exists()


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/analyze_cross_market_convergence_dataset.py").read_text())
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
