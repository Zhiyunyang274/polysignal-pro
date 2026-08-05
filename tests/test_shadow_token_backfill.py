"""Tests for Phase 8G.1 offline shadow token ID backfill."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.backfill_shadow_token_ids as backfill
from polysignal.shadow.forward_observations import ShadowTokenIdResolver
from polysignal.shadow.models import SHADOW_TRADE_FIELDS


class FakeGammaLookupClient:
    def __init__(self, markets=None, search_results=None, errors=None, max_api_calls=20):
        self.markets = markets or {}
        self.search_results = search_results or {}
        self.errors = errors or {}
        self.api_calls_used = 0
        self.max_api_calls = max_api_calls

    def lookup_market_by_id(self, market_id: str):
        if self.api_calls_used >= self.max_api_calls:
            raise RuntimeError("max_api_calls_exceeded")
        self.api_calls_used += 1
        if market_id in self.errors:
            raise self.errors[market_id]
        return self.markets.get(market_id)

    def search_market_by_question(self, question: str):
        if self.api_calls_used >= self.max_api_calls:
            raise RuntimeError("max_api_calls_exceeded")
        self.api_calls_used += 1
        return self.search_results.get(question, [])


def write_shadow_trade(path: Path, market_id: str = "m1") -> None:
    row = {
        "shadow_trade_id": "shadow_1",
        "market_id": market_id,
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
        "yes_token_id": "",
        "no_token_id": "",
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
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHADOW_TRADE_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def setup_dirs(tmp_path: Path, market_id: str = "m1") -> tuple[Path, Path]:
    runs_dir = tmp_path / "runs"
    shadow_dir = runs_dir / "shadow"
    shadow_dir.mkdir(parents=True)
    write_shadow_trade(shadow_dir / "shadow_trades.csv", market_id)
    (shadow_dir / "shadow_positions.json").write_text(json.dumps({
        "generated_at": "2026-05-11T00:00:00",
        "open_positions": [],
        "closed_positions": [],
        "insufficient_forward_data_positions": [],
    }))
    return runs_dir, shadow_dir


def run_backfill(tmp_path: Path, runs_dir: Path, shadow_dir: Path, dry_run: bool = False):
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        *(["--dry_run"] if dry_run else []),
    ])
    return backfill.run_backfill(args)


def test_recovers_token_ids_from_tradable_candidates_json(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.json").write_text(json.dumps({
        "tradable_candidates": [
            {"market_id": "m1", "yes_token_id": "yes1", "no_token_id": "no1"}
        ]
    }))

    result = backfill.build_token_index(runs_dir, shadow_dir)

    assert result.token_index["m1"].yes_token_id == "yes1"
    assert result.token_index["m1"].no_token_id == "no1"


def test_recovers_token_ids_from_events_jsonl(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    run_dir = runs_dir / "run_a"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(json.dumps({
        "market_id": "m1",
        "yes_token_id": "yes1",
        "no_token_id": "no1",
    }) + "\n")

    result = backfill.build_token_index(runs_dir, shadow_dir)

    assert result.token_index["m1"].yes_token_id == "yes1"


def test_recovers_from_clob_token_ids_and_outcomes(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.json").write_text(json.dumps({
        "tradable_candidates": [
            {"market_id": "m1", "clobTokenIds": ["no1", "yes1"], "outcomes": ["No", "Yes"]}
        ]
    }))

    result = backfill.build_token_index(runs_dir, shadow_dir)

    assert result.token_index["m1"].yes_token_id == "yes1"
    assert result.token_index["m1"].no_token_id == "no1"


def test_json_encoded_clob_token_ids_string(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.csv").write_text(
        'market_id,clobTokenIds,outcomes\nm1,"[""yes1"", ""no1""]","[""Yes"", ""No""]"\n'
    )

    result = backfill.build_token_index(runs_dir, shadow_dir)

    assert result.token_index["m1"].yes_token_id == "yes1"
    assert result.token_index["m1"].no_token_id == "no1"


def test_missing_token_ids_outputs_missing(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)

    summary, _, _, _ = run_backfill(tmp_path, runs_dir, shadow_dir, dry_run=True)

    assert summary["shadow_trades_missing_token_id"] == 1
    assert summary["shadow_trades_backfilled"] == 0


def test_does_not_use_market_id_as_token_id(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.csv").write_text(
        "market_id,yes_token_id,no_token_id\nm1,m1,no1\n"
    )

    result = backfill.build_token_index(runs_dir, shadow_dir)

    assert "m1" not in result.token_index


def test_shadow_trades_write_token_ids(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.json").write_text(json.dumps({
        "tradable_candidates": [
            {"market_id": "m1", "yes_token_id": "yes1", "no_token_id": "no1"}
        ]
    }))
    args = backfill.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary, outputs, trades, tradable_rows = backfill.run_backfill(args)
    backfill.write_outputs(summary, outputs, trades, tradable_rows, True)

    rows = list(csv.DictReader(open(shadow_dir / "shadow_trades_with_tokens.csv")))
    assert rows[0]["yes_token_id"] == "yes1"
    assert rows[0]["no_token_id"] == "no1"


def test_shadow_positions_write_token_ids(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.json").write_text(json.dumps({
        "tradable_candidates": [
            {"market_id": "m1", "yes_token_id": "yes1", "no_token_id": "no1"}
        ]
    }))
    args = backfill.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary, outputs, trades, tradable_rows = backfill.run_backfill(args)
    backfill.write_outputs(summary, outputs, trades, tradable_rows, True)

    positions = json.loads((shadow_dir / "updated_shadow_positions.json").read_text())
    trade = positions["insufficient_forward_data_positions"][0]
    assert trade["yes_token_id"] == "yes1"
    assert trade["no_token_id"] == "no1"


def test_token_id_backfill_summary_format(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    args = backfill.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary, outputs, trades, tradable_rows = backfill.run_backfill(args)
    backfill.write_outputs(summary, outputs, trades, tradable_rows, True)
    payload = json.loads((shadow_dir / "token_id_backfill_summary.json").read_text())

    assert "token_pairs_found" in payload
    assert "safety_verification" in payload
    assert "output_files" in payload


def test_dry_run_does_not_write_files(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)

    rc = backfill.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir), "--dry_run"])

    assert rc == 0
    assert not (shadow_dir / "token_id_backfill_summary.json").exists()
    assert not (shadow_dir / "shadow_trades_with_tokens.csv").exists()


def test_allow_api_lookup_false_does_not_call_network(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)

    summary, _, _, _ = run_backfill(tmp_path, runs_dir, shadow_dir, dry_run=True)

    assert summary["api_lookup_enabled"] is False
    assert summary["api_calls_used"] == 0
    assert summary["safety_verification"]["network_calls"] is False


def test_poller_resolver_finds_backfilled_files(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    (runs_dir / "tradable_candidates.json").write_text(json.dumps({
        "tradable_candidates": [
            {"market_id": "m1", "yes_token_id": "yes1", "no_token_id": "no1"}
        ]
    }))
    args = backfill.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(shadow_dir)])
    summary, outputs, trades, tradable_rows = backfill.run_backfill(args)
    backfill.write_outputs(summary, outputs, trades, tradable_rows, True)

    resolution = ShadowTokenIdResolver(runs_dir, shadow_dir).resolve("m1")

    assert resolution.complete
    assert resolution.yes_token_id == "yes1"


def test_no_forbidden_trading_imports():
    tree = ast.parse(Path("scripts/backfill_shadow_token_ids.py").read_text())
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


def test_mock_gamma_api_success_returns_tokens(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    client = FakeGammaLookupClient(markets={
        "m1": {
            "id": "m1",
            "question": "Will test happen?",
            "clobTokenIds": ["yes1", "no1"],
            "outcomes": ["Yes", "No"],
        }
    })
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        "--allow_api_lookup",
    ])

    summary, _, trades, _ = backfill.run_backfill(args, api_client=client)

    assert summary["api_lookup_successes"] == 1
    assert summary["shadow_trades_backfilled"] == 1
    assert trades[0].yes_token_id == "yes1"
    assert trades[0].no_token_id == "no1"


def test_gamma_yes_no_mapping_with_reversed_outcomes():
    pair, error = backfill.extract_gamma_token_pair(
        {
            "id": "m1",
            "clobTokenIds": ["no1", "yes1"],
            "outcomes": ["No", "Yes"],
        },
        "m1",
    )

    assert error is None
    assert pair.yes_token_id == "yes1"
    assert pair.no_token_id == "no1"


def test_gamma_json_encoded_clob_token_ids():
    pair, error = backfill.extract_gamma_token_pair(
        {
            "id": "m1",
            "clobTokenIds": '["yes1", "no1"]',
            "outcomes": '["Yes", "No"]',
        },
        "m1",
    )

    assert error is None
    assert pair.yes_token_id == "yes1"


def test_gamma_ambiguous_outcome_mapping():
    pair, error = backfill.extract_gamma_token_pair(
        {
            "id": "m1",
            "clobTokenIds": ["t1", "t2"],
            "outcomes": ["Home", "Away"],
        },
        "m1",
    )

    assert pair is None
    assert error == "ambiguous_outcome_mapping"


def test_gamma_unsupported_market_structure():
    pair, error = backfill.extract_gamma_token_pair(
        {
            "id": "m1",
            "clobTokenIds": ["t1", "t2", "t3"],
            "outcomes": ["Yes", "No", "Other"],
        },
        "m1",
    )

    assert pair is None
    assert error == "unsupported_market_structure"


def test_gamma_api_error_graceful_handling(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    client = FakeGammaLookupClient(errors={"m1": RuntimeError("gamma down")})
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        "--allow_api_lookup",
    ])

    summary, _, _, _ = backfill.run_backfill(args, api_client=client)

    assert summary["api_lookup_failures"] == 1
    assert summary["errors"][0]["error"] == "api_error:gamma down"


def test_gamma_max_api_calls_respected(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    with open(shadow_dir / "shadow_trades.csv", "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHADOW_TRADE_FIELDS)
        writer.writerow({
            field: "" for field in SHADOW_TRADE_FIELDS
        } | {
            "shadow_trade_id": "shadow_2",
            "market_id": "m2",
            "question": "Will other happen?",
            "side": "YES",
            "entry_time": "2026-05-11T00:00:00",
            "entry_price": "1.0",
            "entry_reason": "tradable_candidate_evidence_passed",
            "status": "insufficient_forward_data",
            "exit_reason": "open",
        })
    client = FakeGammaLookupClient(markets={
        "m1": {"id": "m1", "question": "Will test happen?", "clobTokenIds": ["yes1", "no1"], "outcomes": ["Yes", "No"]},
        "m2": {"id": "m2", "question": "Will other happen?", "clobTokenIds": ["yes2", "no2"], "outcomes": ["Yes", "No"]},
    }, max_api_calls=1)
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        "--allow_api_lookup",
        "--max_api_calls", "1",
    ])

    summary, _, _, _ = backfill.run_backfill(args, api_client=client)

    assert summary["api_calls_used"] == 1
    assert summary["api_lookup_successes"] == 1


def test_ambiguous_market_match_does_not_write_token(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    client = FakeGammaLookupClient(markets={
        "m1": {
            "id": "m1",
            "question": "Different question?",
            "clobTokenIds": ["yes1", "no1"],
            "outcomes": ["Yes", "No"],
        }
    })
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        "--allow_api_lookup",
    ])

    summary, _, trades, _ = backfill.run_backfill(args, api_client=client)

    assert summary["ambiguous_market_matches"] == 1
    assert trades[0].yes_token_id == ""


def test_market_lookup_not_found_recorded(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    client = FakeGammaLookupClient(markets={})
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        "--allow_api_lookup",
    ])

    summary, _, _, _ = backfill.run_backfill(args, api_client=client)

    assert summary["market_lookup_not_found"] == 1


def test_api_lookup_writes_backfilled_outputs(tmp_path: Path):
    runs_dir, shadow_dir = setup_dirs(tmp_path)
    client = FakeGammaLookupClient(markets={
        "m1": {
            "id": "m1",
            "question": "Will test happen?",
            "clobTokenIds": ["yes1", "no1"],
            "outcomes": ["Yes", "No"],
        }
    })
    args = backfill.parse_args([
        "--runs_dir", str(runs_dir),
        "--shadow_dir", str(shadow_dir),
        "--allow_api_lookup",
    ])
    summary, outputs, trades, rows = backfill.run_backfill(args, api_client=client)
    backfill.write_outputs(summary, outputs, trades, rows, True)

    trade_rows = list(csv.DictReader(open(shadow_dir / "shadow_trades_with_tokens.csv")))
    positions = json.loads((shadow_dir / "updated_shadow_positions.json").read_text())

    assert trade_rows[0]["yes_token_id"] == "yes1"
    assert positions["insufficient_forward_data_positions"][0]["no_token_id"] == "no1"
