#!/usr/bin/env python3
"""Trading MVP Step 9B — offline cross-market relationship calibration.

This script reads Step 9A cross-market candidates and calibrates relationship
confidence using deterministic string/entity heuristics only. It does not call
APIs, LLMs, run_paper.py, authenticated endpoints, or any execution path.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any

from polysignal.utils.time import utc_now
from scripts.discover_cross_market_edges import (
    EDGE_TYPE,
    RELATIONSHIP_DUPLICATE,
    RELATIONSHIP_MUTUALLY_EXCLUSIVE,
    RELATIONSHIP_NEAR_DUPLICATE,
    normalize_question_text,
    question_tokens,
)
from scripts.discover_executable_edges import verify_safety
from scripts.run_shadow_paper_loop import safe_float

STATUS_HIGH_DUPLICATE = "high_confidence_duplicate"
STATUS_MEDIUM_RELATED = "medium_confidence_related"
STATUS_MUTEX_WATCH = "mutually_exclusive_watch"
STATUS_AMBIGUOUS = "ambiguous_relationship"
STATUS_FALSE_MATCH = "likely_false_match"

CONDITIONAL_TERMS = {
    "if",
    "given",
    "assuming",
    "conditional",
    "contingent",
    "unless",
    "provided",
    "after",
    "before",
}
CONFLICTING_TERM_PAIRS = [
    ("democrat", "republican"),
    ("democrats", "republicans"),
    (" d ", " r "),
    ("yes", "no"),
    ("over", "under"),
    ("above", "below"),
    ("more", "less"),
    ("before", "after"),
    ("nomination", "presidency"),
    ("senate", "house"),
]
GENERIC_ENTITY_TERMS = {
    "will",
    "yes",
    "no",
    "the",
    "a",
    "an",
    "in",
    "on",
    "by",
    "of",
    "to",
    "d",
    "r",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate cross-market relationship confidence offline")
    parser.add_argument("--runs_dir", type=str, default="runs")
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument("--min_price_gap", type=float, default=0.05)
    parser.add_argument("--min_relationship_confidence", type=float, default=0.75)
    parser.add_argument("--max_spread", type=float, default=0.05)
    parser.add_argument("--min_depth", type=float, default=1.0)
    parser.add_argument("--min_liquidity", type=float, default=1.0)
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cross_market_edge_candidates_calibrated": rows}, indent=2, sort_keys=True))


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cross-Market Relationship Calibration Report",
        "",
        f"Generated at: `{summary.get('ended_at')}`",
        "",
        "This is offline, read-only, shadow-only relationship calibration.",
        "Price gap alone is not a trading signal.",
        "Probability edge v1/v2 remains quarantined by feedback gates.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "candidates_loaded",
        "groups_loaded",
        "high_confidence_duplicate_count",
        "medium_confidence_related_count",
        "ambiguous_relationship_count",
        "likely_false_match_count",
        "mutually_exclusive_watch_count",
        "shadow_entry_eligible_count",
        "watch_only_count",
        "rejected_count",
        "avg_relationship_confidence",
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


def extract_years(text: str) -> set[str]:
    return set(re.findall(r"\b20\d{2}\b", text or ""))


def extract_named_entities(text: str) -> set[str]:
    entities: set[str] = set()
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3}", text or ""):
        value = match.group(0).strip()
        normalized = normalize_question_text(value)
        parts = normalized.split()
        if parts and parts[0] in GENERIC_ENTITY_TERMS:
            normalized = " ".join(parts[1:])
        if normalized and normalized not in GENERIC_ENTITY_TERMS and len(normalized) > 1:
            entities.add(normalized)
    # Preserve common single-letter political abbreviations as entities when they
    # appear in compact market titles, because D/R swaps are meaningful conflicts.
    for token in re.findall(r"\b[DRAI]\b", text or ""):
        entities.add(token.lower())
    return entities


def normalized_similarity(question: str, reference_question: str) -> float:
    q = normalize_question_text(question)
    ref = normalize_question_text(reference_question)
    if not q or not ref:
        return 0.0
    return SequenceMatcher(None, q, ref).ratio()


def shared_event_keywords(question: str, reference_question: str) -> set[str]:
    return question_tokens(question) & question_tokens(reference_question)


def has_conditional_language(question: str, reference_question: str) -> bool:
    tokens = set(normalize_question_text(question).split()) | set(normalize_question_text(reference_question).split())
    return bool(tokens & CONDITIONAL_TERMS)


def conflicting_terms_penalty(question: str, reference_question: str) -> float:
    q = f" {normalize_question_text(question)} "
    ref = f" {normalize_question_text(reference_question)} "
    penalty = 0.0
    for left, right in CONFLICTING_TERM_PAIRS:
        left_norm = f" {left.strip()} "
        right_norm = f" {right.strip()} "
        if (left_norm in q and right_norm in ref) or (right_norm in q and left_norm in ref):
            penalty += 0.18
    return min(0.5, penalty)


def different_entity_penalty(question: str, reference_question: str) -> float:
    q_entities = extract_named_entities(question)
    ref_entities = extract_named_entities(reference_question)
    if not q_entities or not ref_entities:
        return 0.0
    overlap = q_entities & ref_entities
    if overlap:
        return 0.0
    return 0.28


def same_resolution_target(question: str, reference_question: str) -> bool:
    q_tokens = question_tokens(question)
    ref_tokens = question_tokens(reference_question)
    resolution_terms = {
        "championship",
        "election",
        "nomination",
        "presidency",
        "senate",
        "house",
        "award",
        "cuts",
        "rate",
        "power",
        "balance",
    }
    return bool((q_tokens & ref_tokens) & resolution_terms)


def same_date_or_timeframe(question: str, reference_question: str) -> bool:
    q_years = extract_years(question)
    ref_years = extract_years(reference_question)
    return bool(q_years and ref_years and q_years & ref_years)


def same_category(row: dict[str, Any]) -> bool:
    # Step 9A rows do not always include reference category. If both are present,
    # compare them; otherwise keep this neutral rather than inventing a mismatch.
    category = str(row.get("category") or "").strip().lower()
    ref_category = str(row.get("reference_category") or "").strip().lower()
    return bool(category and ref_category and category == ref_category)


def relationship_features(row: dict[str, Any]) -> dict[str, Any]:
    q = str(row.get("question") or "")
    ref = str(row.get("reference_question") or "")
    similarity = normalized_similarity(q, ref)
    shared_keywords = shared_event_keywords(q, ref)
    q_entities = extract_named_entities(q)
    ref_entities = extract_named_entities(ref)
    shared_entities = q_entities & ref_entities
    conditional_penalty = 0.18 if has_conditional_language(q, ref) else 0.0
    conflict_penalty = conflicting_terms_penalty(q, ref)
    entity_penalty = different_entity_penalty(q, ref)
    same_time = same_date_or_timeframe(q, ref)
    same_target = same_resolution_target(q, ref)
    category_match = same_category(row)
    score = (
        0.42 * similarity
        + min(0.22, 0.035 * len(shared_keywords))
        + (0.13 if shared_entities else 0.0)
        + (0.08 if same_time else 0.0)
        + (0.08 if same_target else 0.0)
        + (0.04 if category_match else 0.0)
        - conflict_penalty
        - entity_penalty
        - conditional_penalty
    )
    confidence = max(0.0, min(1.0, score))
    return {
        "normalized_question_similarity": similarity,
        "shared_event_keywords": "|".join(sorted(shared_keywords)),
        "shared_named_entities": "|".join(sorted(shared_entities)),
        "shared_date_or_timeframe": same_time,
        "same_resolution_target": same_target,
        "same_category": category_match,
        "conflicting_terms_penalty": conflict_penalty,
        "different_entity_penalty": entity_penalty,
        "conditional_language_penalty": conditional_penalty,
        "relationship_confidence": confidence,
    }


def relationship_status(row: dict[str, Any], features: dict[str, Any], min_confidence: float) -> str:
    relationship = str(row.get("relationship_type") or "")
    confidence = safe_float(features.get("relationship_confidence"), 0.0)
    similarity = safe_float(features.get("normalized_question_similarity"), 0.0)
    conflict_penalty = safe_float(features.get("conflicting_terms_penalty"), 0.0)
    entity_penalty = safe_float(features.get("different_entity_penalty"), 0.0)
    conditional_penalty = safe_float(features.get("conditional_language_penalty"), 0.0)

    if relationship == RELATIONSHIP_MUTUALLY_EXCLUSIVE:
        return STATUS_MUTEX_WATCH
    if conflict_penalty >= 0.28 or entity_penalty >= 0.28:
        return STATUS_FALSE_MATCH
    if conditional_penalty > 0 and confidence < min_confidence:
        return STATUS_AMBIGUOUS
    if relationship in {RELATIONSHIP_DUPLICATE, RELATIONSHIP_NEAR_DUPLICATE}:
        if confidence >= min_confidence and similarity >= 0.76:
            return STATUS_HIGH_DUPLICATE
        if confidence >= 0.55:
            return STATUS_MEDIUM_RELATED
    if confidence < 0.35 or similarity < 0.35:
        return STATUS_FALSE_MATCH
    return STATUS_AMBIGUOUS


def liquidity_quality_passes(row: dict[str, Any], args: argparse.Namespace) -> bool:
    return (
        safe_float(row.get("entry_price"), 0.0) > 0
        and safe_float(row.get("spread"), 999.0) <= args.max_spread
        and safe_float(row.get("orderbook_depth"), 0.0) >= args.min_depth
        and safe_float(row.get("liquidity_score"), 0.0) >= args.min_liquidity
    )


def calibrate_row(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    calibrated = dict(row)
    features = relationship_features(row)
    status = relationship_status(row, features, args.min_relationship_confidence)
    price_gap = safe_float(row.get("price_gap"), 0.0)
    quality_pass = liquidity_quality_passes(row, args)
    can_shadow = (
        status == STATUS_HIGH_DUPLICATE
        and price_gap >= args.min_price_gap
        and quality_pass
    )
    if status == STATUS_FALSE_MATCH:
        action = "reject"
    elif can_shadow:
        action = "shadow_entry"
    else:
        action = "watch_only"

    if action == "shadow_entry":
        failure = ""
        edge_pass = True
        tier = "tier1_mispricing"
        hint = "eligible_shadow_entry"
    elif status == STATUS_FALSE_MATCH:
        failure = STATUS_FALSE_MATCH
        edge_pass = False
        tier = ""
        hint = "rejected"
    elif status == STATUS_MUTEX_WATCH:
        failure = STATUS_MUTEX_WATCH
        edge_pass = False
        tier = ""
        hint = "watch_only"
    elif status == STATUS_AMBIGUOUS:
        failure = STATUS_AMBIGUOUS
        edge_pass = False
        tier = ""
        hint = "watch_only"
    elif status == STATUS_MEDIUM_RELATED:
        failure = "relationship_confidence_too_low"
        edge_pass = False
        tier = ""
        hint = "watch_only"
    else:
        failure = "relationship_confidence_too_low" if not can_shadow else ""
        edge_pass = False
        tier = ""
        hint = "watch_only"

    evidence_parts = [
        part for part in str(row.get("evidence") or row.get("reasons") or "").split("|") if part
    ]
    evidence_parts.extend([status, "relationship_calibrated"])
    if confidence := features.get("relationship_confidence"):
        evidence_parts.append(f"relationship_confidence={float(confidence):.4f}")
    reasons = list(dict.fromkeys(evidence_parts))

    calibrated.update(features)
    calibrated.update({
        "relationship_status": status,
        "recommended_action": action,
        "confidence": features["relationship_confidence"],
        "edge_pass": edge_pass,
        "edge_failure_reason": failure,
        "near_miss_tier": tier,
        "entry_decision_hint": hint,
        "evidence": "|".join(reasons),
        "reasons": "|".join(reasons),
        "relationship_calibration_source": "deterministic_string_entity_heuristics",
        "relationship_quality_pass": quality_pass,
        "feedback_gate_status": "enabled",
        "feedback_gate_reason": "non_probability_edge",
        "gate_passed": True,
    })
    return calibrated


def calibrate_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, Any]]:
    return [calibrate_row(row, args) for row in rows if str(row.get("edge_type") or EDGE_TYPE) == EDGE_TYPE]


def summarize(started: datetime, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ended = utc_now()
    statuses = Counter(str(row.get("relationship_status") or "") for row in rows)
    actions = Counter(str(row.get("recommended_action") or "") for row in rows)
    groups = {str(row.get("group_id") or "") for row in rows if row.get("group_id")}
    confidences = [safe_float(row.get("relationship_confidence"), 0.0) for row in rows]
    return {
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - started).total_seconds(),
        "candidates_loaded": len(rows),
        "groups_loaded": len(groups),
        "high_confidence_duplicate_count": statuses[STATUS_HIGH_DUPLICATE],
        "medium_confidence_related_count": statuses[STATUS_MEDIUM_RELATED],
        "ambiguous_relationship_count": statuses[STATUS_AMBIGUOUS],
        "likely_false_match_count": statuses[STATUS_FALSE_MATCH],
        "mutually_exclusive_watch_count": statuses[STATUS_MUTEX_WATCH],
        "shadow_entry_eligible_count": actions["shadow_entry"],
        "watch_only_count": actions["watch_only"],
        "rejected_count": actions["reject"],
        "avg_relationship_confidence": mean(confidences) if confidences else 0.0,
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": "NO",
    }


BASE_FIELDS = [
    "edge_type",
    "group_id",
    "relationship_type",
    "market_id",
    "question",
    "side",
    "yes_token_id",
    "no_token_id",
    "entry_price",
    "reference_market_id",
    "reference_question",
    "reference_price",
    "price_gap",
    "expected_edge",
    "confidence",
    "evidence",
    "recommended_action",
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "spread",
    "liquidity_score",
    "orderbook_depth",
    "entry_yes_best_ask",
    "entry_no_best_ask",
    "entry_yes_best_bid",
    "entry_no_best_bid",
    "combined_ask",
    "source",
    "category",
    "volume",
    "timestamp",
    "expected_edge_source",
    "expected_edge_status",
    "edge_pass",
    "edge_failure_reason",
    "reasons",
    "near_miss_tier",
    "evidence_level",
    "entry_decision_hint",
    "tradable_score",
    "feedback_gate_status",
    "feedback_gate_reason",
    "gate_passed",
]
CALIBRATION_FIELDS = [
    "normalized_question_similarity",
    "shared_event_keywords",
    "shared_named_entities",
    "shared_date_or_timeframe",
    "same_resolution_target",
    "same_category",
    "conflicting_terms_penalty",
    "different_entity_penalty",
    "conditional_language_penalty",
    "relationship_confidence",
    "relationship_status",
    "relationship_calibration_source",
    "relationship_quality_pass",
]
FIELDS = BASE_FIELDS + [field for field in CALIBRATION_FIELDS if field not in BASE_FIELDS]


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print("DRY RUN: cross-market relationship calibration" if dry_run else "Cross-market relationship calibration")
    for key in [
        "candidates_loaded",
        "groups_loaded",
        "high_confidence_duplicate_count",
        "medium_confidence_related_count",
        "ambiguous_relationship_count",
        "likely_false_match_count",
        "mutually_exclusive_watch_count",
        "shadow_entry_eligible_count",
        "watch_only_count",
        "rejected_count",
        "avg_relationship_confidence",
    ]:
        print(f"{key}: {summary.get(key, 0)}")
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


def run(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = utc_now()
    rows = load_csv(Path(args.runs_dir) / "cross_market_edge_candidates.csv")
    calibrated = calibrate_rows(rows, args)
    return calibrated, summarize(started, calibrated)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, summary = run(args)
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0

    output_dir = Path(args.output_dir)
    csv_path = output_dir / "cross_market_edge_candidates_calibrated.csv"
    json_path = output_dir / "cross_market_edge_candidates_calibrated.json"
    summary_path = output_dir / "cross_market_relationship_calibration_summary.json"
    report_path = output_dir / "cross_market_relationship_calibration_report.md"
    write_csv(csv_path, rows, FIELDS)
    write_json(json_path, rows)
    write_summary(summary_path, summary)
    write_report(report_path, summary)
    print(f"cross_market_edge_candidates_calibrated_csv: {csv_path}")
    print(f"cross_market_edge_candidates_calibrated_json: {json_path}")
    print(f"cross_market_relationship_calibration_summary_json: {summary_path}")
    print(f"cross_market_relationship_calibration_report_md: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
