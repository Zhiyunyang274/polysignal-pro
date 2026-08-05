#!/usr/bin/env python3
"""
Trading MVP Step 10 — Crypto Price Threshold Edge discovery schema v5.

This script is read-only and shadow-only. It scans public Gamma markets for
BTC/ETH/SOL threshold questions, reads public spot prices and public CLOB
orderbooks, then emits crypto_price_threshold_v1 candidates. It does not
authenticate, sign, place orders, cancel orders, call LLMs, or enter any live
execution pathway.

Title-local expiry timestamps are reconciled with Gamma and explicit rule
timezone evidence before being emitted as canonical UTC. Touch contracts whose
entry history lacks complete candle coverage remain watch-only.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Literal, cast

import httpx

from polysignal.ingestion.api_errors import CLOBError
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.shadow.expiry_provenance import (
    ExpiryProvenance,
    resolve_expiry_provenance,
)
from polysignal.shadow.gamma_raw_snapshot import (
    GammaRawPayloadSnapshot,
    GammaRawSnapshotRecorder,
    GammaSnapshotConflictError,
    GammaSnapshotResult,
)
from polysignal.shadow.historical_barrier_provenance import (
    HISTORICAL_BARRIER_STATUS_VERIFIED,
    BinanceHistoricalKlineClient,
    BinanceKlineFetchResult,
    HistoricalArtifactConflictError,
    HistoricalBarrierEvidence,
    HistoricalCandleAuditReference,
    HistoricalCandleSnapshotReference,
    RuleObservationWindow,
    evaluate_historical_barrier,
    historical_evidence_candidate_fields,
    merge_kline_fetch_results,
    not_required_historical_evidence,
    parse_rule_observation_window,
    persist_historical_candle_snapshot,
    prepare_historical_candle_audit,
    unavailable_historical_evidence,
)
from polysignal.shadow.resolution_provenance import (
    ResolutionProvenance,
    resolve_resolution_provenance,
)
from scripts.discover_executable_edges import (
    GammaActiveMarketClient,
    TokenPair,
    extract_token_pair,
    filter_markets,
    market_id,
    market_safety_reject_reason,
    market_volume,
    question,
    verify_safety,
)
from scripts.discover_multi_edge_candidates import book_features, clamp
from scripts.run_shadow_paper_loop import safe_float

EDGE_TYPE = "crypto_price_threshold_v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DISCOVERY_SCHEMA_VERSION = "crypto_threshold_edge_discovery_v5"
PARSER_VERSION = "crypto_threshold_parser_v4"
MODEL_VERSION = "crypto_threshold_probability_v1"
SETTLEMENT_THRESHOLD = "settlement_threshold"
TOUCH_BEFORE_EXPIRY = "touch_before_expiry"
BARRIER_UP = "up"
BARRIER_DOWN = "down"
BARRIER_UNKNOWN = "unknown"
MISSING_HISTORICAL_BARRIER_EVIDENCE = "missing_historical_barrier_evidence"
MISSING_RULE_BARRIER_START = "missing_rule_barrier_start"
HISTORICAL_BARRIER_EVIDENCE_NOT_REQUIRED = "not_required"
MAX_ENTRY_EVIDENCE_AGE_SECONDS = 60.0
MAX_ORDERBOOK_CONCURRENCY = 8
ASSET_ALIASES = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum"),
    "SOL": ("sol", "solana"),
}
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
ANNUAL_VOL_PROXY = {"BTC": 0.60, "ETH": 0.75, "SOL": 0.95}
OUTPUT_FIELDS = [
    "schema_version",
    "edge_type",
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
    "resolution_source",
    "resolution_source_origin",
    "resolution_source_locator",
    "resolution_source_adapter_version",
    "resolution_source_provenance_sha256",
    "resolution_rules",
    "resolution_rules_sha256",
    "resolution_status",
    "parser_confidence",
    "side",
    "yes_token_id",
    "no_token_id",
    "spot_price",
    "spot_timestamp",
    "spot_source",
    "distance_to_threshold",
    "distance_pct",
    "time_to_expiry_hours",
    "volatility_proxy",
    "yes_best_bid",
    "yes_best_ask",
    "no_best_bid",
    "no_best_ask",
    "yes_spread",
    "no_spread",
    "max_spread",
    "spread",
    "orderbook_depth",
    "depth",
    "liquidity_score",
    "market_implied_probability",
    "model_estimated_probability",
    "expected_edge",
    "executable_edge",
    "confidence",
    "probability_reason",
    "evidence",
    "risk_flags",
    "recommended_action",
    "edge_status",
    "edge_failure_reason",
    "expected_edge_source",
    "expected_edge_status",
    "edge_pass",
    "entry_yes_best_ask",
    "entry_no_best_ask",
    "entry_yes_best_bid",
    "entry_no_best_bid",
    "entry_yes_best_ask_size",
    "entry_no_best_ask_size",
    "entry_yes_best_bid_size",
    "entry_no_best_bid_size",
    "entry_quote_timestamp",
    "yes_orderbook_timestamp",
    "no_orderbook_timestamp",
    "combined_ask",
    "combined_ask_gap",
    "near_miss_tier",
    "evidence_level",
    "entry_decision_hint",
    "source",
    "volume",
    "category",
    "timestamp",
    "reasons",
    "tradable_score",
]
DIAGNOSTIC_FIELDS = [
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
    "resolution_source",
    "resolution_source_origin",
    "resolution_source_locator",
    "resolution_source_adapter_version",
    "resolution_source_provenance_sha256",
    "resolution_rules_sha256",
    "resolution_status",
    "parser_confidence",
    "diagnostic_status",
    "diagnostic_reason",
    "is_avoid_candidate",
    "has_token_ids",
    "spot_loaded",
    "orderbook_loaded",
    "recommended_action",
    "expected_edge",
    "confidence",
]


@dataclass
class ParsedCryptoThreshold:
    asset: str
    threshold_price: float
    direction: str
    expiry_time: str
    parser_confidence: float
    parse_notes: list[str]
    contract_kind: str = ""
    barrier_direction: str = BARRIER_UNKNOWN
    parser_version: str = PARSER_VERSION
    model_version: str = MODEL_VERSION


@dataclass
class SpotPrice:
    asset: str
    price: float
    timestamp: str
    source: str
    error: str = ""


@dataclass(frozen=True)
class HistoricalBarrierPlan:
    """Rule-local history request shared by candidates with the same source window."""

    window: RuleObservationWindow
    provenance: ResolutionProvenance
    expiry: ExpiryProvenance
    symbol: str = ""
    start_time: datetime | None = None
    preload_key: tuple[str, str] | None = None
    prerequisite_failure: str = ""


@dataclass(frozen=True)
class EligibleThresholdMarket:
    market: dict[str, Any]
    parsed: ParsedCryptoThreshold
    pair: TokenPair


@dataclass(frozen=True)
class ObservedOrderBooks:
    yes_book: CLOBOrderbook | None
    no_book: CLOBOrderbook | None
    observed_at: datetime
    error: str = ""


class BinanceSpotPriceProvider:
    """Public Binance ticker reader. No API key, auth header, or signing."""

    BASE_URL = "https://api.binance.com"

    def __init__(self, base_url: str = BASE_URL, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def get_spot_prices(self, assets: list[str]) -> dict[str, SpotPrice]:
        prices: dict[str, SpotPrice] = {}
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_seconds
        ) as client:
            for asset in assets:
                symbol = BINANCE_SYMBOLS.get(asset)
                if not symbol:
                    continue
                try:
                    response = await client.get("/api/v3/ticker/price", params={"symbol": symbol})
                    response.raise_for_status()
                    payload = response.json()
                    price = safe_float(payload.get("price"), 0.0)
                    if price <= 0:
                        observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        prices[asset] = SpotPrice(
                            asset,
                            0.0,
                            observed_at,
                            "binance_public_ticker",
                            "missing_price",
                        )
                    else:
                        observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        prices[asset] = SpotPrice(
                            asset, price, observed_at, "binance_public_ticker"
                        )
                except Exception as exc:
                    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    prices[asset] = SpotPrice(
                        asset, 0.0, observed_at, "binance_public_ticker", str(exc)
                    )
        return prices


class GammaCoverageClient(GammaActiveMarketClient):
    """Public read-only Gamma market fetcher with pagination and search helpers."""

    async def fetch_active_markets_page(self, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_seconds
        ) as client:
            response = await client.get("/markets", params=params)
            response.raise_for_status()
            payload = response.json()
        return (
            [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, list)
            else []
        )

    async def search_markets(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "search": keyword,
        }
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_seconds
        ) as client:
            response = await client.get("/markets", params=params)
            response.raise_for_status()
            payload = response.json()
        return (
            [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, list)
            else []
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover read-only crypto threshold edge candidates"
    )
    parser.add_argument("--assets", type=str, default="BTC,ETH,SOL")
    parser.add_argument("--max_markets", type=int, default=500)
    parser.add_argument("--min_volume", type=float, default=1000.0)
    parser.add_argument("--min_edge", type=float, default=0.02)
    parser.add_argument("--min_confidence", type=float, default=0.6)
    parser.add_argument("--page_size", type=int, default=100)
    parser.add_argument("--enable_keyword_search", action="store_true", default=True)
    parser.add_argument(
        "--search_keywords",
        type=str,
        default="bitcoin,btc,ethereum,eth,solana,sol,crypto,price,above,hit,reach",
    )
    parser.add_argument("--output_dir", type=str, default="runs")
    parser.add_argument(
        "--avoid_candidates_file",
        "--avoid_file",
        dest="avoid_candidates_file",
        type=str,
        default="runs/avoid_candidates.csv",
    )
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--data_mode", type=str, default="real_readonly")
    return parser.parse_args(argv)


def parse_assets(value: str) -> list[str]:
    assets = []
    for item in value.split(","):
        asset = item.strip().upper()
        if asset in ASSET_ALIASES and asset not in assets:
            assets.append(asset)
    return assets


def parse_keywords(value: str) -> list[str]:
    keywords: list[str] = []
    for item in value.split(","):
        keyword = item.strip().lower()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def load_avoid_market_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, newline="") as file:
        return {
            str(row.get("market_id") or "").strip()
            for row in csv.DictReader(file)
            if str(row.get("market_id") or "").strip()
        }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace(",", " ")).strip()


def resolution_provenance(
    market: dict[str, Any], parsed: ParsedCryptoThreshold
) -> ResolutionProvenance:
    return resolve_resolution_provenance(
        market,
        parsed.contract_kind,
        parsed.asset,
        parsed.barrier_direction,
    )


def expiry_provenance(
    market: dict[str, Any], parsed: ParsedCryptoThreshold, resolution_rules: str
) -> ExpiryProvenance:
    """Canonicalize the title-local cutoff using rules and Gamma metadata."""

    return resolve_expiry_provenance(market, parsed.expiry_time, resolution_rules)


def parse_aware_utc(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None and math.isfinite(numeric) and numeric >= 0:
        seconds = numeric / 1000.0 if numeric >= 100_000_000_000 else numeric
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def aware_utc_now(time_provider: Any) -> datetime:
    observed = time_provider()
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise ValueError("time provider must return timezone-aware datetimes")
    return observed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    timespec = "milliseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def next_batch_entry_time(scheduled_at: datetime) -> datetime:
    """Commit to a future minute before quotes exist; never round a recorded quote."""

    observed = scheduled_at.astimezone(timezone.utc)
    return observed.replace(second=0, microsecond=0) + timedelta(minutes=1)


async def wait_for_batch_entry(
    entry_time: datetime,
    time_provider: Any,
    sleep_provider: Any,
) -> None:
    remaining = (entry_time - aware_utc_now(time_provider)).total_seconds()
    if remaining > 0:
        await sleep_provider(remaining)


def entry_timestamp_failure(
    *,
    label: str,
    value: Any,
    entry_time: datetime,
) -> str:
    observed = parse_aware_utc(value)
    if observed is None:
        return f"missing_or_invalid_{label}_timestamp"
    age_seconds = (entry_time - observed).total_seconds()
    if age_seconds < 0:
        return f"{label}_timestamp_after_batch_entry"
    if age_seconds > MAX_ENTRY_EVIDENCE_AGE_SECONDS:
        return f"stale_{label}_snapshot"
    return ""


def entry_evidence_failure(
    *,
    spot: SpotPrice,
    quote_observed_at: datetime,
    yes_book: CLOBOrderbook | None,
    no_book: CLOBOrderbook | None,
    entry_time: datetime,
) -> str:
    checks = (
        ("spot", spot.timestamp),
        ("entry_quote", quote_observed_at),
        ("yes_orderbook", yes_book.timestamp if yes_book else None),
        ("no_orderbook", no_book.timestamp if no_book else None),
    )
    return next(
        (
            failure
            for label, value in checks
            if (failure := entry_timestamp_failure(label=label, value=value, entry_time=entry_time))
        ),
        "",
    )


def gamma_start_date(market: dict[str, Any]) -> str:
    """Preserve Gamma start metadata for audit; never use it as the rule start."""

    for field in ("startDate", "start_date"):
        value = market.get(field)
        if value in (None, ""):
            continue
        return value.strip() if isinstance(value, str) else str(value)
    return ""


def historical_manifest_fields(
    market: dict[str, Any],
    provenance: ResolutionProvenance,
    expiry: ExpiryProvenance,
) -> dict[str, Any]:
    return {
        "resolution_rules": provenance.rules,
        "resolution_rules_sha256": provenance.rules_sha256,
        "expiry_time": expiry.expiry_time,
        "expiry_local_time": expiry.expiry_local_time,
        "expiry_timezone": expiry.expiry_timezone,
        "expiry_time_origin": expiry.expiry_time_origin,
        "expiry_time_adapter_version": expiry.expiry_time_adapter_version,
        "expiry_time_provenance_sha256": expiry.expiry_time_provenance_sha256,
        "expiry_status": expiry.status,
        "gamma_start_date": gamma_start_date(market),
        "gamma_end_date": expiry.gamma_end_date,
        "gamma_market_updated_at": expiry.gamma_market_updated_at,
        "gamma_market_schema": expiry.gamma_market_schema,
        "gamma_market_version": expiry.gamma_market_version,
    }


def historical_barrier_plan(
    market: dict[str, Any], parsed: ParsedCryptoThreshold
) -> HistoricalBarrierPlan | None:
    contract_kind, _ = resolved_contract_semantics(parsed)
    if contract_kind != TOUCH_BEFORE_EXPIRY:
        return None
    provenance = resolution_provenance(market, parsed)
    expiry = expiry_provenance(market, parsed, provenance.rules)
    window = parse_rule_observation_window(provenance.rules, expiry.expiry_time)
    start_time = parse_aware_utc(window.start_time)
    symbol = BINANCE_SYMBOLS.get(parsed.asset, "")
    window_failure = (
        MISSING_RULE_BARRIER_START
        if window.status == "missing_explicit_rule_start_time"
        else ("" if window.status == "verified" else window.status)
    )
    prerequisite_failure = next(
        (
            status
            for status in (
                "" if provenance.status == "verified" else provenance.status,
                "" if expiry.status == "verified" else expiry.status,
                window_failure,
                (
                    ""
                    if parsed.barrier_direction in {BARRIER_UP, BARRIER_DOWN}
                    else "unverifiable_barrier_direction"
                ),
                "" if parsed.threshold_price > 0 else "invalid_barrier_threshold",
                "" if symbol else "unsupported_binance_symbol",
            )
            if status
        ),
        "",
    )
    preload_key = (
        (symbol, window.start_time)
        if not prerequisite_failure and symbol and start_time is not None
        else None
    )
    return HistoricalBarrierPlan(
        window=window,
        provenance=provenance,
        expiry=expiry,
        symbol=symbol,
        start_time=start_time,
        preload_key=preload_key,
        prerequisite_failure=prerequisite_failure,
    )


def default_historical_evidence(
    market: dict[str, Any], parsed: ParsedCryptoThreshold
) -> HistoricalBarrierEvidence:
    plan = historical_barrier_plan(market, parsed)
    if plan is None:
        return not_required_historical_evidence()
    return unavailable_historical_evidence(
        plan.window,
        plan.prerequisite_failure or plan.window.status,
    )


def detect_asset(text: str, assets: list[str]) -> tuple[str, float]:
    normalized = normalize_text(text)
    for asset in assets:
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in ASSET_ALIASES[asset]):
            return asset, 0.25
    return "", 0.0


def parse_threshold_price(text: str) -> tuple[float, float]:
    patterns = [
        r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|\d+(?:\.\d+)?)\s*([kKmM]?)",
        r"\b([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*([kKmM])\b",
        r"\b([0-9]{3,}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*()\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw, suffix = match.groups()
            value = safe_float(raw.replace(",", ""), 0.0)
            if value <= 0:
                continue
            if suffix.lower() == "k":
                value *= 1000.0
            elif suffix.lower() == "m":
                value *= 1_000_000.0
            if not suffix and 1900 <= value <= 2100:
                continue
            if value >= 10:
                return value, 0.25
    return 0.0, 0.0


def has_price_threshold_context(text: str) -> bool:
    normalized = normalize_text(text)
    if "all time high" in normalized or "all-time high" in normalized:
        return True
    if re.search(
        r"\b(hit|hits|touch|touches|reach|reaches|break|breaks|rally|rallies|"
        r"rise|rises|dip|dips|drop|drops|fall|falls|decline|declines|"
        r"above|below|under|over|price|ath)\b",
        normalized,
    ):
        return True
    return bool(re.search(r"\bto\s+\$?\s*\d", normalized))


def parse_contract_semantics(text: str) -> tuple[str, str]:
    normalized = normalize_text(text)
    if "all time high" in normalized or "all-time high" in normalized:
        return TOUCH_BEFORE_EXPIRY, BARRIER_UP

    upward_touch = bool(
        re.search(r"\b(reach|reaches|break|breaks|rally|rallies|rise|rises)\b", normalized)
    )
    downward_touch = bool(
        re.search(r"\b(dip|dips|drop|drops|fall|falls|decline|declines)\b", normalized)
    )
    terminal_up = bool(re.search(r"\b(above|over|greater than|higher than|at least)\b", normalized))
    terminal_down = bool(re.search(r"\b(below|under|less than|lower than)\b", normalized))
    generic_touch = bool(
        re.search(r"\b(hit|hits|touch|touches)\b", normalized)
        or re.search(r"\bto\s+\$?\s*\d", normalized)
    )

    if upward_touch and (downward_touch or terminal_down):
        return TOUCH_BEFORE_EXPIRY, BARRIER_UNKNOWN
    if downward_touch and terminal_up:
        return TOUCH_BEFORE_EXPIRY, BARRIER_UNKNOWN
    if upward_touch:
        return TOUCH_BEFORE_EXPIRY, BARRIER_UP
    if downward_touch:
        return TOUCH_BEFORE_EXPIRY, BARRIER_DOWN
    if generic_touch:
        return TOUCH_BEFORE_EXPIRY, BARRIER_UNKNOWN
    if terminal_up and terminal_down:
        return SETTLEMENT_THRESHOLD, BARRIER_UNKNOWN
    if terminal_up:
        return SETTLEMENT_THRESHOLD, BARRIER_UP
    if terminal_down:
        return SETTLEMENT_THRESHOLD, BARRIER_DOWN
    return "", BARRIER_UNKNOWN


def parse_direction(text: str) -> tuple[str, float]:
    contract_kind, barrier_direction = parse_contract_semantics(text)
    if contract_kind == SETTLEMENT_THRESHOLD and barrier_direction == BARRIER_UP:
        return "above", 0.20
    if contract_kind == SETTLEMENT_THRESHOLD and barrier_direction == BARRIER_DOWN:
        return "below", 0.20
    if contract_kind == TOUCH_BEFORE_EXPIRY:
        return "hit_before_expiry", 0.20
    return "", 0.0


def parse_expiry_time(text: str, now: datetime | None = None) -> tuple[str, float]:
    now = now or datetime.utcnow()
    normalized = normalize_text(text)
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, weekday in weekdays.items():
        if re.search(rf"\b(by|before|this)\s+{name}\b", normalized):
            days_until = (weekday - now.weekday()) % 7
            if days_until == 0:
                days_until = 7
            expiry = (now + timedelta(days=days_until)).replace(
                hour=23, minute=59, second=0, microsecond=0
            )
            return expiry.isoformat(), 0.15
    if "end of week" in normalized or "this week" in normalized:
        days_until_sunday = (6 - now.weekday()) % 7
        expiry = (now + timedelta(days=days_until_sunday)).replace(
            hour=23, minute=59, second=0, microsecond=0
        )
        return expiry.isoformat(), 0.15
    if "end of month" in normalized or "this month" in normalized:
        if now.month == 12:
            next_month = now.replace(year=now.year + 1, month=1, day=1)
        else:
            next_month = now.replace(month=now.month + 1, day=1)
        expiry = (next_month - timedelta(minutes=1)).replace(second=0, microsecond=0)
        return expiry.isoformat(), 0.15
    if "end of year" in normalized or "this year" in normalized:
        expiry = now.replace(month=12, day=31, hour=23, minute=59, second=0, microsecond=0)
        return expiry.isoformat(), 0.15
    year_match = re.search(r"\b(?:end of|by|before)\s+(\d{4})\b", normalized)
    if year_match:
        year = int(year_match.group(1))
        return datetime(year, 12, 31, 23, 59).isoformat(), 0.15

    month_names = (
        "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        "jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    )
    match = re.search(rf"\b({month_names})\s+(\d{{1,2}})(?:\s+|,\s*)(\d{{4}})\b", normalized)
    if match:
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        month = month_map[match.group(1)]
        day = int(match.group(2))
        year = int(match.group(3))
        try:
            return datetime(year, month, day, 23, 59).isoformat(), 0.20
        except ValueError:
            return "", 0.0
    return "", 0.0


def gamma_markets_endpoint(gamma_client: Any) -> str:
    base_url = str(getattr(gamma_client, "base_url", "") or "").rstrip("/")
    return f"{base_url}/markets" if base_url else "gamma_client:/markets"


async def fetch_market_universe(
    args: argparse.Namespace,
    gamma_client: Any,
    snapshot_recorder: GammaRawSnapshotRecorder | None = None,
) -> tuple[list[dict[str, Any]], int, list[dict[str, str]]]:
    page_size = max(1, min(int(getattr(args, "page_size", 100) or 100), int(args.max_markets)))
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    markets: list[dict[str, Any]] = []
    endpoint = gamma_markets_endpoint(gamma_client)

    offset = 0
    while len(markets) < args.max_markets:
        limit = min(page_size, args.max_markets - len(markets))
        query: dict[str, str | int | float | bool | None] = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }
        request_started = datetime.now(timezone.utc)
        try:
            if hasattr(gamma_client, "fetch_active_markets_page"):
                page = await gamma_client.fetch_active_markets_page(limit, offset)
            elif offset == 0:
                page = await gamma_client.fetch_active_markets(args.max_markets)
                query["limit"] = args.max_markets
                query.pop("offset")
            else:
                page = []
        except Exception as exc:
            if snapshot_recorder is not None:
                snapshot_recorder.record_error(
                    kind="page",
                    endpoint=endpoint,
                    query=query,
                    error=str(exc),
                    started_at=request_started,
                    completed_at=datetime.now(timezone.utc),
                )
            errors.append({"stage": "gamma_page", "error": str(exc), "offset": str(offset)})
            break
        terminal_page = (
            not page or len(page) < limit or not hasattr(gamma_client, "fetch_active_markets_page")
        )
        if snapshot_recorder is not None:
            snapshot_recorder.record_success(
                kind="page",
                endpoint=endpoint,
                query=query,
                payloads=page,
                started_at=request_started,
                completed_at=datetime.now(timezone.utc),
                terminal=terminal_page,
            )
        if not page:
            break
        for market in page:
            mid = market_id(market)
            if mid and mid not in seen:
                markets.append(market)
                seen.add(mid)
                if len(markets) >= args.max_markets:
                    break
        if len(page) < limit or not hasattr(gamma_client, "fetch_active_markets_page"):
            break
        offset += page_size

    if getattr(args, "enable_keyword_search", False):
        for keyword in parse_keywords(getattr(args, "search_keywords", "")):
            if len(markets) >= args.max_markets:
                break
            query = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "search": keyword,
            }
            request_started = datetime.now(timezone.utc)
            try:
                if hasattr(gamma_client, "search_markets"):
                    search_rows = await gamma_client.search_markets(keyword, page_size)
                else:
                    search_rows = []
            except Exception as exc:
                if snapshot_recorder is not None:
                    snapshot_recorder.record_error(
                        kind="search",
                        endpoint=endpoint,
                        query=query,
                        error=str(exc),
                        started_at=request_started,
                        completed_at=datetime.now(timezone.utc),
                    )
                errors.append({"stage": "gamma_search", "keyword": keyword, "error": str(exc)})
                continue
            if snapshot_recorder is not None:
                snapshot_recorder.record_success(
                    kind="search",
                    endpoint=endpoint,
                    query=query,
                    payloads=search_rows,
                    started_at=request_started,
                    completed_at=datetime.now(timezone.utc),
                    terminal=True,
                )
            for market in search_rows:
                mid = market_id(market)
                if mid and mid not in seen:
                    markets.append(market)
                    seen.add(mid)
                    if len(markets) >= args.max_markets:
                        break
    return markets, len(seen), errors


def parse_crypto_threshold_market(
    market: dict[str, Any], assets: list[str], now: datetime | None = None
) -> ParsedCryptoThreshold | None:
    market_question = question(market)
    asset, asset_score = detect_asset(market_question, assets)
    if not asset:
        return None
    if not has_price_threshold_context(market_question):
        return None
    threshold, threshold_score = parse_threshold_price(market_question)
    contract_kind, barrier_direction = parse_contract_semantics(market_question)
    direction, direction_score = parse_direction(market_question)
    expiry, expiry_score = parse_expiry_time(market_question, now)
    notes: list[str] = []
    if not threshold:
        notes.append("missing_threshold")
    if not direction:
        notes.append("missing_direction")
    if contract_kind == TOUCH_BEFORE_EXPIRY and barrier_direction == BARRIER_UNKNOWN:
        notes.append("unverifiable_barrier_direction")
    if not expiry:
        notes.append("missing_expiry")
    confidence = asset_score + threshold_score + direction_score + expiry_score
    if threshold and direction and expiry:
        confidence = min(1.0, confidence + 0.20)
    return ParsedCryptoThreshold(
        asset=asset,
        threshold_price=threshold,
        direction=direction,
        expiry_time=expiry,
        parser_confidence=round(confidence, 6),
        parse_notes=notes,
        contract_kind=contract_kind,
        barrier_direction=barrier_direction,
        parser_version=PARSER_VERSION,
        model_version=MODEL_VERSION,
    )


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def hours_until(expiry_time: str, now: datetime | None = None) -> float:
    if not expiry_time:
        return 0.0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    try:
        expiry = datetime.fromisoformat(expiry_time.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if expiry.tzinfo is None:
        return 0.0
    return max(0.0, (expiry.astimezone(timezone.utc) - current).total_seconds() / 3600.0)


def estimate_probability(
    parsed: ParsedCryptoThreshold,
    spot_price: float,
    time_to_expiry_hours: float,
) -> tuple[float, float, str]:
    if spot_price <= 0 or parsed.threshold_price <= 0 or time_to_expiry_hours <= 0:
        return 0.0, 0.0, "missing_spot_threshold_or_expiry"
    distance = parsed.threshold_price - spot_price
    ann_vol = ANNUAL_VOL_PROXY.get(parsed.asset, 0.75)
    horizon_years = max(time_to_expiry_hours / (24.0 * 365.0), 1.0 / (24.0 * 365.0))
    sigma_price = max(spot_price * ann_vol * math.sqrt(horizon_years), spot_price * 0.005)
    z = distance / sigma_price
    above_probability = 1.0 - normal_cdf(z)
    below_probability = normal_cdf(z)
    contract_kind, barrier_direction = resolved_contract_semantics(parsed)

    if barrier_direction == BARRIER_UNKNOWN:
        probability = 0.5
        probability_kind = "unverifiable_barrier_direction"
    elif contract_kind == SETTLEMENT_THRESHOLD and barrier_direction == BARRIER_UP:
        probability = above_probability
        probability_kind = "terminal_above"
    elif contract_kind == SETTLEMENT_THRESHOLD and barrier_direction == BARRIER_DOWN:
        probability = below_probability
        probability_kind = "terminal_below"
    elif contract_kind == TOUCH_BEFORE_EXPIRY and barrier_direction == BARRIER_UP:
        probability = clamp(above_probability * 1.35, 0.0, 0.98)
        probability_kind = "touch_up"
    elif contract_kind == TOUCH_BEFORE_EXPIRY and barrier_direction == BARRIER_DOWN:
        probability = clamp(below_probability * 1.35, 0.0, 0.98)
        probability_kind = "touch_down"
    else:
        probability = 0.5
        probability_kind = "unsupported_contract_semantics"
    probability = clamp(probability, 0.02, 0.98)
    reason = (
        f"distance={distance:.6f};sigma_price={sigma_price:.6f};"
        f"direction={parsed.direction};contract_kind={contract_kind};"
        f"barrier_direction={barrier_direction};probability_kind={probability_kind};"
        f"vol_proxy={ann_vol:.3f};model_version={parsed.model_version}"
    )
    return round(probability, 6), ann_vol, reason


def resolved_contract_semantics(parsed: ParsedCryptoThreshold) -> tuple[str, str]:
    contract_kind = parsed.contract_kind
    barrier_direction = parsed.barrier_direction
    if barrier_direction == BARRIER_UNKNOWN and parsed.direction == "above":
        barrier_direction = BARRIER_UP
    elif barrier_direction == BARRIER_UNKNOWN and parsed.direction == "below":
        barrier_direction = BARRIER_DOWN
    if not contract_kind and parsed.direction in {"above", "below"}:
        contract_kind = SETTLEMENT_THRESHOLD
    elif not contract_kind and parsed.direction == "hit_before_expiry":
        contract_kind = TOUCH_BEFORE_EXPIRY
    return contract_kind, barrier_direction


def barrier_failure_reason(parsed: ParsedCryptoThreshold, spot_price: float) -> str:
    contract_kind, barrier_direction = resolved_contract_semantics(parsed)
    if barrier_direction not in {BARRIER_UP, BARRIER_DOWN}:
        return "unverifiable_barrier_direction"
    if contract_kind != TOUCH_BEFORE_EXPIRY or spot_price <= 0 or parsed.threshold_price <= 0:
        return ""
    if barrier_direction == BARRIER_UP and spot_price >= parsed.threshold_price:
        return "already_crossed_barrier"
    if barrier_direction == BARRIER_DOWN and spot_price <= parsed.threshold_price:
        return "already_crossed_barrier"
    return ""


def confidence_score(
    parser_confidence: float,
    spot_price: float,
    time_to_expiry_hours: float,
    spread: float,
    depth: float,
    liquidity: float,
) -> float:
    parser_component = clamp(parser_confidence)
    spot_component = 1.0 if spot_price > 0 else 0.0
    expiry_component = clamp(time_to_expiry_hours / 168.0)
    spread_component = clamp(1.0 - (spread / 0.10))
    depth_component = clamp(depth / 8.0)
    liquidity_component = clamp(liquidity / 200.0)
    confidence = (
        0.25 * parser_component
        + 0.20 * spot_component
        + 0.15 * expiry_component
        + 0.20 * spread_component
        + 0.10 * depth_component
        + 0.10 * liquidity_component
    )
    return round(clamp(confidence), 6)


def action_for_candidate(
    expected_edge: float,
    confidence: float,
    side_ask: float,
    parser_confidence: float,
    spot_price: float,
    spread: float,
    depth: float,
    min_edge: float,
    min_confidence: float,
    barrier_failure: str = "",
) -> tuple[str, str]:
    if spot_price <= 0:
        return "reject", "missing_spot_price"
    if barrier_failure:
        return "watch_only", barrier_failure
    if side_ask <= 0:
        return "reject", "missing_side_ask"
    if parser_confidence < 0.75:
        return "watch_only", "low_parser_confidence"
    if depth < 1:
        return "watch_only", "insufficient_depth"
    if spread > 0.05:
        return "watch_only", "spread_too_wide"
    if expected_edge > min_edge and confidence >= min_confidence:
        return "shadow_entry", ""
    if expected_edge <= min_edge:
        return "watch_only", "edge_too_low"
    return "watch_only", "confidence_too_low"


def build_candidate(
    market: dict[str, Any],
    parsed: ParsedCryptoThreshold,
    pair: TokenPair,
    spot: SpotPrice,
    yes_book: CLOBOrderbook | None,
    no_book: CLOBOrderbook | None,
    args: argparse.Namespace,
    timestamp: str,
    now: datetime | None = None,
    gamma_snapshot: GammaRawPayloadSnapshot | None = None,
    historical_evidence: HistoricalBarrierEvidence | None = None,
    entry_evidence_failure_reason: str = "",
    entry_quote_timestamp: str = "",
) -> dict[str, Any]:
    yes = book_features(yes_book)
    no = book_features(no_book)
    provenance = resolution_provenance(market, parsed)
    resolution_source = provenance.source
    resolution_rules = provenance.rules
    resolution_fingerprint = provenance.rules_sha256
    resolution_status = provenance.status
    expiry = expiry_provenance(market, parsed, resolution_rules)
    time_hours = hours_until(expiry.expiry_time, now)
    model_prob, vol_proxy, probability_reason = estimate_probability(parsed, spot.price, time_hours)
    yes_edge = model_prob - yes["best_ask"] - 0.01 if yes["best_ask"] else -1.0
    no_edge = (1.0 - model_prob) - no["best_ask"] - 0.01 if no["best_ask"] else -1.0
    side = "YES" if yes_edge >= no_edge else "NO"
    expected_edge = yes_edge if side == "YES" else no_edge
    side_ask = yes["best_ask"] if side == "YES" else no["best_ask"]
    max_spread = max(yes["spread"], no["spread"])
    depth = yes["depth"] + no["depth"]
    liquidity = yes["liquidity"] + no["liquidity"]
    confidence = confidence_score(
        parsed.parser_confidence, spot.price, time_hours, max_spread, depth, liquidity
    )
    barrier_failure = barrier_failure_reason(parsed, spot.price)
    history = historical_evidence or default_historical_evidence(market, parsed)
    historical_status = history.status
    contract_kind, _ = resolved_contract_semantics(parsed)
    historical_failure = (
        historical_status
        if contract_kind == TOUCH_BEFORE_EXPIRY
        and historical_status != HISTORICAL_BARRIER_STATUS_VERIFIED
        else ""
    )
    action, failure = action_for_candidate(
        expected_edge,
        confidence,
        side_ask,
        parsed.parser_confidence,
        spot.price,
        max_spread,
        depth,
        args.min_edge,
        args.min_confidence,
        barrier_failure=(barrier_failure or historical_failure or entry_evidence_failure_reason),
    )
    expiry_failure = "" if expiry.status == "verified" else expiry.status
    if expiry_failure and action != "reject":
        action = "watch_only"
        failure = expiry_failure
    resolution_failure = "" if resolution_status == "verified" else resolution_status
    if resolution_failure and action != "reject":
        action = "watch_only"
        failure = resolution_failure
    combined_ask = yes["best_ask"] + no["best_ask"] if yes["best_ask"] and no["best_ask"] else 0.0
    distance = parsed.threshold_price - spot.price if spot.price and parsed.threshold_price else 0.0
    distance_pct = distance / spot.price if spot.price else 0.0
    evidence = [
        EDGE_TYPE,
        "crypto_threshold_edge",
        "external_spot_price" if spot.price > 0 else "missing_spot_price",
        (
            "threshold_parser_high_confidence"
            if parsed.parser_confidence >= 0.75
            else "low_parser_confidence"
        ),
        "spot_price_fresh" if spot.price > 0 else "spot_price_missing",
        f"contract_kind={parsed.contract_kind}",
        f"barrier_direction={parsed.barrier_direction}",
        f"resolution_status={resolution_status}",
        f"expiry_status={expiry.status}",
        f"historical_barrier_evidence_status={historical_status}",
    ]
    if failure:
        evidence.append(failure)
    expected_edge_status = next(
        (
            reason
            for reason in (
                resolution_failure,
                expiry_failure,
                barrier_failure,
                historical_failure,
                entry_evidence_failure_reason,
            )
            if reason
        ),
        "edge_positive" if expected_edge > args.min_edge else "edge_too_low",
    )
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "edge_type": EDGE_TYPE,
        "market_id": market_id(market),
        "question": question(market),
        "asset": parsed.asset,
        "threshold_price": parsed.threshold_price,
        "direction": parsed.direction,
        "contract_kind": parsed.contract_kind,
        "barrier_direction": parsed.barrier_direction,
        "parser_version": parsed.parser_version,
        "model_version": parsed.model_version,
        "expiry_time": expiry.expiry_time,
        "expiry_local_time": expiry.expiry_local_time,
        "expiry_timezone": expiry.expiry_timezone,
        "expiry_time_origin": expiry.expiry_time_origin,
        "expiry_time_adapter_version": expiry.expiry_time_adapter_version,
        "expiry_time_provenance_sha256": expiry.expiry_time_provenance_sha256,
        "gamma_start_date": gamma_start_date(market),
        "gamma_end_date": expiry.gamma_end_date,
        "gamma_market_updated_at": expiry.gamma_market_updated_at,
        "gamma_market_schema": expiry.gamma_market_schema,
        "gamma_market_version": expiry.gamma_market_version,
        "expiry_status": expiry.status,
        "gamma_raw_market_snapshot_path": (gamma_snapshot.snapshot_path if gamma_snapshot else ""),
        "gamma_raw_market_snapshot_sha256": (
            gamma_snapshot.snapshot_sha256 if gamma_snapshot else ""
        ),
        **historical_evidence_candidate_fields(history),
        "resolution_source": resolution_source,
        "resolution_source_origin": provenance.source_origin,
        "resolution_source_locator": provenance.source_locator,
        "resolution_source_adapter_version": provenance.source_adapter_version,
        "resolution_source_provenance_sha256": provenance.source_provenance_sha256,
        "resolution_rules": resolution_rules,
        "resolution_rules_sha256": resolution_fingerprint,
        "resolution_status": resolution_status,
        "parser_confidence": parsed.parser_confidence,
        "side": side,
        "yes_token_id": pair.yes_token_id,
        "no_token_id": pair.no_token_id,
        "spot_price": spot.price,
        "spot_timestamp": spot.timestamp,
        "spot_source": spot.source,
        "distance_to_threshold": distance,
        "distance_pct": distance_pct,
        "time_to_expiry_hours": time_hours,
        "volatility_proxy": vol_proxy,
        "yes_best_bid": yes["best_bid"],
        "yes_best_ask": yes["best_ask"],
        "no_best_bid": no["best_bid"],
        "no_best_ask": no["best_ask"],
        "yes_spread": yes["spread"],
        "no_spread": no["spread"],
        "max_spread": max_spread,
        "spread": max_spread,
        "orderbook_depth": depth,
        "depth": depth,
        "liquidity_score": liquidity,
        "market_implied_probability": yes["best_ask"] if yes["best_ask"] else 0.0,
        "model_estimated_probability": model_prob,
        "estimated_probability": model_prob,
        "expected_edge": expected_edge,
        "executable_edge": expected_edge,
        "confidence": confidence,
        "probability_reason": probability_reason,
        "evidence": "|".join(evidence),
        "risk_flags": "|".join(
            dict.fromkeys(
                flag
                for flag in (
                    barrier_failure,
                    historical_failure,
                    entry_evidence_failure_reason,
                    resolution_failure,
                    expiry_failure,
                )
                if flag
            )
        ),
        "recommended_action": action,
        "edge_status": "edge_candidate" if action == "shadow_entry" else failure or "watch_only",
        "edge_failure_reason": failure,
        "expected_edge_source": EDGE_TYPE,
        "expected_edge_status": expected_edge_status,
        "edge_pass": action == "shadow_entry",
        "entry_yes_best_ask": yes["best_ask"],
        "entry_no_best_ask": no["best_ask"],
        "entry_yes_best_bid": yes["best_bid"],
        "entry_no_best_bid": no["best_bid"],
        "entry_yes_best_ask_size": yes["best_ask_size"],
        "entry_no_best_ask_size": no["best_ask_size"],
        "entry_yes_best_bid_size": yes["best_bid_size"],
        "entry_no_best_bid_size": no["best_bid_size"],
        "entry_quote_timestamp": entry_quote_timestamp,
        "yes_orderbook_timestamp": str(yes_book.timestamp or "") if yes_book else "",
        "no_orderbook_timestamp": str(no_book.timestamp or "") if no_book else "",
        "combined_ask": combined_ask,
        "combined_ask_gap": max(0.0, 1.0 - combined_ask) if combined_ask else 0.0,
        "near_miss_tier": "tier1_mispricing" if action == "shadow_entry" else "",
        "evidence_level": "external_spot_threshold_edge",
        "entry_decision_hint": (
            "eligible_shadow_entry" if action == "shadow_entry" else "watch_only"
        ),
        "source": "crypto_threshold_edge",
        "volume": market_volume(market),
        "category": str(market.get("category") or ""),
        "timestamp": timestamp,
        "reasons": "|".join(evidence),
        "tradable_score": 0.0,
    }


def diagnostic_row(
    market: dict[str, Any],
    parsed: ParsedCryptoThreshold | None,
    status: str,
    reason: str,
    *,
    is_avoid_candidate: bool = False,
    has_token_ids: bool = False,
    spot_loaded: bool = False,
    orderbook_loaded: bool = False,
    recommended_action: str = "",
    expected_edge: float = 0.0,
    confidence: float = 0.0,
    gamma_snapshot: GammaRawPayloadSnapshot | None = None,
    historical_evidence: HistoricalBarrierEvidence | None = None,
) -> dict[str, Any]:
    provenance = resolution_provenance(market, parsed) if parsed else ResolutionProvenance()
    expiry = (
        expiry_provenance(market, parsed, provenance.rules)
        if parsed
        else ExpiryProvenance(expiry_time_origin="", expiry_time_adapter_version="")
    )
    history = (
        historical_evidence or default_historical_evidence(market, parsed)
        if parsed
        else HistoricalBarrierEvidence(status="")
    )
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "market_id": market_id(market),
        "question": question(market),
        "asset": parsed.asset if parsed else "",
        "threshold_price": parsed.threshold_price if parsed else 0.0,
        "direction": parsed.direction if parsed else "",
        "contract_kind": parsed.contract_kind if parsed else "",
        "barrier_direction": parsed.barrier_direction if parsed else "",
        "parser_version": parsed.parser_version if parsed else PARSER_VERSION,
        "model_version": parsed.model_version if parsed else MODEL_VERSION,
        "expiry_time": expiry.expiry_time,
        "expiry_local_time": expiry.expiry_local_time,
        "expiry_timezone": expiry.expiry_timezone,
        "expiry_time_origin": expiry.expiry_time_origin,
        "expiry_time_adapter_version": expiry.expiry_time_adapter_version,
        "expiry_time_provenance_sha256": expiry.expiry_time_provenance_sha256,
        "gamma_start_date": gamma_start_date(market),
        "gamma_end_date": expiry.gamma_end_date,
        "gamma_market_updated_at": expiry.gamma_market_updated_at,
        "gamma_market_schema": expiry.gamma_market_schema,
        "gamma_market_version": expiry.gamma_market_version,
        "expiry_status": expiry.status,
        "gamma_raw_market_snapshot_path": (gamma_snapshot.snapshot_path if gamma_snapshot else ""),
        "gamma_raw_market_snapshot_sha256": (
            gamma_snapshot.snapshot_sha256 if gamma_snapshot else ""
        ),
        **historical_evidence_candidate_fields(history),
        "resolution_source": provenance.source,
        "resolution_source_origin": provenance.source_origin,
        "resolution_source_locator": provenance.source_locator,
        "resolution_source_adapter_version": provenance.source_adapter_version,
        "resolution_source_provenance_sha256": provenance.source_provenance_sha256,
        "resolution_rules_sha256": provenance.rules_sha256,
        "resolution_status": provenance.status,
        "parser_confidence": parsed.parser_confidence if parsed else 0.0,
        "diagnostic_status": status,
        "diagnostic_reason": reason,
        "is_avoid_candidate": is_avoid_candidate,
        "has_token_ids": has_token_ids,
        "spot_loaded": spot_loaded,
        "orderbook_loaded": orderbook_loaded,
        "recommended_action": recommended_action,
        "expected_edge": expected_edge,
        "confidence": confidence,
    }


def historical_preload_plans(
    parsed_markets: list[tuple[dict[str, Any], ParsedCryptoThreshold]],
    avoid_ids: set[str],
) -> dict[str, HistoricalBarrierPlan]:
    plans: dict[str, HistoricalBarrierPlan] = {}
    for market, parsed in parsed_markets:
        if parsed.parser_confidence < 0.75:
            continue
        if market_safety_reject_reason(market, avoid_ids):
            continue
        pair, _ = extract_token_pair(market)
        if pair is None:
            continue
        plan = historical_barrier_plan(market, parsed)
        if plan is not None:
            plans[market_id(market)] = plan
    return plans


async def preload_historical_klines(
    plans: dict[str, HistoricalBarrierPlan],
    historical_client: Any,
    preload_end: datetime,
) -> tuple[
    dict[tuple[str, str], BinanceKlineFetchResult],
    dict[tuple[str, str], str],
]:
    unique_plans: dict[tuple[str, str], HistoricalBarrierPlan] = {}
    failures: dict[tuple[str, str], str] = {}
    for plan in plans.values():
        if plan.preload_key is None:
            continue
        if plan.start_time is None or plan.start_time >= preload_end:
            failures[plan.preload_key] = "historical_rule_window_not_started_before_preload"
            continue
        unique_plans.setdefault(plan.preload_key, plan)

    async def fetch(
        key: tuple[str, str], plan: HistoricalBarrierPlan
    ) -> tuple[tuple[str, str], BinanceKlineFetchResult | None, str]:
        assert plan.start_time is not None
        try:
            result = await historical_client.fetch_klines(
                symbol=plan.symbol,
                start_time=plan.start_time,
                end_time=preload_end,
            )
        except Exception as exc:
            return key, None, f"historical_preload_error:{type(exc).__name__}"
        if not isinstance(result, BinanceKlineFetchResult):
            return key, None, "invalid_historical_preload_result"
        return key, result, ""

    fetched = await asyncio.gather(*(fetch(key, plan) for key, plan in unique_plans.items()))
    results: dict[tuple[str, str], BinanceKlineFetchResult] = {}
    for key, result, error in fetched:
        if result is not None:
            results[key] = result
        if error:
            failures[key] = error
    return results, failures


async def fetch_historical_entry_tails(
    *,
    plans: dict[str, HistoricalBarrierPlan],
    preload_results: dict[tuple[str, str], BinanceKlineFetchResult],
    historical_client: Any,
    preload_end: datetime,
    entry_time: datetime,
) -> tuple[dict[str, BinanceKlineFetchResult], dict[str, str], int]:
    starts_by_symbol: dict[str, list[datetime]] = {}
    for plan in plans.values():
        if (
            plan.preload_key is not None
            and plan.start_time is not None
            and plan.preload_key in preload_results
        ):
            starts_by_symbol.setdefault(plan.symbol, []).append(plan.start_time)

    async def fetch(
        symbol: str, starts: list[datetime]
    ) -> tuple[str, BinanceKlineFetchResult | None, str]:
        tail_start = max(preload_end - timedelta(minutes=1), max(starts))
        if entry_time <= tail_start:
            return symbol, None, "historical_entry_not_after_tail_start"
        try:
            result = await historical_client.fetch_klines(
                symbol=symbol,
                start_time=tail_start,
                end_time=entry_time,
            )
        except Exception as exc:
            return symbol, None, f"historical_tail_error:{type(exc).__name__}"
        if not isinstance(result, BinanceKlineFetchResult):
            return symbol, None, "invalid_historical_tail_result"
        return symbol, result, ""

    requested = {
        symbol: starts
        for symbol, starts in starts_by_symbol.items()
        if entry_time > max(preload_end - timedelta(minutes=1), max(starts))
    }
    failures = {
        symbol: "historical_entry_not_after_tail_start"
        for symbol in starts_by_symbol
        if symbol not in requested
    }
    fetched = await asyncio.gather(*(fetch(symbol, starts) for symbol, starts in requested.items()))
    tails: dict[str, BinanceKlineFetchResult] = {}
    for symbol, result, failure in fetched:
        if result is not None:
            tails[symbol] = result
        if failure:
            failures[symbol] = failure
    return tails, failures, len(requested)


def merge_historical_entry_results(
    *,
    plans: dict[str, HistoricalBarrierPlan],
    preload_results: dict[tuple[str, str], BinanceKlineFetchResult],
    tails: dict[str, BinanceKlineFetchResult],
    entry_time: datetime,
) -> tuple[
    dict[tuple[str, str], BinanceKlineFetchResult],
    dict[tuple[str, str], str],
]:
    merged: dict[tuple[str, str], BinanceKlineFetchResult] = {}
    failures: dict[tuple[str, str], str] = {}
    unique_plans = {
        plan.preload_key: plan
        for plan in plans.values()
        if plan.preload_key is not None and plan.start_time is not None
    }
    for key, plan in unique_plans.items():
        assert key is not None
        assert plan.start_time is not None
        base = preload_results.get(key)
        tail = tails.get(plan.symbol)
        if base is None or tail is None:
            continue
        try:
            merged[key] = merge_kline_fetch_results(
                base,
                tail,
                start_time=plan.start_time,
                end_time=entry_time,
            )
        except (TypeError, ValueError) as exc:
            failures[key] = f"historical_merge_error:{type(exc).__name__}"
    return merged, failures


def historical_evidence_from_entry_result(
    *,
    market: dict[str, Any],
    parsed: ParsedCryptoThreshold,
    plan: HistoricalBarrierPlan | None,
    entry_time: datetime,
    merged_results: dict[tuple[str, str], BinanceKlineFetchResult],
    preload_failures: dict[tuple[str, str], str],
    tail_failures: dict[str, str],
    merge_failures: dict[tuple[str, str], str],
    candle_snapshots: dict[tuple[str, str], HistoricalCandleSnapshotReference],
    candle_audits: dict[tuple[str, str], HistoricalCandleAuditReference],
    output_dir: Path,
) -> tuple[HistoricalBarrierEvidence, str]:
    if plan is None:
        return not_required_historical_evidence(), ""
    if plan.prerequisite_failure:
        return unavailable_historical_evidence(plan.window, plan.prerequisite_failure), ""
    if plan.preload_key is None:
        return unavailable_historical_evidence(plan.window), ""
    merged = merged_results.get(plan.preload_key)
    if merged is None:
        failure = (
            preload_failures.get(plan.preload_key)
            or tail_failures.get(plan.symbol)
            or merge_failures.get(plan.preload_key)
        )
        failure = failure or "historical_entry_coverage_unavailable"
        return unavailable_historical_evidence(plan.window, failure), failure
    try:
        evidence = evaluate_historical_barrier(
            asset=parsed.asset,
            barrier_direction=cast(Literal["up", "down"], parsed.barrier_direction),
            threshold_price=parsed.threshold_price,
            entry_time=entry_time,
            window=plan.window,
            fetch_result=merged,
            output_dir=output_dir,
            resolution_rules=plan.provenance.rules,
            manifest=historical_manifest_fields(market, plan.provenance, plan.expiry),
            candle_snapshot=candle_snapshots.get(plan.preload_key),
            candle_audit=candle_audits.get(plan.preload_key),
        )
    except HistoricalArtifactConflictError:
        raise
    except (TypeError, ValueError) as exc:
        failure = f"historical_evaluation_error:{type(exc).__name__}"
        return unavailable_historical_evidence(plan.window, failure), failure
    return evidence, ""


async def fetch_batch_orderbooks(
    eligible: list[EligibleThresholdMarket],
    clob_client: Any,
    time_provider: Any,
) -> dict[str, ObservedOrderBooks]:
    semaphore = asyncio.Semaphore(MAX_ORDERBOOK_CONCURRENCY)

    async def fetch(item: EligibleThresholdMarket) -> tuple[str, ObservedOrderBooks]:
        try:
            async with semaphore:
                yes_book, no_book = await clob_client.get_market_orderbook(
                    item.pair.yes_token_id,
                    item.pair.no_token_id,
                )
            error = ""
        except CLOBError as exc:
            yes_book, no_book = None, None
            error = str(exc)
        return (
            market_id(item.market),
            ObservedOrderBooks(
                yes_book=yes_book,
                no_book=no_book,
                observed_at=aware_utc_now(time_provider),
                error=error,
            ),
        )

    return dict(await asyncio.gather(*(fetch(item) for item in eligible)))


async def discover_crypto_threshold_edges(
    args: argparse.Namespace,
    gamma_client: Any | None = None,
    clob_client: Any | None = None,
    spot_provider: Any | None = None,
    historical_kline_client: Any | None = None,
    time_provider: Any | None = None,
    sleep_provider: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = datetime.now(timezone.utc)
    assets = parse_assets(args.assets)
    gamma = gamma_client or GammaCoverageClient()
    clob = clob_client or CLOBReadOnlyClient(max_retries=1)
    spotter = spot_provider or BinanceSpotPriceProvider()
    historical_client = historical_kline_client or BinanceHistoricalKlineClient()
    observed_now = time_provider or (lambda: datetime.now(timezone.utc))
    sleeper = sleep_provider or asyncio.sleep
    close_clob = clob_client is None
    snapshot_recorder = (
        None
        if bool(getattr(args, "dry_run", False))
        else GammaRawSnapshotRecorder(Path(args.output_dir))
    )
    gamma_snapshot_result: GammaSnapshotResult | None = None
    errors: list[dict[str, str]] = []
    api_error_count = 0
    raw_markets: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    parsed_markets: list[tuple[dict[str, Any], ParsedCryptoThreshold]] = []
    crypto_markets_detected = 0
    parsed_threshold_markets = 0
    orderbooks_fetched = 0
    spot_prices: dict[str, SpotPrice] = {}
    avoid_file = getattr(args, "avoid_candidates_file", None) or getattr(args, "avoid_file", None)
    avoid_ids = load_avoid_market_ids(Path(avoid_file or "runs/avoid_candidates.csv"))
    avoid_candidate_count = 0
    forbidden_category_count = 0
    ambiguous_market_count = 0
    missing_token_id_count = 0
    excluded_parse_low_confidence = 0
    excluded_missing_spot = 0
    excluded_missing_orderbook = 0
    eligible_after_avoid_filter = 0
    historical_plans: dict[str, HistoricalBarrierPlan] = {}
    historical_preloads: dict[tuple[str, str], BinanceKlineFetchResult] = {}
    historical_preload_failures: dict[tuple[str, str], str] = {}
    historical_preload_end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    historical_preload_request_count = 0
    historical_tail_request_count = 0
    batch_entry_time: datetime | None = None

    try:
        try:
            raw_markets, _, fetch_errors = await fetch_market_universe(
                args,
                gamma,
                snapshot_recorder,
            )
            errors.extend(fetch_errors)
            api_error_count += len(fetch_errors)
        except GammaSnapshotConflictError:
            raise
        except Exception as exc:
            api_error_count += 1
            errors.append({"stage": "gamma_markets", "error": str(exc)})
            raw_markets = []

        if snapshot_recorder is not None:
            error_stages = {str(error.get("stage") or "") for error in errors}
            if "gamma_page" in error_stages or "gamma_markets" in error_stages:
                gamma_terminal_status = "pagination_error"
            elif "gamma_search" in error_stages:
                gamma_terminal_status = "partial_with_search_errors"
            elif len(raw_markets) >= int(args.max_markets):
                gamma_terminal_status = "max_markets_reached"
            else:
                gamma_terminal_status = "complete"
            gamma_snapshot_result = snapshot_recorder.finalize(
                terminal_status=gamma_terminal_status,
                created_at=datetime.now(timezone.utc),
            )

        markets = filter_markets(raw_markets, args.min_volume, args.max_markets)
        for market in markets:
            parsed = parse_crypto_threshold_market(market, assets, started)
            if parsed is None:
                continue
            crypto_markets_detected += 1
            if parsed.threshold_price > 0 and parsed.direction and parsed.expiry_time:
                parsed_threshold_markets += 1
            parsed_markets.append((market, parsed))
            if parsed.parser_confidence < 0.75:
                excluded_parse_low_confidence += 1
                diagnostics.append(
                    diagnostic_row(market, parsed, "excluded", "parse_low_confidence")
                )

        if args.dry_run:
            summary = build_summary(
                started,
                markets,
                crypto_markets_detected,
                parsed_threshold_markets,
                spot_prices,
                candidates,
                api_error_count,
                errors,
                orderbooks_fetched,
                avoid_candidate_count,
                forbidden_category_count,
                ambiguous_market_count,
                missing_token_id_count,
                excluded_parse_low_confidence,
                excluded_missing_spot,
                excluded_missing_orderbook,
                eligible_after_avoid_filter,
                diagnostics,
                gamma_snapshot_result,
            )
            summary["active_markets_available"] = len(markets)
            summary["historical_barrier_preload_request_count"] = 0
            summary["historical_barrier_tail_request_count"] = 0
            return [], summary

        eligible: list[EligibleThresholdMarket] = []
        for market, parsed in parsed_markets:
            if parsed.parser_confidence < 0.75:
                continue
            safety_reject = market_safety_reject_reason(market, avoid_ids)
            if safety_reject:
                if safety_reject == "avoid_candidate":
                    avoid_candidate_count += 1
                elif safety_reject == "forbidden_category":
                    forbidden_category_count += 1
                elif safety_reject == "ambiguous_market":
                    ambiguous_market_count += 1
                diagnostics.append(
                    diagnostic_row(
                        market,
                        parsed,
                        "excluded",
                        safety_reject,
                        is_avoid_candidate=safety_reject == "avoid_candidate",
                    )
                )
                continue
            eligible_after_avoid_filter += 1
            pair, token_error = extract_token_pair(market)
            if pair is None:
                if token_error == "missing_token_id":
                    missing_token_id_count += 1
                errors.append({"market_id": market_id(market), "error": token_error})
                diagnostics.append(diagnostic_row(market, parsed, "excluded", token_error))
                continue
            eligible.append(EligibleThresholdMarket(market=market, parsed=parsed, pair=pair))

        historical_plans = historical_preload_plans(parsed_markets, avoid_ids)
        historical_preload_end = aware_utc_now(observed_now).replace(second=0, microsecond=0)
        historical_preload_request_count = len(
            {
                plan.preload_key
                for plan in historical_plans.values()
                if plan.preload_key is not None
                and plan.start_time is not None
                and plan.start_time < historical_preload_end
            }
        )
        historical_preloads, historical_preload_failures = await preload_historical_klines(
            historical_plans,
            historical_client,
            historical_preload_end,
        )
        for (symbol, start_time), failure in historical_preload_failures.items():
            if failure.startswith(("historical_preload_error:", "invalid_historical_preload")):
                api_error_count += 1
                errors.append(
                    {
                        "stage": "historical_barrier_preload",
                        "symbol": symbol,
                        "start_time": start_time,
                        "error": failure,
                    }
                )

        batch_entry_time = next_batch_entry_time(aware_utc_now(observed_now))
        needed_assets = sorted({item.parsed.asset for item in eligible if item.parsed.asset})
        orderbook_task = asyncio.create_task(fetch_batch_orderbooks(eligible, clob, observed_now))
        try:
            spot_prices = await spotter.get_spot_prices(needed_assets)
        except Exception as exc:
            api_error_count += 1
            errors.append({"stage": "spot_prices", "error": str(exc)})
            spot_prices = {}
        observed_books = await orderbook_task
        await wait_for_batch_entry(batch_entry_time, observed_now, sleeper)

        tails, tail_failures, historical_tail_request_count = await fetch_historical_entry_tails(
            plans=historical_plans,
            preload_results=historical_preloads,
            historical_client=historical_client,
            preload_end=historical_preload_end,
            entry_time=batch_entry_time,
        )
        merged_results, merge_failures = merge_historical_entry_results(
            plans=historical_plans,
            preload_results=historical_preloads,
            tails=tails,
            entry_time=batch_entry_time,
        )
        candle_snapshots = {
            key: persist_historical_candle_snapshot(result, Path(args.output_dir).resolve())
            for key, result in merged_results.items()
        }
        plan_by_key = {
            plan.preload_key: plan
            for plan in historical_plans.values()
            if plan.preload_key is not None and plan.start_time is not None
        }
        candle_audits = {
            key: prepare_historical_candle_audit(
                result,
                start_time=cast(datetime, plan_by_key[key].start_time),
                entry_time=batch_entry_time,
            )
            for key, result in merged_results.items()
        }
        for symbol, failure in tail_failures.items():
            if failure.startswith(("historical_tail_error:", "invalid_historical_tail_result")):
                api_error_count += 1
                errors.append(
                    {
                        "stage": "historical_barrier_entry_tail",
                        "symbol": symbol,
                        "error": failure,
                    }
                )
        for (symbol, start_time), failure in merge_failures.items():
            api_error_count += 1
            errors.append(
                {
                    "stage": "historical_barrier_entry_merge",
                    "symbol": symbol,
                    "start_time": start_time,
                    "error": failure,
                }
            )

        entry_timestamp = iso_utc(batch_entry_time)
        output_dir = Path(args.output_dir).resolve()
        for item in eligible:
            market = item.market
            parsed = item.parsed
            pair = item.pair
            observed = observed_books.get(market_id(market))
            if observed is None:
                api_error_count += 1
                errors.append(
                    {"market_id": market_id(market), "error": "missing_orderbook_batch_result"}
                )
                continue
            if observed.error:
                api_error_count += 1
                errors.append({"market_id": market_id(market), "error": observed.error})
                continue
            yes_book = observed.yes_book
            no_book = observed.no_book
            orderbooks_fetched += int(yes_book is not None) + int(no_book is not None)
            spot = spot_prices.get(parsed.asset) or SpotPrice(
                parsed.asset, 0.0, entry_timestamp, "none", "missing_spot_price"
            )
            if spot.price <= 0:
                excluded_missing_spot += 1
            if yes_book is None or no_book is None:
                excluded_missing_orderbook += 1
            history, historical_error = historical_evidence_from_entry_result(
                market=market,
                parsed=parsed,
                plan=historical_plans.get(market_id(market)),
                entry_time=batch_entry_time,
                merged_results=merged_results,
                preload_failures=historical_preload_failures,
                tail_failures=tail_failures,
                merge_failures=merge_failures,
                candle_snapshots=candle_snapshots,
                candle_audits=candle_audits,
                output_dir=output_dir,
            )
            if historical_error.startswith(("historical_evaluation_error:",)):
                api_error_count += 1
                errors.append(
                    {
                        "stage": "historical_barrier_entry_tail",
                        "market_id": market_id(market),
                        "error": historical_error,
                    }
                )
            quote_timestamp = iso_utc(observed.observed_at)
            timestamp_failure = entry_evidence_failure(
                spot=spot,
                quote_observed_at=observed.observed_at,
                yes_book=yes_book,
                no_book=no_book,
                entry_time=batch_entry_time,
            )
            candidate = build_candidate(
                market,
                parsed,
                pair,
                spot,
                yes_book,
                no_book,
                args,
                entry_timestamp,
                batch_entry_time,
                gamma_snapshot=(
                    snapshot_recorder.snapshot_for_payload(market)
                    if snapshot_recorder is not None
                    else None
                ),
                historical_evidence=history,
                entry_evidence_failure_reason=timestamp_failure,
                entry_quote_timestamp=quote_timestamp,
            )
            candidates.append(candidate)
            diagnostics.append(
                diagnostic_row(
                    market,
                    parsed,
                    "candidate" if candidate["recommended_action"] != "reject" else "excluded",
                    candidate.get("edge_failure_reason")
                    or candidate.get("recommended_action")
                    or "candidate",
                    has_token_ids=True,
                    spot_loaded=spot.price > 0,
                    orderbook_loaded=yes_book is not None and no_book is not None,
                    recommended_action=str(candidate.get("recommended_action") or ""),
                    expected_edge=safe_float(candidate.get("expected_edge")),
                    confidence=safe_float(candidate.get("confidence")),
                    gamma_snapshot=(
                        snapshot_recorder.snapshot_for_payload(market)
                        if snapshot_recorder is not None
                        else None
                    ),
                    historical_evidence=history,
                )
            )
    finally:
        if close_clob:
            await clob.close()

    summary = build_summary(
        started,
        filter_markets(raw_markets, args.min_volume, args.max_markets),
        crypto_markets_detected,
        parsed_threshold_markets,
        spot_prices,
        candidates,
        api_error_count,
        errors,
        orderbooks_fetched,
        avoid_candidate_count,
        forbidden_category_count,
        ambiguous_market_count,
        missing_token_id_count,
        excluded_parse_low_confidence,
        excluded_missing_spot,
        excluded_missing_orderbook,
        eligible_after_avoid_filter,
        diagnostics,
        gamma_snapshot_result,
    )
    summary["diagnostics"] = diagnostics
    summary["historical_barrier_preload_request_count"] = historical_preload_request_count
    summary["historical_barrier_tail_request_count"] = historical_tail_request_count
    summary["historical_barrier_preload_failure_count"] = len(historical_preload_failures)
    summary["batch_entry_time"] = iso_utc(batch_entry_time) if batch_entry_time else ""
    summary["historical_barrier_candle_snapshot_count"] = len(
        {
            str(row.get("historical_barrier_candle_snapshot_path") or "")
            for row in candidates
            if str(row.get("historical_barrier_candle_snapshot_path") or "")
        }
    )
    summary["historical_barrier_evidence_manifest_count"] = len(
        {
            str(row.get("historical_barrier_evidence_path") or "")
            for row in candidates
            if str(row.get("historical_barrier_evidence_path") or "")
        }
    )
    return candidates, summary


def build_summary(
    started: datetime,
    markets: list[dict[str, Any]],
    crypto_markets_detected: int,
    parsed_threshold_markets: int,
    spot_prices: dict[str, SpotPrice],
    candidates: list[dict[str, Any]],
    api_error_count: int,
    errors: list[dict[str, str]],
    orderbooks_fetched: int,
    avoid_candidate_count: int = 0,
    forbidden_category_count: int = 0,
    ambiguous_market_count: int = 0,
    missing_token_id_count: int = 0,
    excluded_parse_low_confidence: int = 0,
    excluded_missing_spot: int = 0,
    excluded_missing_orderbook: int = 0,
    eligible_after_avoid_filter: int = 0,
    diagnostics: list[dict[str, Any]] | None = None,
    gamma_snapshot_result: GammaSnapshotResult | None = None,
) -> dict[str, Any]:
    ended = datetime.now(timezone.utc)
    duration_started = (
        started if started.tzinfo is not None else started.replace(tzinfo=timezone.utc)
    )
    expected_edges = [safe_float(row.get("expected_edge")) for row in candidates]
    confidences = [safe_float(row.get("confidence")) for row in candidates]
    asset_distribution = Counter(str(row.get("asset") or "unknown") for row in candidates)
    resolution_status_distribution = Counter(
        str(row.get("resolution_status") or "missing") for row in candidates
    )
    resolution_source_origin_distribution = Counter(
        str(row.get("resolution_source_origin") or "missing") for row in candidates
    )
    resolution_source_adapter_distribution = Counter(
        str(row.get("resolution_source_adapter_version") or "missing") for row in candidates
    )
    expiry_status_distribution = Counter(
        str(row.get("expiry_status") or "missing") for row in candidates
    )
    expiry_timezone_distribution = Counter(
        str(row.get("expiry_timezone") or "missing") for row in candidates
    )
    expiry_time_origin_distribution = Counter(
        str(row.get("expiry_time_origin") or "missing") for row in candidates
    )
    expiry_time_adapter_distribution = Counter(
        str(row.get("expiry_time_adapter_version") or "missing") for row in candidates
    )
    historical_barrier_evidence_status_distribution = Counter(
        str(row.get("historical_barrier_evidence_status") or "missing") for row in candidates
    )
    historical_barrier_evidence_adapter_distribution = Counter(
        str(row.get("historical_barrier_evidence_adapter_version") or "missing")
        for row in candidates
    )
    historical_barrier_evidence_source_distribution = Counter(
        str(row.get("historical_barrier_evidence_source") or "missing") for row in candidates
    )
    historical_barrier_evidence_interval_distribution = Counter(
        str(row.get("historical_barrier_evidence_interval") or "missing") for row in candidates
    )
    historical_barrier_evidence_symbol_distribution = Counter(
        str(row.get("historical_barrier_evidence_symbol") or "missing") for row in candidates
    )
    historical_barrier_failure_distribution = Counter(
        str(row.get("historical_barrier_evidence_status") or "missing")
        for row in candidates
        if str(row.get("historical_barrier_evidence_status") or "missing")
        not in {HISTORICAL_BARRIER_STATUS_VERIFIED, HISTORICAL_BARRIER_EVIDENCE_NOT_REQUIRED}
    )
    historical_barrier_missing_range_candidates = sum(
        1
        for row in candidates
        if str(row.get("historical_barrier_evidence_missing_ranges") or "[]") != "[]"
    )
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": (ended - duration_started).total_seconds(),
        "markets_scanned": len(markets),
        "crypto_markets_detected": crypto_markets_detected,
        "parsed_threshold_markets": parsed_threshold_markets,
        "spot_prices_loaded": sum(1 for spot in spot_prices.values() if spot.price > 0),
        "orderbooks_fetched": orderbooks_fetched,
        "candidates_generated": len(candidates),
        "shadow_entry_candidates": sum(
            1 for row in candidates if row.get("recommended_action") == "shadow_entry"
        ),
        "watch_only_candidates": sum(
            1 for row in candidates if row.get("recommended_action") == "watch_only"
        ),
        "rejected_candidates": sum(
            1 for row in candidates if row.get("recommended_action") == "reject"
        ),
        "asset_distribution": dict(asset_distribution),
        "resolution_status_distribution": dict(resolution_status_distribution),
        "resolution_source_origin_distribution": dict(resolution_source_origin_distribution),
        "resolution_source_adapter_distribution": dict(resolution_source_adapter_distribution),
        "verified_resolution_source_candidates": resolution_status_distribution.get("verified", 0),
        "expiry_status_distribution": dict(expiry_status_distribution),
        "expiry_timezone_distribution": dict(expiry_timezone_distribution),
        "expiry_time_origin_distribution": dict(expiry_time_origin_distribution),
        "expiry_time_adapter_distribution": dict(expiry_time_adapter_distribution),
        "verified_expiry_candidates": expiry_status_distribution.get("verified", 0),
        "historical_barrier_evidence_status_distribution": dict(
            historical_barrier_evidence_status_distribution
        ),
        "historical_barrier_evidence_adapter_distribution": dict(
            historical_barrier_evidence_adapter_distribution
        ),
        "historical_barrier_evidence_source_distribution": dict(
            historical_barrier_evidence_source_distribution
        ),
        "historical_barrier_evidence_interval_distribution": dict(
            historical_barrier_evidence_interval_distribution
        ),
        "historical_barrier_evidence_symbol_distribution": dict(
            historical_barrier_evidence_symbol_distribution
        ),
        "historical_barrier_failure_distribution": dict(historical_barrier_failure_distribution),
        "verified_historical_barrier_evidence_candidates": (
            historical_barrier_evidence_status_distribution.get(
                HISTORICAL_BARRIER_STATUS_VERIFIED, 0
            )
        ),
        "historical_barrier_candle_count": sum(
            int(safe_float(row.get("historical_barrier_evidence_candle_count")))
            for row in candidates
        ),
        "historical_barrier_missing_range_candidates": (
            historical_barrier_missing_range_candidates
        ),
        "missing_historical_barrier_evidence_candidates": (
            historical_barrier_evidence_status_distribution.get(
                MISSING_HISTORICAL_BARRIER_EVIDENCE, 0
            )
        ),
        "gamma_raw_snapshot_schema_version": (
            gamma_snapshot_result.schema_version if gamma_snapshot_result else ""
        ),
        "gamma_raw_snapshot_adapter_version": (
            gamma_snapshot_result.adapter_version if gamma_snapshot_result else ""
        ),
        "gamma_raw_snapshot_terminal_status": (
            gamma_snapshot_result.terminal_status if gamma_snapshot_result else "not_recorded"
        ),
        "gamma_raw_snapshot_manifest_path": (
            gamma_snapshot_result.manifest_path if gamma_snapshot_result else ""
        ),
        "gamma_raw_snapshot_manifest_sha256": (
            gamma_snapshot_result.manifest_sha256 if gamma_snapshot_result else ""
        ),
        "gamma_raw_snapshot_request_count": (
            gamma_snapshot_result.request_count if gamma_snapshot_result else 0
        ),
        "gamma_raw_snapshot_error_count": (
            gamma_snapshot_result.error_count if gamma_snapshot_result else 0
        ),
        "gamma_raw_snapshot_payload_count": (
            gamma_snapshot_result.payload_count if gamma_snapshot_result else 0
        ),
        "gamma_raw_snapshot_unique_market_count": (
            gamma_snapshot_result.unique_market_count if gamma_snapshot_result else 0
        ),
        "gamma_raw_snapshot_duplicate_market_id_count": (
            gamma_snapshot_result.duplicate_market_id_count if gamma_snapshot_result else 0
        ),
        "avg_expected_edge": mean(expected_edges) if expected_edges else 0.0,
        "max_expected_edge": max(expected_edges) if expected_edges else 0.0,
        "avg_confidence": mean(confidences) if confidences else 0.0,
        "api_error_count": api_error_count,
        "avoid_candidate_count": avoid_candidate_count,
        "excluded_avoid_candidates": avoid_candidate_count,
        "forbidden_category_count": forbidden_category_count,
        "ambiguous_market_count": ambiguous_market_count,
        "missing_token_id_count": missing_token_id_count,
        "excluded_missing_token": missing_token_id_count,
        "excluded_parse_low_confidence": excluded_parse_low_confidence,
        "excluded_missing_spot": excluded_missing_spot,
        "excluded_missing_orderbook": excluded_missing_orderbook,
        "eligible_after_avoid_filter": eligible_after_avoid_filter,
        "diagnostics_count": len(diagnostics or []),
        "tiny_live_recommendation": "NO",
        "safety_verification": verify_safety(),
        "errors": errors[:100],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(OUTPUT_FIELDS)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_diagnostics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DIAGNOSTIC_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in DIAGNOSTIC_FIELDS})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"crypto_threshold_edge_candidates": rows}, indent=2, sort_keys=True)
    )


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Crypto Threshold Edge Discovery Report",
        "",
        f"Generated at: `{summary['ended_at']}`",
        "",
        "This is read-only, shadow-only crypto threshold edge discovery.",
        (
            "External spot prices are public read-only inputs; no API key, auth, "
            "signing, orders, LLM calls, or live trading are used."
        ),
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "markets_scanned",
        "crypto_markets_detected",
        "parsed_threshold_markets",
        "spot_prices_loaded",
        "orderbooks_fetched",
        "candidates_generated",
        "shadow_entry_candidates",
        "watch_only_candidates",
        "rejected_candidates",
        "avg_expected_edge",
        "max_expected_edge",
        "avg_confidence",
        "api_error_count",
        "avoid_candidate_count",
        "forbidden_category_count",
        "ambiguous_market_count",
        "missing_token_id_count",
        "excluded_avoid_candidates",
        "excluded_parse_low_confidence",
        "excluded_missing_token",
        "excluded_missing_spot",
        "excluded_missing_orderbook",
        "eligible_after_avoid_filter",
        "diagnostics_count",
        "verified_expiry_candidates",
        "missing_historical_barrier_evidence_candidates",
        "verified_historical_barrier_evidence_candidates",
        "historical_barrier_candle_count",
        "historical_barrier_missing_range_candidates",
        "historical_barrier_preload_request_count",
        "historical_barrier_tail_request_count",
        "historical_barrier_preload_failure_count",
        "gamma_raw_snapshot_request_count",
        "gamma_raw_snapshot_error_count",
        "gamma_raw_snapshot_payload_count",
        "gamma_raw_snapshot_unique_market_count",
        "gamma_raw_snapshot_duplicate_market_id_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Asset Distribution",
            "",
            "```json",
            json.dumps(summary.get("asset_distribution", {}), indent=2, sort_keys=True),
            "```",
            "",
            "## Gamma Raw Fetch Evidence",
            "",
            "```json",
            json.dumps(
                {
                    "schema_version": summary.get("gamma_raw_snapshot_schema_version", ""),
                    "adapter_version": summary.get("gamma_raw_snapshot_adapter_version", ""),
                    "terminal_status": summary.get("gamma_raw_snapshot_terminal_status", ""),
                    "manifest_path": summary.get("gamma_raw_snapshot_manifest_path", ""),
                    "manifest_sha256": summary.get("gamma_raw_snapshot_manifest_sha256", ""),
                },
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "## Resolution Provenance",
            "",
            "```json",
            json.dumps(
                {
                    "status": summary.get("resolution_status_distribution", {}),
                    "origin": summary.get("resolution_source_origin_distribution", {}),
                    "adapter": summary.get("resolution_source_adapter_distribution", {}),
                },
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "## Expiry And Historical Barrier Evidence",
            "",
            "```json",
            json.dumps(
                {
                    "expiry_status": summary.get("expiry_status_distribution", {}),
                    "expiry_timezone": summary.get("expiry_timezone_distribution", {}),
                    "expiry_origin": summary.get("expiry_time_origin_distribution", {}),
                    "expiry_adapter": summary.get("expiry_time_adapter_distribution", {}),
                    "historical_barrier_evidence_status": summary.get(
                        "historical_barrier_evidence_status_distribution", {}
                    ),
                    "historical_barrier_evidence_adapter": summary.get(
                        "historical_barrier_evidence_adapter_distribution", {}
                    ),
                    "historical_barrier_evidence_source": summary.get(
                        "historical_barrier_evidence_source_distribution", {}
                    ),
                    "historical_barrier_evidence_interval": summary.get(
                        "historical_barrier_evidence_interval_distribution", {}
                    ),
                    "historical_barrier_evidence_symbol": summary.get(
                        "historical_barrier_evidence_symbol_distribution", {}
                    ),
                    "historical_barrier_failure": summary.get(
                        "historical_barrier_failure_distribution", {}
                    ),
                },
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            f"Tiny live recommendation: **{summary.get('tiny_live_recommendation', 'NO')}**",
            "",
            "## Safety Verification",
            "",
            "```json",
            json.dumps(summary.get("safety_verification", {}), indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def print_summary(summary: dict[str, Any], dry_run: bool) -> None:
    print(
        "DRY RUN: crypto threshold edge discovery" if dry_run else "Crypto threshold edge discovery"
    )
    for key in [
        "markets_scanned",
        "active_markets_available",
        "crypto_markets_detected",
        "parsed_threshold_markets",
        "spot_prices_loaded",
        "orderbooks_fetched",
        "candidates_generated",
        "shadow_entry_candidates",
        "watch_only_candidates",
        "rejected_candidates",
        "avg_expected_edge",
        "max_expected_edge",
        "avg_confidence",
        "api_error_count",
        "avoid_candidate_count",
        "forbidden_category_count",
        "ambiguous_market_count",
        "missing_token_id_count",
        "excluded_avoid_candidates",
        "excluded_parse_low_confidence",
        "excluded_missing_token",
        "excluded_missing_spot",
        "excluded_missing_orderbook",
        "eligible_after_avoid_filter",
        "diagnostics_count",
        "verified_expiry_candidates",
        "missing_historical_barrier_evidence_candidates",
        "verified_historical_barrier_evidence_candidates",
        "historical_barrier_candle_count",
        "historical_barrier_missing_range_candidates",
        "historical_barrier_preload_request_count",
        "historical_barrier_tail_request_count",
        "historical_barrier_preload_failure_count",
        "gamma_raw_snapshot_request_count",
        "gamma_raw_snapshot_error_count",
        "gamma_raw_snapshot_payload_count",
        "gamma_raw_snapshot_unique_market_count",
        "gamma_raw_snapshot_duplicate_market_id_count",
    ]:
        if key in summary:
            print(f"{key}: {summary.get(key, 0)}")
    print(f"asset_distribution: {summary.get('asset_distribution', {})}")
    print(f"resolution_status_distribution: {summary.get('resolution_status_distribution', {})}")
    print(f"expiry_status_distribution: {summary.get('expiry_status_distribution', {})}")
    print(
        "historical_barrier_evidence_status_distribution: "
        f"{summary.get('historical_barrier_evidence_status_distribution', {})}"
    )
    print(
        "historical_barrier_failure_distribution: "
        f"{summary.get('historical_barrier_failure_distribution', {})}"
    )
    print(
        "gamma_raw_snapshot_terminal_status: "
        f"{summary.get('gamma_raw_snapshot_terminal_status', 'not_recorded')}"
    )
    print(
        "gamma_raw_snapshot_manifest_sha256: "
        f"{summary.get('gamma_raw_snapshot_manifest_sha256', '')}"
    )
    print(f"tiny_live_recommendation: {summary.get('tiny_live_recommendation', 'NO')}")


async def run_async(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.data_mode != "real_readonly":
        raise ValueError("discover_crypto_threshold_edges only supports data_mode=real_readonly")
    avoid_path = Path(args.avoid_candidates_file)
    if not avoid_path.is_file():
        raise FileNotFoundError(f"avoid_candidates_file not found: {avoid_path}")
    output_path = Path(args.output_dir).resolve()
    protected_outputs = {REPO_ROOT.resolve(), (REPO_ROOT / "runs").resolve()}
    if not args.dry_run and output_path in protected_outputs:
        raise ValueError("output_dir must be an isolated crypto-threshold run directory")
    return await discover_crypto_threshold_edges(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidates, summary = asyncio.run(run_async(args))
    print_summary(summary, args.dry_run)
    if args.dry_run:
        return 0
    output_dir = Path(args.output_dir)
    outputs = {
        "crypto_threshold_edge_candidates_csv": output_dir / "crypto_threshold_edge_candidates.csv",
        "crypto_threshold_edge_candidates_json": output_dir
        / "crypto_threshold_edge_candidates.json",
        "crypto_threshold_edge_discovery_summary_json": output_dir
        / "crypto_threshold_edge_discovery_summary.json",
        "crypto_threshold_edge_discovery_report_md": output_dir
        / "crypto_threshold_edge_discovery_report.md",
        "crypto_threshold_market_diagnostics_csv": output_dir
        / "crypto_threshold_market_diagnostics.csv",
    }
    write_csv(outputs["crypto_threshold_edge_candidates_csv"], candidates)
    write_json(outputs["crypto_threshold_edge_candidates_json"], candidates)
    write_summary(outputs["crypto_threshold_edge_discovery_summary_json"], summary)
    write_report(outputs["crypto_threshold_edge_discovery_report_md"], summary)
    write_diagnostics_csv(
        outputs["crypto_threshold_market_diagnostics_csv"], summary.get("diagnostics", [])
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
