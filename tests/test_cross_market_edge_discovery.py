"""Tests for Trading MVP Step 9A cross-market consistency edge discovery."""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import json
from pathlib import Path

import yaml

import scripts.discover_cross_market_edges as cross
import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.ingestion.api_types import CLOBOrderbook


class FakeGammaClient:
    def __init__(self, markets=None, error: Exception = None):
        self.markets = markets or []
        self.error = error
        self.calls = 0

    async def fetch_active_markets(self, limit: int):
        self.calls += 1
        if self.error:
            raise self.error
        return self.markets[:limit]


class FakeCLOBClient:
    def __init__(self, books=None, error: Exception = None):
        self.books = books or {}
        self.error = error
        self.calls = 0
        self.closed = False

    async def get_market_orderbook(self, yes_token_id: str, no_token_id: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.books.get(yes_token_id), self.books.get(no_token_id)

    async def close(self):
        self.closed = True


def market(**overrides):
    payload = {
        "id": "m1",
        "question": "Will Team A win the 2026 championship?",
        "slug": "team-a-win-2026-championship",
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


def orderbook(asset_id: str, bid: float, ask: float, size: float = 10.0) -> CLOBOrderbook:
    return CLOBOrderbook(
        asset_id=asset_id,
        bids=[{"price": str(bid), "size": str(size)}],
        asks=[{"price": str(ask), "size": str(size)}],
    )


def args(tmp_path: Path, **overrides):
    payload = {
        "max_markets": 1000,
        "min_volume": 1000.0,
        "min_price_gap": 0.05,
        "max_group_size": 20,
        "dry_run": False,
        "output_dir": str(tmp_path / "runs"),
        "data_mode": "real_readonly",
        "max_api_errors": 20,
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_normalized_question_grouping():
    q1 = "Will Team A win the 2026 championship?"
    q2 = "Team A: win the 2026 championship!"

    assert cross.jaccard(cross.question_tokens(q1), cross.question_tokens(q2)) > 0.8


def test_near_duplicate_detection():
    markets = [
        market(id="m1", slug="", question="Will Team A win the 2026 championship?"),
        market(id="m2", slug="", question="Will Team A win 2026 championship?"),
    ]

    groups = cross.detect_related_groups(markets, 20)

    assert any(group["relationship_type"] in {"same_event_duplicate", "near_duplicate"} for group in groups)


def test_price_gap_calculation():
    group = {"group_id": "g1", "relationship_type": "same_event_duplicate", "confidence": 0.9}
    cheap = cross.PricedMarket(
        market(id="cheap", question="Will Team A win?", clobTokenIds='["yes_c","no_c"]'),
        cross.TokenPair("yes_c", "no_c"),
        cross.price_levels(orderbook("yes_c", 0.40, 0.42)),
        cross.price_levels(orderbook("no_c", 0.56, 0.58)),
    )
    rich = cross.PricedMarket(
        market(id="rich", question="Will Team A win?", clobTokenIds='["yes_r","no_r"]'),
        cross.TokenPair("yes_r", "no_r"),
        cross.price_levels(orderbook("yes_r", 0.55, 0.57)),
        cross.price_levels(orderbook("no_r", 0.41, 0.43)),
    )

    rows = cross.build_candidate_rows(group, [cheap, rich], 0.05, "t")

    assert rows
    assert round(rows[0]["price_gap"], 4) == 0.15
    assert rows[0]["reference_market_id"] == "rich"


def test_mutually_exclusive_group_detection():
    markets = [
        market(id="a", question="Will Alice win the 2026 election?", slug=""),
        market(id="b", question="Will Bob win the 2026 election?", slug=""),
    ]

    groups = cross.detect_related_groups(markets, 20)

    assert any(group["relationship_type"] == "mutually_exclusive_group" for group in groups)


def test_watch_only_default_for_moderate_duplicate_gap():
    group = {"group_id": "g1", "relationship_type": "same_event_duplicate", "confidence": 0.9}
    cheap = cross.PricedMarket(
        market(id="cheap", clobTokenIds='["yes_c","no_c"]'),
        cross.TokenPair("yes_c", "no_c"),
        cross.price_levels(orderbook("yes_c", 0.45, 0.47)),
        cross.price_levels(orderbook("no_c", 0.51, 0.53)),
    )
    rich = cross.PricedMarket(
        market(id="rich", clobTokenIds='["yes_r","no_r"]'),
        cross.TokenPair("yes_r", "no_r"),
        cross.price_levels(orderbook("yes_r", 0.51, 0.53)),
        cross.price_levels(orderbook("no_r", 0.45, 0.47)),
    )

    rows = cross.build_candidate_rows(group, [cheap, rich], 0.05, "t")

    assert rows[0]["recommended_action"] == "watch_only"


def test_strong_duplicate_price_gap_can_shadow_entry():
    group = {"group_id": "g1", "relationship_type": "same_event_duplicate", "confidence": 0.9}
    cheap = cross.PricedMarket(
        market(id="cheap", clobTokenIds='["yes_c","no_c"]'),
        cross.TokenPair("yes_c", "no_c"),
        cross.price_levels(orderbook("yes_c", 0.30, 0.31, size=20)),
        cross.price_levels(orderbook("no_c", 0.68, 0.69, size=20)),
    )
    rich = cross.PricedMarket(
        market(id="rich", clobTokenIds='["yes_r","no_r"]'),
        cross.TokenPair("yes_r", "no_r"),
        cross.price_levels(orderbook("yes_r", 0.50, 0.51, size=20)),
        cross.price_levels(orderbook("no_r", 0.48, 0.49, size=20)),
    )

    rows = cross.build_candidate_rows(group, [cheap, rich], 0.05, "t")

    assert rows[0]["recommended_action"] == "shadow_entry"
    assert rows[0]["edge_type"] == "cross_market_consistency_v1"


def test_ambiguous_relationship_stays_watch_only():
    group = {"group_id": "g1", "relationship_type": "mutually_exclusive_group", "confidence": 0.55}
    a = cross.PricedMarket(
        market(id="a", clobTokenIds='["yes_a","no_a"]'),
        cross.TokenPair("yes_a", "no_a"),
        cross.price_levels(orderbook("yes_a", 0.10, 0.11)),
        cross.price_levels(orderbook("no_a", 0.88, 0.89)),
    )
    b = cross.PricedMarket(
        market(id="b", clobTokenIds='["yes_b","no_b"]'),
        cross.TokenPair("yes_b", "no_b"),
        cross.price_levels(orderbook("yes_b", 0.50, 0.51)),
        cross.price_levels(orderbook("no_b", 0.48, 0.49)),
    )

    rows = cross.build_candidate_rows(group, [a, b], 0.05, "t")

    assert rows[0]["recommended_action"] == "watch_only"


def test_output_csv_json_summary_format(tmp_path: Path):
    row = {
        field: ""
        for field in cross.FIELDS
    }
    row.update({"edge_type": "cross_market_consistency_v1", "market_id": "m1", "recommended_action": "watch_only"})
    summary = cross.summarize(__import__("datetime").datetime.utcnow(), [market()], [], [row], 0, 0, [])

    cross.write_csv(tmp_path / "cross_market_edge_candidates.csv", [row])
    cross.write_json(tmp_path / "cross_market_edge_candidates.json", [row])
    cross.write_summary(tmp_path / "cross_market_edge_discovery_summary.json", summary)
    cross.write_report(tmp_path / "cross_market_edge_discovery_report.md", summary)

    assert list(csv.DictReader(open(tmp_path / "cross_market_edge_candidates.csv")))[0]["edge_type"]
    assert json.loads((tmp_path / "cross_market_edge_candidates.json").read_text())["cross_market_edge_candidates"]
    assert json.loads((tmp_path / "cross_market_edge_discovery_summary.json").read_text())["tiny_live_recommendation"] == "NO"
    assert "Cross-Market Edge Discovery Report" in (tmp_path / "cross_market_edge_discovery_report.md").read_text()


def test_dry_run_does_not_write_files(tmp_path: Path, monkeypatch):
    async def fake_run_async(parsed_args):
        return [], {
            "markets_scanned": 1,
            "groups_detected": 0,
            "duplicate_groups_detected": 0,
            "mutually_exclusive_groups_detected": 0,
            "orderbooks_fetched": 0,
            "candidates_generated": 0,
            "watch_only_candidates": 0,
            "shadow_entry_candidates": 0,
            "avg_price_gap": 0,
            "max_price_gap": 0,
            "api_error_count": 0,
            "tiny_live_recommendation": "NO",
        }

    monkeypatch.setattr(cross, "run_async", fake_run_async)

    rc = cross.main(["--dry_run", "--output_dir", str(tmp_path)])

    assert rc == 0
    assert not (tmp_path / "cross_market_edge_candidates.csv").exists()


def test_discover_cross_market_edges_integration(tmp_path: Path):
    markets = [
        market(id="cheap", slug="", question="Will Team A win the 2026 championship?", clobTokenIds='["yes_c","no_c"]'),
        market(id="rich", slug="", question="Will Team A win 2026 championship?", clobTokenIds='["yes_r","no_r"]'),
    ]
    books = {
        "yes_c": orderbook("yes_c", 0.30, 0.31, 20),
        "no_c": orderbook("no_c", 0.68, 0.69, 20),
        "yes_r": orderbook("yes_r", 0.50, 0.51, 20),
        "no_r": orderbook("no_r", 0.48, 0.49, 20),
    }

    rows, summary = asyncio.run(cross.discover_cross_market_edges(args(tmp_path), FakeGammaClient(markets), FakeCLOBClient(books)))

    assert summary["groups_detected"] >= 1
    assert rows
    assert summary["shadow_entry_candidates"] >= 1


def test_shadow_loop_can_read_cross_market_candidates(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    row = {field: "" for field in cross.FIELDS}
    row.update({
        "edge_type": "cross_market_consistency_v1",
        "market_id": "m1",
        "question": "Q?",
        "side": "YES",
        "yes_token_id": "yes",
        "no_token_id": "no",
        "entry_price": "0.31",
        "expected_edge": "0.1",
        "confidence": "0.9",
        "evidence": "cross_market_consistency_v1|same_event_duplicate|cross_market_price_gap",
        "recommended_action": "shadow_entry",
        "yes_best_ask": "0.31",
        "yes_best_bid": "0.30",
        "no_best_ask": "0.69",
        "no_best_bid": "0.68",
        "entry_yes_best_ask": "0.31",
        "entry_yes_best_bid": "0.30",
        "entry_no_best_ask": "0.69",
        "entry_no_best_bid": "0.68",
        "spread": "0.01",
        "liquidity_score": "20",
        "orderbook_depth": "2",
        "combined_ask": "1.0",
        "source": "cross_market_discovery",
        "reasons": "cross_market_consistency_v1|same_event_duplicate|cross_market_price_gap",
        "near_miss_tier": "tier1_mispricing",
        "edge_pass": "True",
        "gate_passed": "True",
        "feedback_gate_status": "enabled",
    })
    cross.write_csv(runs_dir / "cross_market_edge_candidates.csv", [row])

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].edge_type == "cross_market_consistency_v1"


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/discover_cross_market_edges.py").read_text())
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
