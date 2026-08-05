#!/usr/bin/env python3
"""
Phase 8G — Token ID backfill for shadow positions.

By default this script only reads local run artifacts. Public Gamma lookup is
enabled only with --allow_api_lookup. It never calls CLOB, LLMs, run_paper.py,
authenticated APIs, or execution modules.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

import scripts.collect_shadow_forward_data as collector
import scripts.build_tradable_candidates as tradable_script
from polysignal.shadow.models import SHADOW_TRADE_FIELDS, ShadowTrade
from polysignal.shadow.reporter import write_shadow_positions_json, write_shadow_trades_csv


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class TokenPair:
    market_id: str
    yes_token_id: str
    no_token_id: str
    source: str


@dataclass
class TokenIndexResult:
    token_index: dict[str, TokenPair]
    markets_scanned: int
    errors: list[dict[str, str]]


@dataclass
class GammaLookupStats:
    api_calls_used: int = 0
    api_lookup_successes: int = 0
    api_lookup_failures: int = 0
    ambiguous_market_matches: int = 0
    ambiguous_outcome_mappings: int = 0
    unsupported_market_structures: int = 0
    market_lookup_not_found: int = 0
    errors: list[dict[str, str]] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


class GammaTokenLookupClient:
    """Public read-only Gamma lookup client with no authentication."""

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        max_api_calls: int = 20,
        base_url: str = BASE_URL,
        cache_file: Optional[Path] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_api_calls = max_api_calls
        self.base_url = base_url.rstrip("/")
        self.cache_file = cache_file
        self.api_calls_used = 0
        self._cache: dict[str, Any] = self._load_cache(cache_file)

    def _load_cache(self, cache_file: Optional[Path]) -> dict[str, Any]:
        if not cache_file or not cache_file.exists() or cache_file.stat().st_size == 0:
            return {}
        try:
            data = json.loads(cache_file.read_text())
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self) -> None:
        if not self.cache_file:
            return
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self._cache, indent=2, sort_keys=True))

    def _get_json(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> Any:
        if self.api_calls_used >= self.max_api_calls:
            raise RuntimeError("max_api_calls_exceeded")
        cache_key = json.dumps({"endpoint": endpoint, "params": params or {}}, sort_keys=True)
        if cache_key in self._cache:
            return self._cache[cache_key]
        self.api_calls_used += 1
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = client.get(endpoint, params=params)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        self._cache[cache_key] = payload
        self._save_cache()
        return payload

    def lookup_market_by_id(self, market_id: str) -> Optional[dict[str, Any]]:
        data = self._get_json(f"/markets/{market_id}")
        return data if isinstance(data, dict) else None

    def search_market_by_question(self, question: str) -> list[dict[str, Any]]:
        data = self._get_json("/markets", params={"search": question, "limit": 10})
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill YES/NO CLOB token IDs for shadow files")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--allow_api_lookup", action="store_true", default=False)
    parser.add_argument("--rebuild_shadow_positions", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max_api_calls", type=int, default=20)
    parser.add_argument("--api_timeout_seconds", type=float, default=10.0)
    parser.add_argument("--api_cache_file", type=str, default="")
    return parser.parse_args(argv)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def verify_safety(
    risk_path: Path = REPO_ROOT / "config" / "risk.yaml",
    llm_path: Path = REPO_ROOT / "config" / "llm.yaml",
) -> dict[str, Any]:
    risk = load_yaml(risk_path)
    llm = load_yaml(llm_path)
    return {
        "live_trading_enabled": bool(risk.get("live_trading_enabled")),
        "allow_auto_execution": bool(risk.get("allow_auto_execution")),
        "paper_trading_enabled": bool(risk.get("paper_trading_enabled")),
        "default_llm_provider": llm.get("provider"),
        "offline_only": True,
        "api_lookup_default_enabled": False,
        "network_calls": False,
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "llm_calls": False,
        "run_paper_invoked": False,
        "private_key_handling": False,
    }


def discover_token_metadata_files(runs_dir: Path, shadow_dir: Path) -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted(runs_dir.glob("run_*/events.jsonl")))
    paths.extend(sorted(runs_dir.glob("run_*/summary.json")))
    paths.extend([
        runs_dir / "tradable_candidates.csv",
        runs_dir / "tradable_candidates.json",
        runs_dir / "market_trajectories.json",
        shadow_dir / "shadow_trades.csv",
        shadow_dir / "updated_shadow_trades.csv",
        shadow_dir / "shadow_positions.json",
        shadow_dir / "updated_shadow_positions.json",
        runs_dir / "persistent_watchlist.csv",
        runs_dir / "alpha_candidates.csv",
        runs_dir / "watchlist_validation.csv",
    ])
    return [path for path in paths if path.exists()]


def build_token_index(runs_dir: Path, shadow_dir: Path) -> TokenIndexResult:
    index: dict[str, TokenPair] = {}
    markets_seen: set[str] = set()
    errors: list[dict[str, str]] = []
    partials: dict[str, dict[str, str]] = {}

    for path in discover_token_metadata_files(runs_dir, shadow_dir):
        try:
            records = load_records(path)
        except Exception as exc:
            errors.append({"file": str(path), "error": str(exc)})
            continue
        for record in records:
            market_id = get_market_id(record)
            if market_id:
                markets_seen.add(market_id)
            pair = extract_token_pair(record, str(path))
            if pair and pair.market_id not in index:
                index[pair.market_id] = pair
                continue
            update_partial_tokens(record, partials)

    for market_id, values in partials.items():
        if market_id in index:
            continue
        yes = values.get("yes_token_id", "")
        no = values.get("no_token_id", "")
        if valid_token_id(yes, market_id) and valid_token_id(no, market_id):
            index[market_id] = TokenPair(market_id, yes, no, values.get("source", "partial_token_records"))

    return TokenIndexResult(index, len(markets_seen), errors)


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".csv":
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    if path.suffix == ".jsonl":
        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.extend(iter_dicts(json.loads(line)))
            except json.JSONDecodeError:
                continue
        return rows
    if path.suffix == ".json":
        if path.stat().st_size == 0:
            return []
        return iter_dicts(json.loads(path.read_text()))
    return []


def iter_dicts(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(value, dict):
        records.append(value)
        for item in value.values():
            records.extend(iter_dicts(item))
    elif isinstance(value, list):
        for item in value:
            records.extend(iter_dicts(item))
    return records


def get_market_id(record: dict[str, Any]) -> str:
    return str(
        record.get("market_id")
        or record.get("market")
        or record.get("id")
        or record.get("condition_id")
        or ""
    )


def extract_token_pair(record: dict[str, Any], source: str) -> Optional[TokenPair]:
    market_id = get_market_id(record)
    if not market_id:
        return None

    explicit_pairs = [
        ("yes_token_id", "no_token_id"),
        ("yes_token_address", "no_token_address"),
        ("yes_clob_token_id", "no_clob_token_id"),
        ("yes_asset_id", "no_asset_id"),
        ("yes_token", "no_token"),
    ]
    for yes_field, no_field in explicit_pairs:
        yes = str(record.get(yes_field) or "")
        no = str(record.get(no_field) or "")
        if valid_token_id(yes, market_id) and valid_token_id(no, market_id):
            return TokenPair(market_id, yes, no, source)

    token_ids = coerce_list(record.get("clobTokenIds") or record.get("clob_token_ids"))
    outcomes = coerce_list(record.get("outcomes"))
    if len(token_ids) >= 2:
        yes, no = token_pair_from_outcomes(token_ids, outcomes)
        if valid_token_id(yes, market_id) and valid_token_id(no, market_id):
            return TokenPair(market_id, yes, no, source)

    return None


def update_partial_tokens(record: dict[str, Any], partials: dict[str, dict[str, str]]) -> None:
    market_id = get_market_id(record)
    if not market_id:
        return
    token_id = str(record.get("token_id") or record.get("asset_id") or "")
    outcome = str(record.get("outcome") or record.get("side") or "").strip().lower()
    if not valid_token_id(token_id, market_id) or outcome not in {"yes", "no"}:
        return
    payload = partials.setdefault(market_id, {"source": "token_id_outcome_records"})
    payload[f"{outcome}_token_id"] = token_id


def valid_token_id(token_id: str, market_id: str) -> bool:
    token = str(token_id or "").strip()
    market = str(market_id or "").strip()
    return bool(token and token != market)


def coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except json.JSONDecodeError:
            pass
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def token_pair_from_outcomes(token_ids: list[Any], outcomes: list[Any]) -> tuple[str, str]:
    if outcomes and len(outcomes) == len(token_ids):
        yes = ""
        no = ""
        for token_id, outcome in zip(token_ids, outcomes):
            normalized = str(outcome).strip().lower()
            if normalized == "yes":
                yes = str(token_id)
            elif normalized == "no":
                no = str(token_id)
        if yes and no:
            return yes, no
    return str(token_ids[0]), str(token_ids[1])


def normalize_question(value: str) -> str:
    return " ".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in str(value or "")).split()
    )


def extract_gamma_token_pair(payload: dict[str, Any], expected_market_id: str, source: str = "gamma_api") -> tuple[Optional[TokenPair], Optional[str]]:
    market_id = get_market_id(payload)
    if str(market_id) != str(expected_market_id):
        return None, "ambiguous_market_match"
    token_ids = coerce_list(payload.get("clobTokenIds") or payload.get("clob_token_ids"))
    outcomes = coerce_list(payload.get("outcomes"))
    if len(token_ids) != 2:
        return None, "unsupported_market_structure"
    if len(outcomes) != 2:
        return None, "ambiguous_outcome_mapping"
    normalized = [str(outcome).strip().lower() for outcome in outcomes]
    if set(normalized) != {"yes", "no"}:
        return None, "ambiguous_outcome_mapping"
    yes, no = token_pair_from_outcomes(token_ids, outcomes)
    if not valid_token_id(yes, expected_market_id) or not valid_token_id(no, expected_market_id):
        return None, "ambiguous_outcome_mapping"
    return TokenPair(str(expected_market_id), yes, no, source), None


def lookup_token_pair_with_gamma(
    market_id: str,
    question: str,
    client: Any,
) -> tuple[Optional[TokenPair], Optional[str]]:
    try:
        payload = client.lookup_market_by_id(market_id)
    except Exception as exc:
        return None, f"api_error:{exc}"

    if payload:
        if str(get_market_id(payload)) != str(market_id):
            return None, "ambiguous_market_match"
        payload_question = str(payload.get("question") or payload.get("title") or "")
        if question and payload_question and normalize_question(question) != normalize_question(payload_question):
            return None, "ambiguous_market_match"
        return extract_gamma_token_pair(payload, market_id)

    if question:
        try:
            matches = client.search_market_by_question(question)
        except Exception as exc:
            return None, f"api_error:{exc}"
        exact = [
            item for item in matches
            if normalize_question(str(item.get("question") or item.get("title") or "")) == normalize_question(question)
        ]
        if len(exact) == 1:
            if str(get_market_id(exact[0])) != str(market_id):
                return None, "ambiguous_market_match"
            return extract_gamma_token_pair(exact[0], market_id)
        if len(exact) > 1 or matches:
            return None, "ambiguous_market_match"

    return None, "market_lookup_not_found"


def lookup_missing_token_pairs(
    token_index: dict[str, TokenPair],
    trades: list[ShadowTrade],
    tradable_rows: list[dict[str, Any]],
    client: Any,
    max_api_calls: int,
) -> GammaLookupStats:
    stats = GammaLookupStats()
    requested: dict[str, str] = {}
    for trade in trades:
        if trade.market_id not in token_index:
            requested.setdefault(trade.market_id, trade.question)
    for row in tradable_rows:
        market_id = str(row.get("market_id") or "")
        if market_id and market_id not in token_index:
            requested.setdefault(market_id, str(row.get("question") or ""))

    for market_id, question in requested.items():
        if getattr(client, "api_calls_used", stats.api_calls_used) >= max_api_calls:
            break
        pair, error = lookup_token_pair_with_gamma(market_id, question, client)
        stats.api_calls_used = getattr(client, "api_calls_used", stats.api_calls_used)
        if pair:
            token_index[pair.market_id] = pair
            stats.api_lookup_successes += 1
            continue
        stats.api_lookup_failures += 1
        if error == "ambiguous_market_match":
            stats.ambiguous_market_matches += 1
        elif error == "ambiguous_outcome_mapping":
            stats.ambiguous_outcome_mappings += 1
        elif error == "unsupported_market_structure":
            stats.unsupported_market_structures += 1
        elif error == "market_lookup_not_found":
            stats.market_lookup_not_found += 1
        stats.errors.append({"market_id": market_id, "error": error or "unknown_api_lookup_error"})
    return stats


def load_tradable_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def backfill_rows(rows: list[dict[str, Any]], token_index: dict[str, TokenPair]) -> tuple[list[dict[str, Any]], int, int]:
    updated: list[dict[str, Any]] = []
    backfilled = 0
    missing = 0
    for row in rows:
        payload = dict(row)
        market_id = str(payload.get("market_id") or "")
        pair = token_index.get(market_id)
        if pair:
            if not payload.get("yes_token_id"):
                payload["yes_token_id"] = pair.yes_token_id
            if not payload.get("no_token_id"):
                payload["no_token_id"] = pair.no_token_id
            backfilled += 1
        else:
            payload.setdefault("yes_token_id", "")
            payload.setdefault("no_token_id", "")
            missing += 1
        updated.append(payload)
    return updated, backfilled, missing


def load_shadow_trades(path: Path) -> list[ShadowTrade]:
    return collector.load_shadow_trades(path)


def backfill_trades(trades: list[ShadowTrade], token_index: dict[str, TokenPair]) -> tuple[list[ShadowTrade], int, int]:
    backfilled = 0
    missing = 0
    for trade in trades:
        pair = token_index.get(trade.market_id)
        if pair:
            trade.yes_token_id = trade.yes_token_id or pair.yes_token_id
            trade.no_token_id = trade.no_token_id or pair.no_token_id
            backfilled += 1
        else:
            missing += 1
    return trades, backfilled, missing


def write_rows_csv(path: Path, rows: list[dict[str, Any]], preferred_fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(preferred_fields)
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def run_backfill(
    args: argparse.Namespace,
    api_client: Optional[Any] = None,
) -> tuple[dict[str, Any], dict[str, str], list[ShadowTrade], list[dict[str, Any]]]:
    started = datetime.utcnow()
    runs_dir = Path(args.runs_dir)
    shadow_dir = Path(args.shadow_dir)
    safety = verify_safety()
    if args.allow_api_lookup:
        safety["network_calls"] = True
    errors: list[dict[str, str]] = []

    index_result = build_token_index(runs_dir, shadow_dir)
    errors.extend(index_result.errors)

    tradable_rows = load_tradable_rows(runs_dir / "tradable_candidates.csv")
    shadow_trades_path = shadow_dir / "shadow_trades.csv"
    trades = load_shadow_trades(shadow_trades_path)

    gamma_stats = GammaLookupStats()
    if args.allow_api_lookup:
        client = api_client or GammaTokenLookupClient(
            timeout_seconds=args.api_timeout_seconds,
            max_api_calls=args.max_api_calls,
            cache_file=Path(args.api_cache_file) if args.api_cache_file else None,
        )
        gamma_stats = lookup_missing_token_pairs(
            index_result.token_index,
            trades,
            tradable_rows,
            client,
            args.max_api_calls,
        )
        errors.extend(gamma_stats.errors)

    tradable_with_tokens, tradable_backfilled, tradable_missing = backfill_rows(
        tradable_rows,
        index_result.token_index,
    )

    trades_with_tokens, shadow_backfilled, shadow_missing = backfill_trades(
        trades,
        index_result.token_index,
    )

    output_files = {
        "token_id_backfill_summary_json": str(shadow_dir / "token_id_backfill_summary.json"),
        "tradable_candidates_with_tokens_csv": str(runs_dir / "tradable_candidates_with_tokens.csv"),
        "shadow_trades_with_tokens_csv": str(shadow_dir / "shadow_trades_with_tokens.csv"),
        "updated_shadow_positions_json": str(shadow_dir / "updated_shadow_positions.json"),
    }
    ended = datetime.utcnow()
    summary = {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "markets_scanned": index_result.markets_scanned,
        "token_pairs_found": len(index_result.token_index),
        "shadow_trades_loaded": len(trades),
        "shadow_trades_backfilled": shadow_backfilled,
        "shadow_trades_missing_token_id": shadow_missing,
        "tradable_candidates_loaded": len(tradable_rows),
        "tradable_candidates_backfilled": tradable_backfilled,
        "tradable_candidates_missing_token_id": tradable_missing,
        "api_lookup_enabled": bool(args.allow_api_lookup),
        "api_calls_used": gamma_stats.api_calls_used,
        "api_lookup_successes": gamma_stats.api_lookup_successes,
        "api_lookup_failures": gamma_stats.api_lookup_failures,
        "ambiguous_market_matches": gamma_stats.ambiguous_market_matches,
        "ambiguous_outcome_mappings": gamma_stats.ambiguous_outcome_mappings,
        "unsupported_market_structures": gamma_stats.unsupported_market_structures,
        "market_lookup_not_found": gamma_stats.market_lookup_not_found,
        "output_files": output_files,
        "safety_verification": safety,
        "errors": errors,
    }
    return summary, output_files, trades_with_tokens, tradable_with_tokens


def write_outputs(
    summary: dict[str, Any],
    output_files: dict[str, str],
    trades: list[ShadowTrade],
    tradable_rows: list[dict[str, Any]],
    rebuild_shadow_positions: bool,
) -> None:
    write_rows_csv(
        Path(output_files["tradable_candidates_with_tokens_csv"]),
        tradable_rows,
        tradable_script.TRADABLE_CANDIDATE_FIELDS,
    )
    write_shadow_trades_csv(Path(output_files["shadow_trades_with_tokens_csv"]), trades)
    if rebuild_shadow_positions:
        write_shadow_positions_json(Path(output_files["updated_shadow_positions_json"]), trades)
    Path(output_files["token_id_backfill_summary_json"]).parent.mkdir(parents=True, exist_ok=True)
    Path(output_files["token_id_backfill_summary_json"]).write_text(json.dumps(summary, indent=2, sort_keys=True))


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: shadow token id backfill" if dry_run else "Shadow token id backfill")
    print(f"markets_scanned: {summary['markets_scanned']}")
    print(f"token_pairs_found: {summary['token_pairs_found']}")
    print(f"shadow_trades_loaded: {summary['shadow_trades_loaded']}")
    print(f"shadow_trades_backfilled: {summary['shadow_trades_backfilled']}")
    print(f"shadow_trades_missing_token_id: {summary['shadow_trades_missing_token_id']}")
    print(f"tradable_candidates_loaded: {summary['tradable_candidates_loaded']}")
    print(f"tradable_candidates_backfilled: {summary['tradable_candidates_backfilled']}")
    print(f"api_lookup_enabled: {summary['api_lookup_enabled']}")
    print(f"api_calls_used: {summary['api_calls_used']}")
    print(f"api_lookup_successes: {summary['api_lookup_successes']}")
    print(f"api_lookup_failures: {summary['api_lookup_failures']}")
    print(f"ambiguous_market_matches: {summary['ambiguous_market_matches']}")
    print(f"ambiguous_outcome_mappings: {summary['ambiguous_outcome_mappings']}")
    print(f"unsupported_market_structures: {summary['unsupported_market_structures']}")
    print(f"market_lookup_not_found: {summary['market_lookup_not_found']}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    summary, output_files, trades, tradable_rows = run_backfill(args)
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    write_outputs(summary, output_files, trades, tradable_rows, args.rebuild_shadow_positions)
    for label, path in output_files.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
