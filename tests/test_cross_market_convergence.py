"""Tests for Trading MVP Step 9D cross-market convergence gating."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.monitor_cross_market_convergence as conv
import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.shadow.cross_market_convergence import CrossMarketConvergenceObservation


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
        "yes_token_id": "cyes",
        "no_token_id": "cno",
        "reference_yes_token_id": "ryes",
        "reference_no_token_id": "rno",
        "entry_price": "0.30",
        "reference_price": "0.50",
        "price_gap": "0.20",
        "expected_edge": "0.19",
        "confidence": "0.90",
        "relationship_confidence": "0.90",
        "relationship_status": "high_confidence_duplicate",
        "recommended_action": "shadow_entry",
        "yes_best_bid": "0.29",
        "yes_best_ask": "0.30",
        "no_best_bid": "0.69",
        "no_best_ask": "0.70",
        "entry_yes_best_bid": "0.29",
        "entry_yes_best_ask": "0.30",
        "entry_no_best_bid": "0.69",
        "entry_no_best_ask": "0.70",
        "spread": "0.01",
        "liquidity_score": "10",
        "orderbook_depth": "4",
        "combined_ask": "1.0",
        "source": "cross_market_discovery",
        "reasons": "cross_market_consistency_v1|same_event_duplicate|cross_market_price_gap|high_confidence_duplicate",
        "near_miss_tier": "tier1_mispricing",
        "evidence_level": "cross_market_consistency",
        "feedback_gate_status": "enabled",
        "gate_passed": "True",
    }
    row.update(overrides)
    return row


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def obs(market_id: str, gap: float, idx: int, stale: bool = False) -> CrossMarketConvergenceObservation:
    return CrossMarketConvergenceObservation(
        timestamp=f"t{idx}",
        group_id="g1",
        market_id=market_id,
        reference_market_id="m2",
        question="Q",
        reference_question="RQ",
        side="YES",
        entry_price=0.30,
        reference_price=0.50,
        price_gap=gap,
        spread=0.01,
        depth=4,
        liquidity=10,
        relationship_confidence=0.9,
        relationship_status="high_confidence_duplicate",
        observation_index=idx,
        stale=stale,
        error="stale_orderbook" if stale else "",
    )


def test_repeated_observations_can_be_loaded():
    payload = obs("m1", 0.2, 1).to_dict()
    loaded = CrossMarketConvergenceObservation.from_dict(payload)

    assert loaded.market_id == "m1"
    assert loaded.price_gap == 0.2


def test_convergence_score_calculation():
    metrics = conv.convergence_metrics([obs("m1", 0.4, 0), obs("m1", 0.3, 1), obs("m1", 0.2, 2)], 3, 0.5)

    assert metrics["convergence_score"] == 0.5
    assert metrics["gate_passed"] is True


def test_gap_shrinking_passes_gate():
    gated = conv.apply_convergence_gate([candidate()], [obs("m1", 0.4, 0), obs("m1", 0.3, 1), obs("m1", 0.1, 2)], 3, 0.5)

    assert gated[0]["recommended_action"] == "shadow_entry"
    assert gated[0]["convergence_gate_passed"] is True


def test_gap_widening_fails_gate():
    gated = conv.apply_convergence_gate([candidate()], [obs("m1", 0.2, 0), obs("m1", 0.25, 1), obs("m1", 0.3, 2)], 3, 0.5)

    assert gated[0]["recommended_action"] == "watch_only"
    assert gated[0]["convergence_reason"] == "price_gap_not_converging"


def test_flat_gap_stays_watch_only():
    gated = conv.apply_convergence_gate([candidate()], [obs("m1", 0.2, 0), obs("m1", 0.2, 1), obs("m1", 0.2, 2)], 3, 0.5)

    assert gated[0]["recommended_action"] == "watch_only"


def test_insufficient_observations_watch_only():
    gated = conv.apply_convergence_gate([candidate()], [obs("m1", 0.2, 0)], 3, 0.5)

    assert gated[0]["convergence_reason"] == "insufficient_convergence_observations"
    assert gated[0]["recommended_action"] == "watch_only"


def test_stale_reference_market_watch_only():
    gated = conv.apply_convergence_gate([candidate()], [obs("m1", 0.2, 0, stale=True), obs("m1", 0.1, 1, stale=True), obs("m1", 0.05, 2, stale=True)], 3, 0.5)

    assert gated[0]["convergence_reason"] == "insufficient_convergence_observations"
    assert gated[0]["recommended_action"] == "watch_only"


def test_convergence_passed_candidate_can_become_shadow_entry(tmp_path: Path):
    row = conv.apply_convergence_gate([candidate()], [obs("m1", 0.4, 0), obs("m1", 0.2, 1), obs("m1", 0.1, 2)], 3, 0.5)[0]
    runs_dir = tmp_path / "runs"
    write_rows(runs_dir / "cross_market_edge_candidates_convergence_gated.csv", [row])

    loaded = shadow_loop.load_candidates(runs_dir)
    result = shadow_loop.ShadowEntryFilter().evaluate(loaded[0])

    assert result.allowed


def test_non_converging_candidate_cannot_become_shadow_entry(tmp_path: Path):
    row = conv.apply_convergence_gate([candidate()], [obs("m1", 0.2, 0), obs("m1", 0.25, 1), obs("m1", 0.3, 2)], 3, 0.5)[0]
    runs_dir = tmp_path / "runs"
    write_rows(runs_dir / "cross_market_edge_candidates_convergence_gated.csv", [row])

    loaded = shadow_loop.load_candidates(runs_dir)
    result = shadow_loop.ShadowEntryFilter().evaluate(loaded[0])

    assert not result.allowed
    assert "price_gap_not_converging" in result.watch_reasons


def test_output_jsonl_csv_summary_report_format(tmp_path: Path):
    rows = conv.apply_convergence_gate([candidate()], [obs("m1", 0.4, 0), obs("m1", 0.2, 1), obs("m1", 0.1, 2)], 3, 0.5)
    observations = [obs("m1", 0.4, 0), obs("m1", 0.2, 1), obs("m1", 0.1, 2)]
    summary = conv.summary_from(__import__("datetime").datetime.utcnow(), [candidate()], observations, rows)
    out = tmp_path / "runs"

    conv.write_jsonl(out / "cross_market_convergence_observations.jsonl", observations)
    conv.write_csv(out / "cross_market_edge_candidates_convergence_gated.csv", rows)
    conv.write_json(out / "cross_market_edge_candidates_convergence_gated.json", rows)
    conv.write_summary(out / "cross_market_convergence_summary.json", summary)
    conv.write_report(out / "cross_market_convergence_report.md", summary)

    assert (out / "cross_market_convergence_observations.jsonl").read_text()
    assert list(csv.DictReader(open(out / "cross_market_edge_candidates_convergence_gated.csv")))[0]["convergence_status"]
    assert json.loads((out / "cross_market_edge_candidates_convergence_gated.json").read_text())["cross_market_edge_candidates_convergence_gated"]
    assert json.loads((out / "cross_market_convergence_summary.json").read_text())["tiny_live_recommendation"] == "NO"
    assert "Cross-Market Convergence Report" in (out / "cross_market_convergence_report.md").read_text()


def test_append_observations_preserves_existing_jsonl(tmp_path: Path):
    path = tmp_path / "runs" / "cross_market_convergence_observations.jsonl"
    conv.write_jsonl(path, [obs("m1", 0.3, 0)], append=True)
    conv.write_jsonl(path, [obs("m1", 0.2, 1)], append=True)

    loaded = conv.load_observations_jsonl(path)

    assert len(loaded) == 2
    assert [item.price_gap for item in loaded] == [0.3, 0.2]


def test_resume_dataset_uses_existing_observations(tmp_path: Path):
    path = tmp_path / "runs" / "cross_market_convergence_observations.jsonl"
    existing = [obs("m1", 0.4, 0), obs("m1", 0.2, 1)]
    conv.write_jsonl(path, existing, append=True)

    loaded = conv.load_observations_jsonl(path)
    gated = conv.apply_convergence_gate([candidate()], loaded + [obs("m1", 0.1, 2)], 3, 0.5)

    assert gated[0]["recommended_action"] == "shadow_entry"


def test_run_shadow_loop_prefers_convergence_gated_candidates(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    calibrated = candidate(market_id="raw")
    gated = conv.apply_convergence_gate([candidate(market_id="gated")], [obs("gated", 0.2, 0)], 3, 0.5)[0]
    write_rows(runs_dir / "cross_market_edge_candidates_calibrated.csv", [calibrated])
    write_rows(runs_dir / "cross_market_edge_candidates_convergence_gated.csv", [gated])

    loaded = shadow_loop.load_candidates(runs_dir)

    assert loaded[0].market_id == "gated"


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/monitor_cross_market_convergence.py").read_text())
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
