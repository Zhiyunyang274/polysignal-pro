"""Tests for Trading MVP Step 4A multi-edge discovery."""

from __future__ import annotations

import argparse
import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.discover_multi_edge_candidates as multi
import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.shadow.edge_candidates import EdgeAction, EdgeCandidate, EdgeType


class FakeGammaClient:
    def __init__(self, markets=None, error: Exception = None):
        self.markets = markets or []
        self.error = error

    async def fetch_active_markets(self, limit: int):
        if self.error:
            raise self.error
        return self.markets[:limit]


class FakeCLOBClient:
    def __init__(self, yes_book=None, no_book=None, error: Exception = None):
        self.yes_book = yes_book
        self.no_book = no_book
        self.error = error
        self.calls = 0
        self.closed = False

    async def get_market_orderbook(self, yes_token_id: str, no_token_id: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.yes_book, self.no_book

    async def close(self):
        self.closed = True


def market(**overrides):
    payload = {
        "id": "m1",
        "question": "Will test happen?",
        "active": True,
        "closed": False,
        "resolved": False,
        "volume": "5000",
        "category": "Sports",
        "clobTokenIds": '["yes1","no1"]',
        "outcomes": '["Yes","No"]',
    }
    payload.update(overrides)
    return payload


def orderbook(
    asset_id: str,
    bid: float = 0.45,
    ask: float = 0.47,
    bid_size: float = 20.0,
    ask_size: float = 10.0,
) -> CLOBOrderbook:
    return CLOBOrderbook(
        asset_id=asset_id,
        bids=[{"price": str(bid), "size": str(bid_size)}],
        asks=[{"price": str(ask), "size": str(ask_size)}],
    )


def args(tmp_path: Path, **overrides):
    payload = {
        "max_markets": 500,
        "min_volume": 1000.0,
        "spread_buffer": 0.01,
        "min_expected_edge": 0.001,
        "min_confidence": 0.6,
        "min_depth": 1.0,
        "max_api_errors": 50,
        "output_dir": str(tmp_path / "runs"),
        "edge_version": "both",
        "output_suffix": "",
        "dry_run": False,
        "data_mode": "real_readonly",
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_edge_candidate_serialization():
    candidate = EdgeCandidate(
        edge_type=EdgeType.PRICE_DISLOCATION_PROBABILITY_V1,
        market_id="m1",
        question="Q?",
        side="YES",
        yes_token_id="yes1",
        no_token_id="no1",
        entry_price=0.47,
        estimated_probability=0.49,
        expected_edge=0.01,
        confidence=0.8,
        liquidity_score=10,
        depth=2,
        spread=0.01,
        risk_flags=["none"],
        evidence=["probability_edge_v1"],
        recommended_action=EdgeAction.WATCH_ONLY,
    )

    restored = EdgeCandidate.from_dict(candidate.to_dict())

    assert restored.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V1
    assert restored.evidence == ["probability_edge_v1"]


def test_combined_ask_arbitrage_edge_calculation():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.47))
    no = multi.book_features(orderbook("no1", 0.44, 0.46))

    candidate = multi.combined_ask_arbitrage_edge(market(), multi.TokenPair("yes1", "no1"), yes, no, args(Path(".")), "t", [])

    assert candidate.edge_type == EdgeType.COMBINED_ASK_ARBITRAGE
    assert round(candidate.combined_ask, 4) == 0.93
    assert round(candidate.expected_edge, 4) == 0.04


def test_combined_ask_above_one_not_shadow_entry():
    yes = multi.book_features(orderbook("yes1", 0.49, 0.51))
    no = multi.book_features(orderbook("no1", 0.48, 0.50))

    candidate = multi.combined_ask_arbitrage_edge(market(), multi.TokenPair("yes1", "no1"), yes, no, args(Path(".")), "t", [])

    assert candidate.recommended_action != EdgeAction.SHADOW_ENTRY
    assert candidate.expected_edge < 0


def test_probability_edge_estimated_probability():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    candidate = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])

    assert candidate.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V1
    assert candidate.estimated_probability > yes["mid"]


def test_probability_edge_expected_edge_calculation():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    candidate = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])

    expected = candidate.estimated_probability - candidate.entry_price - 0.01
    assert round(candidate.expected_edge, 6) == round(expected, 6)


