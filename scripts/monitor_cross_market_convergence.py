#!/usr/bin/env python3
"""Trading MVP Step 9D — read-only cross-market convergence monitor.

This script observes high-confidence duplicate cross-market candidates over
time and only marks candidates as shadow-entry eligible when the price gap
shows repeated convergence. It never authenticates, signs, places orders,
cancels orders, calls LLMs, invokes run_paper.py, or touches live config.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

import httpx

from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.shadow.cross_market_convergence import CrossMarketConvergenceObservation
from scripts.discover_cross_market_edges import EDGE_TYPE, mid_price, price_levels
from scripts.discover_executable_edges import (
    TokenPair,
    extract_token_pair,
    verify_safety,
)
from scripts.run_shadow_paper_loop import safe_bool, safe_float

STATUS_HIGH_DUPLICATE = "high_confidence_duplicate"

CONVERGENCE_FIELDS = [
    "convergence_gate_passed",
    "convergence_score",
    "convergence_status",
    "convergence_reason",
    "convergence_observation_count",
    "initial_price_gap",
    "final_price_gap",
    "gap_change",
]


class GammaMarketLookupClient:
    """Public read-only Gamma market lookup with no authentication."""

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, base_url: str = BASE_URL, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_market(self, market_id_value: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.get(f"/markets/{market_id_value}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor cross-market price-gap convergence")
    parser.add_argument("--duration_minutes", type=int, default=30)
    parser.add_argument("--interval_seconds", type=int, default=60)
    parser.add_argument("--max_candidates", type=int, default=20)
    parser.add_argument("--min_convergence_score", type=float, default=0.5)
    parser.add_argument("--min_observations", type=int, default=3)
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--run_id", type=str, default="")
    parser.add_argument("--append", action="store_true", default=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_observations_jsonl(path: Path) -> list[CrossMarketConvergenceObservation]:
    if not path.exists():
        return []
    observations: list[CrossMarketConvergenceObservation] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            observations.append(CrossMarketConvergenceObservation.from_dict(payload))
    return observations


def select_candidates(rows: list[dict[str, str]], max_candidates: int) -> list[dict[str, str]]:
    selected = [
        row for row in rows
        if str(row.get("edge_type") or "") == EDGE_TYPE
        and str(row.get("relationship_status") or "") == STATUS_HIGH_DUPLICATE
    ]
    selected.sort(
        key=lambda row: (
            safe_float(row.get("relationship_confidence")),
            safe_float(row.get("price_gap")),
            safe_float(row.get("liquidity_score")),
        ),
        reverse=True,
    )
    return selected[:max_candidates] if max_candidates > 0 else selected


def build_token_index(rows: list[dict[str, str]]) -> dict[str, TokenPair]:
    index: dict[str, TokenPair] = {}
    for row in rows:
        mid = str(row.get("market_id") or "")
        yes = str(row.get("yes_token_id") or "")
        no = str(row.get("no_token_id") or "")
        if mid and yes and no and yes != mid and no != mid:
            index[mid] = TokenPair(yes, no)
        ref_mid = str(row.get("reference_market_id") or "")
        ref_yes = str(row.get("reference_yes_token_id") or "")
        ref_no = str(row.get("reference_no_token_id") or "")
        if ref_mid and ref_yes and ref_no and ref_yes != ref_mid and ref_no != ref_mid:
            index[ref_mid] = TokenPair(ref_yes, ref_no)
    return index


async def resolve_token_pair(
    market_id_value: str,
    token_index: dict[str, TokenPair],
    gamma_client: Any,
) -> tuple[TokenPair | None, str]:
    if market_id_value in token_index:
        return token_index[market_id_value], ""
    try:
        market = await gamma_client.fetch_market(market_id_value)
    except Exception as exc:
        return None, f"gamma_lookup_error:{exc}"
    if not market:
        return None, "market_lookup_not_found"
    pair, error = extract_token_pair(market)
    if pair:
        token_index[market_id_value] = pair
    return pair, error


def row_side_price(row: dict[str, Any]) -> float:
    side = str(row.get("side") or "YES").upper()
    if side == "NO":
        return safe_float(row.get("no_best_ask") or row.get("entry_no_best_ask") or row.get("entry_price"))
    return safe_float(row.get("yes_best_ask") or row.get("entry_yes_best_ask") or row.get("entry_price"))


def row_exit_bid(row: dict[str, Any]) -> float:
    side = str(row.get("side") or "YES").upper()
    if side == "NO":
        return safe_float(row.get("no_best_bid") or row.get("entry_no_best_bid"))
    return safe_float(row.get("yes_best_bid") or row.get("entry_yes_best_bid"))


async def observe_candidate(
    row: dict[str, str],
    observation_index: int,
    run_id: str,
    token_index: dict[str, TokenPair],
    gamma_client: Any,
    clob_client: Any,
) -> CrossMarketConvergenceObservation:
    timestamp = datetime.utcnow().isoformat()
    mid = str(row.get("market_id") or "")
    ref_mid = str(row.get("reference_market_id") or "")
    relationship_confidence = safe_float(row.get("relationship_confidence"))
    relationship_status = str(row.get("relationship_status") or "")
    side = str(row.get("side") or "YES").upper()

    pair, pair_error = await resolve_token_pair(mid, token_index, gamma_client)
    ref_pair, ref_error = await resolve_token_pair(ref_mid, token_index, gamma_client)
    if not pair or not ref_pair:
        return CrossMarketConvergenceObservation(
            timestamp=timestamp,
            group_id=str(row.get("group_id") or ""),
            market_id=mid,
            reference_market_id=ref_mid,
            question=str(row.get("question") or ""),
            reference_question=str(row.get("reference_question") or ""),
            side=side,
            entry_price=row_side_price(row),
            reference_price=safe_float(row.get("reference_price")),
            price_gap=safe_float(row.get("price_gap")),
            spread=safe_float(row.get("spread")),
            depth=safe_float(row.get("orderbook_depth")),
            liquidity=safe_float(row.get("liquidity_score")),
            relationship_confidence=relationship_confidence,
            relationship_status=relationship_status,
            observation_index=observation_index,
            stale=True,
            error=pair_error or ref_error or "missing_token_id",
            run_id=run_id,
        )

    try:
        yes_book, no_book = await clob_client.get_market_orderbook(pair.yes_token_id, pair.no_token_id)
        ref_yes_book, ref_no_book = await clob_client.get_market_orderbook(ref_pair.yes_token_id, ref_pair.no_token_id)
    except Exception as exc:
        return CrossMarketConvergenceObservation(
            timestamp=timestamp,
            group_id=str(row.get("group_id") or ""),
            market_id=mid,
            reference_market_id=ref_mid,
            question=str(row.get("question") or ""),
            reference_question=str(row.get("reference_question") or ""),
            side=side,
            entry_price=row_side_price(row),
            reference_price=safe_float(row.get("reference_price")),
            price_gap=safe_float(row.get("price_gap")),
            spread=safe_float(row.get("spread")),
            depth=safe_float(row.get("orderbook_depth")),
            liquidity=safe_float(row.get("liquidity_score")),
            relationship_confidence=relationship_confidence,
            relationship_status=relationship_status,
            observation_index=observation_index,
            stale=True,
            error=f"clob_lookup_error:{exc}",
            run_id=run_id,
        )

    yes = price_levels(yes_book)
    no = price_levels(no_book)
    ref_yes = price_levels(ref_yes_book)
    ref_no = price_levels(ref_no_book)
    entry_features = no if side == "NO" else yes
    ref_features = ref_no if side == "NO" else ref_yes
    entry_price = entry_features["best_ask"]
    reference_price = mid_price(ref_features)
    price_gap = max(0.0, reference_price - mid_price(entry_features))
    spread = max(yes["spread"], no["spread"])
    depth = yes["depth"] + no["depth"]
    liquidity = yes["liquidity"] + no["liquidity"]
    stale = not entry_price or not row_exit_bid({
        "side": side,
        "yes_best_bid": yes["best_bid"],
        "no_best_bid": no["best_bid"],
    }) or not reference_price
    return CrossMarketConvergenceObservation(
        timestamp=timestamp,
        group_id=str(row.get("group_id") or ""),
        market_id=mid,
        reference_market_id=ref_mid,
        question=str(row.get("question") or ""),
        reference_question=str(row.get("reference_question") or ""),
        side=side,
        entry_price=entry_price,
        reference_price=reference_price,
        price_gap=price_gap,
        spread=spread,
        depth=depth,
        liquidity=liquidity,
        relationship_confidence=relationship_confidence,
        relationship_status=relationship_status,
        observation_index=observation_index,
        stale=stale,
        error="stale_orderbook" if stale else "",
        run_id=run_id,
    )


def convergence_metrics(
    observations: list[CrossMarketConvergenceObservation],
    min_observations: int,
    min_convergence_score: float,
) -> dict[str, Any]:
    valid = [obs for obs in observations if not obs.stale and not obs.error]
    if len(valid) < min_observations:
        initial = valid[0].price_gap if valid else (observations[0].price_gap if observations else 0.0)
        final = valid[-1].price_gap if valid else initial
        return {
            "gate_passed": False,
            "status": "insufficient_convergence_observations",
            "reason": "insufficient_convergence_observations",
            "observation_count": len(valid),
            "initial_price_gap": initial,
            "final_price_gap": final,
            "gap_change": final - initial,
            "convergence_score": 0.0,
        }
    gaps = [obs.price_gap for obs in valid]
    initial = gaps[0]
    final = gaps[-1]
    gap_change = final - initial
    expanded = any(gap > initial for gap in gaps[1:])
    score = max(0.0, (initial - final) / initial) if initial > 0 else 0.0
    if expanded:
        status = "price_gap_expanded"
        reason = "price_gap_not_converging"
    elif final >= initial:
        status = "price_gap_not_converging"
        reason = "price_gap_not_converging"
    elif score < min_convergence_score:
        status = "convergence_score_too_low"
        reason = "price_gap_not_converging"
    else:
        status = "convergence_gate_passed"
        reason = "convergence_gate_passed"
    return {
        "gate_passed": status == "convergence_gate_passed",
        "status": status,
        "reason": reason,
        "observation_count": len(valid),
        "initial_price_gap": initial,
        "final_price_gap": final,
        "gap_change": gap_change,
        "convergence_score": score,
    }


def apply_convergence_gate(
    rows: list[dict[str, str]],
    observations: list[CrossMarketConvergenceObservation],
    min_observations: int,
    min_convergence_score: float,
) -> list[dict[str, Any]]:
    by_market: dict[str, list[CrossMarketConvergenceObservation]] = defaultdict(list)
    for obs in observations:
        by_market[obs.market_id].append(obs)
    gated: list[dict[str, Any]] = []
    for row in rows:
        metrics = convergence_metrics(by_market.get(str(row.get("market_id") or ""), []), min_observations, min_convergence_score)
        output = dict(row)
        output.update({
            "convergence_gate_passed": metrics["gate_passed"],
            "convergence_score": metrics["convergence_score"],
            "convergence_status": metrics["status"],
            "convergence_reason": metrics["reason"],
            "convergence_observation_count": metrics["observation_count"],
            "initial_price_gap": metrics["initial_price_gap"],
            "final_price_gap": metrics["final_price_gap"],
            "gap_change": metrics["gap_change"],
        })
        reasons = [item for item in str(output.get("reasons") or output.get("evidence") or "").split("|") if item]
        reasons = [item for item in reasons if item not in {"convergence_not_observed", "price_gap_not_converging", "insufficient_convergence_observations"}]
        if metrics["gate_passed"]:
            output["recommended_action"] = "shadow_entry"
            output["edge_pass"] = True
            output["edge_failure_reason"] = ""
            output["near_miss_tier"] = "tier1_mispricing"
            reasons.extend(["cross_market_convergence_observed", "convergence_gate_passed"])
        else:
            output["recommended_action"] = "watch_only"
            output["edge_pass"] = False
            output["edge_failure_reason"] = metrics["reason"]
            output["near_miss_tier"] = ""
            reasons.append(metrics["reason"])
        output["entry_decision_hint"] = "eligible_shadow_entry" if metrics["gate_passed"] else "watch_only"
        output["reasons"] = "|".join(dict.fromkeys(reasons))
        output["evidence"] = output["reasons"]
        gated.append(output)
    return gated


def summary_from(
    started: datetime,
    rows: list[dict[str, str]],
    observations: list[CrossMarketConvergenceObservation],
    gated: list[dict[str, Any]],
) -> dict[str, Any]:
    ended = datetime.utcnow()
    initial_gaps = [safe_float(row.get("initial_price_gap")) for row in gated if safe_float(row.get("initial_price_gap")) > 0]
    final_gaps = [safe_float(row.get("final_price_gap")) for row in gated if safe_float(row.get("final_price_gap")) > 0]
    changes = [safe_float(row.get("gap_change")) for row in gated if row.get("gap_change") not in (None, "")]
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "candidates_monitored": len(rows),
        "observations_collected": len(observations),
        "groups_monitored": len({str(row.get("group_id") or "") for row in rows if row.get("group_id")}),
        "convergence_pass_count": sum(1 for row in gated if safe_bool(row.get("convergence_gate_passed"))),
        "convergence_fail_count": sum(1 for row in gated if row.get("convergence_reason") == "price_gap_not_converging"),
        "insufficient_observation_count": sum(1 for row in gated if row.get("convergence_reason") == "insufficient_convergence_observations"),
        "avg_initial_gap": mean(initial_gaps) if initial_gaps else 0.0,
        "avg_final_gap": mean(final_gaps) if final_gaps else 0.0,
        "avg_gap_change": mean(changes) if changes else 0.0,
        "shadow_entry_eligible_count": sum(1 for row in gated if row.get("recommended_action") == "shadow_entry"),
        "watch_only_count": sum(1 for row in gated if row.get("recommended_action") == "watch_only"),
        "rejected_count": sum(1 for row in gated if row.get("recommended_action") == "reject"),
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": "NO",
    }


def write_jsonl(path: Path, observations: list[CrossMarketConvergenceObservation], append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not observations:
        if not path.exists():
            path.write_text("")
        return
    payload = "\n".join(json.dumps(obs.to_dict(), sort_keys=True) for obs in observations) + "\n"
    if append and path.exists():
        with open(path, "a") as f:
            f.write(payload)
    else:
        path.write_text(payload)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    for field in CONVERGENCE_FIELDS:
        if field not in fields:
            fields.append(field)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cross_market_edge_candidates_convergence_gated": rows}, indent=2, sort_keys=True))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cross-Market Convergence Report",
        "",
        f"Generated at: `{summary.get('ended_at')}`",
        "",
        "This is read-only, shadow-only convergence calibration. Price gap alone is not a trading signal.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "candidates_monitored",
        "observations_collected",
        "groups_monitored",
        "convergence_pass_count",
        "convergence_fail_count",
        "insufficient_observation_count",
        "avg_initial_gap",
        "avg_final_gap",
        "avg_gap_change",
        "shadow_entry_eligible_count",
        "watch_only_count",
        "rejected_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        "Tiny live recommendation: **NO**",
        "",
        "## Safety Verification",
        "",
        "```json",
        json.dumps(summary.get("safety_verification", {}), indent=2, sort_keys=True),
        "```",
        "",
    ])
    path.write_text("\n".join(lines))


async def monitor_convergence(
    args: argparse.Namespace,
    gamma_client: Any | None = None,
    clob_client: Any | None = None,
) -> tuple[list[CrossMarketConvergenceObservation], list[dict[str, Any]], dict[str, Any]]:
    started = datetime.utcnow()
    output_dir = Path(args.output_dir)
    run_id = args.run_id or f"cross_market_convergence_{started.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    rows = select_candidates(load_csv(output_dir / "cross_market_edge_candidates_calibrated.csv"), args.max_candidates)
    if args.dry_run:
        gated = apply_convergence_gate(rows, [], args.min_observations, args.min_convergence_score)
        summary = summary_from(started, rows, [], gated)
        summary["run_id"] = run_id
        summary["append_enabled"] = bool(args.append)
        summary["resume_enabled"] = bool(args.resume)
        return [], gated, summary

    gamma = gamma_client or GammaMarketLookupClient()
    clob = clob_client or CLOBReadOnlyClient(max_retries=1)
    close_clob = clob_client is None
    token_index = build_token_index(load_csv(output_dir / "cross_market_edge_candidates_calibrated.csv"))
    existing_observations = load_observations_jsonl(output_dir / "cross_market_convergence_observations.jsonl") if args.resume else []
    observations: list[CrossMarketConvergenceObservation] = []
    try:
        total_seconds = max(0, args.duration_minutes * 60)
        intervals = max(args.min_observations, int(total_seconds / max(1, args.interval_seconds)) + 1)
        for observation_index in range(intervals):
            for row in rows:
                observations.append(await observe_candidate(row, observation_index, run_id, token_index, gamma, clob))
            if observation_index < intervals - 1:
                await asyncio.sleep(max(0, args.interval_seconds))
    finally:
        if close_clob:
            await clob.close()
    observations_for_gate = existing_observations + observations
    gated = apply_convergence_gate(rows, observations_for_gate, args.min_observations, args.min_convergence_score)
    summary = summary_from(started, rows, observations_for_gate, gated)
    summary.update({
        "run_id": run_id,
        "new_observations_collected": len(observations),
        "existing_observations_loaded": len(existing_observations),
        "append_enabled": bool(args.append),
        "resume_enabled": bool(args.resume),
    })
    return observations, gated, summary


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: cross-market convergence monitor" if dry_run else "Cross-market convergence monitor")
    for key in [
        "candidates_monitored",
        "observations_collected",
        "groups_monitored",
        "convergence_pass_count",
        "convergence_fail_count",
        "insufficient_observation_count",
        "avg_initial_gap",
        "avg_final_gap",
        "avg_gap_change",
        "shadow_entry_eligible_count",
        "watch_only_count",
        "rejected_count",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    observations, gated, summary = asyncio.run(monitor_convergence(args))
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    write_jsonl(output_dir / "cross_market_convergence_observations.jsonl", observations, append=args.append)
    write_summary(output_dir / "cross_market_convergence_summary.json", summary)
    write_report(output_dir / "cross_market_convergence_report.md", summary)
    write_csv(output_dir / "cross_market_edge_candidates_convergence_gated.csv", gated)
    write_json(output_dir / "cross_market_edge_candidates_convergence_gated.json", gated)
    print(f"cross_market_convergence_observations_jsonl: {output_dir / 'cross_market_convergence_observations.jsonl'}")
    print(f"cross_market_convergence_summary_json: {output_dir / 'cross_market_convergence_summary.json'}")
    print(f"cross_market_convergence_report_md: {output_dir / 'cross_market_convergence_report.md'}")
    print(f"cross_market_edge_candidates_convergence_gated_csv: {output_dir / 'cross_market_edge_candidates_convergence_gated.csv'}")
    print(f"cross_market_edge_candidates_convergence_gated_json: {output_dir / 'cross_market_edge_candidates_convergence_gated.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
