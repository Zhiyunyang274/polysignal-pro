"""Tests for Trading MVP Step 3 executable edge discovery."""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import json
from pathlib import Path

import yaml

import scripts.discover_executable_edges as discovery
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


def orderbook(asset_id: str, bid: float = 0.45, ask: float = 0.47, size: float = 10.0) -> CLOBOrderbook:
    return CLOBOrderbook(
        asset_id=asset_id,
        bids=[{"price": str(bid), "size": str(size)}],
        asks=[{"price": str(ask), "size": str(size)}],
    )


def args(tmp_path: Path, **overrides):
    payload = {
        "max_markets": 500,
        "min_volume": 1000.0,
        "max_api_errors": 20,
        "spread_buffer": 0.01,
        "min_executable_edge": 0.001,
        "min_depth": 1.0,
        "dry_run": False,
        "output_dir": str(tmp_path / "runs"),
        "data_mode": "real_readonly",
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_mock_gamma_active_markets_extraction(tmp_path: Path):
    gamma = FakeGammaClient([market(), market(id="m2", active=False), market(id="m3", volume="10")])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path), gamma, clob))

    assert gamma.calls == 1
    assert summary["markets_scanned"] == 1
    assert summary["markets_with_token_ids"] == 1


def test_mock_token_ids_extraction_json_strings():
    pair, error = discovery.extract_token_pair(market(clobTokenIds='["yes_token","no_token"]', outcomes='["Yes","No"]'))

    assert error == ""
    assert pair.yes_token_id == "yes_token"
    assert pair.no_token_id == "no_token"


def test_token_ids_extraction_reversed_outcomes():
    pair, error = discovery.extract_token_pair(market(clobTokenIds='["no_token","yes_token"]', outcomes='["No","Yes"]'))

    assert error == ""
    assert pair.yes_token_id == "yes_token"
    assert pair.no_token_id == "no_token"


def test_mock_clob_orderbook_parsing():
    levels = discovery.price_levels(orderbook("yes1", 0.44, 0.46, 12))

    assert levels["best_bid"] == 0.44
    assert levels["best_ask"] == 0.46
    assert round(levels["spread"], 4) == 0.02
    assert levels["depth"] == 2


def test_combined_ask_and_gap_calculation():
    row = discovery.build_edge_candidate(
        market(),
        discovery.TokenPair("yes1", "no1"),
        orderbook("yes1", 0.45, 0.47),
        orderbook("no1", 0.44, 0.46),
        0.01,
        0.001,
        1,
        "t",
    )

    assert round(row["combined_ask"], 4) == 0.93
    assert round(row["combined_ask_gap"], 4) == 0.07


def test_executable_edge_formula():
    row = discovery.build_edge_candidate(
        market(),
        discovery.TokenPair("yes1", "no1"),
        orderbook("yes1", 0.45, 0.47),
        orderbook("no1", 0.44, 0.46),
        0.01,
        0.001,
        1,
        "t",
    )

    assert round(row["executable_edge"], 4) == 0.04
    assert row["edge_pass"] is True


def test_combined_ask_at_or_above_one_not_candidate(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1", 0.49, 0.51), orderbook("no1", 0.48, 0.50))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path), gamma, clob))

    assert candidates == []
    assert summary["combined_ask_below_one_count"] == 0
    assert summary["edge_candidates_count"] == 0


def test_executable_edge_below_min_not_candidate(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1", 0.48, 0.495), orderbook("no1", 0.48, 0.495))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path, min_executable_edge=0.01), gamma, clob))

    assert candidates == []
    assert summary["combined_ask_below_one_count"] == 1
    assert summary["edge_candidates_count"] == 0


def test_spread_too_wide_not_candidate(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1", 0.10, 0.40), orderbook("no1", 0.10, 0.40))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path), gamma, clob))

    assert candidates == []
    assert summary["spread_too_wide_count"] == 1


def test_depth_insufficient_not_candidate(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1", 0.45, 0.47), orderbook("no1", 0.44, 0.46))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path, min_depth=10), gamma, clob))

    assert candidates == []
    assert summary["insufficient_depth_count"] == 1


def test_api_error_graceful(tmp_path: Path):
    gamma = FakeGammaClient(error=RuntimeError("boom"))
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path), gamma, clob))

    assert candidates == []
    assert summary["api_error_count"] == 1
    assert summary["errors"]


def test_forbidden_category_is_skipped(tmp_path: Path):
    gamma = FakeGammaClient([market(category="politics")])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path), gamma, clob))

    assert candidates == []
    assert summary["forbidden_category_count"] == 1
    assert clob.calls == 0


