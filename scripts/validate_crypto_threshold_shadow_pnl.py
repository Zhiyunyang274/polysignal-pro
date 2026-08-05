#!/usr/bin/env python3
"""Validate crypto-threshold candidates with corrected offline shadow PnL.

The validator consumes Step 11 candidates and ``forward_observations.jsonl``
written by the existing read-only shadow poller. It never calls an API, LLM,
PaperTrader, or execution path. Missing, stale, pre-entry, or side-ambiguous
forward observations remain insufficient data and never create PnL.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.shadow.entry_filter import EntryDecision, EntryFilterConfig, ShadowEntryFilter
from polysignal.shadow.expiry_provenance import expiry_integrity_reasons
from polysignal.shadow.historical_barrier_provenance import (
    historical_evidence_integrity_reasons,
)
from polysignal.shadow.models import SHADOW_TRADE_FIELDS
from polysignal.shadow.resolution_provenance import (
    normalize_resolution_text,
    resolution_integrity_reasons,
    resolution_rules_sha256,
)

EDGE_TYPE = "crypto_price_threshold_v1"
TINY_LIVE_RECOMMENDATION = "NO"
SCHEMA_VERSION = "crypto_threshold_shadow_pnl_v7"
DISCOVERY_SCHEMA_VERSION = "crypto_threshold_edge_discovery_v5"
PARSER_VERSION = "crypto_threshold_parser_v4"
CLUSTER_POLICY = "asset_expiry_contract_kind_v1"
TRUSTED_FORWARD_SOURCE = "clob_rest_readonly"
DEFAULT_MAX_ENTRY_AGE_MINUTES = 1.0
DEFAULT_MAX_CLOCK_SKEW_SECONDS = 5.0
MAX_CLOCK_SKEW_SECONDS = 5.0
REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_SHADOW_DIR = (REPO_ROOT / "runs" / "shadow").resolve()

HISTORICAL_BARRIER_FIELDS = [
    "historical_barrier_evidence_status",
    "historical_barrier_evidence_source",
    "historical_barrier_evidence_start_time",
    "historical_barrier_evidence_end_time",
    "historical_barrier_evidence_sha256",
    "historical_barrier_evidence_adapter_version",
    "historical_barrier_evidence_origin",
    "historical_barrier_evidence_locator",
    "historical_barrier_evidence_interval",
    "historical_barrier_evidence_symbol",
    "historical_barrier_evidence_candle_count",
    "historical_barrier_evidence_missing_ranges",
    "historical_barrier_evidence_path",
    "historical_barrier_candle_snapshot_path",
    "historical_barrier_candle_snapshot_sha256",
    "historical_barrier_rule_window_adapter_version",
    "historical_barrier_rule_window_provenance_sha256",
    "historical_barrier_crossed_at",
    "historical_barrier_expected_candle_count",
    "historical_barrier_min_low_price",
    "historical_barrier_max_high_price",
    "historical_barrier_tail_coverage_status",
    "historical_barrier_tail_covered_through",
    "historical_barrier_first_touch_at",
]
SETTLEMENT_HISTORICAL_BLANK_TEXT_FIELDS = [
    field
    for field in HISTORICAL_BARRIER_FIELDS
    if field
    not in {
        "historical_barrier_evidence_status",
        "historical_barrier_evidence_adapter_version",
        "historical_barrier_rule_window_adapter_version",
        "historical_barrier_evidence_candle_count",
        "historical_barrier_evidence_missing_ranges",
        "historical_barrier_expected_candle_count",
    }
]

VALIDATION_FIELDS = [
    "shadow_trade_id",
    "schema_version",
    "market_id",
    "question",
    "asset",
    "threshold_price",
    "direction",
    "contract_kind",
    "barrier_direction",
    "parser_version",
    "model_version",
    "expiry_time",
    "expiry_local_time",
    "expiry_timezone",
    "expiry_time_origin",
    "expiry_time_adapter_version",
    "expiry_time_provenance_sha256",
    "gamma_start_date",
    "gamma_end_date",
    "gamma_market_updated_at",
    "gamma_market_schema",
    "gamma_market_version",
    "expiry_status",
    "gamma_raw_market_snapshot_path",
    "gamma_raw_market_snapshot_sha256",
    *HISTORICAL_BARRIER_FIELDS,
    "resolution_source",
    "resolution_source_origin",
    "resolution_source_locator",
    "resolution_source_adapter_version",
    "resolution_source_provenance_sha256",
    "resolution_rules",
    "resolution_rules_sha256",
    "resolution_status",
    "spot_price",
    "spot_timestamp",
    "spot_source",
    "entry_quote_timestamp",
    "yes_orderbook_timestamp",
    "no_orderbook_timestamp",
    "entry_yes_best_ask_size",
    "entry_no_best_ask_size",
    "entry_yes_best_bid_size",
    "entry_no_best_bid_size",
    "entry_share_quantity",
    "notional",
    "entry_identity_sha256",
    "entry_epoch",
    "cluster_id",
    "side",
    "entry_time",
    "entry_snapshot_age_minutes",
    "persisted_entry_record_reused",
    "entry_price",
    "entry_price_source",
    "exit_time",
    "exit_price",
    "exit_price_source",
    "exit_side_best_bid_size",
    "holding_minutes",
    "expected_edge",
    "confidence",
    "gross_price_change",
    "cost_price_change",
    "net_price_change",
    "return_pct",
    "pnl",
    "status",
    "insufficient_reason",
    "forward_source",
]

RECONCILIATION_FIELDS = [
    "schema_version",
    "market_id",
    "question",
    "asset",
    "threshold_price",
    "contract_kind",
    "barrier_direction",
    "parser_version",
    "model_version",
    "expiry_time",
    "expiry_local_time",
    "expiry_timezone",
    "expiry_time_origin",
    "expiry_time_adapter_version",
    "expiry_time_provenance_sha256",
    "gamma_start_date",
    "gamma_end_date",
    "gamma_market_updated_at",
    "gamma_market_schema",
    "gamma_market_version",
    "expiry_status",
    "gamma_raw_market_snapshot_path",
    "gamma_raw_market_snapshot_sha256",
    *HISTORICAL_BARRIER_FIELDS,
    "resolution_source",
    "resolution_source_origin",
    "resolution_source_locator",
    "resolution_source_adapter_version",
    "resolution_source_provenance_sha256",
    "resolution_rules_sha256",
    "resolution_status",
    "discovery_action",
    "discovery_hint",
    "edge_pass",
    "shared_entry_decision",
    "shared_reject_reasons",
    "shared_watch_reasons",
    "entry_time",
    "spot_timestamp",
    "entry_quote_timestamp",
    "yes_orderbook_timestamp",
    "no_orderbook_timestamp",
    "entry_yes_best_ask_size",
    "entry_no_best_ask_size",
    "entry_yes_best_bid_size",
    "entry_no_best_bid_size",
    "entry_snapshot_age_minutes",
    "persisted_entry_record_reused",
    "position_created",
    "position_exclusion_reasons",
]


@dataclass
class ValidationPosition:
    """One corrected, hypothetical crypto-threshold shadow position."""

    shadow_trade_id: str
    schema_version: str
    market_id: str
    question: str
    asset: str
    threshold_price: float
    direction: str
    contract_kind: str
    barrier_direction: str
    parser_version: str
    model_version: str
    expiry_time: str
    expiry_local_time: str
    expiry_timezone: str
    expiry_time_origin: str
    expiry_time_adapter_version: str
    expiry_time_provenance_sha256: str
    gamma_start_date: str
    gamma_end_date: str
    gamma_market_updated_at: str
    gamma_market_schema: str
    gamma_market_version: str
    expiry_status: str
    gamma_raw_market_snapshot_path: str
    gamma_raw_market_snapshot_sha256: str
    historical_barrier_evidence_status: str
    historical_barrier_evidence_source: str
    historical_barrier_evidence_start_time: str
    historical_barrier_evidence_end_time: str
    historical_barrier_evidence_sha256: str
    historical_barrier_evidence_adapter_version: str
    historical_barrier_evidence_origin: str
    historical_barrier_evidence_locator: str
    historical_barrier_evidence_interval: str
    historical_barrier_evidence_symbol: str
    historical_barrier_evidence_candle_count: int
    historical_barrier_evidence_missing_ranges: str
    historical_barrier_evidence_path: str
    historical_barrier_candle_snapshot_path: str
    historical_barrier_candle_snapshot_sha256: str
    historical_barrier_rule_window_adapter_version: str
    historical_barrier_rule_window_provenance_sha256: str
    historical_barrier_crossed_at: str
    historical_barrier_expected_candle_count: int
    historical_barrier_min_low_price: str
    historical_barrier_max_high_price: str
    historical_barrier_tail_coverage_status: str
    historical_barrier_tail_covered_through: str
    historical_barrier_first_touch_at: str
    resolution_source: str
    resolution_source_origin: str
    resolution_source_locator: str
    resolution_source_adapter_version: str
    resolution_source_provenance_sha256: str
    resolution_rules: str
    resolution_rules_sha256: str
    resolution_status: str
    spot_price: float
    spot_timestamp: str
    spot_source: str
    entry_quote_timestamp: str
    yes_orderbook_timestamp: str
    no_orderbook_timestamp: str
    entry_yes_best_ask_size: float
    entry_no_best_ask_size: float
    entry_yes_best_bid_size: float
    entry_no_best_bid_size: float
    entry_share_quantity: float
    notional: float
    entry_identity_sha256: str
    entry_epoch: str
    cluster_id: str
    side: str
    entry_time: str
    entry_snapshot_age_minutes: float
    persisted_entry_record_reused: bool
    entry_price: float
    entry_price_source: str
    expected_edge: float
    confidence: float
    yes_token_id: str
    no_token_id: str
    entry_yes_best_ask: float
    entry_no_best_ask: float
    entry_yes_best_bid: float
    entry_no_best_bid: float
    combined_ask: float
    orderbook_spread: float
    orderbook_depth: float
    liquidity_score: float
    evidence: str
    source: str
    exit_time: str | None = None
    exit_price: float | None = None
    exit_price_source: str = ""
    exit_side_best_bid_size: float | None = None
    holding_minutes: float | None = None
    gross_price_change: float | None = None
    cost_price_change: float | None = None
    net_price_change: float | None = None
    return_pct: float | None = None
    pnl: float | None = None
    status: str = "insufficient_forward_data"
    insufficient_reason: str = "missing_forward_observation"
    forward_source: str = ""

    def to_validation_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {field: payload.get(field) for field in VALIDATION_FIELDS}

    def to_shadow_trade_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {field: "" for field in SHADOW_TRADE_FIELDS}
        row.update(
            {
                "shadow_trade_id": self.shadow_trade_id,
                "market_id": self.market_id,
                "question": self.question,
                "side": self.side,
                "entry_time": self.entry_time,
                "entry_price": self.entry_price,
                "entry_reason": prepared_entry_reason(self.entry_identity_sha256),
                "expected_edge": self.expected_edge,
                "confidence": self.confidence,
                "edge_type": EDGE_TYPE,
                "evidence": self.evidence,
                "entry_yes_best_ask": self.entry_yes_best_ask,
                "entry_no_best_ask": self.entry_no_best_ask,
                "entry_yes_best_bid": self.entry_yes_best_bid,
                "entry_no_best_bid": self.entry_no_best_bid,
                "entry_side_price": self.entry_price,
                "entry_price_source": self.entry_price_source,
                "exit_side_price": self.exit_price if self.exit_price is not None else "",
                "exit_price_source": self.exit_price_source,
                "price_model_status": "side_specific_entry_exit",
                "price_model_notes": self.insufficient_reason,
                "combined_ask": self.combined_ask,
                "liquidity_score": self.liquidity_score,
                "risk_decision": "allow_shadow",
                "yes_token_id": self.yes_token_id,
                "no_token_id": self.no_token_id,
                "exit_time": self.exit_time or "",
                "exit_price": self.exit_price if self.exit_price is not None else "",
                # Keep the compatibility artifact inside the existing ExitReason enum.
                "exit_reason": "fixed_horizon" if self.status == "closed" else "open",
                "pnl": self.pnl if self.pnl is not None else "",
                "return_pct": self.return_pct if self.return_pct is not None else "",
                "status": self.status,
                "category": "Crypto",
                "source": self.source,
                "orderbook_spread": self.orderbook_spread,
                "orderbook_depth": self.orderbook_depth,
                "holding_minutes": self.holding_minutes if self.holding_minutes is not None else "",
            }
        )
        return row


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate corrected crypto-threshold shadow PnL from offline observations"
    )
    parser.add_argument(
        "--candidate_file",
        default="runs/crypto_threshold_edge_candidates.csv",
    )
    parser.add_argument("--avoid_file", default="runs/avoid_candidates.csv")
    parser.add_argument("--output_dir", default="runs/crypto_threshold_shadow")
    parser.add_argument(
        "--forward_observations",
        default="",
        help=(
            "Existing read-only poller artifact; defaults to OUTPUT_DIR/forward_observations.jsonl"
        ),
    )
    parser.add_argument(
        "--evaluation_time",
        default="",
        help="UTC ISO timestamp used for deterministic freshness checks; defaults to now",
    )
    parser.add_argument(
        "--max_entry_age_minutes",
        type=float,
        default=DEFAULT_MAX_ENTRY_AGE_MINUTES,
    )
    parser.add_argument(
        "--max_clock_skew_seconds",
        type=float,
        default=DEFAULT_MAX_CLOCK_SKEW_SECONDS,
        help="Maximum allowed clock skew for future evidence timestamps (hard capped at 5 seconds)",
    )
    # Keep parsing the old option for callers upgrading from v3, but never allow
    # it to bypass the five-second safety cap.
    parser.add_argument(
        "--future_tolerance_minutes",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--min_forward_horizon_minutes", type=float, default=240.0)
    parser.add_argument("--legacy_min_expected_edge", type=float, default=0.001)
    parser.add_argument("--min_confidence", type=float, default=0.6)
    parser.add_argument("--max_spread", type=float, default=0.05)
    parser.add_argument("--notional", type=float, default=1.0)
    parser.add_argument("--fee_bps", type=float, default=0.0)
    parser.add_argument("--slippage_bps", type=float, default=100.0)
    parser.add_argument("--min_sample_size", type=int, default=20)
    parser.add_argument("--min_independent_clusters", type=int, default=5)
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args(argv)


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def parse_utc_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if isinstance(value, bool):
        return None
    raw = str("" if value is None else value).strip()
    if not raw:
        return None

    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None:
        if not math.isfinite(numeric) or numeric < 0:
            return None
        magnitude = abs(numeric)
        if magnitude >= 100_000_000_000_000:
            return None
        epoch_seconds = numeric / 1000.0 if magnitude >= 100_000_000_000 else numeric
        try:
            return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def effective_max_clock_skew_seconds(args: argparse.Namespace) -> float:
    configured = optional_float(getattr(args, "max_clock_skew_seconds", None))
    if configured is None or configured < 0:
        raise ValueError("max_clock_skew_seconds must be a finite non-negative number")
    if configured > MAX_CLOCK_SKEW_SECONDS:
        raise ValueError(
            f"max_clock_skew_seconds must not exceed {MAX_CLOCK_SKEW_SECONDS:g} seconds"
        )

    legacy_minutes = getattr(args, "future_tolerance_minutes", None)
    if legacy_minutes is None:
        return configured
    legacy_value = optional_float(legacy_minutes)
    if legacy_value is None or legacy_value < 0:
        raise ValueError("future_tolerance_minutes must be a finite non-negative number")
    legacy_seconds = legacy_value * 60.0
    if legacy_seconds > MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("future_tolerance_minutes may not exceed the five-second clock-skew cap")
    return min(configured, legacy_seconds)


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_prepared_input(
    prepared_path: Path,
    output_dir: Path,
    expected_sha256: str,
) -> Path | None:
    """Preserve a content-addressed prepared input before replacing the working CSV."""

    if not expected_sha256:
        return None
    if not prepared_path.is_file():
        raise RuntimeError("prepared shadow-trades input disappeared before output write")
    content = prepared_path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError("prepared shadow-trades input changed during validation")

    snapshot_dir = output_dir / "prepared_inputs"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"shadow_trades_{actual_sha256}.csv"
    if snapshot_path.exists():
        if not snapshot_path.is_file() or snapshot_path.read_bytes() != content:
            raise RuntimeError("content-addressed prepared-input snapshot conflicts with input")
        return snapshot_path
    with snapshot_path.open("xb") as handle:
        handle.write(content)
    return snapshot_path


def load_avoid_market_ids(path: Path) -> set[str]:
    return {
        str(row.get("market_id") or "").strip()
        for row in load_csv_rows(path)
        if str(row.get("market_id") or "").strip()
    }


def load_prepared_trade_index(path: Path) -> dict[str, dict[str, str]]:
    return {
        str(row.get("shadow_trade_id") or ""): row
        for row in load_csv_rows(path)
        if str(row.get("shadow_trade_id") or "")
    }


def _identity_text(value: Any) -> str:
    return normalize_resolution_text(value)


def _identity_number(value: Any) -> str:
    parsed = optional_float(value)
    return format(parsed, ".17g") if parsed is not None else f"invalid:{_identity_text(value)}"


def _identity_time(value: Any) -> str:
    parsed = parse_utc_time(value)
    return iso_utc(parsed) if parsed is not None else f"invalid:{_identity_text(value)}"


def entry_identity_sha256(row: dict[str, Any], notional: float = 1.0) -> str:
    """Bind every entry-time fact that can affect eligibility, sizing, or auditability."""

    entry_price, entry_price_field = candidate_entry_price(row)
    shares = notional / entry_price if entry_price > 0 else math.inf
    text_fields = [
        "schema_version",
        "market_id",
        "question",
        "asset",
        "category",
        "run_ids",
        "direction",
        "contract_kind",
        "barrier_direction",
        "parser_version",
        "model_version",
        "expiry_local_time",
        "expiry_timezone",
        "expiry_time_origin",
        "expiry_time_adapter_version",
        "expiry_time_provenance_sha256",
        "gamma_market_schema",
        "gamma_market_version",
        "expiry_status",
        "gamma_raw_market_snapshot_path",
        "gamma_raw_market_snapshot_sha256",
        "historical_barrier_evidence_status",
        "historical_barrier_evidence_source",
        "historical_barrier_evidence_sha256",
        "historical_barrier_evidence_adapter_version",
        "historical_barrier_evidence_origin",
        "historical_barrier_evidence_locator",
        "historical_barrier_evidence_interval",
        "historical_barrier_evidence_symbol",
        "historical_barrier_evidence_missing_ranges",
        "historical_barrier_evidence_path",
        "historical_barrier_candle_snapshot_path",
        "historical_barrier_candle_snapshot_sha256",
        "historical_barrier_rule_window_adapter_version",
        "historical_barrier_rule_window_provenance_sha256",
        "historical_barrier_tail_coverage_status",
        "resolution_source",
        "resolution_source_origin",
        "resolution_source_locator",
        "resolution_source_adapter_version",
        "resolution_source_provenance_sha256",
        "resolution_rules",
        "resolution_rules_sha256",
        "resolution_status",
        "spot_source",
        "side",
        "yes_token_id",
        "no_token_id",
        "recommended_action",
        "entry_decision_hint",
        "edge_type",
        "expected_edge_source",
        "expected_edge_status",
        "edge_failure_reason",
        "edge_notes",
        "risk_flags",
        "near_miss_tier",
        "evidence",
        "reasons",
        "relationship_status",
        "reference_market_id",
        "reference_question",
        "convergence_status",
        "convergence_reason",
        "feedback_gate_status",
        "feedback_gate_reason",
        "evidence_level",
        "source",
    ]
    time_fields = [
        "expiry_time",
        "gamma_start_date",
        "gamma_end_date",
        "gamma_market_updated_at",
        "historical_barrier_evidence_start_time",
        "historical_barrier_evidence_end_time",
        "historical_barrier_crossed_at",
        "historical_barrier_tail_covered_through",
        "historical_barrier_first_touch_at",
        "spot_timestamp",
        "timestamp",
        "entry_quote_timestamp",
        "yes_orderbook_timestamp",
        "no_orderbook_timestamp",
    ]
    number_fields = [
        "threshold_price",
        "historical_barrier_evidence_candle_count",
        "historical_barrier_expected_candle_count",
        "historical_barrier_min_low_price",
        "historical_barrier_max_high_price",
        "spot_price",
        "entry_yes_best_bid",
        "entry_yes_best_ask",
        "entry_no_best_bid",
        "entry_no_best_ask",
        "entry_yes_best_bid_size",
        "entry_yes_best_ask_size",
        "entry_no_best_bid_size",
        "entry_no_best_ask_size",
        "combined_ask",
        "spread",
        "orderbook_depth",
        "liquidity_score",
        "expected_edge",
        "executable_edge",
        "combined_ask_gap",
        "confidence",
        "tradable_score",
        "ambiguity_risk",
        "alpha_score",
        "parser_confidence",
        "relationship_confidence",
        "price_gap",
        "reference_price",
        "convergence_score",
        "convergence_observation_count",
        "initial_price_gap",
        "final_price_gap",
        "gap_change",
    ]
    material = {
        "identity_schema": SCHEMA_VERSION,
        "text": {field: _identity_text(row.get(field)) for field in text_fields},
        "times": {field: _identity_time(row.get(field)) for field in time_fields},
        "numbers": {field: _identity_number(row.get(field)) for field in number_fields},
        "edge_pass": _identity_text(row.get("edge_pass")).lower(),
        "convergence_gate_passed": _identity_text(row.get("convergence_gate_passed")).lower(),
        "gate_passed": _identity_text(row.get("gate_passed")).lower(),
        "is_avoid_candidate": _identity_text(row.get("is_avoid_candidate")).lower(),
        "entry_price_field": entry_price_field,
        "notional": _identity_number(notional),
        "entry_share_quantity": _identity_number(shares),
        "computed_resolution_rules_sha256": resolution_rules_sha256(row.get("resolution_rules")),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def prepared_entry_reason(identity_sha256: str) -> str:
    return f"crypto_threshold_shared_gate_passed|entry_identity_sha256={identity_sha256}"


def _prepared_number_matches(prepared: dict[str, str], field: str, expected: Any) -> bool:
    actual = optional_float(prepared.get(field))
    wanted = optional_float(expected)
    return bool(
        actual is not None
        and wanted is not None
        and math.isclose(actual, wanted, rel_tol=0.0, abs_tol=1e-12)
    )


def prepared_entry_matches(
    row: dict[str, Any],
    prepared: dict[str, str] | None,
    notional: float = 1.0,
) -> bool:
    """Confirm that this exact hypothetical entry was persisted while fresh."""
    if not prepared:
        return False
    entry_time = parse_utc_time(row.get("timestamp"))
    prepared_time = parse_utc_time(prepared.get("entry_time"))
    entry_price, _ = candidate_entry_price(row)
    identity_sha256 = entry_identity_sha256(row, notional)
    return bool(
        prepared.get("shadow_trade_id") == stable_trade_id(row, notional)
        and prepared.get("entry_reason") == prepared_entry_reason(identity_sha256)
        and prepared.get("market_id") == str(row.get("market_id") or "")
        and prepared.get("question") == str(row.get("question") or "")
        and str(prepared.get("side") or "").upper() == str(row.get("side") or "").upper()
        and entry_time is not None
        and prepared_time == entry_time
        and _prepared_number_matches(prepared, "entry_side_price", entry_price)
        and _prepared_number_matches(prepared, "entry_price", entry_price)
        and all(
            _prepared_number_matches(prepared, field, row.get(field))
            for field in [
                "entry_yes_best_ask",
                "entry_no_best_ask",
                "entry_yes_best_bid",
                "entry_no_best_bid",
                "combined_ask",
                "liquidity_score",
                "expected_edge",
                "confidence",
                "orderbook_depth",
            ]
        )
        and _prepared_number_matches(prepared, "orderbook_spread", row.get("spread"))
        and prepared.get("yes_token_id") == str(row.get("yes_token_id") or "")
        and prepared.get("no_token_id") == str(row.get("no_token_id") or "")
        and prepared.get("edge_type") == EDGE_TYPE
        and prepared.get("evidence") == str(row.get("evidence") or row.get("reasons") or "")
        and prepared.get("risk_decision") == "allow_shadow"
    )


def load_forward_observations(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Load the existing poller's JSONL artifact without inventing defaults."""
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    invalid_count = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if not isinstance(payload, dict):
            invalid_count += 1
            continue
        rows.append(payload)
    return rows, invalid_count


