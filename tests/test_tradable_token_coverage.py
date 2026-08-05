"""Tests for Trading MVP tradable candidate token coverage."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import yaml

import scripts.improve_tradable_token_coverage as coverage


class FakeGammaLookupClient:
    def __init__(self, markets=None, search_results=None, errors=None, max_api_calls=50):
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


def write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "market_id",
        "question",
        "source",
        "yes_token_id",
        "no_token_id",
        "tradable_score",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(runs_dir: Path, *extra: str):
    return coverage.parse_args(["--runs_dir", str(runs_dir), "--shadow_dir", str(runs_dir / "shadow"), *extra])


def test_gamma_lookup_success_backfills_missing_token_ids(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?", "source": "control_group"}
    ])
    client = FakeGammaLookupClient(markets={
        "m1": {"id": "m1", "question": "Will test happen?", "clobTokenIds": ["yes1", "no1"], "outcomes": ["Yes", "No"]}
    })

    summary, rows = coverage.improve_coverage(parse_args(runs_dir, "--allow_api_lookup"), api_client=client)

    assert summary["token_backfilled"] == 1
    assert summary["still_missing_token"] == 0
    assert rows[0]["yes_token_id"] == "yes1"
    assert rows[0]["no_token_id"] == "no1"


def test_ambiguous_market_does_not_write_token(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Original question?", "source": "watchlist"}
    ])
    client = FakeGammaLookupClient(markets={
        "m1": {"id": "m1", "question": "Different question?", "clobTokenIds": ["yes1", "no1"], "outcomes": ["Yes", "No"]}
    })

    summary, rows = coverage.improve_coverage(parse_args(runs_dir, "--allow_api_lookup"), api_client=client)

    assert summary["ambiguous_market_matches"] == 1
    assert summary["token_backfilled"] == 0
    assert rows[0]["yes_token_id"] == ""


def test_ambiguous_outcome_does_not_write_token(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?", "source": "watchlist"}
    ])
    client = FakeGammaLookupClient(markets={
        "m1": {"id": "m1", "question": "Will test happen?", "clobTokenIds": ["t1", "t2"], "outcomes": ["Home", "Away"]}
    })

    summary, rows = coverage.improve_coverage(parse_args(runs_dir, "--allow_api_lookup"), api_client=client)

    assert summary["ambiguous_outcome_mappings"] == 1
    assert rows[0]["no_token_id"] == ""


def test_unsupported_market_structure_does_not_write_token(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?", "source": "watchlist"}
    ])
    client = FakeGammaLookupClient(markets={
        "m1": {
            "id": "m1",
            "question": "Will test happen?",
            "clobTokenIds": ["t1", "t2", "t3"],
            "outcomes": ["Yes", "No", "Other"],
        }
    })

    summary, rows = coverage.improve_coverage(parse_args(runs_dir, "--allow_api_lookup"), api_client=client)

    assert summary["unsupported_market_structures"] == 1
    assert rows[0]["yes_token_id"] == ""


def test_market_id_not_used_as_token_id(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?", "yes_token_id": "m1", "no_token_id": "no1"}
    ])

    summary, rows = coverage.improve_coverage(parse_args(runs_dir))

    assert summary["still_missing_token"] == 1
    assert rows[0]["token_id_source"] == "missing_token_id"


def test_exact_question_search_fallback_can_backfill(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?", "source": "watchlist"}
    ])
    client = FakeGammaLookupClient(
        markets={"m1": None},
        search_results={
            "Will test happen?": [
                {"id": "m1", "question": "Will test happen?", "clobTokenIds": ["yes1", "no1"], "outcomes": ["Yes", "No"]}
            ]
        },
    )

    summary, rows = coverage.improve_coverage(parse_args(runs_dir, "--allow_api_lookup"), api_client=client)

    assert summary["api_lookup_successes"] == 1
    assert rows[0]["yes_token_id"] == "yes1"


def test_token_coverage_summary_and_csv_written(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?"}
    ])
    client = FakeGammaLookupClient(markets={
        "m1": {"id": "m1", "question": "Will test happen?", "clobTokenIds": ["yes1", "no1"], "outcomes": ["Yes", "No"]}
    })
    summary, rows = coverage.improve_coverage(parse_args(runs_dir, "--allow_api_lookup"), api_client=client)

    coverage.write_outputs(summary, rows)

    payload = json.loads((runs_dir / "token_coverage_summary.json").read_text())
    out_rows = list(csv.DictReader(open(runs_dir / "tradable_candidates_with_tokens.csv")))
    assert payload["token_backfilled"] == 1
    assert out_rows[0]["yes_token_id"] == "yes1"
    assert (runs_dir / "token_coverage_report.md").exists()


def test_dry_run_does_not_write_outputs(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?"}
    ])

    rc = coverage.main(["--runs_dir", str(runs_dir), "--shadow_dir", str(runs_dir / "shadow"), "--dry_run"])

    assert rc == 0
    assert not (runs_dir / "token_coverage_summary.json").exists()
    assert not (runs_dir / "tradable_candidates_with_tokens.csv").exists()


def test_allow_api_lookup_false_does_not_call_network(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    write_candidates(runs_dir / "tradable_candidates.csv", [
        {"market_id": "m1", "question": "Will test happen?"}
    ])

    summary, _ = coverage.improve_coverage(parse_args(runs_dir))

    assert summary["api_lookup_enabled"] is False
    assert summary["api_calls_used"] == 0


def test_no_forbidden_trading_imports():
    tree = ast.parse(Path("scripts/improve_tradable_token_coverage.py").read_text())
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
