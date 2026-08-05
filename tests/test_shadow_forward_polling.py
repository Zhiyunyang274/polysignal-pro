"""Tests for Phase 8F.2 read-only shadow forward price polling."""

from __future__ import annotations

import ast
import asyncio
import csv
import json
from pathlib import Path

import yaml

import scripts.poll_shadow_forward_prices as poller
from polysignal.ingestion.api_types import CLOBOrderbook, CLOBPriceLevel
from polysignal.shadow.forward_observations import ShadowTokenIdResolver
from polysignal.shadow.models import SHADOW_TRADE_FIELDS


def orderbook(
    bids: list[tuple[str, str]] | None = None,
    asks: list[tuple[str, str]] | None = None,
    asset_id: str = "token",
) -> CLOBOrderbook:
    return CLOBOrderbook(
        asset_id=asset_id,
        bids=[CLOBPriceLevel(price=price, size=size) for price, size in (bids or [])],
        asks=[CLOBPriceLevel(price=price, size=size) for price, size in (asks or [])],
    )


class FakeCLOBClient:
    def __init__(self, yes_book=None, no_book=None, error: Exception | None = None):
        self.yes_book = yes_book or orderbook(bids=[("1.06", "10")], asks=[("1.08", "5")])
        self.no_book = no_book or orderbook(bids=[("0.02", "8")], asks=[("0.03", "4")])
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


def write_shadow_trade(path: Path, extra_fields: list[str] | None = None, **overrides) -> dict[str, str]:
    row = {
        "shadow_trade_id": "shadow_1",
        "market_id": "market_1",
        "question": "Will test happen?",
        "side": "YES",
        "entry_time": "2026-05-11T00:00:00",
        "entry_price": "1.0",
        "entry_reason": "tradable_candidate_evidence_passed",
        "tradable_score": "20",
        "alpha_score": "0",
        "combined_ask": "1.0",
        "liquidity_score": "3",
        "ambiguity_risk": "10",
        "risk_decision": "allow_shadow",
        "exit_time": "",
        "exit_price": "",
        "exit_reason": "open",
        "pnl": "0",
        "return_pct": "0",
        "status": "insufficient_forward_data",
        "run_id": "",
        "category": "Sports",
        "source": "control_group",
        "evidence_level": "control_group",
        "near_miss_tier": "",
        "orderbook_spread": "0.01",
        "orderbook_depth": "3",
        "max_adverse_excursion": "0",
        "max_favorable_excursion": "0",
        "holding_minutes": "0",
    }
    row.update(overrides)
    fields = list(SHADOW_TRADE_FIELDS)
    for field in extra_fields or []:
        if field not in fields:
            fields.append(field)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fields})
    return row


def setup_shadow(tmp_path: Path, with_tokens: bool = True) -> tuple[Path, Path]:
    runs_dir = tmp_path / "runs"
    shadow_dir = runs_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    extra = ["yes_token_id", "no_token_id"] if with_tokens else []
    overrides = {"yes_token_id": "yes_token_1", "no_token_id": "no_token_1"} if with_tokens else {}
    write_shadow_trade(shadow_dir / "shadow_trades.csv", extra_fields=extra, **overrides)
    (shadow_dir / "shadow_positions.json").write_text(json.dumps({
        "generated_at": "2026-05-11T00:00:00",
        "open_positions": [],
        "closed_positions": [],
        "insufficient_forward_data_positions": [],
    }))
    return runs_dir, shadow_dir


def run(coro):
    return asyncio.run(coro)


def test_token_id_missing_graceful_handling(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path, with_tokens=False)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, dry_run=True)

    summary = run(poller.run_poll(config, FakeCLOBClient()))

    assert summary["positions_loaded"] == 1
    assert summary["missing_token_id_count"] == 1
    assert summary["positions_polled"] == 0


def test_does_not_treat_market_id_as_token_id(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path, with_tokens=False)
    (runs_dir / "tradable_candidates.csv").write_text(
        "market_id,yes_token_id,no_token_id\nmarket_1,market_1,no_token_1\n"
    )

    resolution = ShadowTokenIdResolver(runs_dir, shadow_dir).resolve("market_1")

    assert not resolution.complete
    assert resolution.error == "missing_token_id"


def test_mock_clob_orderbook_generates_forward_observation(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, once=True, update_positions=False)

    summary = run(poller.run_poll(config, FakeCLOBClient()))

    assert summary["observations_written"] == 1
    payload = json.loads((shadow_dir / "forward_observations.jsonl").read_text().splitlines()[0])
    assert payload["source"] == "clob_rest_readonly"
    assert payload["yes_token_id"] == "yes_token_1"