def stable_trade_id(row: dict[str, Any], notional: float = 1.0) -> str:
    return f"crypto_shadow_{entry_identity_sha256(row, notional)[:20]}"


def candidate_entry_epoch(row: dict[str, Any]) -> str:
    timestamp = parse_utc_time(row.get("timestamp"))
    return timestamp.strftime("%Y-%m-%dT%H:%MZ") if timestamp else "unknown"


def candidate_cluster_id(row: dict[str, Any]) -> str:
    asset = str(row.get("asset") or "unknown").strip().upper()
    expiry = parse_utc_time(row.get("expiry_time"))
    expiry_key = iso_utc(expiry) if expiry else "unknown"
    contract_kind = str(row.get("contract_kind") or "unknown").strip().lower()
    return "|".join(
        [
            asset,
            expiry_key,
            contract_kind,
        ]
    )


def candidate_entry_price(row: dict[str, Any]) -> tuple[float, str]:
    side = str(row.get("side") or "").strip().upper()
    field = "entry_no_best_ask" if side == "NO" else "entry_yes_best_ask"
    return safe_float(row.get(field)), field


def orderbook_timestamp_integrity(
    value: Any,
    label: str,
    local_timestamp: datetime | None,
    max_quote_age_minutes: float,
    max_clock_skew_seconds: float,
) -> tuple[datetime | None, str | None]:
    timestamp = parse_utc_time(value)
    if timestamp is None:
        return None, f"missing_or_invalid_{label}_orderbook_timestamp"
    if local_timestamp is None:
        return timestamp, None
    age_seconds = (local_timestamp - timestamp).total_seconds()
    if age_seconds < -max_clock_skew_seconds:
        return timestamp, f"{label}_orderbook_timestamp_in_future"
    if age_seconds > max_quote_age_minutes * 60.0:
        return timestamp, f"stale_{label}_orderbook_snapshot"
    return timestamp, None


