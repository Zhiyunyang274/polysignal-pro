"""Tests for corrected crypto-threshold shadow PnL validation."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.validate_crypto_threshold_shadow_pnl as validator
from polysignal.shadow.expiry_provenance import resolve_expiry_provenance
from polysignal.shadow.forward_observations import ForwardObservation
from polysignal.shadow.historical_barrier_provenance import (
    BINANCE_INTERVAL_MS,
    HISTORICAL_BARRIER_STATUS_VERIFIED,
    BinanceKlineFetchResult,
    BinanceKlinePageAudit,
    evaluate_historical_barrier,
    historical_evidence_candidate_fields,
    not_required_historical_evidence,
    parse_binance_kline,
    parse_rule_observation_window,
)
from polysignal.shadow.resolution_provenance import resolve_resolution_provenance

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLUTION_RULES = (
    "This market resolves Yes when the Coinbase closing price for Bitcoin (BTC) is above "
    "the threshold at 11:59 PM ET on the expiry date."
)
EXPIRY_LOCAL_TIME = "2026-12-31T23:59:00"
EXPIRY_GAMMA_MARKET = {
    "endDate": "2027-01-01T05:00:00Z",
    "updatedAt": "2026-08-04T09:00:00Z",
    "$schema": "gamma-market-v1",
    "version": "42",
}
TOUCH_RESOLUTION_SOURCE = "https://www.binance.com/en/trade/BTC_USDT"
TOUCH_RESOLUTION_RULES = (
    'This market resolves "Yes" if any Binance 1 minute candle for BTC/USDT between '
    "August 4, 2026, 6:00 AM and December 31, 2026, 11:59 PM in the ET timezone has "
    'a final "High" price equal to or greater than the price specified in the title. '
    "Otherwise it resolves No.\n\n"
    "The resolution source for this market is Binance, specifically the BTC/USDT prices "
    f'available at {TOUCH_RESOLUTION_SOURCE}, with the chart settings on "1m" for '
    "one-minute candles."
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate(**overrides: object) -> dict[str, str]:
    entry_timestamp = str(overrides.get("timestamp", "2026-08-04T10:02:00"))
    resolution_rules = str(overrides.get("resolution_rules", RESOLUTION_RULES))
    contract_kind = str(overrides.get("contract_kind", "settlement_threshold"))
    asset = str(overrides.get("asset", "BTC"))
    barrier_direction = str(overrides.get("barrier_direction", "up"))
    provenance = resolve_resolution_provenance(
        {
            "resolutionSource": str(
                overrides.get(
                    "resolution_source",
                    "https://www.coinbase.com/price/bitcoin",
                )
            ),
            "resolutionCriteria": resolution_rules,
        },
        contract_kind,
        asset,
        barrier_direction,
    )
    expiry_provenance = resolve_expiry_provenance(
        EXPIRY_GAMMA_MARKET,
        str(overrides.get("expiry_local_time", EXPIRY_LOCAL_TIME)),
        resolution_rules,
    )
    row = {
        "schema_version": "crypto_threshold_edge_discovery_v5",
        "edge_type": "crypto_price_threshold_v1",
        "market_id": "m1",
        "question": "Will BTC be above $100k?",
        "asset": asset,
        "threshold_price": "100000",
        "direction": "above",
        "contract_kind": contract_kind,
        "barrier_direction": barrier_direction,
        "parser_version": "crypto_threshold_parser_v4",
        "model_version": "crypto_threshold_probability_v1",
        "expiry_time": expiry_provenance.expiry_time,
        "expiry_local_time": expiry_provenance.expiry_local_time,
        "expiry_timezone": expiry_provenance.expiry_timezone,
        "expiry_time_origin": expiry_provenance.expiry_time_origin,
        "expiry_time_adapter_version": expiry_provenance.expiry_time_adapter_version,
        "expiry_time_provenance_sha256": expiry_provenance.expiry_time_provenance_sha256,
        "gamma_start_date": "",
        "gamma_end_date": expiry_provenance.gamma_end_date,
        "gamma_market_updated_at": expiry_provenance.gamma_market_updated_at,
        "gamma_market_schema": expiry_provenance.gamma_market_schema,
        "gamma_market_version": expiry_provenance.gamma_market_version,
        "expiry_status": expiry_provenance.status,
        "gamma_raw_market_snapshot_path": "",
        "gamma_raw_market_snapshot_sha256": "",
        **historical_evidence_candidate_fields(
            not_required_historical_evidence()
            if contract_kind != "touch_before_expiry"
            else not_required_historical_evidence().model_copy(
                update={"status": "missing_historical_barrier_evidence"}
            )
        ),
        "resolution_source": provenance.source,
        "resolution_source_origin": provenance.source_origin,
        "resolution_source_locator": provenance.source_locator,
        "resolution_source_adapter_version": provenance.source_adapter_version,
        "resolution_source_provenance_sha256": provenance.source_provenance_sha256,
        "resolution_rules": provenance.rules,
        "resolution_rules_sha256": str(
            overrides.get(
                "resolution_rules_sha256",
                provenance.rules_sha256,
            )
        ),
        "resolution_status": provenance.status,
        "parser_confidence": "1.0",
        "side": "YES",
        "yes_token_id": "yes1",
        "no_token_id": "no1",
        "spot_price": "90000",
        "spot_timestamp": "2026-08-04T10:01:00",
        "spot_source": "fixture_spot",
        "entry_quote_timestamp": entry_timestamp,
        "yes_orderbook_timestamp": entry_timestamp,
        "no_orderbook_timestamp": entry_timestamp,
        "entry_yes_best_ask": "0.40",
        "entry_no_best_ask": "0.60",
        "entry_yes_best_bid": "0.39",
        "entry_no_best_bid": "0.59",
        "entry_yes_best_ask_size": "100",
        "entry_no_best_ask_size": "100",
        "entry_yes_best_bid_size": "100",
        "entry_no_best_bid_size": "100",
        "combined_ask": "1.0",
        "spread": "0.01",
        "orderbook_depth": "100",
        "liquidity_score": "100",
        "expected_edge": "0.20",
        "confidence": "0.95",
        "evidence": (
            "crypto_price_threshold_v1|crypto_threshold_edge|external_spot_price|"
            "threshold_parser_high_confidence|spot_price_fresh"
        ),
        "reasons": (
            "crypto_price_threshold_v1|crypto_threshold_edge|external_spot_price|"
            "threshold_parser_high_confidence|spot_price_fresh"
        ),
        "risk_flags": "",
        "recommended_action": "shadow_entry",
        "edge_pass": "True",
        "near_miss_tier": "tier1_mispricing",
        "entry_decision_hint": "eligible_shadow_entry",
        "source": "crypto_threshold_edge",
        "timestamp": entry_timestamp,
        "tradable_score": "0",
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return {str(key): str(value) for key, value in row.items()}


def touch_candidate(artifact_root: Path, **overrides) -> dict[str, str]:
    row = candidate(
        question="Will BTC touch $100,000 before December 31?",
        contract_kind="touch_before_expiry",
        direction="hit_before_expiry",
        resolution_rules=TOUCH_RESOLUTION_RULES,
        resolution_source=TOUCH_RESOLUTION_SOURCE,
        timestamp="2026-08-04T10:02:00Z",
        **overrides,
    )
    entry = validator.parse_utc_time(row["timestamp"])
    window = parse_rule_observation_window(row["resolution_rules"], row["expiry_time"])
    start = validator.parse_utc_time(window.start_time)
    assert entry is not None
    assert start is not None
    assert window.status == "verified"

    candles = []
    start_ms = int(start.timestamp() * 1000)
    entry_ms = int(entry.timestamp() * 1000)
    for open_time_ms in range(start_ms, entry_ms, BINANCE_INTERVAL_MS):
        parsed, error = parse_binance_kline(
            [
                open_time_ms,
                "90000",
                "90010",
                "89990",
                "90000",
                "1.0",
                open_time_ms + BINANCE_INTERVAL_MS - 1,
                "90000",
                10,
                "0.5",
                "45000",
                "0",
            ]
        )
        assert error == ""
        assert parsed is not None
        candles.append(parsed)
    page = BinanceKlinePageAudit(
        sequence=1,
        requested_start_ms=start_ms,
        requested_end_ms=entry_ms,
        expected_candle_count=len(candles),
        received_candle_count=len(candles),
        attempts=1,
        status="complete",
    )
    fetch = BinanceKlineFetchResult(
        status="complete",
        symbol="BTCUSDT",
        start_time=window.start_time,
        end_time=entry.isoformat().replace("+00:00", "Z"),
        server_time_before=(entry - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        server_time_after=(entry + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        pages=(page,),
        candles=tuple(candles),
    )
    evidence = evaluate_historical_barrier(
        asset="BTC",
        barrier_direction="up",
        threshold_price=Decimal(row["threshold_price"]),
        entry_time=entry,
        window=window,
        fetch_result=fetch,
        output_dir=artifact_root,
        resolution_rules=row["resolution_rules"],
        manifest=row,
    )
    assert evidence.status == HISTORICAL_BARRIER_STATUS_VERIFIED
    row.update(
        {key: str(value) for key, value in historical_evidence_candidate_fields(evidence).items()}
    )
    return row


def write_canonical_artifact(directory: Path, prefix: str, payload: dict) -> tuple[Path, str]:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    path = directory / f"{prefix}_{digest}.json"
    path.write_bytes(content)
    return path, digest


def replace_touch_snapshot_with_gap(row: dict[str, str]) -> None:
    candle_path = Path(row["historical_barrier_candle_snapshot_path"])
    candle_payload = json.loads(candle_path.read_text())
    candle_payload["candles"].pop(0)
    candle_payload["pages"][0]["received_candle_count"] -= 1
    new_candle_path, new_candle_digest = write_canonical_artifact(
        candle_path.parent,
        "binance_1m",
        candle_payload,
    )

    evidence_path = Path(row["historical_barrier_evidence_path"])
    evidence_payload = json.loads(evidence_path.read_text())
    evidence_payload["candle_snapshot_sha256"] = new_candle_digest
    new_evidence_path, new_evidence_digest = write_canonical_artifact(
        evidence_path.parent,
        "evidence",
        evidence_payload,
    )
    row.update(
        {
            "historical_barrier_candle_snapshot_path": str(new_candle_path),
            "historical_barrier_candle_snapshot_sha256": new_candle_digest,
            "historical_barrier_evidence_path": str(new_evidence_path),
            "historical_barrier_evidence_sha256": new_evidence_digest,
        }
    )


def watch_candidate(**overrides):
    row = candidate(
        market_id="m-watch",
        expected_edge="-0.01",
        recommended_action="watch_only",
        edge_pass="False",
        near_miss_tier="",
        entry_decision_hint="watch_only",
        evidence="crypto_price_threshold_v1|crypto_threshold_edge|edge_too_low",
        reasons="crypto_price_threshold_v1|crypto_threshold_edge|edge_too_low",
    )
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(dict.fromkeys(field for row in rows for field in row))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def observation(row: dict[str, str], **overrides):
    observation_overrides = dict(overrides)
    notional = float(observation_overrides.pop("notional", 1.0))
    observed_timestamp = observation_overrides.get("timestamp", "2026-08-04T14:02:00")
    payload = {
        "shadow_trade_id": validator.stable_trade_id(row, notional),
        "market_id": row["market_id"],
        "timestamp": observed_timestamp,
        "observed_price": 0.99,
        "yes_token_id": row["yes_token_id"],
        "no_token_id": row["no_token_id"],
        "yes_best_bid": 0.50,
        "yes_best_ask": 0.51,
        "no_best_bid": 0.49,
        "no_best_ask": 0.50,
        "yes_best_bid_size": 100.0,
        "yes_best_ask_size": 100.0,
        "no_best_bid_size": 100.0,
        "no_best_ask_size": 100.0,
        "yes_orderbook_timestamp": observation_overrides.get(
            "yes_orderbook_timestamp", observed_timestamp
        ),
        "no_orderbook_timestamp": observation_overrides.get(
            "no_orderbook_timestamp", observed_timestamp
        ),
        "side": row["side"],
        "source": "clob_rest_readonly",
        "stale": False,
        "error": "",
    }
    payload.update(observation_overrides)
    return payload


def write_observations(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def args(tmp_path: Path, candidate_path: Path, **overrides):
    output_dir = tmp_path / "crypto_shadow"
    avoid_path = tmp_path / "avoid_candidates.csv"
    if not avoid_path.exists():
        avoid_path.write_text("market_id,reason\n")
    argv = [
        "--candidate_file",
        str(candidate_path),
        "--output_dir",
        str(output_dir),
        "--avoid_file",
        str(avoid_path),
        "--evaluation_time",
        "2026-08-04T14:30:00",
        "--max_entry_age_minutes",
        "600",
        "--slippage_bps",
        "0",
        "--min_sample_size",
        "1",
        "--min_independent_clusters",
        "1",
    ]
    forward_path = overrides.pop("forward_path", None)
    if forward_path is not None:
        argv.extend(["--forward_observations", str(forward_path)])
    for key, value in overrides.items():
        option = f"--{key}"
        if isinstance(value, bool):
            if value:
                argv.append(option)
        else:
            argv.extend([option, str(value)])
    return validator.parse_args(argv)


def test_default_entry_snapshot_age_is_one_minute():
    assert validator.parse_args([]).max_entry_age_minutes == pytest.approx(1.0)


def test_validator_v7_accepts_only_discovery_v5_candidates():
    assert validator.SCHEMA_VERSION == "crypto_threshold_shadow_pnl_v7"
    assert validator.DISCOVERY_SCHEMA_VERSION == "crypto_threshold_edge_discovery_v5"


def test_default_clock_skew_is_hard_capped_at_five_seconds():
    parsed = validator.parse_args([])

    assert parsed.max_clock_skew_seconds == pytest.approx(5.0)
    assert validator.effective_max_clock_skew_seconds(parsed) == pytest.approx(5.0)


def test_legacy_future_tolerance_can_only_make_clock_skew_stricter():
    parsed = validator.parse_args(["--future_tolerance_minutes", "0.05"])

    assert validator.effective_max_clock_skew_seconds(parsed) == pytest.approx(3.0)


def test_parse_utc_time_accepts_iso_epoch_seconds_and_epoch_milliseconds():
    expected = datetime(2026, 8, 4, 10, 2, tzinfo=timezone.utc)
    epoch_seconds = expected.timestamp()

    for value in [
        "2026-08-04T10:02:00Z",
        epoch_seconds,
        str(int(epoch_seconds)),
        int(epoch_seconds * 1000),
        str(int(epoch_seconds * 1000)),
    ]:
        assert validator.parse_utc_time(value) == expected

    assert validator.parse_utc_time(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 10**15, "bad-time"])
def test_parse_utc_time_rejects_invalid_or_unsupported_values(value):
    assert validator.parse_utc_time(value) is None


def test_forward_observation_round_trip_preserves_execution_metadata():
    payload = {
        "shadow_trade_id": "shadow-1",
        "market_id": "market-1",
        "timestamp": "2026-08-04T14:02:00",
        "observed_price": 0.5,
        "yes_best_bid_size": "2.5",
        "yes_best_ask_size": "3.5",
        "no_best_bid_size": "4.5",
        "no_best_ask_size": "5.5",
        "yes_orderbook_timestamp": "1785852120000",
        "no_orderbook_timestamp": "1785852120001",
    }

    observation_model = ForwardObservation.from_dict(payload)
    exit_observation = observation_model.to_exit_observation()

    assert observation_model.yes_best_bid_size == pytest.approx(2.5)
    assert observation_model.no_best_ask_size == pytest.approx(5.5)
    assert exit_observation["yes_orderbook_timestamp"] == "1785852120000"
    assert exit_observation["no_orderbook_timestamp"] == "1785852120001"


def test_step11_artifact_reconciliation_is_explicit(tmp_path: Path):
    candidate_path = REPO_ROOT / "runs" / "crypto_threshold_edge_candidates.csv"
    parsed = args(
        tmp_path,
        candidate_path,
        evaluation_time="2026-08-04T00:00:00",
        avoid_file=REPO_ROOT / "runs" / "avoid_candidates.csv",
    )

    summary, positions, diagnostics = validator.validate(parsed)

    reconciliation = summary["reconciliation"]
    assert reconciliation["candidates_loaded"] == 45
    assert reconciliation["discovery_shadow_entry_count"] == 29
    assert reconciliation["discovery_watch_only_count"] == 16
    assert reconciliation["legacy_prefilter"]["candidates_after_prefilter"] == 41
    assert reconciliation["legacy_prefilter"]["entry_decision_distribution"] == {
        "eligible_shadow_entry": 28,
        "watch_only": 13,
    }
    assert reconciliation["strict_gate_eligible_count"] == 28
    assert reconciliation["discovery_shadow_entry_cluster_count"] == 3
    assert reconciliation["discovery_to_shared_gate_transitions"]["shadow_entry->watch_only"] == 1
    assert reconciliation["all_candidates_accounted_for"] is True
    assert len(diagnostics) == 45
    assert positions == []


def test_old_entry_and_spot_snapshots_fail_closed(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    stale = candidate(timestamp="2026-08-04T08:00:00", spot_timestamp="2026-08-04T07:59:00")
    write_candidates(candidate_path, [stale])

    summary, positions, diagnostics = validator.validate(
        args(tmp_path, candidate_path, max_entry_age_minutes=60)
    )

    assert positions == []
    assert diagnostics[0]["entry_time"] == "2026-08-04T08:00:00"
    assert "stale_entry_snapshot" in diagnostics[0]["position_exclusion_reasons"]
    assert "stale_spot_snapshot" in diagnostics[0]["position_exclusion_reasons"]
    assert summary["validation"]["status"] == "entry_snapshot_refresh_required"
    assert summary["performance"]["total_pnl"] is None


def test_all_touch_candidates_without_history_report_the_actual_blocker():
    result = validator.validation_conclusion(
        {
            "positions_created": 0,
            "target_edge_candidates": 44,
            "position_exclusion_reasons": {
                "missing_historical_barrier_evidence": 44,
                "discovery_action_not_shadow_entry": 44,
            },
        },
        {
            "closed_positions": 0,
            "closed_position_cluster_count": 0,
            "average_return": None,
        },
        min_sample_size=20,
        min_independent_clusters=5,
    )

    assert result["status"] == "historical_barrier_evidence_required"
    assert result["reasons"] == ["missing_historical_barrier_evidence"]
    assert result["supports_tiny_live"] is False


def test_verified_touch_history_is_recomputed_offline_before_entry(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = touch_candidate(tmp_path)
    write_candidates(candidate_path, [row])

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert len(positions) == 1, diagnostics[0]["position_exclusion_reasons"]
    assert diagnostics[0]["position_exclusion_reasons"] == []
    assert positions[0].historical_barrier_evidence_status == (HISTORICAL_BARRIER_STATUS_VERIFIED)
    assert positions[0].historical_barrier_evidence_candle_count == 2
    assert positions[0].historical_barrier_expected_candle_count == 2
    assert positions[0].historical_barrier_tail_coverage_status == "closed_through_entry"
    assert positions[0].historical_barrier_tail_covered_through == ("2026-08-04T10:02:00Z")
    assert summary["schema_version"] == "crypto_threshold_shadow_pnl_v7"
    for field in validator.HISTORICAL_BARRIER_FIELDS:
        assert field in diagnostics[0]
        assert diagnostics[0][field] == row[field]


def test_tampered_touch_evidence_artifact_fails_closed(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = touch_candidate(tmp_path)
    Path(row["historical_barrier_evidence_path"]).write_text("{}")
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert (
        "historical_barrier_evidence_artifact_mismatch"
        in diagnostics[0]["position_exclusion_reasons"]
    )


def test_touch_artifacts_outside_candidate_directory_are_rejected(tmp_path: Path):
    artifact_root = tmp_path / "outside"
    artifact_root.mkdir()
    candidate_dir = tmp_path / "discovery"
    candidate_dir.mkdir()
    candidate_path = candidate_dir / "candidates.csv"
    row = touch_candidate(artifact_root)
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    reasons = diagnostics[0]["position_exclusion_reasons"]
    assert "historical_barrier_evidence_artifact_path_invalid" in reasons
    assert "historical_barrier_candle_snapshot_path_invalid" in reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "historical_barrier_evidence_symbol",
            "ETHUSDT",
            "historical_barrier_evidence_symbol_mismatch",
        ),
        (
            "historical_barrier_evidence_end_time",
            "2026-08-04T10:03:00Z",
            "historical_barrier_entry_time_mismatch",
        ),
    ],
)
def test_touch_evidence_wrong_symbol_or_range_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    row = touch_candidate(tmp_path)
    row[field] = value
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]


def test_rehashed_touch_snapshot_with_candle_gap_fails_closed(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = touch_candidate(tmp_path)
    replace_touch_snapshot_with_gap(row)
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    reasons = diagnostics[0]["position_exclusion_reasons"]
    assert "partial_coverage" in reasons
    assert "historical_barrier_candle_snapshot_status_mismatch" in reasons


def test_every_historical_barrier_field_is_bound_into_entry_identity():
    row = candidate()
    identity = validator.entry_identity_sha256(row)
    numeric_fields = {
        "historical_barrier_evidence_candle_count",
        "historical_barrier_expected_candle_count",
        "historical_barrier_min_low_price",
        "historical_barrier_max_high_price",
    }
    time_fields = {
        "historical_barrier_evidence_start_time",
        "historical_barrier_evidence_end_time",
        "historical_barrier_crossed_at",
        "historical_barrier_tail_covered_through",
        "historical_barrier_first_touch_at",
    }

    for field in validator.HISTORICAL_BARRIER_FIELDS:
        changed = dict(row)
        if field in numeric_fields:
            changed[field] = "1"
        elif field in time_fields:
            changed[field] = "2026-08-04T09:00:00Z"
        else:
            changed[field] = f"changed:{field}"
        assert validator.entry_identity_sha256(changed) != identity, field

    assert set(validator.HISTORICAL_BARRIER_FIELDS).issubset(validator.VALIDATION_FIELDS)
    assert set(validator.HISTORICAL_BARRIER_FIELDS).issubset(validator.RECONCILIATION_FIELDS)
    for field, value in (
        ("gamma_start_date", "2026-08-04T09:00:00Z"),
        ("gamma_raw_market_snapshot_path", "gamma/raw.json"),
        ("gamma_raw_market_snapshot_sha256", "f" * 64),
    ):
        changed = dict(row)
        changed[field] = value
        assert validator.entry_identity_sha256(changed) != identity, field
        assert field in validator.VALIDATION_FIELDS
        assert field in validator.RECONCILIATION_FIELDS


def test_discovery_v4_candidate_is_audit_only(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(
        candidate_path,
        [candidate(schema_version="crypto_threshold_edge_discovery_v4")],
    )

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert "unsupported_candidate_schema_version" in diagnostics[0]["position_exclusion_reasons"]
    assert summary["performance"]["total_pnl"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("historical_barrier_evidence_path", "historical_barrier_evidence/evidence_x.json"),
        ("historical_barrier_evidence_sha256", "a" * 64),
        ("historical_barrier_evidence_start_time", "2026-08-04T10:00:00Z"),
        ("historical_barrier_evidence_candle_count", "1"),
        ("historical_barrier_min_low_price", "89990"),
        ("historical_barrier_tail_coverage_status", "closed_through_entry"),
        ("historical_barrier_first_touch_at", "2026-08-04T10:01:00Z"),
    ],
)
def test_settlement_contract_rejects_historical_artifact_fields(
    tmp_path: Path,
    field: str,
    value: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**{field: value})])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert (
        "settlement_historical_barrier_artifact_fields_present"
        in diagnostics[0]["position_exclusion_reasons"]
    )


def test_exactly_one_minute_old_entry_and_spot_snapshots_are_accepted(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate(spot_timestamp="2026-08-04T10:02:00")
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(
        args(
            tmp_path,
            candidate_path,
            evaluation_time="2026-08-04T10:03:00",
            max_entry_age_minutes=1,
        )
    )

    assert len(positions) == 1
    assert diagnostics[0]["entry_snapshot_age_minutes"] == pytest.approx(1.0)


def test_entry_and_spot_snapshots_just_over_one_minute_are_rejected(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate(spot_timestamp="2026-08-04T10:02:00")
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(
        args(
            tmp_path,
            candidate_path,
            evaluation_time="2026-08-04T10:03:00.001000",
            max_entry_age_minutes=1,
        )
    )

    assert positions == []
    reasons = diagnostics[0]["position_exclusion_reasons"]
    assert "stale_entry_snapshot" in reasons
    assert "stale_spot_snapshot" in reasons


def test_missing_forward_data_has_no_exit_or_pnl(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate()
    write_candidates(candidate_path, [row])

    summary, positions, _ = validator.validate(args(tmp_path, candidate_path))

    assert len(positions) == 1
    position = positions[0]
    assert position.entry_time == row["timestamp"]
    assert position.threshold_price == 100000
    assert position.contract_kind == "settlement_threshold"
    assert position.barrier_direction == "up"
    assert position.parser_version == "crypto_threshold_parser_v4"
    assert position.model_version == "crypto_threshold_probability_v1"
    assert position.resolution_source_origin == row["resolution_source_origin"]
    assert position.resolution_source_locator == row["resolution_source_locator"]
    assert position.resolution_source_adapter_version == row["resolution_source_adapter_version"]
    assert (
        position.resolution_source_provenance_sha256 == row["resolution_source_provenance_sha256"]
    )
    assert position.spot_price == 90000
    assert position.spot_timestamp == row["spot_timestamp"]
    assert position.spot_source == "fixture_spot"
    assert position.entry_quote_timestamp == row["entry_quote_timestamp"]
    assert position.yes_orderbook_timestamp == row["yes_orderbook_timestamp"]
    assert position.no_orderbook_timestamp == row["no_orderbook_timestamp"]
    assert position.status == "insufficient_forward_data"
    assert position.exit_price is None
    assert position.return_pct is None
    assert position.pnl is None
    assert summary["performance"]["closed_positions"] == 0
    assert summary["performance"]["win_rate"] is None
    assert summary["performance"]["total_pnl"] is None
    assert summary["performance"]["insufficient_reason_distribution"] == {
        "missing_forward_observation": 1
    }
    assert summary["performance"]["concentration"]["asset"] == {
        "counts": {"BTC": 1},
        "distinct_values": 1,
        "largest_share": 1.0,
    }


def test_pre_entry_and_equal_time_observations_are_rejected(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    write_observations(
        forward_path,
        [
            observation(row, timestamp="2026-08-04T10:01:00", yes_best_bid=0.90),
            observation(row, timestamp="2026-08-04T10:02:00", yes_best_bid=0.90),
            observation(row, timestamp="2026-08-04T11:02:00", yes_best_bid=0.90),
            observation(row, timestamp="2026-08-04T14:02:00", yes_best_bid=0.50),
        ],
    )

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "closed"
    assert positions[0].exit_time == "2026-08-04T14:02:00"
    assert positions[0].exit_price == pytest.approx(0.50)
    assert positions[0].pnl == pytest.approx(0.25)
    assert (
        summary["forward_data"]["observation_rejection_reasons"][
            "observation_not_strictly_post_entry"
        ]
        == 2
    )
    assert (
        summary["forward_data"]["observation_rejection_reasons"][
            "observation_before_min_forward_horizon"
        ]
        == 1
    )


def test_short_forward_horizon_surfaces_specific_insufficient_reason(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    write_observations(
        forward_path,
        [observation(row, timestamp="2026-08-04T11:02:00")],
    )

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].insufficient_reason == "observation_before_min_forward_horizon"
    assert summary["performance"]["insufficient_reason_distribution"] == {
        "observation_before_min_forward_horizon": 1
    }
    assert summary["validation"]["reasons"] == ["observation_before_min_forward_horizon"]


def test_cross_run_market_only_observation_is_not_reused(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    write_observations(
        forward_path,
        [observation(row, shadow_trade_id="different_run_trade", yes_best_bid=0.99)],
    )

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "insufficient_forward_data"
    assert positions[0].pnl is None
    assert summary["forward_data"]["observation_rejection_reasons"] == {
        "shadow_trade_id_mismatch": 1
    }


@pytest.mark.parametrize(
    ("observation_overrides", "dropped_field", "reason"),
    [
        ({}, "source", "missing_forward_observation_source"),
        ({"source": "fixture_readonly"}, "", "untrusted_forward_observation_source"),
        ({}, "stale", "missing_forward_stale_flag"),
        ({"stale": "false"}, "", "stale_forward_observation"),
        ({"stale": True}, "", "stale_forward_observation"),
        ({}, "error", "missing_forward_error_field"),
        ({"error": None}, "", "forward_observation_error"),
        ({"error": "api_error"}, "", "forward_observation_error"),
        ({"yes_best_bid": None}, "", "missing_side_specific_exit_bid"),
        ({"yes_best_ask": None}, "", "missing_side_specific_exit_ask"),
        (
            {"yes_best_bid": 0.52, "yes_best_ask": 0.51},
            "",
            "crossed_side_specific_exit_book",
        ),
        ({"side": ""}, "", "missing_observation_side"),
        ({"yes_token_id": ""}, "", "missing_observation_token_ids"),
        ({"yes_token_id": "wrong-token"}, "", "observation_token_mismatch"),
    ],
)
def test_invalid_forward_side_bid_never_creates_pnl(
    tmp_path: Path,
    observation_overrides: dict,
    dropped_field: str,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    observed = observation(row, **observation_overrides)
    if dropped_field:
        observed.pop(dropped_field)
    write_observations(forward_path, [observed])

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "insufficient_forward_data"
    assert positions[0].exit_price is None
    assert positions[0].pnl is None
    assert summary["forward_data"]["observation_rejection_reasons"][reason] == 1


@pytest.mark.parametrize(
    ("observation_overrides", "dropped_field", "reason"),
    [
        ({}, "yes_orderbook_timestamp", "missing_or_invalid_forward_yes_orderbook_timestamp"),
        (
            {"no_orderbook_timestamp": "not-a-timestamp"},
            "",
            "missing_or_invalid_forward_no_orderbook_timestamp",
        ),
        (
            {"yes_orderbook_timestamp": "2026-08-04T03:00:00"},
            "",
            "stale_forward_yes_orderbook_snapshot",
        ),
        (
            {"no_orderbook_timestamp": "2026-08-04T14:02:05.001000"},
            "",
            "forward_no_orderbook_timestamp_in_future",
        ),
    ],
)
def test_forward_server_orderbook_timestamps_fail_closed(
    tmp_path: Path,
    observation_overrides: dict,
    dropped_field: str,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    observed = observation(row, **observation_overrides)
    if dropped_field:
        observed.pop(dropped_field)
    write_observations(forward_path, [observed])

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "insufficient_forward_data"
    assert positions[0].pnl is None
    assert summary["forward_data"]["observation_rejection_reasons"][reason] == 1


def test_forward_epoch_millisecond_timestamp_at_clock_skew_cap_is_accepted(
    tmp_path: Path,
):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    observed_time = datetime(2026, 8, 4, 14, 2, tzinfo=timezone.utc)
    server_time = observed_time.replace(microsecond=0).timestamp() * 1000 + 5000
    write_candidates(candidate_path, [row])
    write_observations(
        forward_path,
        [
            observation(
                row,
                yes_orderbook_timestamp=str(int(server_time)),
                no_orderbook_timestamp=str(int(server_time)),
            )
        ],
    )

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "closed"
    assert summary["inputs"]["max_clock_skew_seconds"] == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("size", "reason"),
    [
        (None, "missing_side_specific_exit_bid_size"),
        (2.499, "insufficient_selected_exit_bid_size"),
    ],
)
def test_forward_selected_bid_size_must_cover_entry_shares(
    tmp_path: Path,
    size: float | None,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    write_observations(forward_path, [observation(row, yes_best_bid_size=size)])

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "insufficient_forward_data"
    assert positions[0].pnl is None
    assert summary["forward_data"]["observation_rejection_reasons"] == {reason: 1}


def test_notional_drives_entry_shares_exit_capacity_and_pnl(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate(entry_yes_best_ask_size="5")
    write_candidates(candidate_path, [row])
    write_observations(forward_path, [observation(row, notional=2, yes_best_bid_size=5)])

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path, notional=2)
    )

    position = positions[0]
    assert position.status == "closed"
    assert position.notional == pytest.approx(2.0)
    assert position.entry_share_quantity == pytest.approx(5.0)
    assert position.exit_side_best_bid_size == pytest.approx(5.0)
    assert position.pnl == pytest.approx(0.5)
    assert summary["forward_data"]["executable_size_policy"]
    assert summary["forward_data"]["source_timestamp_policy"]


def test_observation_after_evaluation_time_is_rejected(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    write_observations(
        forward_path,
        [observation(row, timestamp="2026-08-04T15:00:00", yes_best_bid=0.99)],
    )

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "insufficient_forward_data"
    assert positions[0].pnl is None
    assert summary["forward_data"]["observation_rejection_reasons"] == {
        "observation_after_evaluation_time": 1
    }


@pytest.mark.parametrize(
    ("candidate_overrides", "reason"),
    [
        ({"entry_yes_best_bid": "0"}, "invalid_entry_yes_best_bid"),
        ({"entry_yes_best_bid": "0.41"}, "entry_bid_above_ask"),
        ({"entry_no_best_ask": "0"}, "invalid_entry_no_best_ask"),
        ({"entry_no_best_bid": "0.61"}, "entry_no_bid_above_ask"),
        ({"no_token_id": "yes1"}, "token_pair_not_distinct"),
        ({"yes_token_id": "m1"}, "market_id_used_as_token_id"),
        ({"expiry_time": "2026-08-04T14:00:00"}, "market_expired_at_evaluation"),
        ({"spot_timestamp": "2026-08-04T10:03:00"}, "spot_timestamp_after_entry"),
        ({"entry_quote_timestamp": ""}, "missing_or_invalid_entry_quote_timestamp"),
        (
            {"entry_quote_timestamp": "2026-08-04T10:03:00"},
            "entry_quote_timestamp_after_entry",
        ),
    ],
)
def test_invalid_entry_snapshot_integrity_fails_closed(
    tmp_path: Path,
    candidate_overrides: dict,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**candidate_overrides)])

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]
    assert summary["performance"]["total_pnl"] is None


@pytest.mark.parametrize(
    ("candidate_overrides", "max_entry_age_minutes", "reason"),
    [
        (
            {"yes_orderbook_timestamp": ""},
            600,
            "missing_or_invalid_yes_orderbook_timestamp",
        ),
        (
            {"no_orderbook_timestamp": "not-a-timestamp"},
            600,
            "missing_or_invalid_no_orderbook_timestamp",
        ),
        (
            {"yes_orderbook_timestamp": "2026-08-04T10:00:59.999000"},
            1,
            "stale_yes_orderbook_snapshot",
        ),
        (
            {"no_orderbook_timestamp": "2026-08-04T10:02:05.001000"},
            600,
            "no_orderbook_timestamp_in_future",
        ),
    ],
)
def test_entry_server_orderbook_timestamps_fail_closed(
    tmp_path: Path,
    candidate_overrides: dict,
    max_entry_age_minutes: float,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**candidate_overrides)])

    summary, positions, diagnostics = validator.validate(
        args(
            tmp_path,
            candidate_path,
            max_entry_age_minutes=max_entry_age_minutes,
        )
    )

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]
    assert summary["performance"]["total_pnl"] is None


def test_entry_server_timestamp_at_exact_clock_skew_cap_is_accepted(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate(no_orderbook_timestamp="2026-08-04T10:02:05")
    write_candidates(candidate_path, [row])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert len(positions) == 1
    assert diagnostics[0]["position_exclusion_reasons"] == []


@pytest.mark.parametrize(
    ("candidate_overrides", "reason"),
    [
        ({"resolution_source": ""}, "missing_resolution_source"),
        ({"resolution_rules": "too short"}, "missing_or_insufficient_resolution_rules"),
        ({"resolution_rules_sha256": "0" * 64}, "resolution_rules_sha256_mismatch"),
        (
            {"resolution_source": "https://unclear.example/resolution"},
            "ambiguous_resolution_source",
        ),
        (
            {
                "resolution_rules": (
                    "This market possibly resolves Yes from the closing price at expiry."
                )
            },
            "ambiguous_resolution_rules",
        ),
        (
            {
                "resolution_rules": (
                    "This settlement market resolves Yes if Bitcoin hits before expiry at any time."
                )
            },
            "resolution_semantics_conflict",
        ),
        ({"resolution_status": ""}, "resolution_status_not_verified"),
    ],
)
def test_resolution_provenance_integrity_fails_closed(
    tmp_path: Path,
    candidate_overrides: dict,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**candidate_overrides)])

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]
    assert summary["performance"]["total_pnl"] is None


def test_v4_candidate_without_adapter_provenance_fails_closed(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate()
    for field in [
        "resolution_source_origin",
        "resolution_source_locator",
        "resolution_source_adapter_version",
        "resolution_source_provenance_sha256",
    ]:
        row.pop(field)
    write_candidates(candidate_path, [row])

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    reasons = diagnostics[0]["position_exclusion_reasons"]
    assert "resolution_source_adapter_version_mismatch" in reasons
    assert "missing_or_invalid_resolution_source_origin" in reasons
    assert "missing_resolution_source_locator" in reasons
    assert "missing_resolution_source_provenance_sha256" in reasons
    assert summary["performance"]["total_pnl"] is None


def test_v5_candidate_without_expiry_provenance_fails_closed(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate(schema_version="crypto_threshold_edge_discovery_v3")
    row["parser_version"] = "crypto_threshold_parser_v3"
    row["schema_version"] = "crypto_threshold_edge_discovery_v3"
    for field in [
        "expiry_local_time",
        "expiry_timezone",
        "expiry_time_origin",
        "expiry_time_adapter_version",
        "expiry_time_provenance_sha256",
        "gamma_end_date",
        "gamma_market_updated_at",
        "gamma_market_schema",
        "gamma_market_version",
        "expiry_status",
    ]:
        row.pop(field)
    write_candidates(candidate_path, [row])

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    reasons = diagnostics[0]["position_exclusion_reasons"]
    assert "unsupported_candidate_schema_version" in reasons
    assert "unsupported_parser_version" in reasons
    assert "missing_title_expiry_time" in reasons
    assert "missing_expiry_time_provenance_sha256" in reasons
    assert summary["schema_version"] == "crypto_threshold_shadow_pnl_v7"
    assert summary["forward_data"]["complete_book_policy"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "resolution_source_locator",
            "market.description",
            "invalid_resolution_source_locator",
        ),
        (
            "resolution_source_provenance_sha256",
            "0" * 64,
            "resolution_source_provenance_sha256_mismatch",
        ),
        (
            "resolution_rules_sha256",
            "0" * 64,
            "resolution_rules_sha256_mismatch",
        ),
    ],
)
def test_tampered_resolution_provenance_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**{field: value})])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]


@pytest.mark.parametrize(
    ("candidate_overrides", "reason"),
    [
        (
            {"entry_yes_best_ask_size": ""},
            "missing_or_invalid_entry_yes_best_ask_size",
        ),
        (
            {"entry_no_best_bid_size": "0"},
            "missing_or_invalid_entry_no_best_bid_size",
        ),
        ({"entry_yes_best_ask_size": "2.499"}, "insufficient_selected_entry_ask_size"),
    ],
)
def test_entry_best_level_size_integrity_fails_closed(
    tmp_path: Path,
    candidate_overrides: dict,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**candidate_overrides)])

    _, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]


def test_entry_ask_size_equal_to_notional_derived_shares_is_accepted(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(entry_yes_best_ask_size="2.5")])

    _, positions, _ = validator.validate(args(tmp_path, candidate_path))

    assert len(positions) == 1
    assert positions[0].entry_share_quantity == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("candidate_overrides", "reason"),
    [
        ({"contract_kind": ""}, "unsupported_or_missing_contract_kind"),
        ({"barrier_direction": "unknown"}, "unverifiable_barrier_direction"),
        ({"parser_version": ""}, "missing_parser_version"),
        ({"model_version": ""}, "missing_model_version"),
        ({"threshold_price": "0"}, "invalid_threshold_price"),
        ({"spot_price": "0"}, "invalid_spot_price"),
        ({"direction": "below"}, "settlement_direction_mismatch"),
        (
            {
                "contract_kind": "touch_before_expiry",
                "direction": "hit_before_expiry",
                "barrier_direction": "up",
                "spot_price": "100000",
            },
            "already_crossed_barrier",
        ),
    ],
)
def test_contract_semantics_integrity_fails_closed(
    tmp_path: Path,
    candidate_overrides: dict,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate(**candidate_overrides)])

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert reason in diagnostics[0]["position_exclusion_reasons"]
    assert summary["performance"]["total_pnl"] is None


def test_semantic_model_version_is_part_of_trade_identity():
    row = candidate()
    changed_parser = candidate(parser_version="crypto_threshold_parser_v5")
    changed_barrier = candidate(
        contract_kind="touch_before_expiry",
        direction="hit_before_expiry",
        barrier_direction="down",
        threshold_price="80000",
    )
    changed_adapter = candidate(resolution_source_adapter_version="resolution_source_adapter_v2")
    changed_rules_hash = candidate(resolution_rules_sha256="0" * 64)
    changed_provenance = candidate(resolution_source_provenance_sha256="1" * 64)

    assert validator.stable_trade_id(row) != validator.stable_trade_id(changed_parser)
    assert validator.stable_trade_id(row) != validator.stable_trade_id(changed_barrier)
    assert validator.stable_trade_id(row) != validator.stable_trade_id(changed_adapter)
    assert validator.stable_trade_id(row) != validator.stable_trade_id(changed_rules_hash)
    assert validator.stable_trade_id(row) != validator.stable_trade_id(changed_provenance)


def test_prepared_entry_identity_rejects_any_entry_evidence_tamper(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    row = candidate()
    write_candidates(candidate_path, [row])
    parsed = args(tmp_path, candidate_path, evaluation_time="2026-08-04T10:30:00")
    summary, positions, diagnostics = validator.validate(parsed)
    output_paths = validator.write_outputs(Path(parsed.output_dir), summary, positions, diagnostics)
    prepared_path = Path(output_paths["shadow_trades_csv"])
    prepared = next(csv.DictReader(prepared_path.open(newline="")))

    assert validator.prepared_entry_matches(row, prepared, 1.0)
    tampered_values = {
        "schema_version": "crypto_threshold_edge_discovery_v3",
        "expiry_time": "2027-01-01T05:00:00Z",
        "expiry_local_time": "2027-01-01T00:00:00",
        "expiry_timezone": "UTC",
        "expiry_time_provenance_sha256": "0" * 64,
        "gamma_end_date": "2027-01-01T06:00:00Z",
        "resolution_source": "https://www.kraken.com/prices/bitcoin",
        "resolution_source_locator": "market.rules:other",
        "resolution_rules": "A different verified Bitcoin Coinbase rule at 11:59 PM ET.",
        "resolution_rules_sha256": "0" * 64,
        "spot_price": "90001",
        "spot_timestamp": "2026-08-04T10:00:59",
        "timestamp": "2026-08-04T10:02:01",
        "entry_quote_timestamp": "2026-08-04T10:01:59",
        "yes_orderbook_timestamp": "2026-08-04T10:01:59",
        "no_orderbook_timestamp": "2026-08-04T10:01:59",
        "entry_yes_best_ask": "0.41",
        "entry_no_best_ask": "0.61",
        "entry_yes_best_bid": "0.38",
        "entry_no_best_bid": "0.58",
        "entry_yes_best_ask_size": "101",
        "entry_no_best_ask_size": "101",
        "entry_yes_best_bid_size": "101",
        "entry_no_best_bid_size": "101",
        "yes_token_id": "yes-tampered",
        "no_token_id": "no-tampered",
        "expected_edge": "0.21",
        "confidence": "0.94",
        "recommended_action": "watch_only",
        "entry_decision_hint": "watch_only",
        "edge_pass": "False",
        "risk_flags": "tampered",
        "near_miss_tier": "tier3",
        "evidence": "tampered-evidence",
        "reasons": "tampered-reasons",
        "combined_ask": "1.01",
        "spread": "0.02",
        "orderbook_depth": "99",
        "liquidity_score": "99",
    }
    for field, value in tampered_values.items():
        tampered = dict(row)
        tampered[field] = value
        assert validator.stable_trade_id(tampered) != validator.stable_trade_id(row), field
        assert not validator.prepared_entry_matches(tampered, prepared, 1.0), field
    assert validator.stable_trade_id(row, 2.0) != validator.stable_trade_id(row, 1.0)
    assert not validator.prepared_entry_matches(row, prepared, 2.0)


def test_current_avoid_list_is_rechecked(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    avoid_path = tmp_path / "avoid_candidates.csv"
    write_candidates(candidate_path, [candidate()])
    avoid_path.write_text("market_id,reason\nm1,new_resolution_risk\n")

    summary, positions, diagnostics = validator.validate(args(tmp_path, candidate_path))

    assert positions == []
    assert "current_avoid_candidate" in diagnostics[0]["position_exclusion_reasons"]
    assert summary["reconciliation"]["current_avoid_market_count"] == 1


def test_no_side_uses_no_ask_and_no_bid_not_generic_price(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate(side="NO")
    write_candidates(candidate_path, [row])
    write_observations(
        forward_path,
        [
            observation(
                row,
                side="NO",
                observed_price=0.01,
                yes_best_bid=0.49,
                no_best_bid=0.70,
                no_best_ask=0.71,
            )
        ],
    )

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    position = positions[0]
    assert position.entry_price == pytest.approx(0.60)
    assert position.entry_price_source == "entry_no_best_ask"
    assert position.exit_price == pytest.approx(0.70)
    assert position.exit_price_source == "no_best_bid"
    assert position.return_pct == pytest.approx((0.70 - 0.60) / 0.60)
    assert summary["forward_data"]["generic_observed_price_fallback_used"] is False


def test_watch_and_shared_gate_demoted_rows_never_create_positions(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    demoted = candidate(
        market_id="m-demoted",
        expected_edge="0.025",
        spread="0.02",
    )
    rows = [candidate(), watch_candidate(), demoted]
    write_candidates(candidate_path, rows)

    summary, positions, _ = validator.validate(args(tmp_path, candidate_path))

    assert [position.market_id for position in positions] == ["m1"]
    transitions = summary["reconciliation"]["discovery_to_shared_gate_transitions"]
    assert transitions["shadow_entry->eligible_shadow_entry"] == 1
    assert transitions["watch_only->watch_only"] == 1
    assert transitions["shadow_entry->watch_only"] == 1


def test_persisted_fresh_entry_can_be_evaluated_after_horizon(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    output_dir = tmp_path / "crypto_shadow"
    row = candidate()
    write_candidates(candidate_path, [row])
    prepare_args = args(
        tmp_path,
        candidate_path,
        evaluation_time="2026-08-04T10:30:00",
        max_entry_age_minutes=60,
    )

    assert validator.run(prepare_args) == 0

    write_observations(
        output_dir / "forward_observations.jsonl",
        [observation(row, timestamp="2026-08-04T14:02:00", yes_best_bid=0.50)],
    )
    review_args = args(
        tmp_path,
        candidate_path,
        evaluation_time="2026-08-04T14:30:00",
        max_entry_age_minutes=60,
    )
    summary, positions, diagnostics = validator.validate(review_args)

    assert positions[0].status == "closed"
    assert positions[0].persisted_entry_record_reused is True
    assert diagnostics[0]["persisted_entry_record_reused"] is True
    assert summary["reconciliation"]["persisted_entry_records_reused"] == 1
    assert positions[0].holding_minutes == pytest.approx(240.0)


def test_persisted_entry_cannot_bypass_server_orderbook_freshness(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    output_dir = tmp_path / "crypto_shadow"
    row = candidate()
    write_candidates(candidate_path, [row])
    prepare_args = args(
        tmp_path,
        candidate_path,
        evaluation_time="2026-08-04T10:30:00",
        max_entry_age_minutes=60,
    )
    assert validator.run(prepare_args) == 0

    stale_source_row = candidate(yes_orderbook_timestamp="2026-08-04T08:00:00")
    write_candidates(candidate_path, [stale_source_row])
    review_args = args(
        tmp_path,
        candidate_path,
        evaluation_time="2026-08-04T14:30:00",
        max_entry_age_minutes=60,
    )

    summary, positions, diagnostics = validator.validate(review_args)

    assert positions == []
    # The validator binds server timestamps into the identity, so changing one cannot reuse
    # the prior prepared entry as a freshness bypass.
    assert diagnostics[0]["persisted_entry_record_reused"] is False
    assert "stale_yes_orderbook_snapshot" in diagnostics[0]["position_exclusion_reasons"]
    assert summary["reconciliation"]["positions_created"] == 0
    assert (output_dir / "shadow_trades.csv").exists()


@pytest.mark.parametrize(
    ("observation_overrides", "reason"),
    [
        ({"no_best_bid": None}, "missing_or_invalid_forward_no_best_bid"),
        (
            {"no_best_bid": 0.60, "no_best_ask": 0.50},
            "crossed_forward_no_orderbook",
        ),
        (
            {"no_best_ask_size": 0},
            "missing_or_invalid_forward_no_best_ask_size",
        ),
    ],
)
def test_forward_opposite_book_requires_complete_non_crossed_quotes_and_sizes(
    tmp_path: Path,
    observation_overrides: dict,
    reason: str,
):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    row = candidate()
    write_candidates(candidate_path, [row])
    write_observations(forward_path, [observation(row, **observation_overrides)])

    summary, positions, _ = validator.validate(
        args(tmp_path, candidate_path, forward_path=forward_path)
    )

    assert positions[0].status == "insufficient_forward_data"
    assert positions[0].pnl is None
    assert summary["forward_data"]["observation_rejection_reasons"] == {reason: 1}


def test_correlated_positions_do_not_satisfy_independent_cluster_gate(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    forward_path = tmp_path / "forward.jsonl"
    first = candidate()
    second = candidate(
        market_id="m2",
        question="Will BTC be below $80k?",
        threshold_price="80000",
        direction="below",
        barrier_direction="down",
        yes_token_id="yes2",
        no_token_id="no2",
        timestamp="2026-08-04T10:03:00",
    )
    write_candidates(candidate_path, [first, second])
    write_observations(
        forward_path,
        [observation(first), observation(second, timestamp="2026-08-04T14:03:00")],
    )

    parsed = args(
        tmp_path,
        candidate_path,
        forward_path=forward_path,
        min_sample_size=2,
        min_independent_clusters=2,
    )
    summary, positions, _ = validator.validate(parsed)

    assert len(positions) == 2
    assert len({position.entry_epoch for position in positions}) == 2
    assert len({position.cluster_id for position in positions}) == 1
    assert summary["cluster_policy"] == validator.CLUSTER_POLICY
    assert summary["performance"]["closed_positions"] == 2
    assert summary["performance"]["closed_position_cluster_count"] == 1
    assert summary["validation"]["status"] == "insufficient_independent_clusters"
    assert summary["validation"]["positive_expectancy_observed"] is False


def test_dry_run_does_not_write_files(tmp_path: Path, capsys):
    candidate_path = tmp_path / "candidates.csv"
    output_dir = tmp_path / "does-not-exist"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path, output_dir=output_dir, dry_run=True)

    assert validator.run(parsed) == 0

    assert not output_dir.exists()
    assert "DRY RUN" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"max_entry_age_minutes": 0}, "must be positive"),
        ({"max_entry_age_minutes": float("nan")}, "positive and finite"),
        ({"min_forward_horizon_minutes": 239}, "at least 240"),
        ({"min_forward_horizon_minutes": float("inf")}, "finite and at least 240"),
        ({"max_clock_skew_seconds": -0.001}, "finite non-negative"),
        ({"max_clock_skew_seconds": 5.001}, "must not exceed 5 seconds"),
        ({"future_tolerance_minutes": 0.084}, "five-second clock-skew cap"),
        ({"notional": 0}, "must be positive"),
        ({"notional": float("nan")}, "positive and finite"),
        ({"fee_bps": -1}, "must be non-negative"),
        ({"fee_bps": float("inf")}, "non-negative and finite"),
        ({"slippage_bps": -1}, "must be non-negative"),
        ({"slippage_bps": float("nan")}, "non-negative and finite"),
        ({"max_spread": float("inf")}, "finite and positive"),
        ({"legacy_min_expected_edge": float("nan")}, "must be finite"),
        ({"min_sample_size": 0}, "must be positive"),
        ({"min_independent_clusters": 0}, "must be positive"),
    ],
)
def test_numeric_safety_configuration_fails_fast(
    tmp_path: Path,
    override: dict,
    message: str,
):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path, **override)

    with pytest.raises(ValueError, match=message):
        validator.validate(parsed)


def test_missing_candidate_file_fails_fast(tmp_path: Path):
    parsed = args(tmp_path, tmp_path / "missing-candidates.csv")

    with pytest.raises(FileNotFoundError, match="candidate_file not found"):
        validator.validate(parsed)


def test_missing_avoid_file_fails_fast(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path, avoid_file=tmp_path / "missing-avoid.csv")

    with pytest.raises(FileNotFoundError, match="avoid_file not found"):
        validator.validate(parsed)


def test_legacy_shadow_output_directory_is_protected(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path, output_dir=REPO_ROOT / "runs" / "shadow")

    with pytest.raises(ValueError, match="isolated Step 12 directory"):
        validator.validate(parsed)


def test_written_insufficient_position_has_blank_pnl_and_tiny_live_no(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path)

    assert validator.run(parsed) == 0

    output_dir = Path(parsed.output_dir)
    summary = json.loads((output_dir / "crypto_threshold_shadow_pnl_summary.json").read_text())
    with (output_dir / "shadow_trades.csv").open(newline="") as handle:
        trade = next(csv.DictReader(handle))
    with (output_dir / "crypto_threshold_shadow_validation.csv").open(newline="") as handle:
        validation_row = next(csv.DictReader(handle))
    with (output_dir / "crypto_threshold_candidate_reconciliation.csv").open(newline="") as handle:
        reconciliation_row = next(csv.DictReader(handle))
    assert trade["status"] == "insufficient_forward_data"
    assert trade["exit_price"] == ""
    assert trade["pnl"] == ""
    assert summary["tiny_live_recommendation"] == "NO"
    assert summary["schema_version"] == "crypto_threshold_shadow_pnl_v7"
    assert summary["inputs"]["max_clock_skew_seconds"] == pytest.approx(5.0)
    assert summary["validation"]["supports_tiny_live"] is False
    assert validation_row["resolution_source"] == "https://www.coinbase.com/price/bitcoin"
    assert validation_row["resolution_rules_sha256"] == validator.resolution_rules_sha256(
        RESOLUTION_RULES
    )
    for field in [
        "resolution_source_origin",
        "resolution_source_locator",
        "resolution_source_adapter_version",
        "resolution_source_provenance_sha256",
    ]:
        assert validation_row[field] == candidate()[field]
        assert reconciliation_row[field] == candidate()[field]
    assert float(validation_row["entry_yes_best_ask_size"]) == pytest.approx(100.0)
    assert float(validation_row["entry_share_quantity"]) == pytest.approx(2.5)
    assert float(validation_row["notional"]) == pytest.approx(1.0)
    provenance = summary["artifact_provenance"]
    assert provenance["output_namespace"] == "crypto_threshold_shadow_step12"
    assert provenance["candidate_file_sha256"]
    assert provenance["avoid_file_sha256"]
    assert provenance["legacy_shadow_dir_protected"].endswith("runs/shadow")
    assert provenance["prepared_shadow_trades_input_sha256"] == ""
    assert provenance["prepared_shadow_trades_sha256"] == ""
    assert provenance["shadow_trades_output_sha256"] == file_sha256(
        output_dir / "shadow_trades.csv"
    )
    report = (output_dir / "crypto_threshold_shadow_pnl_report.md").read_text()
    assert "tiny_live_recommendation: NO" in report
    assert '- Insufficient reason distribution: {"missing_forward_observation": 1}' in report


def test_prepared_input_and_final_output_hashes_are_separately_verifiable(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path)
    output_dir = Path(parsed.output_dir)
    output_dir.mkdir(parents=True)
    prepared_path = output_dir / "shadow_trades.csv"
    prepared_path.write_text("legacy_prepared_input\n")
    prepared_hash = file_sha256(prepared_path)

    assert validator.run(parsed) == 0

    final_hash = file_sha256(prepared_path)
    summary = json.loads((output_dir / "crypto_threshold_shadow_pnl_summary.json").read_text())
    provenance = summary["artifact_provenance"]
    assert provenance["prepared_shadow_trades_input_sha256"] == prepared_hash
    assert provenance["prepared_shadow_trades_sha256"] == prepared_hash
    assert provenance["prepared_shadow_trades_sha256_semantics"] == (
        "legacy_alias_of_prepared_shadow_trades_input_sha256"
    )
    assert provenance["shadow_trades_output_sha256"] == final_hash
    assert provenance["shadow_trades_output_path"] == str(prepared_path.resolve())
    assert final_hash != prepared_hash
    snapshot_path = Path(provenance["prepared_shadow_trades_input_snapshot_path"])
    assert snapshot_path.name == f"shadow_trades_{prepared_hash}.csv"
    assert snapshot_path.read_bytes() == b"legacy_prepared_input\n"
    assert provenance["prepared_shadow_trades_input_snapshot_sha256"] == prepared_hash
    assert (
        "Immutable prepared-input snapshot"
        in (output_dir / "crypto_threshold_shadow_pnl_report.md").read_text()
    )

    prepared_path.write_bytes(b"legacy_prepared_input\n")
    assert validator.run(parsed) == 0
    repeated_summary = json.loads(
        (output_dir / "crypto_threshold_shadow_pnl_summary.json").read_text()
    )
    assert repeated_summary["artifact_provenance"][
        "prepared_shadow_trades_input_snapshot_path"
    ] == str(snapshot_path.resolve())
    assert snapshot_path.read_bytes() == b"legacy_prepared_input\n"


def test_prepared_input_snapshot_is_not_overwritten_on_hash_conflict(tmp_path: Path):
    candidate_path = tmp_path / "candidates.csv"
    write_candidates(candidate_path, [candidate()])
    parsed = args(tmp_path, candidate_path)
    output_dir = Path(parsed.output_dir)
    output_dir.mkdir(parents=True)
    prepared_path = output_dir / "shadow_trades.csv"
    original_input = b"legacy_prepared_input\n"
    prepared_path.write_bytes(original_input)

    assert validator.run(parsed) == 0
    summary = json.loads((output_dir / "crypto_threshold_shadow_pnl_summary.json").read_text())
    snapshot_path = Path(
        summary["artifact_provenance"]["prepared_shadow_trades_input_snapshot_path"]
    )
    snapshot_path.write_bytes(b"tampered_snapshot\n")
    prepared_path.write_bytes(original_input)

    with pytest.raises(RuntimeError, match="snapshot conflicts"):
        validator.run(parsed)
    assert snapshot_path.read_bytes() == b"tampered_snapshot\n"


def test_no_forbidden_live_auth_llm_or_network_imports():
    source_path = REPO_ROOT / "scripts" / "validate_crypto_threshold_shadow_pnl.py"
    tree = ast.parse(source_path.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        "polysignal.execution.live_trader_stub",
        "polysignal.execution.paper_trader",
        "polysignal.ingestion.clob_client",
        "polysignal.llm.provider",
        "httpx",
        "requests",
    }
    assert not (imported & forbidden)
    assert validator.TINY_LIVE_RECOMMENDATION == "NO"