def test_confidence_changes_with_spread_and_depth():
    low = multi.confidence_score(spread=0.08, depth=1, liquidity=1, min_depth=1)
    high = multi.confidence_score(spread=0.005, depth=10, liquidity=100, min_depth=1)

    assert high > low


def test_expected_edge_insufficient_watch_only():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.47, bid_size=2, ask_size=100))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    candidate = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])

    assert candidate.recommended_action == EdgeAction.WATCH_ONLY


def test_confidence_insufficient_watch_only():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    candidate = multi.probability_edge_for_side(
        market(),
        multi.TokenPair("yes1", "no1"),
        yes,
        no,
        "YES",
        args(Path("."), min_confidence=0.99),
        "t",
        [],
    )

    assert candidate.expected_edge > 0
    assert candidate.recommended_action == EdgeAction.WATCH_ONLY


def test_edge_positive_confidence_quality_shadow_entry():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    candidate = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])

    assert candidate.expected_edge > 0
    assert candidate.confidence >= 0.6
    assert candidate.recommended_action == EdgeAction.SHADOW_ENTRY


def test_probability_v2_adjustment_more_conservative_than_v1():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    v1 = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])
    v2 = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])

    assert v2.edge_type == EdgeType.PRICE_DISLOCATION_PROBABILITY_V2
    assert abs(v2.probability_adjustment) < abs(v1.estimated_probability - yes["mid"])
    assert v2.calibrated_expected_edge <= v1.expected_edge
    assert v2.calibration_version == "probability_edge_v2"


def test_probability_v2_wide_spread_lowers_confidence():
    narrow = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    wide = multi.book_features(orderbook("yes1", 0.40, 0.50, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    narrow_candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), narrow, no, "YES", args(Path(".")), "t", [])
    wide_candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), wide, no, "YES", args(Path(".")), "t", [])

    assert wide_candidate.confidence < narrow_candidate.confidence
    assert wide_candidate.adverse_selection_penalty > narrow_candidate.adverse_selection_penalty


def test_probability_v2_shallow_depth_lowers_confidence():
    deep = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    shallow = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=1, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    deep_candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), deep, no, "YES", args(Path(".")), "t", [])
    shallow_candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), shallow, no, "YES", args(Path(".")), "t", [])

    assert shallow_candidate.confidence < deep_candidate.confidence
    assert shallow_candidate.liquidity_penalty >= deep_candidate.liquidity_penalty


def test_probability_v2_weak_bid_lowers_expected_edge():
    strong_bid = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    weak_bid = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=0.1, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    strong = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), strong_bid, no, "YES", args(Path(".")), "t", [])
    weak = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), weak_bid, no, "YES", args(Path(".")), "t", [])

    assert weak.exit_bid_penalty > strong.exit_bid_penalty
    assert weak.calibrated_expected_edge < strong.calibrated_expected_edge


def test_probability_v2_calibrated_edge_not_above_raw_expected_edge():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))

    candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])
    raw_expected_edge = candidate.raw_estimated_probability + candidate.probability_adjustment - candidate.entry_price - 0.01

    assert candidate.calibrated_expected_edge <= raw_expected_edge
    assert candidate.expected_edge == candidate.calibrated_expected_edge


def test_probability_v2_fewer_shadow_entries_than_v1_on_same_mock():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))
    parsed_args = args(Path("."), min_confidence=0.6)

    v1 = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", parsed_args, "t", [])
    v2 = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", parsed_args, "t", [])

    assert v1.recommended_action == EdgeAction.SHADOW_ENTRY
    assert v2.recommended_action != EdgeAction.SHADOW_ENTRY


def test_probability_v2_strong_edge_can_still_shadow_entry():
    yes = multi.book_features(orderbook("yes1", 0.20, 0.201, bid_size=500, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.798, 0.799, bid_size=500, ask_size=1))

    candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path("."), min_confidence=0.5), "t", [])

    assert candidate.calibrated_expected_edge > 0
    assert candidate.recommended_action == EdgeAction.SHADOW_ENTRY


def test_probability_v2_missing_entry_ask_not_shadow_entry():
    yes = multi.book_features(orderbook("yes1", 0.20, 0.201, bid_size=500, ask_size=1))
    no = multi.book_features(CLOBOrderbook(asset_id="no1", bids=[{"price": "0.99", "size": "500"}], asks=[]))

    candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "NO", args(Path("."), min_confidence=0.5), "t", [])

    assert candidate.entry_price == 0
    assert candidate.recommended_action == EdgeAction.REJECT
    assert "missing_entry_ask" in candidate.evidence