def test_yes_best_bid_and_ask_parsed_correctly():
    yes_book = orderbook(bids=[("0.40", "1"), ("0.42", "1")], asks=[("0.45", "1"), ("0.44", "1")])

    assert poller.best_bid(yes_book) == 0.42
    assert poller.best_ask(yes_book) == 0.44


def test_no_best_bid_and_ask_parsed_correctly():
    no_book = orderbook(bids=[("0.50", "1"), ("0.55", "1")], asks=[("0.60", "1"), ("0.58", "1")])

    assert poller.best_bid(no_book) == 0.55
    assert poller.best_ask(no_book) == 0.58


def test_yes_side_observed_price_uses_yes_best_bid(tmp_path: Path):
    _, shadow_dir = setup_shadow(tmp_path)
    trade = poller.load_positions(shadow_dir)[0]
    obs = poller.build_forward_observation(
        trade,
        poller.TokenIdResolution("market_1", "yes_token_1", "no_token_1"),
        orderbook(bids=[("0.41", "1")], asks=[("0.43", "1")]),
        orderbook(bids=[("0.54", "1")], asks=[("0.56", "1")]),
        "2026-05-11T01:00:00",
    )

    assert obs.observed_price == 0.41


def test_no_side_observed_price_uses_no_best_bid(tmp_path: Path):
    _, shadow_dir = setup_shadow(tmp_path)
    write_shadow_trade(
        shadow_dir / "shadow_trades.csv",
        extra_fields=["yes_token_id", "no_token_id"],
        side="NO",
        yes_token_id="yes_token_1",
        no_token_id="no_token_1",
    )
    trade = poller.load_positions(shadow_dir)[0]
    obs = poller.build_forward_observation(
        trade,
        poller.TokenIdResolution("market_1", "yes_token_1", "no_token_1"),
        orderbook(bids=[("0.41", "1")], asks=[("0.43", "1")]),
        orderbook(bids=[("0.54", "1")], asks=[("0.56", "1")]),
        "2026-05-11T01:00:00",
    )

    assert obs.observed_price == 0.54


def test_once_polls_only_once(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    client = FakeCLOBClient()
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, once=True, update_positions=False)

    run(poller.run_poll(config, client))

    assert client.calls == 1


def test_dry_run_does_not_write_files(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, dry_run=True)

    run(poller.run_poll(config, FakeCLOBClient()))

    assert not (shadow_dir / "forward_poll_summary.json").exists()
    assert not (shadow_dir / "forward_observations.jsonl").exists()


def test_api_error_recorded_without_crash(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, once=True, update_positions=False)

    summary = run(poller.run_poll(config, FakeCLOBClient(error=RuntimeError("api down"))))

    assert summary["api_error_count"] == 1
    assert summary["errors"][0]["error"] == "api down"


def test_forward_observations_jsonl_format(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, once=True, update_positions=False)

    run(poller.run_poll(config, FakeCLOBClient()))
    payload = json.loads((shadow_dir / "forward_observations.jsonl").read_text().splitlines()[0])

    assert {"shadow_trade_id", "market_id", "yes_best_bid", "no_best_ask", "combined_ask"} <= set(payload)


def test_forward_poll_summary_json_format(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, once=True, update_positions=False)

    run(poller.run_poll(config, FakeCLOBClient()))
    summary = json.loads((shadow_dir / "forward_poll_summary.json").read_text())

    assert "positions_loaded" in summary
    assert "safety_verification" in summary
    assert summary["safety_verification"]["read_only_clob_rest"] is True


def test_poll_can_update_positions_with_collector(tmp_path: Path):
    runs_dir, shadow_dir = setup_shadow(tmp_path)
    config = poller.PollConfig(runs_dir=runs_dir, shadow_dir=shadow_dir, once=True, update_positions=True)

    run(poller.run_poll(config, FakeCLOBClient()))
    summary = json.loads((shadow_dir / "paper_performance_summary.json").read_text())

    assert summary["closed_positions"] == 1
    assert summary["total_pnl"] > 0


def test_no_live_paper_or_risk_governor_imports():
    tree = ast.parse(Path("scripts/poll_shadow_forward_prices.py").read_text())
    forbidden = {"LiveTrader", "PaperTrader", "RiskGovernor"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)

    assert forbidden.isdisjoint(imported)


def test_no_private_key_handling():
    text = Path("scripts/poll_shadow_forward_prices.py").read_text().lower()

    assert "private_key" not in text.replace("private_key_handling", "")
    assert "secret" not in text
    assert "api_key" not in text


def test_live_trading_enabled_remains_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False
    assert risk["allow_auto_execution"] is False