def historical_integrity_row(row: dict[str, Any]) -> dict[str, Any]:
    """Restore integer fields serialized by CSV before typed offline verification."""

    normalized = dict(row)
    for field in (
        "historical_barrier_evidence_candle_count",
        "historical_barrier_expected_candle_count",
    ):
        raw = str(row.get(field) or "").strip()
        try:
            parsed = int(raw)
        except ValueError:
            continue
        if raw == str(parsed):
            normalized[field] = parsed
    return normalized


def settlement_historical_artifact_fields_present(row: dict[str, Any]) -> bool:
    if any(str(row.get(field) or "").strip() for field in SETTLEMENT_HISTORICAL_BLANK_TEXT_FIELDS):
        return True
    for field in (
        "historical_barrier_evidence_candle_count",
        "historical_barrier_expected_candle_count",
    ):
        count = optional_float(row.get(field))
        if count not in (None, 0.0):
            return True
    raw_missing_ranges = row.get("historical_barrier_evidence_missing_ranges")
    if raw_missing_ranges in (None, ""):
        return False
    try:
        missing_ranges = json.loads(str(raw_missing_ranges))
    except json.JSONDecodeError:
        return True
    return bool(missing_ranges != [])


def entry_integrity_reasons(
    row: dict[str, Any],
    artifact_root: Path,
    evaluation_time: datetime,
    max_entry_age_minutes: float,
    max_clock_skew_seconds: float,
    notional: float,
    avoid_ids: set[str],
    persisted_entry_record_reused: bool,
) -> tuple[list[str], datetime | None, float | None]:
    reasons: list[str] = []
    if str(row.get("recommended_action") or "") != "shadow_entry":
        reasons.append("discovery_action_not_shadow_entry")
    if str(row.get("entry_decision_hint") or "") != EntryDecision.ELIGIBLE_SHADOW_ENTRY.value:
        reasons.append("discovery_hint_not_eligible")
    if not safe_bool(row.get("edge_pass")):
        reasons.append("edge_pass_false")
    if str(row.get("risk_flags") or "").strip():
        reasons.append("risk_flags_present")
    reasons.extend(resolution_integrity_reasons(row))
    reasons.extend(expiry_integrity_reasons(row))
    reasons.extend(
        historical_evidence_integrity_reasons(
            historical_integrity_row(row),
            artifact_root=artifact_root,
        )
    )

    contract_kind = str(row.get("contract_kind") or "").strip()
    barrier_direction = str(row.get("barrier_direction") or "").strip()
    direction = str(row.get("direction") or "").strip()
    discovery_schema_version = str(row.get("schema_version") or "").strip()
    parser_version = str(row.get("parser_version") or "").strip()
    threshold_price = optional_float(row.get("threshold_price"))
    spot_price = optional_float(row.get("spot_price"))
    if discovery_schema_version != DISCOVERY_SCHEMA_VERSION:
        reasons.append("unsupported_candidate_schema_version")
    if not parser_version:
        reasons.append("missing_parser_version")
    elif parser_version != PARSER_VERSION:
        reasons.append("unsupported_parser_version")
    if contract_kind not in {"settlement_threshold", "touch_before_expiry"}:
        reasons.append("unsupported_or_missing_contract_kind")
    elif contract_kind == "settlement_threshold" and settlement_historical_artifact_fields_present(
        row
    ):
        reasons.append("settlement_historical_barrier_artifact_fields_present")
    if barrier_direction not in {"up", "down"}:
        reasons.append("unverifiable_barrier_direction")
    if not str(row.get("model_version") or "").strip():
        reasons.append("missing_model_version")
    if threshold_price is None or threshold_price <= 0:
        reasons.append("invalid_threshold_price")
    if spot_price is None or spot_price <= 0:
        reasons.append("invalid_spot_price")
    if contract_kind == "settlement_threshold":
        expected_direction = "above" if barrier_direction == "up" else "below"
        if direction != expected_direction:
            reasons.append("settlement_direction_mismatch")
    elif contract_kind == "touch_before_expiry" and direction != "hit_before_expiry":
        reasons.append("touch_direction_mismatch")

    if (
        contract_kind == "touch_before_expiry"
        and threshold_price is not None
        and spot_price is not None
        and (
            (barrier_direction == "up" and spot_price >= threshold_price)
            or (barrier_direction == "down" and spot_price <= threshold_price)
        )
    ):
        reasons.append("already_crossed_barrier")

    market_id = str(row.get("market_id") or "").strip()
    side = str(row.get("side") or "").strip().upper()
    if not market_id:
        reasons.append("missing_market_id")
    if side not in {"YES", "NO"}:
        reasons.append("invalid_side")
    if market_id in avoid_ids:
        reasons.append("current_avoid_candidate")

    for outcome in ["yes", "no"]:
        bid = optional_float(row.get(f"entry_{outcome}_best_bid"))
        ask = optional_float(row.get(f"entry_{outcome}_best_ask"))
        if bid is None or not 0 < bid <= 1:
            reasons.append(f"invalid_entry_{outcome}_best_bid")
        if ask is None or not 0 < ask <= 1:
            reasons.append(f"invalid_entry_{outcome}_best_ask")
        if bid is not None and ask is not None and 0 < bid <= 1 and 0 < ask <= 1 and bid > ask:
            reasons.append(f"entry_{outcome}_bid_above_ask")
        for level in ["bid", "ask"]:
            size_field = f"entry_{outcome}_best_{level}_size"
            size = optional_float(row.get(size_field))
            if size is None or size <= 0:
                reasons.append(f"missing_or_invalid_{size_field}")

    entry_price, _ = candidate_entry_price(row)
    if not 0 < entry_price <= 1:
        reasons.append("invalid_side_specific_entry_ask")
    entry_bid_field = "entry_no_best_bid" if side == "NO" else "entry_yes_best_bid"
    entry_bid = optional_float(row.get(entry_bid_field))
    if entry_bid is None or not 0 < entry_bid <= 1:
        reasons.append("invalid_side_specific_entry_bid")
    elif 0 < entry_price <= 1 and entry_bid > entry_price:
        reasons.append("entry_bid_above_ask")
    if side in {"YES", "NO"} and 0 < entry_price <= 1:
        selected_prefix = "no" if side == "NO" else "yes"
        selected_ask_size = optional_float(row.get(f"entry_{selected_prefix}_best_ask_size"))
        entry_share_quantity = notional / entry_price
        if (
            selected_ask_size is not None
            and selected_ask_size > 0
            and selected_ask_size + 1e-12 < entry_share_quantity
        ):
            reasons.append("insufficient_selected_entry_ask_size")

    yes_token_id = str(row.get("yes_token_id") or "").strip()
    no_token_id = str(row.get("no_token_id") or "").strip()
    if not yes_token_id:
        reasons.append("missing_yes_token_id")
    if not no_token_id:
        reasons.append("missing_no_token_id")
    if yes_token_id and no_token_id and yes_token_id == no_token_id:
        reasons.append("token_pair_not_distinct")
    if market_id and market_id in {yes_token_id, no_token_id}:
        reasons.append("market_id_used_as_token_id")

    entry_time = parse_utc_time(row.get("timestamp"))
    spot_time = parse_utc_time(row.get("spot_timestamp"))
    quote_time = parse_utc_time(row.get("entry_quote_timestamp"))
    expiry_time = parse_utc_time(row.get("expiry_time"))
    if entry_time is None:
        reasons.append("missing_or_invalid_entry_timestamp")
    if spot_time is None:
        reasons.append("missing_or_invalid_spot_timestamp")
    if entry_time is not None and spot_time is not None and spot_time > entry_time:
        reasons.append("spot_timestamp_after_entry")
    if quote_time is None:
        reasons.append("missing_or_invalid_entry_quote_timestamp")
    if entry_time is not None and quote_time is not None and quote_time > entry_time:
        reasons.append("entry_quote_timestamp_after_entry")
    if expiry_time is None:
        reasons.append("missing_or_invalid_expiry_time")
    elif expiry_time <= evaluation_time:
        reasons.append("market_expired_at_evaluation")

    ages: list[float] = []
    for label, timestamp in [
        ("entry", entry_time),
        ("spot", spot_time),
        ("entry_quote", quote_time),
    ]:
        if timestamp is None:
            continue
        age_seconds = (evaluation_time - timestamp).total_seconds()
        age_minutes = age_seconds / 60.0
        ages.append(age_minutes)
        if age_seconds < -max_clock_skew_seconds:
            reasons.append(f"{label}_timestamp_in_future")
        elif age_minutes > max_entry_age_minutes and not persisted_entry_record_reused:
            reasons.append(f"stale_{label}_snapshot")

    for outcome in ["yes", "no"]:
        book_time, timestamp_error = orderbook_timestamp_integrity(
            row.get(f"{outcome}_orderbook_timestamp"),
            outcome,
            entry_time,
            max_entry_age_minutes,
            max_clock_skew_seconds,
        )
        if timestamp_error:
            reasons.append(timestamp_error)
        if book_time is not None:
            ages.append((evaluation_time - book_time).total_seconds() / 60.0)
    snapshot_age = max(ages) if ages else None
    return list(dict.fromkeys(reasons)), entry_time, snapshot_age


