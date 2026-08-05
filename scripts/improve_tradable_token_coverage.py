#!/usr/bin/env python3
"""
Trading MVP Step 1 — Improve tradable candidate token coverage.

This script only reads local candidate artifacts and, when explicitly enabled,
uses public Gamma read-only lookup to recover YES/NO CLOB token IDs. It does
not authenticate, sign, place orders, cancel orders, call LLMs, or run
run_paper.py.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from scripts.backfill_shadow_token_ids import (
    GammaLookupStats,
    GammaTokenLookupClient,
    TokenPair,
    build_token_index,
    lookup_token_pair_with_gamma,
    valid_token_id,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Improve token coverage for tradable candidates")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--shadow_dir", type=str, default="runs/shadow")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--allow_api_lookup", action="store_true", default=False)
    parser.add_argument("--max_api_calls", type=int, default=50)
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
        "public_gamma_read_only": True,
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "llm_calls": False,
        "run_paper_invoked": False,
        "private_key_handling": False,
        "tiny_live_recommendation": "NO",
    }


def load_candidate_rows(runs_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    preferred = runs_dir / "tradable_candidates_with_tokens.csv"
    fallback = runs_dir / "tradable_candidates.csv"
    path = preferred if preferred.exists() else fallback
    if not path.exists():
        return path, []
    with open(path, newline="") as f:
        return path, list(csv.DictReader(f))


def row_has_valid_tokens(row: dict[str, Any]) -> bool:
    market_id = str(row.get("market_id") or "")
    return (
        valid_token_id(str(row.get("yes_token_id") or ""), market_id)
        and valid_token_id(str(row.get("no_token_id") or ""), market_id)
    )


def seed_index_from_rows(rows: list[dict[str, Any]], token_index: dict[str, TokenPair]) -> None:
    for row in rows:
        market_id = str(row.get("market_id") or "")
        yes = str(row.get("yes_token_id") or "")
        no = str(row.get("no_token_id") or "")
        if market_id and market_id not in token_index and valid_token_id(yes, market_id) and valid_token_id(no, market_id):
            token_index[market_id] = TokenPair(market_id, yes, no, "tradable_candidates_with_tokens")


def lookup_missing_candidates(
    rows: list[dict[str, Any]],
    token_index: dict[str, TokenPair],
    client: Any,
    max_api_calls: int,
) -> GammaLookupStats:
    stats = GammaLookupStats()
    for row in rows:
        market_id = str(row.get("market_id") or "")
        if not market_id or market_id in token_index:
            continue
        if getattr(client, "api_calls_used", stats.api_calls_used) >= max_api_calls:
            break
        pair, error = lookup_token_pair_with_gamma(market_id, str(row.get("question") or ""), client)
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


def backfill_candidate_rows(rows: list[dict[str, Any]], token_index: dict[str, TokenPair]) -> tuple[list[dict[str, Any]], int, int]:
    updated: list[dict[str, Any]] = []
    token_backfilled = 0
    still_missing = 0
    for row in rows:
        payload = dict(row)
        market_id = str(payload.get("market_id") or "")
        pair = token_index.get(market_id)
        had_tokens = row_has_valid_tokens(payload)
        if pair:
            payload["yes_token_id"] = pair.yes_token_id
            payload["no_token_id"] = pair.no_token_id
            payload["token_id_source"] = pair.source
            if not had_tokens:
                token_backfilled += 1
        else:
            payload.setdefault("yes_token_id", "")
            payload.setdefault("no_token_id", "")
            payload["token_id_source"] = "missing_token_id"
            still_missing += 1
        updated.append(payload)
    return updated, token_backfilled, still_missing


def output_files(runs_dir: Path) -> dict[str, str]:
    return {
        "token_coverage_summary_json": str(runs_dir / "token_coverage_summary.json"),
        "token_coverage_report_md": str(runs_dir / "token_coverage_report.md"),
        "tradable_candidates_with_tokens_csv": str(runs_dir / "tradable_candidates_with_tokens.csv"),
    }


def build_summary(
    started: datetime,
    rows: list[dict[str, Any]],
    updated_rows: list[dict[str, Any]],
    token_backfilled: int,
    still_missing: int,
    candidate_file: Path,
    api_lookup_enabled: bool,
    index_markets_scanned: int,
    token_pairs_found: int,
    gamma_stats: GammaLookupStats,
    errors: list[dict[str, str]],
    runs_dir: Path,
) -> dict[str, Any]:
    ended = datetime.utcnow()
    candidates_with_tokens = sum(1 for row in updated_rows if row_has_valid_tokens(row))
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "candidate_file": str(candidate_file),
        "candidates_loaded": len(rows),
        "candidates_with_tokens": candidates_with_tokens,
        "token_backfilled": token_backfilled,
        "still_missing_token": still_missing,
        "token_coverage_ratio": (candidates_with_tokens / len(rows)) if rows else 0.0,
        "markets_scanned": index_markets_scanned,
        "token_pairs_found": token_pairs_found,
        "api_lookup_enabled": api_lookup_enabled,
        "api_calls_used": gamma_stats.api_calls_used,
        "api_lookup_successes": gamma_stats.api_lookup_successes,
        "api_lookup_failures": gamma_stats.api_lookup_failures,
        "ambiguous_market_matches": gamma_stats.ambiguous_market_matches,
        "ambiguous_outcome_mappings": gamma_stats.ambiguous_outcome_mappings,
        "unsupported_market_structures": gamma_stats.unsupported_market_structures,
        "market_lookup_not_found": gamma_stats.market_lookup_not_found,
        "output_files": output_files(runs_dir),
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": "NO",
        "errors": errors + gamma_stats.errors,
    }


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    for key in ["yes_token_id", "no_token_id", "token_id_source"]:
        if key not in fields:
            fields.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Token Coverage Report",
        "",
        f"Generated at: `{summary['ended_at']}`",
        "",
        "This is a public read-only token coverage step. It is not trading.",
        "Token IDs are never guessed, and market_id is never used as a token_id.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "candidates_loaded",
        "candidates_with_tokens",
        "token_backfilled",
        "still_missing_token",
        "token_coverage_ratio",
        "api_calls_used",
        "api_lookup_successes",
        "api_lookup_failures",
        "ambiguous_market_matches",
        "ambiguous_outcome_mappings",
        "unsupported_market_structures",
        "market_lookup_not_found",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        f"Tiny live recommendation: **{summary.get('tiny_live_recommendation', 'NO')}**",
        "",
        "## Safety Verification",
        "",
        json.dumps(summary["safety_verification"], indent=2),
        "",
    ])
    path.write_text("\n".join(lines))


def improve_coverage(
    args: argparse.Namespace,
    api_client: Optional[Any] = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = datetime.utcnow()
    runs_dir = Path(args.runs_dir)
    shadow_dir = Path(args.shadow_dir)
    candidate_file, rows = load_candidate_rows(runs_dir)
    index_result = build_token_index(runs_dir, shadow_dir)
    token_index = dict(index_result.token_index)
    seed_index_from_rows(rows, token_index)
    errors = list(index_result.errors)

    gamma_stats = GammaLookupStats()
    if args.allow_api_lookup:
        client = api_client or GammaTokenLookupClient(
            timeout_seconds=args.api_timeout_seconds,
            max_api_calls=args.max_api_calls,
            cache_file=Path(args.api_cache_file) if args.api_cache_file else None,
        )
        gamma_stats = lookup_missing_candidates(rows, token_index, client, args.max_api_calls)

    updated_rows, token_backfilled, still_missing = backfill_candidate_rows(rows, token_index)
    summary = build_summary(
        started=started,
        rows=rows,
        updated_rows=updated_rows,
        token_backfilled=token_backfilled,
        still_missing=still_missing,
        candidate_file=candidate_file,
        api_lookup_enabled=bool(args.allow_api_lookup),
        index_markets_scanned=index_result.markets_scanned,
        token_pairs_found=len(token_index),
        gamma_stats=gamma_stats,
        errors=errors,
        runs_dir=runs_dir,
    )
    return summary, updated_rows


def write_outputs(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    files = summary["output_files"]
    write_rows_csv(Path(files["tradable_candidates_with_tokens_csv"]), rows)
    write_summary(Path(files["token_coverage_summary_json"]), summary)
    write_report(Path(files["token_coverage_report_md"]), summary)


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: tradable token coverage" if dry_run else "Tradable token coverage")
    for key in [
        "candidates_loaded",
        "candidates_with_tokens",
        "token_backfilled",
        "still_missing_token",
        "api_lookup_enabled",
        "api_calls_used",
        "api_lookup_successes",
        "api_lookup_failures",
        "ambiguous_market_matches",
        "ambiguous_outcome_mappings",
        "unsupported_market_structures",
        "market_lookup_not_found",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    summary, rows = improve_coverage(args)
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    write_outputs(summary, rows)
    print(f"token_coverage_summary_json: {summary['output_files']['token_coverage_summary_json']}")
    print(f"token_coverage_report_md: {summary['output_files']['token_coverage_report_md']}")
    print(f"tradable_candidates_with_tokens_csv: {summary['output_files']['tradable_candidates_with_tokens_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