def test_probability_v2_outputs_calibration_fields():
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))
    candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(Path(".")), "t", [])
    row = multi.candidate_to_output(candidate)

    assert row["raw_estimated_probability"] > 0
    assert row["calibrated_estimated_probability"] > 0
    assert row["exit_bid_penalty"] >= 0
    assert row["adverse_selection_penalty"] >= 0
    assert row["liquidity_penalty"] >= 0
    assert row["calibrated_expected_edge"] == candidate.calibrated_expected_edge


def test_alpha_tradable_llm_do_not_participate_in_expected_edge():
    source = Path("scripts/discover_multi_edge_candidates.py").read_text()

    assert "alpha_score" not in source
    assert "safe_float(row.get(\"tradable_score\"" not in source
    assert "LLM provider" not in source


def test_output_csv_json_summary_format(tmp_path: Path):
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))
    candidate = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(tmp_path), "t", [])
    rows = multi.output_rows([candidate])
    summary = multi.summarize(__import__("datetime").datetime.utcnow(), [market()], 1, 2, [candidate], 0, [])

    multi.write_csv(tmp_path / "multi_edge_candidates.csv", rows)
    multi.write_json(tmp_path / "multi_edge_candidates.json", rows)
    multi.write_summary(tmp_path / "multi_edge_discovery_summary.json", summary)
    multi.write_report(tmp_path / "multi_edge_discovery_report.md", summary)

    assert list(csv.DictReader(open(tmp_path / "multi_edge_candidates.csv")))[0]["edge_type"]
    assert json.loads((tmp_path / "multi_edge_candidates.json").read_text())["multi_edge_candidates"]
    assert json.loads((tmp_path / "multi_edge_discovery_summary.json").read_text())["tiny_live_recommendation"] == "NO"
    assert "Multi-Edge Discovery Report" in (tmp_path / "multi_edge_discovery_report.md").read_text()


def test_discovery_feedback_gate_forces_probability_watch_only(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "edge_feedback_calibration_summary.json").write_text(json.dumps({
        "edge_types_analyzed": ["price_dislocation_probability_v2"],
        "trades_analyzed": 10,
        "overall_win_rate": 0.1,
        "overall_average_return": -0.24,
        "expected_edge_realized_return_correlation": -0.17,
        "confidence_win_correlation": -0.01,
        "false_positive_count": 9,
        "high_confidence_loss_count": 9,
        "edge_type_performance": {
            "price_dislocation_probability_v2": {
                "trades": 10,
                "closed_trades": 10,
                "win_rate": 0.1,
                "average_return": -0.24,
            }
        },
    }))
    yes = multi.book_features(orderbook("yes1", 0.20, 0.201, bid_size=500, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.798, 0.799, bid_size=500, ask_size=1))
    candidate = multi.probability_edge_v2_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(tmp_path, output_dir=str(runs_dir), min_confidence=0.5), "t", [])

    gates = multi.build_feedback_gates(runs_dir)
    multi.apply_feedback_gates([candidate], gates)

    assert candidate.feedback_gate_status == "quarantined"
    assert candidate.recommended_action == EdgeAction.WATCH_ONLY
    assert "feedback_gate_failed" in candidate.evidence
    assert "edge_type_quarantined" in candidate.evidence


def test_combined_ask_edge_not_changed_by_probability_feedback_gate(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "edge_feedback_calibration_summary.json").write_text(json.dumps({
        "trades_analyzed": 10,
        "overall_average_return": -1,
        "expected_edge_realized_return_correlation": -1,
        "confidence_win_correlation": -1,
    }))
    yes = multi.book_features(orderbook("yes1", 0.45, 0.47))
    no = multi.book_features(orderbook("no1", 0.44, 0.46))
    candidate = multi.combined_ask_arbitrage_edge(market(), multi.TokenPair("yes1", "no1"), yes, no, args(tmp_path), "t", [])
    before = candidate.recommended_action

    multi.apply_feedback_gates([candidate], multi.build_feedback_gates(runs_dir))

    assert candidate.recommended_action == before
    assert candidate.feedback_gate_status == "enabled"


