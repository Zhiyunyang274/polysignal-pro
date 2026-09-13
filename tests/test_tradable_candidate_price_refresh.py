"""Tests for Phase 8J tradable candidate side-specific price refresh."""

from __future__ import annotations

import ast
import asyncio
import csv
import json
from pathlib import Path

import yaml

import scripts.refresh_tradable_candidate_prices as refresh
import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.ingestion.api_errors import CLOBError
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.shadow.entry_filter import ShadowEntryFilter


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


def orderbook(asset_id: str, bid: float = 0.46, ask: float = 0.47, size: float = 10.0) -> CLOBOrderbook:
    return CLOBOrderbook(
        asset_id=asset_id,
        bids=[{"price": str(bid), "size": str(size)}],
        asks=[{"price": str(ask), "size": str(size)}],
    )


def write_candidates(path: Path, yes_token_id: str = "yes1", no_token_id: str = "no1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "market_id,question,category,source,combined_ask,ambiguity_risk,liquidity_score,spread,"
        "orderbook_depth,near_miss_tier,appearances,evidence_level,is_avoid_candidate,"
        "tradable_score,entry_decision_hint,reasons,alpha_score,yes_token_id,no_token_id\n"
        f"m1,Question?,Sports,control_group,1.01,10,3,0.01,3,,3,control_group,False,"
        f"20,watch_only,low_risk_control_group,0,{yes_token_id},{no_token_id}\n"
    )


def test_mock_clob_orderbook_refreshes_yes_no_bid_ask(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates_with_tokens.csv")
    client = FakeCLOBClient(orderbook("yes1", 0.46, 0.47), orderbook("no1", 0.46, 0.47))

    rows, summary = asyncio.run(refresh.refresh_prices(
        refresh.load_csv(runs_dir / "tradable_candidates_with_tokens.csv"),
        runs_dir,
        50,
        10,
        client,
    ))

    assert summary["candidates_priced"] == 1
    assert rows[0]["yes_best_bid"] == 0.46
    assert rows[0]["yes_best_ask"] == 0.47
    assert rows[0]["no_best_bid"] == 0.46
    assert rows[0]["no_best_ask"] == 0.47


def test_missing_token_id_graceful(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates_with_tokens.csv", "", "")
    client = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))

    rows, summary = asyncio.run(refresh.refresh_prices(refresh.load_csv(runs_dir / "tradable_candidates_with_tokens.csv"), runs_dir, 50, 10, client))

    assert summary["missing_token_id_count"] == 1
    assert rows[0]["price_refresh_status"] == "missing_token_id"
    assert client.calls == 0


def test_empty_orderbook_graceful(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates_with_tokens.csv")
    client = FakeCLOBClient(CLOBOrderbook(asset_id="yes1"), CLOBOrderbook(asset_id="no1"))

    rows, summary = asyncio.run(refresh.refresh_prices(refresh.load_csv(runs_dir / "tradable_candidates_with_tokens.csv"), runs_dir, 50, 10, client))

    assert summary["empty_orderbook_count"] == 1
    assert rows[0]["price_refresh_status"] == "empty_orderbook"


def test_api_error_graceful(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates_with_tokens.csv")
    client = FakeCLOBClient(error=CLOBError("boom"))

    rows, summary = asyncio.run(refresh.refresh_prices(refresh.load_csv(runs_dir / "tradable_candidates_with_tokens.csv"), runs_dir, 50, 10, client))

    assert summary["api_error_count"] == 1
    assert rows[0]["price_refresh_status"] == "api_error"


def test_spread_and_combined_ask_calculation():
    row = {"market_id": "m1", "yes_token_id": "yes1", "no_token_id": "no1"}

    priced = refresh.apply_price_snapshot(row, orderbook("yes1", 0.45, 0.47), orderbook("no1", 0.44, 0.46), "t")

    assert round(priced["yes_spread"], 4) == 0.02
    assert round(priced["no_spread"], 4) == 0.02
    assert round(priced["combined_ask"], 4) == 0.93
    assert priced["entry_yes_best_ask"] == 0.47
    assert priced["entry_no_best_ask"] == 0.46


def test_combined_ask_not_side_entry_after_refresh():
    row = {"market_id": "m1", "yes_token_id": "yes1", "no_token_id": "no1"}
    priced = refresh.apply_price_snapshot(row, orderbook("yes1", 0.45, 0.47), orderbook("no1", 0.44, 0.46), "t")
    candidate = shadow_loop.candidate_from_tradable(priced, set())

    assert candidate.combined_ask == 0.9299999999999999
    assert candidate.side_entry_ask() == 0.47
    assert candidate.side_entry_ask() != candidate.combined_ask


def test_expected_edge_insufficient_watch_only():
    row = {
        "market_id": "m1",
        "question": "Q?",
        "source": "control_group",
        "tradable_score": "20",
        "reasons": "low_risk_control_group",
        "liquidity_score": "3",
        "orderbook_depth": "3",
        "ambiguity_risk": "5",
    }
    priced = refresh.apply_price_snapshot(row, orderbook("yes1", 0.50, 0.51), orderbook("no1", 0.49, 0.50), "t")

    result = ShadowEntryFilter().evaluate(shadow_loop.candidate_from_tradable(priced, set()))

    assert result.entry_decision.value == "watch_only"


def test_expected_edge_pass_can_be_eligible():
    row = {
        "market_id": "m1",
        "question": "Q?",
        "source": "watchlist",
        "tradable_score": "20",
        "reasons": "non_avoid_watchlist",
        "evidence_level": "strong",
        "near_miss_tier": "tier2_strong_near_miss",
        "liquidity_score": "3",
        "orderbook_depth": "3",
        "ambiguity_risk": "5",
    }
    priced = refresh.apply_price_snapshot(row, orderbook("yes1", 0.45, 0.47), orderbook("no1", 0.44, 0.46), "t")

    result = ShadowEntryFilter().evaluate(shadow_loop.candidate_from_tradable(priced, set()))

    assert result.entry_decision.value == "eligible_shadow_entry"


def test_priced_candidates_csv_json_format(tmp_path: Path):
    rows = [refresh.apply_price_snapshot({"market_id": "m1"}, orderbook("yes1"), orderbook("no1"), "t")]

    refresh.write_csv(tmp_path / "tradable_candidates_priced.csv", rows)
    refresh.write_json(tmp_path / "tradable_candidates_priced.json", rows)

    csv_rows = list(csv.DictReader(open(tmp_path / "tradable_candidates_priced.csv")))
    payload = json.loads((tmp_path / "tradable_candidates_priced.json").read_text())
    assert csv_rows[0]["yes_best_ask"]
    assert payload["tradable_candidates_priced"][0]["no_best_ask"]


def test_run_shadow_loop_prefers_priced_candidates(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    write_candidates(runs_dir / "tradable_candidates.csv", "", "")
    priced = refresh.apply_price_snapshot(
        {
            "market_id": "m1",
            "question": "Q?",
            "source": "control_group",
            "tradable_score": "20",
            "reasons": "low_risk_control_group",
            "liquidity_score": "3",
            "orderbook_depth": "3",
            "ambiguity_risk": "5",
        },
        orderbook("yes1", 0.45, 0.47),
        orderbook("no1", 0.44, 0.46),
        "t",
    )
    refresh.write_csv(runs_dir / "tradable_candidates_priced.csv", [priced])

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].entry_yes_best_ask == 0.47
    assert candidates[0].expected_edge > 0


def test_no_forbidden_imports():
    tree = ast.parse(Path("scripts/refresh_tradable_candidate_prices.py").read_text())
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