def evaluate_candidate_rows(
    rows: list[dict[str, str]],
    artifact_root: Path,
    evaluation_time: datetime,
    args: argparse.Namespace,
    avoid_ids: set[str],
    prepared_trade_index: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    target_rows = [row for row in rows if str(row.get("edge_type") or "") == EDGE_TYPE]
    entry_filter = ShadowEntryFilter(
        EntryFilterConfig(
            min_confidence=args.min_confidence,
            max_spread=args.max_spread,
        )
    )
    decision_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    integrity_exclusions: Counter[str] = Counter()
    diagnostics: list[dict[str, Any]] = []
    eligible_rows: list[dict[str, Any]] = []
    strict_gate_rows: list[dict[str, str]] = []
    persisted_entry_reuse_count = 0
    seen_keys: set[tuple[str, str]] = set()

    legacy_rows = [
        row
        for row in target_rows
        if safe_float(row.get("expected_edge")) >= args.legacy_min_expected_edge
        and safe_float(row.get("confidence")) >= args.min_confidence
    ]
    legacy_decisions: Counter[str] = Counter()
    for row in legacy_rows:
        legacy_result = entry_filter.evaluate(shadow_loop.candidate_from_tradable(row, avoid_ids))
        legacy_decisions[legacy_result.entry_decision.value] += 1

    for row in target_rows:
        candidate = shadow_loop.candidate_from_tradable(row, avoid_ids)
        result = entry_filter.evaluate(candidate)
        decision = result.entry_decision.value
        action = str(row.get("recommended_action") or "unknown")
        decision_counts[decision] += 1
        transition_counts[f"{action}->{decision}"] += 1

        prepared = prepared_trade_index.get(stable_trade_id(row, args.notional))
        persisted_entry_record_reused = prepared_entry_matches(row, prepared, args.notional)
        integrity_reasons, entry_time, snapshot_age = entry_integrity_reasons(
            row,
            artifact_root,
            evaluation_time,
            args.max_entry_age_minutes,
            args.max_clock_skew_seconds,
            args.notional,
            avoid_ids,
            persisted_entry_record_reused,
        )
        key = (str(row.get("market_id") or ""), str(row.get("side") or "").upper())
        if key in seen_keys:
            integrity_reasons.append("duplicate_market_side")
        seen_keys.add(key)
        if not result.allowed:
            integrity_reasons.insert(0, "shared_entry_gate_not_eligible")
        else:
            strict_gate_rows.append(row)

        position_created = result.allowed and not integrity_reasons
        if position_created:
            eligible_row: dict[str, Any] = dict(row)
            eligible_row["_persisted_entry_record_reused"] = persisted_entry_record_reused
            eligible_row["_validation_notional"] = args.notional
            eligible_rows.append(eligible_row)
            persisted_entry_reuse_count += int(persisted_entry_record_reused)
        else:
            integrity_exclusions.update(list(dict.fromkeys(integrity_reasons)))

        diagnostics.append(
            {
                "schema_version": row.get("schema_version", ""),
                "market_id": row.get("market_id", ""),
                "question": row.get("question", ""),
                "asset": row.get("asset", ""),
                "threshold_price": optional_float(row.get("threshold_price")),
                "contract_kind": row.get("contract_kind", ""),
                "barrier_direction": row.get("barrier_direction", ""),
                "parser_version": row.get("parser_version", ""),
                "model_version": row.get("model_version", ""),
                "expiry_time": row.get("expiry_time", ""),
                "expiry_local_time": row.get("expiry_local_time", ""),
                "expiry_timezone": row.get("expiry_timezone", ""),
                "expiry_time_origin": row.get("expiry_time_origin", ""),
                "expiry_time_adapter_version": row.get("expiry_time_adapter_version", ""),
                "expiry_time_provenance_sha256": row.get("expiry_time_provenance_sha256", ""),
                "gamma_start_date": row.get("gamma_start_date", ""),
                "gamma_end_date": row.get("gamma_end_date", ""),
                "gamma_market_updated_at": row.get("gamma_market_updated_at", ""),
                "gamma_market_schema": row.get("gamma_market_schema", ""),
                "gamma_market_version": row.get("gamma_market_version", ""),
                "expiry_status": row.get("expiry_status", ""),
                "gamma_raw_market_snapshot_path": row.get("gamma_raw_market_snapshot_path", ""),
                "gamma_raw_market_snapshot_sha256": row.get("gamma_raw_market_snapshot_sha256", ""),
                **{field: row.get(field, "") for field in HISTORICAL_BARRIER_FIELDS},
                "resolution_source": row.get("resolution_source", ""),
                "resolution_source_origin": row.get("resolution_source_origin", ""),
                "resolution_source_locator": row.get("resolution_source_locator", ""),
                "resolution_source_adapter_version": row.get(
                    "resolution_source_adapter_version", ""
                ),
                "resolution_source_provenance_sha256": row.get(
                    "resolution_source_provenance_sha256", ""
                ),
                "resolution_rules_sha256": row.get("resolution_rules_sha256", ""),
                "resolution_status": row.get("resolution_status", ""),
                "discovery_action": action,
                "discovery_hint": row.get("entry_decision_hint", ""),
                "edge_pass": safe_bool(row.get("edge_pass")),
                "shared_entry_decision": decision,
                "shared_reject_reasons": result.reject_reasons,
                "shared_watch_reasons": result.watch_reasons,
                "entry_time": iso_utc(entry_time) if entry_time else "",
                "spot_timestamp": row.get("spot_timestamp", ""),
                "entry_quote_timestamp": row.get("entry_quote_timestamp", ""),
                "yes_orderbook_timestamp": row.get("yes_orderbook_timestamp", ""),
                "no_orderbook_timestamp": row.get("no_orderbook_timestamp", ""),
                "entry_yes_best_ask_size": optional_float(row.get("entry_yes_best_ask_size")),
                "entry_no_best_ask_size": optional_float(row.get("entry_no_best_ask_size")),
                "entry_yes_best_bid_size": optional_float(row.get("entry_yes_best_bid_size")),
                "entry_no_best_bid_size": optional_float(row.get("entry_no_best_bid_size")),
                "entry_snapshot_age_minutes": snapshot_age,
                "persisted_entry_record_reused": persisted_entry_record_reused,
                "position_created": position_created,
                "position_exclusion_reasons": list(dict.fromkeys(integrity_reasons)),
            }
        )

    discovery_actions = Counter(
        str(row.get("recommended_action") or "unknown") for row in target_rows
    )
    discovery_shadow_count = discovery_actions.get("shadow_entry", 0)
    strict_eligible_count = decision_counts.get(EntryDecision.ELIGIBLE_SHADOW_ENTRY.value, 0)
    reconciliation = {
        "candidates_loaded": len(rows),
        "target_edge_candidates": len(target_rows),
        "non_target_edge_candidates": len(rows) - len(target_rows),
        "discovery_action_distribution": dict(discovery_actions),
        "discovery_shadow_entry_count": discovery_shadow_count,
        "discovery_watch_only_count": discovery_actions.get("watch_only", 0),
        "legacy_prefilter": {
            "min_expected_edge": args.legacy_min_expected_edge,
            "min_confidence": args.min_confidence,
            "candidates_after_prefilter": len(legacy_rows),
            "excluded_before_entry_filter": len(target_rows) - len(legacy_rows),
            "entry_decision_distribution": dict(legacy_decisions),
        },
        "shared_entry_gate_distribution_without_prefilter": dict(decision_counts),
        "discovery_to_shared_gate_transitions": dict(transition_counts),
        "strict_gate_eligible_count": strict_eligible_count,
        "strict_gate_delta_from_discovery_shadow_entry": strict_eligible_count
        - discovery_shadow_count,
        "positions_created": len(eligible_rows),
        "fresh_positions_created": len(eligible_rows) - persisted_entry_reuse_count,
        "persisted_entry_records_reused": persisted_entry_reuse_count,
        "position_delta_from_strict_gate": len(eligible_rows) - strict_eligible_count,
        "discovery_shadow_entry_cluster_count": len(
            {
                candidate_cluster_id(row)
                for row in target_rows
                if str(row.get("recommended_action") or "") == "shadow_entry"
            }
        ),
        "strict_gate_eligible_cluster_count": len(
            {candidate_cluster_id(row) for row in strict_gate_rows}
        ),
        "position_cluster_count": len({candidate_cluster_id(row) for row in eligible_rows}),
        "current_avoid_market_count": len(avoid_ids),
        "position_exclusion_reasons": dict(integrity_exclusions),
        "all_candidates_accounted_for": len(target_rows) == sum(decision_counts.values()),
        "implicit_min_edge_confidence_prefilter_applied_to_validation": False,
    }
    return eligible_rows, diagnostics, reconciliation


def relevant_exit_bid(observation: dict[str, Any], side: str) -> float | None:
    field = "no_best_bid" if side == "NO" else "yes_best_bid"
    value = optional_float(observation.get(field))
    if value is None or not 0 < value <= 1:
        return None
    return value


def relevant_exit_bid_size(observation: dict[str, Any], side: str) -> float | None:
    field = "no_best_bid_size" if side == "NO" else "yes_best_bid_size"
    value = optional_float(observation.get(field))
    if value is None or value <= 0:
        return None
    return value


def forward_observation_metadata_error(observation: dict[str, Any]) -> str | None:
    if "source" not in observation or not str(observation.get("source") or "").strip():
        return "missing_forward_observation_source"
    if observation.get("source") != TRUSTED_FORWARD_SOURCE:
        return "untrusted_forward_observation_source"
    if "stale" not in observation:
        return "missing_forward_stale_flag"
    if observation.get("stale") is not False:
        return "stale_forward_observation"
    if "error" not in observation:
        return "missing_forward_error_field"
    if observation.get("error") != "":
        return "forward_observation_error"
    return None


def selected_exit_quote_error(observation: dict[str, Any], side: str) -> str | None:
    prefix = "no" if side == "NO" else "yes"
    bid = optional_float(observation.get(f"{prefix}_best_bid"))
    ask = optional_float(observation.get(f"{prefix}_best_ask"))
    if bid is None or not 0 < bid <= 1:
        return "missing_side_specific_exit_bid"
    if ask is None or not 0 < ask <= 1:
        return "missing_side_specific_exit_ask"
    if bid > ask:
        return "crossed_side_specific_exit_book"
    return None


def opposite_exit_quote_error(observation: dict[str, Any], side: str) -> str | None:
    prefix = "yes" if side == "NO" else "no"
    bid = optional_float(observation.get(f"{prefix}_best_bid"))
    ask = optional_float(observation.get(f"{prefix}_best_ask"))
    if bid is None or not 0 < bid <= 1:
        return f"missing_or_invalid_forward_{prefix}_best_bid"
    if ask is None or not 0 < ask <= 1:
        return f"missing_or_invalid_forward_{prefix}_best_ask"
    if bid > ask:
        return f"crossed_forward_{prefix}_orderbook"
    return None


def selected_exit_size_error(
    observation: dict[str, Any], side: str, entry_share_quantity: float
) -> str | None:
    size = relevant_exit_bid_size(observation, side)
    if size is None:
        return "missing_side_specific_exit_bid_size"
    if size + 1e-12 < entry_share_quantity:
        return "insufficient_selected_exit_bid_size"
    return None


def remaining_forward_size_error(observation: dict[str, Any], side: str) -> str | None:
    selected_prefix = "no" if side == "NO" else "yes"
    for outcome in ["yes", "no"]:
        for level in ["bid", "ask"]:
            if outcome == selected_prefix and level == "bid":
                continue
            field = f"{outcome}_best_{level}_size"
            value = optional_float(observation.get(field))
            if value is None or value <= 0:
                return f"missing_or_invalid_forward_{field}"
    return None


def observation_token_error(row: dict[str, Any], observation: dict[str, Any]) -> str | None:
    for field in ["yes_token_id", "no_token_id"]:
        candidate_token = str(row.get(field) or "").strip()
        observed_token = str(observation.get(field) or "").strip()
        if not observed_token:
            return "missing_observation_token_ids"
        if candidate_token != observed_token:
            return "observation_token_mismatch"
    return None


def choose_forward_observation(
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    rejection_counts: Counter[str],
    evaluation_time: datetime,
    min_forward_horizon_minutes: float,
    notional: float,
    max_quote_age_minutes: float,
    max_clock_skew_seconds: float,
) -> tuple[dict[str, Any] | None, str]:
    market_id = str(row.get("market_id") or "")
    side = str(row.get("side") or "").upper()
    trade_id = stable_trade_id(row, notional)
    entry_time = parse_utc_time(row.get("timestamp"))
    expiry_time = parse_utc_time(row.get("expiry_time"))
    entry_price, _ = candidate_entry_price(row)
    entry_share_quantity = notional / entry_price if entry_price > 0 else math.inf
    market_observations = [
        observation
        for observation in observations
        if str(observation.get("market_id") or "") == market_id
    ]
    if not market_observations:
        return None, "missing_forward_observation"

    valid: list[tuple[datetime, dict[str, Any]]] = []
    candidate_rejections: Counter[str] = Counter()

    def reject(reason: str) -> None:
        rejection_counts[reason] += 1
        candidate_rejections[reason] += 1

    for observation in market_observations:
        observed_trade_id = str(observation.get("shadow_trade_id") or "").strip()
        if not observed_trade_id:
            reject("missing_shadow_trade_id")
            continue
        if observed_trade_id != trade_id:
            reject("shadow_trade_id_mismatch")
            continue
        observed_time = parse_utc_time(observation.get("timestamp"))
        if observed_time is None:
            reject("invalid_observation_timestamp")
            continue
        if entry_time is None or observed_time <= entry_time:
            reject("observation_not_strictly_post_entry")
            continue
        if observed_time > evaluation_time:
            reject("observation_after_evaluation_time")
            continue
        holding_minutes = (observed_time - entry_time).total_seconds() / 60.0
        if holding_minutes < min_forward_horizon_minutes:
            reject("observation_before_min_forward_horizon")
            continue
        if expiry_time is not None and observed_time > expiry_time:
            reject("observation_after_market_expiry")
            continue
        metadata_error = forward_observation_metadata_error(observation)
        if metadata_error:
            reject(metadata_error)
            continue
        observed_side = str(observation.get("side") or "").strip().upper()
        if not observed_side:
            reject("missing_observation_side")
            continue
        if observed_side != side:
            reject("observation_side_mismatch")
            continue
        token_error = observation_token_error(row, observation)
        if token_error:
            reject(token_error)
            continue
        quote_error = selected_exit_quote_error(observation, side)
        if quote_error:
            reject(quote_error)
            continue
        opposite_quote_error = opposite_exit_quote_error(observation, side)
        if opposite_quote_error:
            reject(opposite_quote_error)
            continue
        timestamp_error = None
        for outcome in ["yes", "no"]:
            _, timestamp_error = orderbook_timestamp_integrity(
                observation.get(f"{outcome}_orderbook_timestamp"),
                f"forward_{outcome}",
                observed_time,
                max_quote_age_minutes,
                max_clock_skew_seconds,
            )
            if timestamp_error:
                break
        if timestamp_error:
            reject(timestamp_error)
            continue
        size_error = selected_exit_size_error(observation, side, entry_share_quantity)
        if size_error:
            reject(size_error)
            continue
        remaining_size_error = remaining_forward_size_error(observation, side)
        if remaining_size_error:
            reject(remaining_size_error)
            continue
        valid.append((observed_time, observation))

    if not valid:
        primary_reason = candidate_rejections.most_common(1)[0][0]
        return None, primary_reason
    valid.sort(key=lambda item: item[0])
    return valid[0][1], ""


def build_position(
    row: dict[str, Any],
    observation: dict[str, Any] | None,
    insufficient_reason: str,
    evaluation_time: datetime,
    args: argparse.Namespace,
) -> ValidationPosition:
    entry_time = parse_utc_time(row.get("timestamp"))
    if entry_time is None:
        raise ValueError("validated candidate is missing entry timestamp")
    entry_price, entry_price_field = candidate_entry_price(row)
    side = str(row.get("side") or "").upper()
    entry_share_quantity = args.notional / entry_price
    identity_sha256 = entry_identity_sha256(row, args.notional)
    snapshot_age = (evaluation_time - entry_time).total_seconds() / 60.0
    position = ValidationPosition(
        shadow_trade_id=stable_trade_id(row, args.notional),
        schema_version=str(row.get("schema_version") or ""),
        market_id=str(row.get("market_id") or ""),
        question=str(row.get("question") or ""),
        asset=str(row.get("asset") or ""),
        threshold_price=safe_float(row.get("threshold_price")),
        direction=str(row.get("direction") or ""),
        contract_kind=str(row.get("contract_kind") or ""),
        barrier_direction=str(row.get("barrier_direction") or ""),
        parser_version=str(row.get("parser_version") or ""),
        model_version=str(row.get("model_version") or ""),
        expiry_time=str(row.get("expiry_time") or ""),
        expiry_local_time=str(row.get("expiry_local_time") or ""),
        expiry_timezone=str(row.get("expiry_timezone") or ""),
        expiry_time_origin=str(row.get("expiry_time_origin") or ""),
        expiry_time_adapter_version=str(row.get("expiry_time_adapter_version") or ""),
        expiry_time_provenance_sha256=str(row.get("expiry_time_provenance_sha256") or "").lower(),
        gamma_start_date=str(row.get("gamma_start_date") or ""),
        gamma_end_date=str(row.get("gamma_end_date") or ""),
        gamma_market_updated_at=str(row.get("gamma_market_updated_at") or ""),
        gamma_market_schema=str(row.get("gamma_market_schema") or ""),
        gamma_market_version=str(row.get("gamma_market_version") or ""),
        expiry_status=str(row.get("expiry_status") or ""),
        gamma_raw_market_snapshot_path=str(row.get("gamma_raw_market_snapshot_path") or ""),
        gamma_raw_market_snapshot_sha256=str(
            row.get("gamma_raw_market_snapshot_sha256") or ""
        ).lower(),
        historical_barrier_evidence_status=str(row.get("historical_barrier_evidence_status") or ""),
        historical_barrier_evidence_source=str(row.get("historical_barrier_evidence_source") or ""),
        historical_barrier_evidence_start_time=str(
            row.get("historical_barrier_evidence_start_time") or ""
        ),
        historical_barrier_evidence_end_time=str(
            row.get("historical_barrier_evidence_end_time") or ""
        ),
        historical_barrier_evidence_sha256=str(
            row.get("historical_barrier_evidence_sha256") or ""
        ).lower(),
        historical_barrier_evidence_adapter_version=str(
            row.get("historical_barrier_evidence_adapter_version") or ""
        ),
        historical_barrier_evidence_origin=str(row.get("historical_barrier_evidence_origin") or ""),
        historical_barrier_evidence_locator=str(
            row.get("historical_barrier_evidence_locator") or ""
        ),
        historical_barrier_evidence_interval=str(
            row.get("historical_barrier_evidence_interval") or ""
        ),
        historical_barrier_evidence_symbol=str(row.get("historical_barrier_evidence_symbol") or ""),
        historical_barrier_evidence_candle_count=int(
            safe_float(row.get("historical_barrier_evidence_candle_count"))
        ),
        historical_barrier_evidence_missing_ranges=str(
            row.get("historical_barrier_evidence_missing_ranges") or ""
        ),
        historical_barrier_evidence_path=str(row.get("historical_barrier_evidence_path") or ""),
        historical_barrier_candle_snapshot_path=str(
            row.get("historical_barrier_candle_snapshot_path") or ""
        ),
        historical_barrier_candle_snapshot_sha256=str(
            row.get("historical_barrier_candle_snapshot_sha256") or ""
        ).lower(),
        historical_barrier_rule_window_adapter_version=str(
            row.get("historical_barrier_rule_window_adapter_version") or ""
        ),
        historical_barrier_rule_window_provenance_sha256=str(
            row.get("historical_barrier_rule_window_provenance_sha256") or ""
        ).lower(),
        historical_barrier_crossed_at=str(row.get("historical_barrier_crossed_at") or ""),
        historical_barrier_expected_candle_count=int(
            safe_float(row.get("historical_barrier_expected_candle_count"))
        ),
        historical_barrier_min_low_price=str(row.get("historical_barrier_min_low_price") or ""),
        historical_barrier_max_high_price=str(row.get("historical_barrier_max_high_price") or ""),
        historical_barrier_tail_coverage_status=str(
            row.get("historical_barrier_tail_coverage_status") or ""
        ),
        historical_barrier_tail_covered_through=str(
            row.get("historical_barrier_tail_covered_through") or ""
        ),
        historical_barrier_first_touch_at=str(row.get("historical_barrier_first_touch_at") or ""),
        resolution_source=normalize_resolution_text(row.get("resolution_source")),
        resolution_source_origin=normalize_resolution_text(row.get("resolution_source_origin")),
        resolution_source_locator=normalize_resolution_text(row.get("resolution_source_locator")),
        resolution_source_adapter_version=normalize_resolution_text(
            row.get("resolution_source_adapter_version")
        ),
        resolution_source_provenance_sha256=normalize_resolution_text(
            row.get("resolution_source_provenance_sha256")
        ).lower(),
        resolution_rules=normalize_resolution_text(row.get("resolution_rules")),
        resolution_rules_sha256=resolution_rules_sha256(row.get("resolution_rules")),
        resolution_status=str(row.get("resolution_status") or ""),
        spot_price=safe_float(row.get("spot_price")),
        spot_timestamp=str(row.get("spot_timestamp") or ""),
        spot_source=str(row.get("spot_source") or ""),
        entry_quote_timestamp=str(row.get("entry_quote_timestamp") or ""),
        yes_orderbook_timestamp=str(row.get("yes_orderbook_timestamp") or ""),
        no_orderbook_timestamp=str(row.get("no_orderbook_timestamp") or ""),
        entry_yes_best_ask_size=safe_float(row.get("entry_yes_best_ask_size")),
        entry_no_best_ask_size=safe_float(row.get("entry_no_best_ask_size")),
        entry_yes_best_bid_size=safe_float(row.get("entry_yes_best_bid_size")),
        entry_no_best_bid_size=safe_float(row.get("entry_no_best_bid_size")),
        entry_share_quantity=entry_share_quantity,
        notional=args.notional,
        entry_identity_sha256=identity_sha256,
        entry_epoch=candidate_entry_epoch(row),
        cluster_id=candidate_cluster_id(row),
        side=side,
        entry_time=iso_utc(entry_time),
        entry_snapshot_age_minutes=snapshot_age,
        persisted_entry_record_reused=safe_bool(row.get("_persisted_entry_record_reused")),
        entry_price=entry_price,
        entry_price_source=entry_price_field,
        expected_edge=safe_float(row.get("expected_edge")),
        confidence=safe_float(row.get("confidence")),
        yes_token_id=str(row.get("yes_token_id") or ""),
        no_token_id=str(row.get("no_token_id") or ""),
        entry_yes_best_ask=safe_float(row.get("entry_yes_best_ask")),
        entry_no_best_ask=safe_float(row.get("entry_no_best_ask")),
        entry_yes_best_bid=safe_float(row.get("entry_yes_best_bid")),
        entry_no_best_bid=safe_float(row.get("entry_no_best_bid")),
        combined_ask=safe_float(row.get("combined_ask")),
        orderbook_spread=safe_float(row.get("spread")),
        orderbook_depth=safe_float(row.get("orderbook_depth")),
        liquidity_score=safe_float(row.get("liquidity_score")),
        evidence=str(row.get("evidence") or row.get("reasons") or ""),
        source=str(row.get("source") or "crypto_threshold_edge"),
        insufficient_reason=insufficient_reason or "missing_forward_observation",
    )
    if observation is None:
        return position

    observed_time = parse_utc_time(observation.get("timestamp"))
    exit_price = relevant_exit_bid(observation, side)
    if observed_time is None or exit_price is None:
        return position
    cost_rate = max(0.0, args.fee_bps + args.slippage_bps) / 10000.0
    gross_change = exit_price - entry_price
    cost_change = entry_price * cost_rate
    net_change = gross_change - cost_change
    position.exit_time = iso_utc(observed_time)
    position.exit_price = exit_price
    position.exit_price_source = f"{side.lower()}_best_bid"
    position.exit_side_best_bid_size = relevant_exit_bid_size(observation, side)
    position.holding_minutes = (observed_time - entry_time).total_seconds() / 60.0
    position.gross_price_change = gross_change
    position.cost_price_change = cost_change
    position.net_price_change = net_change
    position.return_pct = net_change / entry_price
    position.pnl = args.notional * position.return_pct
    position.status = "closed"
    position.insufficient_reason = ""
    position.forward_source = str(observation.get("source") or "offline_forward_observation")
    return position


def max_drawdown(positions: list[ValidationPosition]) -> float | None:
    closed = sorted(
        [position for position in positions if position.status == "closed"],
        key=lambda position: position.exit_time or "",
    )
    if not closed:
        return None
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for position in closed:
        equity += position.pnl or 0.0
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = mean(xs)
    y_mean = mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_variance = sum((x - x_mean) ** 2 for x in xs)
    y_variance = sum((y - y_mean) ** 2 for y in ys)
    denominator = math.sqrt(x_variance * y_variance)
    return numerator / denominator if denominator > 0 else None


def grouped_performance(
    positions: list[ValidationPosition], attribute: str
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[ValidationPosition]] = defaultdict(list)
    for position in positions:
        groups[str(getattr(position, attribute) or "unknown")].append(position)
    output: dict[str, dict[str, Any]] = {}
    for key, values in groups.items():
        closed = [value for value in values if value.status == "closed"]
        returns = [value.return_pct for value in closed if value.return_pct is not None]
        output[key] = {
            "positions": len(values),
            "closed_positions": len(closed),
            "insufficient_forward_data_positions": len(values) - len(closed),
            "average_return": mean(returns) if returns else None,
            "win_rate": (
                len([value for value in returns if value > 0]) / len(returns) if returns else None
            ),
        }
    return output


def concentration_summary(positions: list[ValidationPosition], attribute: str) -> dict[str, Any]:
    counts = Counter(str(getattr(position, attribute) or "unknown") for position in positions)
    total = len(positions)
    return {
        "counts": dict(counts),
        "distinct_values": len(counts),
        "largest_share": max(counts.values()) / total if total else None,
    }


def performance_summary(positions: list[ValidationPosition]) -> dict[str, Any]:
    closed = [position for position in positions if position.status == "closed"]
    insufficient_reasons = Counter(
        position.insufficient_reason
        for position in positions
        if position.status != "closed" and position.insufficient_reason
    )
    returns = [position.return_pct for position in closed if position.return_pct is not None]
    pnl_values = [position.pnl for position in closed if position.pnl is not None]
    realized_changes = [
        position.net_price_change for position in closed if position.net_price_change is not None
    ]
    expected_edges = [position.expected_edge for position in closed]
    position_clusters = Counter(position.cluster_id for position in positions)
    closed_clusters = Counter(position.cluster_id for position in closed)
    return {
        "total_positions": len(positions),
        "closed_positions": len(closed),
        "insufficient_forward_data_positions": len(positions) - len(closed),
        "insufficient_reason_distribution": dict(insufficient_reasons),
        "forward_data_coverage": len(closed) / len(positions) if positions else None,
        "win_rate": (
            len([value for value in returns if value > 0]) / len(returns) if returns else None
        ),
        "average_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None,
        "total_pnl": sum(pnl_values) if pnl_values else None,
        "max_drawdown": max_drawdown(positions),
        "average_holding_minutes": (
            mean(
                [
                    position.holding_minutes
                    for position in closed
                    if position.holding_minutes is not None
                ]
            )
            if closed
            else None
        ),
        "expected_edge_realized_price_change_correlation": pearson_correlation(
            expected_edges, realized_changes
        ),
        "position_cluster_count": len(position_clusters),
        "closed_position_cluster_count": len(closed_clusters),
        "max_position_cluster_share": (
            max(position_clusters.values()) / len(positions) if positions else None
        ),
        "asset_performance": grouped_performance(positions, "asset"),
        "side_performance": grouped_performance(positions, "side"),
        "direction_performance": grouped_performance(positions, "direction"),
        "contract_kind_performance": grouped_performance(positions, "contract_kind"),
        "barrier_direction_performance": grouped_performance(positions, "barrier_direction"),
        "expiry_performance": grouped_performance(positions, "expiry_time"),
        "cluster_performance": grouped_performance(positions, "cluster_id"),
        "concentration": {
            attribute: concentration_summary(positions, attribute)
            for attribute in [
                "asset",
                "expiry_time",
                "side",
                "contract_kind",
                "barrier_direction",
                "cluster_id",
            ]
        },
    }


def validation_conclusion(
    reconciliation: dict[str, Any],
    performance: dict[str, Any],
    min_sample_size: int,
    min_independent_clusters: int,
) -> dict[str, Any]:
    positions_created = reconciliation.get("positions_created", 0)
    closed_positions = performance.get("closed_positions", 0)
    closed_clusters = performance.get("closed_position_cluster_count", 0)
    average_return = performance.get("average_return")
    exclusion_reasons = reconciliation.get("position_exclusion_reasons") or {}
    target_candidates = reconciliation.get("target_edge_candidates", 0)
    missing_history_count = exclusion_reasons.get("missing_historical_barrier_evidence", 0)
    if (
        positions_created == 0
        and target_candidates > 0
        and missing_history_count == target_candidates
    ):
        status = "historical_barrier_evidence_required"
        reasons = ["missing_historical_barrier_evidence"]
    elif positions_created == 0:
        status = "entry_snapshot_refresh_required"
        reasons = ["no_fresh_entry_snapshots"]
    elif closed_positions == 0:
        status = "insufficient_forward_data"
        reasons = list(performance.get("insufficient_reason_distribution") or {})
        if not reasons:
            reasons = ["missing_forward_observation"]
    elif closed_positions < min_sample_size:
        status = "insufficient_sample"
        reasons = [f"closed_positions_below_{min_sample_size}"]
    elif closed_clusters < min_independent_clusters:
        status = "insufficient_independent_clusters"
        reasons = [f"independent_clusters_below_{min_independent_clusters}"]
    elif average_return is None or average_return <= 0:
        status = "negative_expectancy_observed"
        reasons = ["average_return_not_positive"]
    else:
        status = "research_only_positive_sample"
        reasons = ["positive_sample_requires_further_out_of_sample_validation"]
    return {
        "status": status,
        "reasons": reasons,
        "min_sample_size": min_sample_size,
        "min_independent_clusters": min_independent_clusters,
        "independent_clusters_observed": closed_clusters,
        "positive_expectancy_observed": bool(
            closed_positions >= min_sample_size
            and closed_clusters >= min_independent_clusters
            and average_return is not None
            and average_return > 0
        ),
        "supports_tiny_live": False,
        "tiny_live_recommendation": TINY_LIVE_RECOMMENDATION,
    }


def verify_safety() -> dict[str, Any]:
    safety = shadow_loop.verify_safety()
    if not safety.get("safe_to_shadow_trade"):
        raise RuntimeError("Refusing shadow validation while safe paper-only flags are not active")
    safety.update(
        {
            "offline_forward_observations_only": True,
            "public_clob_refresh_delegated_to_existing_read_only_poller": True,
            "authenticated_endpoints": False,
            "order_placement": False,
            "order_cancellation": False,
            "tiny_live_recommendation": TINY_LIVE_RECOMMENDATION,
        }
    )
    return safety


def validate_configuration(args: argparse.Namespace) -> None:
    candidate_path = Path(args.candidate_file)
    avoid_path = Path(args.avoid_file)
    output_path = Path(args.output_dir).resolve()
    if not candidate_path.is_file():
        raise FileNotFoundError(f"candidate_file not found: {candidate_path}")
    if not avoid_path.is_file():
        raise FileNotFoundError(f"avoid_file not found: {avoid_path}")
    protected_outputs = {
        REPO_ROOT.resolve(),
        (REPO_ROOT / "runs").resolve(),
        LEGACY_SHADOW_DIR,
    }
    if output_path in protected_outputs or LEGACY_SHADOW_DIR in output_path.parents:
        raise ValueError("output_dir must be an isolated Step 12 directory")
    if not math.isfinite(args.max_entry_age_minutes) or args.max_entry_age_minutes <= 0:
        raise ValueError("max_entry_age_minutes must be positive and finite")
    if (
        not math.isfinite(args.min_forward_horizon_minutes)
        or args.min_forward_horizon_minutes < 240
    ):
        raise ValueError("min_forward_horizon_minutes must be finite and at least 240")
    args.max_clock_skew_seconds = effective_max_clock_skew_seconds(args)
    if not math.isfinite(args.notional) or args.notional <= 0:
        raise ValueError("notional must be positive and finite")
    if (
        not math.isfinite(args.fee_bps)
        or not math.isfinite(args.slippage_bps)
        or args.fee_bps < 0
        or args.slippage_bps < 0
    ):
        raise ValueError("fee_bps and slippage_bps must be non-negative and finite")
    if args.min_sample_size <= 0 or args.min_independent_clusters <= 0:
        raise ValueError("sample and independent-cluster gates must be positive")
    if not math.isfinite(args.max_spread) or args.max_spread <= 0:
        raise ValueError("max_spread must be finite and positive")
    if not math.isfinite(args.min_confidence) or not 0 <= args.min_confidence <= 1:
        raise ValueError("min_confidence must be finite and between zero and one")
    if not math.isfinite(args.legacy_min_expected_edge):
        raise ValueError("legacy_min_expected_edge must be finite")


def validate(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[ValidationPosition], list[dict[str, Any]]]:
    validate_configuration(args)
    candidate_path = Path(args.candidate_file)
    output_dir = Path(args.output_dir)
    forward_path = (
        Path(args.forward_observations)
        if args.forward_observations
        else (output_dir / "forward_observations.jsonl")
    )
    evaluation_time = (
        parse_utc_time(args.evaluation_time)
        if args.evaluation_time
        else (datetime.now(timezone.utc))
    )
    if evaluation_time is None:
        raise ValueError("evaluation_time must be a valid ISO timestamp")

    rows = load_csv_rows(candidate_path)
    avoid_path = Path(args.avoid_file)
    avoid_ids = load_avoid_market_ids(avoid_path)
    prepared_path = output_dir / "shadow_trades.csv"
    prepared_trade_index = load_prepared_trade_index(prepared_path)
    prepared_input_sha256 = file_sha256(prepared_path)
    observations, invalid_observation_count = load_forward_observations(forward_path)
    eligible_rows, diagnostics, reconciliation = evaluate_candidate_rows(
        rows,
        candidate_path.parent,
        evaluation_time,
        args,
        avoid_ids,
        prepared_trade_index,
    )
    rejection_counts: Counter[str] = Counter()
    positions: list[ValidationPosition] = []
    for row in eligible_rows:
        observation, reason = choose_forward_observation(
            row,
            observations,
            rejection_counts,
            evaluation_time,
            args.min_forward_horizon_minutes,
            args.notional,
            args.max_entry_age_minutes,
            args.max_clock_skew_seconds,
        )
        positions.append(build_position(row, observation, reason, evaluation_time, args))

    performance = performance_summary(positions)
    conclusion = validation_conclusion(
        reconciliation,
        performance,
        args.min_sample_size,
        args.min_independent_clusters,
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "cluster_policy": CLUSTER_POLICY,
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "mode": "offline_shadow_validation",
        "inputs": {
            "candidate_file": str(candidate_path),
            "candidate_file_exists": candidate_path.exists(),
            "avoid_file": str(avoid_path),
            "avoid_file_exists": avoid_path.exists(),
            "forward_observations": str(forward_path),
            "forward_observations_exists": forward_path.exists(),
            "evaluation_time": iso_utc(evaluation_time),
            "max_entry_age_minutes": args.max_entry_age_minutes,
            "max_clock_skew_seconds": args.max_clock_skew_seconds,
            "min_forward_horizon_minutes": args.min_forward_horizon_minutes,
            "notional": args.notional,
            "fee_bps": args.fee_bps,
            "slippage_bps": args.slippage_bps,
        },
        "artifact_provenance": {
            "output_namespace": "crypto_threshold_shadow_step12",
            "output_dir": str(output_dir.resolve()),
            "legacy_shadow_dir_protected": str(LEGACY_SHADOW_DIR),
            "candidate_file_sha256": file_sha256(candidate_path),
            "avoid_file_sha256": file_sha256(avoid_path),
            "forward_observations_sha256": file_sha256(forward_path),
            "prepared_shadow_trades_input_sha256": prepared_input_sha256,
            # Backward-compatible alias. This always describes the pre-write input.
            "prepared_shadow_trades_sha256": prepared_input_sha256,
            "prepared_shadow_trades_sha256_semantics": (
                "legacy_alias_of_prepared_shadow_trades_input_sha256"
            ),
            "prepared_trade_records_loaded": len(prepared_trade_index),
            "prepared_shadow_trades_input_snapshot_path": "",
            "prepared_shadow_trades_input_snapshot_sha256": "",
            "shadow_trades_output_sha256": "",
        },
        "reconciliation": reconciliation,
        "forward_data": {
            "observations_loaded": len(observations),
            "invalid_observations": invalid_observation_count,
            "observation_rejection_reasons": dict(rejection_counts),
            "matching_policy": (
                "exact_trade_id_market_id_and_token_pair_after_entry_before_evaluation"
            ),
            "min_forward_horizon_minutes": args.min_forward_horizon_minutes,
            "price_policy": "entry_side_ask_to_exit_side_bid",
            "source_timestamp_policy": (
                "both_yes_no_server_orderbook_timestamps_required_with_quote_age_and_clock_skew_gates"
            ),
            "complete_book_policy": (
                "both_yes_no_non_crossed_bid_ask_prices_and_all_four_positive_sizes_required"
            ),
            "executable_size_policy": (
                "notional_divided_by_entry_ask_must_fit_entry_ask_and_exit_bid_size"
            ),
            "generic_observed_price_fallback_used": False,
        },
        "performance": performance,
        "validation": conclusion,
        "safety_verification": verify_safety(),
        "tiny_live_recommendation": TINY_LIVE_RECOMMENDATION,
    }
    return summary, positions, diagnostics


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            for field in [
                "shared_reject_reasons",
                "shared_watch_reasons",
                "position_exclusion_reasons",
            ]:
                if isinstance(payload.get(field), list):
                    payload[field] = "|".join(payload[field])
            writer.writerow({field: payload.get(field, "") for field in fieldnames})


def write_positions_json(path: Path, positions: list[ValidationPosition]) -> None:
    payload = {
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "open_positions": [],
        "closed_positions": [
            position.to_shadow_trade_dict() for position in positions if position.status == "closed"
        ],
        "insufficient_forward_data_positions": [
            position.to_shadow_trade_dict() for position in positions if position.status != "closed"
        ],
    }
    path.write_text(json.dumps(payload, indent=2, allow_nan=False))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    reconciliation = summary["reconciliation"]
    performance = summary["performance"]
    validation = summary["validation"]
    forward = summary["forward_data"]
    provenance = summary["artifact_provenance"]
    lines = [
        "# Crypto Threshold Corrected Shadow PnL Validation",
        "",
        "This report is hypothetical, offline research. It is not a live trading result.",
        "Entry uses the selected side ask; exit uses the same side bid.",
        "Missing or invalid forward data never contributes PnL.",
        "",
        "## Artifact Provenance",
        "",
        f"- Prepared input SHA-256: {provenance['prepared_shadow_trades_input_sha256'] or 'none'}",
        "- Immutable prepared-input snapshot: "
        f"{provenance['prepared_shadow_trades_input_snapshot_path'] or 'none'}",
        "- Immutable snapshot SHA-256: "
        f"{provenance['prepared_shadow_trades_input_snapshot_sha256'] or 'none'}",
        "",
        "## Candidate Reconciliation",
        "",
        f"- Candidates loaded: {reconciliation['candidates_loaded']}",
        f"- Discovery shadow entries: {reconciliation['discovery_shadow_entry_count']}",
        f"- Discovery watch only: {reconciliation['discovery_watch_only_count']}",
        "- Legacy prefilter candidates: "
        f"{reconciliation['legacy_prefilter']['candidates_after_prefilter']}",
        f"- Strict shared-gate eligible: {reconciliation['strict_gate_eligible_count']}",
        f"- Validation positions created: {reconciliation['positions_created']}",
        f"- Fresh positions created: {reconciliation['fresh_positions_created']}",
        f"- Persisted entries reused: {reconciliation['persisted_entry_records_reused']}",
        f"- Cluster policy: {summary['cluster_policy']}",
        "- Discovery shadow-entry clusters: "
        f"{reconciliation['discovery_shadow_entry_cluster_count']}",
        f"- All candidates accounted for: {reconciliation['all_candidates_accounted_for']}",
        "",
        "Position exclusion reasons:",
        "",
        "```json",
        json.dumps(reconciliation["position_exclusion_reasons"], indent=2),
        "```",
        "",
        "## Forward Data",
        "",
        f"- Observations loaded: {forward['observations_loaded']}",
        f"- Invalid observations: {forward['invalid_observations']}",
        f"- Matching policy: {forward['matching_policy']}",
        f"- Price policy: {forward['price_policy']}",
        f"- Source timestamp policy: {forward['source_timestamp_policy']}",
        f"- Complete book policy: {forward['complete_book_policy']}",
        f"- Executable size policy: {forward['executable_size_policy']}",
        "",
        "Observation rejection reasons:",
        "",
        "```json",
        json.dumps(forward["observation_rejection_reasons"], indent=2),
        "```",
        "",
        "## Performance",
        "",
        f"- Total positions: {performance['total_positions']}",
        f"- Closed positions: {performance['closed_positions']}",
        f"- Insufficient forward data: {performance['insufficient_forward_data_positions']}",
        "- Insufficient reason distribution: "
        + json.dumps(performance["insufficient_reason_distribution"], sort_keys=True),
        f"- Win rate: {performance['win_rate']}",
        f"- Average return: {performance['average_return']}",
        f"- Total PnL: {performance['total_pnl']}",
        f"- Max drawdown: {performance['max_drawdown']}",
        f"- Closed independent clusters: {performance['closed_position_cluster_count']}",
        f"- Max position cluster share: {performance['max_position_cluster_share']}",
        "",
        "Position concentration:",
        "",
        "```json",
        json.dumps(performance["concentration"], indent=2),
        "```",
        "",
        "## Validation Gate",
        "",
        f"- Status: {validation['status']}",
        f"- Supports tiny live: {validation['supports_tiny_live']}",
        f"- tiny_live_recommendation: {TINY_LIVE_RECOMMENDATION}",
        "",
    ]
    path.write_text("\n".join(lines))


def write_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    positions: list[ValidationPosition],
    diagnostics: list[dict[str, Any]],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = summary.setdefault("artifact_provenance", {})
    prepared_path = output_dir / "shadow_trades.csv"
    prepared_input_sha256 = str(provenance.get("prepared_shadow_trades_input_sha256") or "")
    current_input_sha256 = file_sha256(prepared_path)
    if current_input_sha256 and not prepared_input_sha256:
        prepared_input_sha256 = current_input_sha256
        provenance["prepared_shadow_trades_input_sha256"] = current_input_sha256
        provenance["prepared_shadow_trades_sha256"] = current_input_sha256
    snapshot_path = snapshot_prepared_input(
        prepared_path,
        output_dir,
        prepared_input_sha256,
    )
    if snapshot_path is not None:
        provenance["prepared_shadow_trades_input_snapshot_path"] = str(snapshot_path.resolve())
        provenance["prepared_shadow_trades_input_snapshot_sha256"] = file_sha256(snapshot_path)

    paths = {
        "validation_csv": output_dir / "crypto_threshold_shadow_validation.csv",
        "reconciliation_csv": output_dir / "crypto_threshold_candidate_reconciliation.csv",
        "summary_json": output_dir / "crypto_threshold_shadow_pnl_summary.json",
        "report_md": output_dir / "crypto_threshold_shadow_pnl_report.md",
        "shadow_trades_csv": prepared_path,
        "shadow_positions_json": output_dir / "shadow_positions.json",
    }
    if snapshot_path is not None:
        paths["prepared_input_snapshot"] = snapshot_path
    write_csv(
        paths["validation_csv"],
        VALIDATION_FIELDS,
        [position.to_validation_dict() for position in positions],
    )
    write_csv(paths["reconciliation_csv"], RECONCILIATION_FIELDS, diagnostics)
    write_csv(
        paths["shadow_trades_csv"],
        SHADOW_TRADE_FIELDS,
        [position.to_shadow_trade_dict() for position in positions],
    )
    output_sha256 = file_sha256(paths["shadow_trades_csv"])
    provenance["shadow_trades_output_sha256"] = output_sha256
    provenance["shadow_trades_output_path"] = str(paths["shadow_trades_csv"].resolve())
    write_positions_json(paths["shadow_positions_json"], positions)
    paths["summary_json"].write_text(json.dumps(summary, indent=2, allow_nan=False))
    write_report(paths["report_md"], summary)
    return {key: str(value) for key, value in paths.items()}


def run(args: argparse.Namespace) -> int:
    summary, positions, diagnostics = validate(args)
    if args.dry_run:
        print("DRY RUN: corrected crypto-threshold shadow PnL validation")
        print(json.dumps(summary, indent=2, allow_nan=False))
        return 0
    paths = write_outputs(Path(args.output_dir), summary, positions, diagnostics)
    print(json.dumps({"summary": summary, "outputs": paths}, indent=2, allow_nan=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