def test_dry_run_does_not_write_files(tmp_path: Path, monkeypatch):
    async def fake_run_async(parsed_args):
        return [], {
            "ended_at": "t",
            "markets_scanned": 1,
            "active_markets_available": 1,
            "orderbooks_fetched": 0,
            "combined_ask_arbitrage_count": 0,
            "probability_edge_count": 0,
            "probability_edge_v2_count": 0,
            "v1_shadow_entry_candidates": 0,
            "v2_shadow_entry_candidates": 0,
            "v2_watch_only_candidates": 0,
            "v2_rejected_candidates": 0,
            "shadow_entry_candidates": 0,
            "watch_only_candidates": 0,
            "rejected_candidates": 0,
            "avg_expected_edge": 0,
            "avg_raw_expected_edge": 0,
            "avg_calibrated_expected_edge": 0,
            "max_expected_edge": 0,
            "avg_confidence": 0,
            "exit_bid_penalty_avg": 0,
            "adverse_selection_penalty_avg": 0,
            "liquidity_penalty_avg": 0,
            "api_error_count": 0,
            "edge_type_counts": {},
            "tiny_live_recommendation": "NO",
            "safety_verification": {},
        }

    monkeypatch.setattr(multi, "run_async", fake_run_async)

    rc = multi.main(["--dry_run", "--output_dir", str(tmp_path)])

    assert rc == 0
    assert not (tmp_path / "multi_edge_candidates.csv").exists()


def test_shadow_loop_prefers_multi_edge_shadow_entries(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    yes = multi.book_features(orderbook("yes1", 0.45, 0.46, bid_size=100, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.53, 0.54))
    shadow_candidate = multi.probability_edge_for_side(market(), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(tmp_path), "t", [])
    watch_candidate = multi.probability_edge_for_side(market(id="m2"), multi.TokenPair("yes2", "no2"), yes, no, "NO", args(tmp_path, min_confidence=0.99), "t", [])
    multi.write_csv(runs_dir / "multi_edge_candidates.csv", multi.output_rows([shadow_candidate, watch_candidate]))

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].market_id == "m1"
    assert candidates[0].expected_edge > 0
    assert candidates[0].edge_type == "price_dislocation_probability_v1"
    assert candidates[0].confidence > 0
    assert "microstructure_probability_edge" in candidates[0].evidence


def test_shadow_loop_prefers_v2_multi_edge_file(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    yes = multi.book_features(orderbook("yes1", 0.20, 0.201, bid_size=500, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.798, 0.799, bid_size=500, ask_size=1))
    v1_candidate = multi.probability_edge_for_side(market(id="v1"), multi.TokenPair("yes1", "no1"), yes, no, "YES", args(tmp_path), "t", [])
    v2_candidate = multi.probability_edge_v2_for_side(market(id="v2"), multi.TokenPair("yes2", "no2"), yes, no, "YES", args(tmp_path, min_confidence=0.5), "t", [])
    multi.write_csv(runs_dir / "multi_edge_candidates.csv", multi.output_rows([v1_candidate]))
    multi.write_csv(runs_dir / "multi_edge_candidates_v2.csv", multi.output_rows([v2_candidate]))

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].market_id == "v2"
    assert candidates[0].edge_type == "price_dislocation_probability_v2"


def test_shadow_loop_prefers_gated_multi_edge_file_and_keeps_watch_rows(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    yes = multi.book_features(orderbook("yes1", 0.20, 0.201, bid_size=500, ask_size=1))
    no = multi.book_features(orderbook("no1", 0.798, 0.799, bid_size=500, ask_size=1))
    gated = multi.probability_edge_v2_for_side(market(id="gated"), multi.TokenPair("yes2", "no2"), yes, no, "YES", args(tmp_path, min_confidence=0.5), "t", [])
    gated.recommended_action = EdgeAction.WATCH_ONLY
    gated.feedback_gate_status = "quarantined"
    gated.feedback_gate_reason = "expected_edge_negative_correlation|confidence_not_predictive"
    gated.gate_passed = False
    fallback = multi.probability_edge_v2_for_side(market(id="fallback"), multi.TokenPair("yes3", "no3"), yes, no, "YES", args(tmp_path, min_confidence=0.5), "t", [])
    multi.write_csv(runs_dir / "multi_edge_candidates_v2.csv", multi.output_rows([fallback]))
    multi.write_csv(runs_dir / "multi_edge_candidates_gated.csv", multi.output_rows([gated]))

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].market_id == "gated"
    assert candidates[0].feedback_gate_status == "quarantined"
    assert candidates[0].gate_passed is False


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/discover_multi_edge_candidates.py").read_text())
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