def test_avoid_candidate_is_skipped(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "avoid_candidates.csv").write_text("market_id\nm1\n")
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path, output_dir=str(runs_dir)), gamma, clob))

    assert candidates == []
    assert summary["avoid_candidate_count"] == 1
    assert clob.calls == 0


def test_ambiguous_market_is_skipped(tmp_path: Path):
    gamma = FakeGammaClient([market(question="Will this maybe happen?")])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))

    candidates, summary = asyncio.run(discovery.discover_edges(args(tmp_path), gamma, clob))

    assert candidates == []
    assert summary["ambiguous_market_count"] == 1
    assert clob.calls == 0


def test_output_csv_json_summary_format(tmp_path: Path):
    rows = [
        discovery.build_edge_candidate(
            market(),
            discovery.TokenPair("yes1", "no1"),
            orderbook("yes1", 0.45, 0.47),
            orderbook("no1", 0.44, 0.46),
            0.01,
            0.001,
            1,
            "t",
        )
    ]
    summary = discovery.build_summary(
        started=__import__("datetime").datetime.utcnow(),
        markets=[market()],
        markets_with_token_ids=1,
        orderbooks_fetched=2,
        candidates=rows,
        evaluated_rows=rows,
        api_error_count=0,
        stale_orderbook_count=0,
        insufficient_depth_count=0,
        spread_too_wide_count=0,
        errors=[],
    )

    discovery.write_csv(tmp_path / "executable_edge_candidates.csv", rows)
    discovery.write_json(tmp_path / "executable_edge_candidates.json", rows)
    discovery.write_summary(tmp_path / "executable_edge_discovery_summary.json", summary)
    discovery.write_report(tmp_path / "executable_edge_discovery_report.md", summary)

    assert list(csv.DictReader(open(tmp_path / "executable_edge_candidates.csv")))[0]["executable_edge"]
    assert json.loads((tmp_path / "executable_edge_candidates.json").read_text())["executable_edge_candidates"]
    assert json.loads((tmp_path / "executable_edge_discovery_summary.json").read_text())["tiny_live_recommendation"] == "NO"
    assert "read-only executable edge discovery" in (tmp_path / "executable_edge_discovery_report.md").read_text()


def test_dry_run_does_not_write_candidate_files(tmp_path: Path, monkeypatch):
    async def fake_run_async(parsed_args):
        return [], {
            "ended_at": "t",
            "markets_scanned": 1,
            "active_markets_available": 1,
            "markets_with_token_ids": 0,
            "orderbooks_fetched": 0,
            "combined_ask_below_one_count": 0,
            "executable_edge_positive_count": 0,
            "edge_candidates_count": 0,
            "api_error_count": 0,
            "stale_orderbook_count": 0,
            "insufficient_depth_count": 0,
            "spread_too_wide_count": 0,
            "tiny_live_recommendation": "NO",
            "safety_verification": {},
        }

    monkeypatch.setattr(discovery, "run_async", fake_run_async)

    rc = discovery.main(["--dry_run", "--output_dir", str(tmp_path)])

    assert rc == 0
    assert not (tmp_path / "executable_edge_candidates.csv").exists()


def test_shadow_loop_prefers_executable_edge_candidates(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    row = discovery.build_edge_candidate(
        market(),
        discovery.TokenPair("yes1", "no1"),
        orderbook("yes1", 0.45, 0.47),
        orderbook("no1", 0.44, 0.46),
        0.01,
        0.001,
        1,
        "t",
    )
    discovery.write_csv(runs_dir / "executable_edge_candidates.csv", [row])

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].tradable_source == "executable_edge_discovery"
    assert candidates[0].expected_edge > 0


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/discover_executable_edges.py").read_text())
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
