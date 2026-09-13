import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

import polysignal.shadow.historical_barrier_provenance as provenance
from polysignal.shadow.expiry_provenance import resolve_expiry_provenance
from polysignal.shadow.gamma_raw_snapshot import canonical_json_bytes
from polysignal.shadow.historical_barrier_provenance import (
    BINANCE_INTERVAL_MS,
    HISTORICAL_BARRIER_STATUS_VERIFIED,
    BinanceHistoricalKlineClient,
    BinanceKlineFetchResult,
    BinanceKlinePageAudit,
    HistoricalArtifactConflictError,
    RuleObservationWindow,
    evaluate_historical_barrier,
    historical_evidence_candidate_fields,
    historical_evidence_integrity_reasons,
    merge_kline_fetch_results,
    not_required_historical_evidence,
    parse_binance_kline,
    parse_rule_observation_window,
    persist_historical_candle_snapshot,
    prepare_historical_candle_audit,
)

ET_RULES = (
    "This market resolves Yes if any Binance 1 minute candle for Bitcoin (BTC/USDT) "
    "between November 24, 2025, 14:00 and December 31, 2026, 23:59 in the ET "
    "timezone has a final High price equal to or greater than the title threshold."
)
ET_EXPIRY = "2027-01-01T04:59:00Z"
START = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
ENTRY = START + timedelta(minutes=3, seconds=30)
UTC_RULES = (
    "This market resolves Yes if any Binance 1 minute candle for Bitcoin (BTC/USDT) "
    "between August 4, 2026, 12:00 and August 4, 2026, 23:59 in the UTC timezone "
    "has a final High price equal to or greater than the title threshold."
)
UTC_EXPIRY = "2026-08-04T23:59:00Z"


def raw_kline(
    open_time_ms: int,
    *,
    open_price: str = "100",
    high_price: str = "101",
    low_price: str = "99",
    close_price: str = "100.5",
) -> list:
    return [
        open_time_ms,
        open_price,
        high_price,
        low_price,
        close_price,
        "1.0",
        open_time_ms + BINANCE_INTERVAL_MS - 1,
        "100.0",
        12,
        "0.5",
        "50.0",
        "0",
    ]


def kline_transport(
    *,
    skip_open_ms: int | None = None,
    duplicate_first: bool = False,
    reverse_rows: bool = False,
    malformed: bool = False,
    retry_status: int | None = None,
    timeout_once: bool = False,
    server_time_ms: int | None = None,
) -> tuple[httpx.MockTransport, dict[str, int]]:
    state = {"kline_calls": 0, "time_calls": 0}
    observed_server_time = server_time_ms or int((ENTRY + timedelta(seconds=10)).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time":
            state["time_calls"] += 1
            return httpx.Response(200, json={"serverTime": observed_server_time})
        assert request.url.path == "/api/v3/klines"
        state["kline_calls"] += 1
        if timeout_once and state["kline_calls"] == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        if retry_status and state["kline_calls"] == 1:
            return httpx.Response(retry_status, json={"code": -1})
        start_ms = int(request.url.params["startTime"])
        end_ms = int(request.url.params["endTime"])
        rows = [
            raw_kline(open_ms)
            for open_ms in range(start_ms, end_ms + 1, BINANCE_INTERVAL_MS)
            if open_ms != skip_open_ms
        ]
        if duplicate_first and rows:
            rows.insert(1, list(rows[0]))
        if reverse_rows:
            rows.reverse()
        if malformed and rows:
            rows[0] = rows[0][:-1]
        return httpx.Response(200, json=rows)

    return httpx.MockTransport(handler), state


def fetch_with_transport(
    transport: httpx.MockTransport,
    *,
    end: datetime = ENTRY,
    page_limit: int = 2,
    max_retries: int = 2,
) -> BinanceKlineFetchResult:
    client = BinanceHistoricalKlineClient(
        transport=transport,
        page_limit=page_limit,
        max_retries=max_retries,
        retry_backoff_seconds=0,
        max_concurrency=1,
    )
    return asyncio.run(client.fetch_klines(symbol="BTCUSDT", start_time=START, end_time=end))


def test_rule_window_parses_explicit_et_start_and_expiry():
    window = parse_rule_observation_window(ET_RULES, ET_EXPIRY)

    assert window.status == "verified"
    assert window.start_time == "2025-11-24T19:00:00Z"
    assert window.end_time == ET_EXPIRY
    assert window.timezone == "America/New_York"
    assert len(window.rules_sha256) == 64
    assert len(window.provenance_sha256) == 64


def test_rule_window_supports_explicit_utc_ampm():
    rules = (
        "Observed between August 4, 2026, 12:00 PM and August 4, 2026, 1:00 PM "
        "in the UTC timezone using one-minute candles."
    )

    window = parse_rule_observation_window(rules, "2026-08-04T13:00:00Z")

    assert window.status == "verified"
    assert window.start_time == "2026-08-04T12:00:00Z"
    assert window.end_time == "2026-08-04T13:00:00Z"


def test_rule_window_never_substitutes_gamma_start_date():
    rules_without_start = (
        "Any Binance 1 minute candle High before 11:59PM ET on the title date resolves Yes."
    )

    window = parse_rule_observation_window(rules_without_start, ET_EXPIRY)

    assert window.status == "missing_explicit_rule_start_time"
    assert window.start_time == ""


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (ET_RULES + " Times are also reported in UTC.", "conflicting_rule_window_timezone"),
        (ET_RULES + " " + ET_RULES, "conflicting_explicit_rule_windows"),
        (
            ET_RULES.replace("November 24, 2025", "November 24, 2027"),
            "invalid_explicit_rule_window_range",
        ),
    ],
)
def test_rule_window_conflicts_fail_closed(rules: str, expected: str):
    assert parse_rule_observation_window(rules, ET_EXPIRY).status == expected


def test_rule_window_expiry_mismatch_fails_closed():
    window = parse_rule_observation_window(ET_RULES, "2027-01-01T05:00:00Z")

    assert window.status == "rule_window_expiry_mismatch"


def test_binance_kline_parser_validates_shape_interval_and_ohlc():
    open_ms = int(START.timestamp() * 1000)
    candle, error = parse_binance_kline(raw_kline(open_ms))
    assert error == ""
    assert candle is not None
    assert candle.open_time_ms == open_ms

    assert parse_binance_kline(raw_kline(open_ms)[:-1])[1] == "invalid_kline_row_shape"
    bad_interval = raw_kline(open_ms)
    bad_interval[6] += 1
    assert parse_binance_kline(bad_interval)[1] == "invalid_kline_interval"
    assert (
        parse_binance_kline(raw_kline(open_ms, high_price="98"))[1] == "invalid_kline_ohlc_bounds"
    )


def test_kline_client_fetches_complete_fixed_pages():
    transport, state = kline_transport()

    result = fetch_with_transport(transport)

    assert result.status == "complete"
    assert len(result.pages) == 2
    assert len(result.candles) == 4
    assert result.missing_ranges == ()
    assert state == {"kline_calls": 2, "time_calls": 2}
    assert [page.expected_candle_count for page in result.pages] == [2, 2]


def test_kline_client_reports_exact_missing_range():
    missing_open = int((START + timedelta(minutes=1)).timestamp() * 1000)
    transport, _ = kline_transport(skip_open_ms=missing_open)

    result = fetch_with_transport(transport)

    assert result.status == "partial_coverage"
    assert result.missing_ranges == ("2026-08-04T12:01:00Z/2026-08-04T12:02:00Z",)


@pytest.mark.parametrize(
    ("transport_options", "expected_error"),
    [
        ({"duplicate_first": True}, "duplicate_klines"),
        ({"reverse_rows": True}, "non_monotonic_klines"),
        ({"malformed": True}, "invalid_kline_row_shape"),
    ],
)
def test_kline_client_rejects_bad_rows(transport_options: dict, expected_error: str):
    transport, _ = kline_transport(**transport_options)

    result = fetch_with_transport(transport)

    assert result.status == expected_error
    assert any(page.error == expected_error for page in result.pages)


@pytest.mark.parametrize(
    "retry_options", [{"retry_status": 429}, {"retry_status": 503}, {"timeout_once": True}]
)
def test_kline_client_retries_transient_failures(retry_options: dict):
    transport, state = kline_transport(**retry_options)

    result = fetch_with_transport(transport, page_limit=1000)

    assert result.status == "complete"
    assert result.pages[0].attempts == 2
    assert state["kline_calls"] == 2


def test_kline_client_exhausted_http_error_is_explicit():
    transport, _ = kline_transport(retry_status=429)

    result = fetch_with_transport(transport, page_limit=1000, max_retries=0)

    assert result.status == "binance_http_429"
    assert result.pages[0].error == "binance_http_429"


def test_kline_client_rejects_entry_after_server_time():
    server_time = int((ENTRY - timedelta(milliseconds=1)).timestamp() * 1000)
    transport, _ = kline_transport(server_time_ms=server_time)

    result = fetch_with_transport(transport)

    assert result.status == "entry_after_binance_server_time"


def manual_window() -> RuleObservationWindow:
    window = parse_rule_observation_window(UTC_RULES, UTC_EXPIRY)
    assert window.status == "verified"
    return window


def manual_fetch(*, high: str = "101", low: str = "99", status: str = "complete"):
    candles = []
    for minute in range(3):
        parsed, error = parse_binance_kline(
            raw_kline(
                int((START + timedelta(minutes=minute)).timestamp() * 1000),
                high_price=high,
                low_price=low,
            )
        )
        assert error == ""
        assert parsed is not None
        candles.append(parsed)
    return BinanceKlineFetchResult(
        status=status,
        symbol="BTCUSDT",
        start_time="2026-08-04T12:00:00Z",
        end_time="2026-08-04T12:03:00Z",
        server_time_before="2026-08-04T12:02:59Z",
        server_time_after="2026-08-04T12:03:01Z",
        pages=(
            BinanceKlinePageAudit(
                sequence=1,
                requested_start_ms=int(START.timestamp() * 1000),
                requested_end_ms=int((START + timedelta(minutes=3)).timestamp() * 1000),
                expected_candle_count=3,
                received_candle_count=3,
                attempts=1,
                status="complete",
            ),
        ),
        candles=tuple(candles),
        missing_ranges=() if status == "complete" else ("missing",),
    )


def test_preload_and_fresh_tail_merge_replaces_overlap():
    base = manual_fetch(high="101")
    tail_candles = []
    for minute in (2, 3):
        parsed, error = parse_binance_kline(
            raw_kline(
                int((START + timedelta(minutes=minute)).timestamp() * 1000),
                high_price="101" if minute == 2 else "105",
            )
        )
        assert error == ""
        assert parsed is not None
        tail_candles.append(parsed)
    tail = BinanceKlineFetchResult(
        status="complete",
        symbol="BTCUSDT",
        start_time="2026-08-04T12:02:00Z",
        end_time="2026-08-04T12:04:00Z",
        server_time_before="2026-08-04T12:03:59Z",
        server_time_after="2026-08-04T12:04:01Z",
        pages=(
            BinanceKlinePageAudit(
                sequence=1,
                requested_start_ms=int((START + timedelta(minutes=2)).timestamp() * 1000),
                requested_end_ms=int((START + timedelta(minutes=4)).timestamp() * 1000),
                expected_candle_count=2,
                received_candle_count=2,
                attempts=1,
                status="complete",
            ),
        ),
        candles=tuple(tail_candles),
    )

    merged = merge_kline_fetch_results(
        base,
        tail,
        start_time=START,
        end_time=START + timedelta(minutes=4),
    )

    assert merged.status == "complete"
    assert len(merged.candles) == 4
    assert merged.candles[2].high_price == "101"
    assert merged.candles[3].high_price == "105"


def test_preload_merge_rejects_overlap_conflict_and_entry_second_tail():
    base = manual_fetch()
    conflicting = base.model_copy(
        update={
            "start_time": "2026-08-04T12:02:00Z",
            "candles": (base.candles[2].model_copy(update={"high_price": "105"}),),
        }
    )

    conflict = merge_kline_fetch_results(
        base,
        conflicting,
        start_time=START,
        end_time=START + timedelta(minutes=3),
    )
    nonaligned = merge_kline_fetch_results(
        base,
        base,
        start_time=START,
        end_time=START + timedelta(minutes=3, seconds=30),
    )

    assert conflict.status == "merged_kline_overlap_conflict"
    assert nonaligned.status == "historical_barrier_entry_not_minute_aligned"


def evaluate(
    tmp_path: Path,
    *,
    direction: str = "up",
    threshold: str = "102",
    fetch: BinanceKlineFetchResult | None = None,
    manifest: dict | None = None,
):
    return evaluate_historical_barrier(
        asset="BTC",
        barrier_direction=direction,
        threshold_price=Decimal(threshold),
        entry_time=START + timedelta(minutes=3),
        window=manual_window(),
        fetch_result=fetch or manual_fetch(),
        output_dir=tmp_path,
        resolution_rules=UTC_RULES,
        manifest=manifest,
    )


def verified_row(evidence, **overrides):
    row = {
        "contract_kind": "touch_before_expiry",
        "asset": "BTC",
        "barrier_direction": "up",
        "threshold_price": "102",
        "entry_time": "2026-08-04T12:03:00Z",
        "expiry_time": UTC_EXPIRY,
        "resolution_rules": UTC_RULES,
        "resolution_rules_sha256": manual_window().rules_sha256,
        **historical_evidence_candidate_fields(evidence),
    }
    row.update(overrides)
    return row


def write_payload(directory: Path, prefix: str, payload: dict) -> tuple[Path, str]:
    content = canonical_json_bytes(payload)
    digest = hashlib.sha256(content).hexdigest()
    path = directory / f"{prefix}_{digest}.json"
    path.write_bytes(content)
    return path, digest


def load_payload(path: str) -> dict:
    return json.loads(Path(path).read_bytes())


def lifecycle_manifest() -> dict:
    provenance = resolve_expiry_provenance(
        {
            "endDate": "2026-08-05T00:00:00Z",
            "updatedAt": "2026-08-04T11:59:00Z",
            "$schema": "gamma-market-v1",
            "version": "v1",
        },
        "2026-08-04T23:59:00",
        UTC_RULES,
    )
    assert provenance.status == "verified"
    return {
        "resolution_rules": UTC_RULES,
        "expiry_time": provenance.expiry_time,
        "expiry_local_time": provenance.expiry_local_time,
        "expiry_timezone": provenance.expiry_timezone,
        "expiry_time_origin": provenance.expiry_time_origin,
        "expiry_time_adapter_version": provenance.expiry_time_adapter_version,
        "expiry_time_provenance_sha256": provenance.expiry_time_provenance_sha256,
        "expiry_status": provenance.status,
        "gamma_start_date": "2026-08-04T11:00:00Z",
        "gamma_end_date": provenance.gamma_end_date,
        "gamma_market_updated_at": provenance.gamma_market_updated_at,
        "gamma_market_schema": provenance.gamma_market_schema,
        "gamma_market_version": provenance.gamma_market_version,
    }


def test_verified_evidence_persists_hashes_and_passes_offline_integrity(tmp_path: Path):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence)

    assert evidence.status == HISTORICAL_BARRIER_STATUS_VERIFIED
    assert evidence.candle_count == 3
    assert hashlib.sha256(Path(evidence.evidence_path).read_bytes()).hexdigest() == evidence.sha256
    assert (
        hashlib.sha256(Path(evidence.candle_snapshot_path).read_bytes()).hexdigest()
        == evidence.candle_snapshot_sha256
    )
    assert historical_evidence_integrity_reasons(row) == []


@pytest.mark.parametrize(
    ("direction", "threshold", "high", "low"),
    [
        ("up", "101", "101", "99"),
        ("down", "99", "101", "99"),
    ],
)
def test_high_low_boundary_touch_is_already_crossed(
    tmp_path: Path,
    direction: str,
    threshold: str,
    high: str,
    low: str,
):
    evidence = evaluate(
        tmp_path,
        direction=direction,
        threshold=threshold,
        fetch=manual_fetch(high=high, low=low),
    )

    assert evidence.status == "barrier_already_crossed"
    assert evidence.barrier_crossed_at == "2026-08-04T12:00:00Z"


def test_partial_fetch_cannot_be_verified(tmp_path: Path):
    evidence = evaluate(tmp_path, fetch=manual_fetch(status="partial_coverage"))

    assert evidence.status == "partial_coverage"
    assert evidence.missing_ranges == ("missing",)


def test_shared_candle_snapshot_is_serialized_once_for_multiple_thresholds(
    tmp_path: Path,
    monkeypatch,
):
    fetch = manual_fetch()
    candle_serializations = 0
    structural_audits = 0
    canonical = provenance.canonical_json_bytes
    recompute = provenance._recompute_candles

    def counting_canonical_json_bytes(payload):
        nonlocal candle_serializations
        if isinstance(payload, dict) and "candles" in payload:
            candle_serializations += 1
        return canonical(payload)

    monkeypatch.setattr(provenance, "canonical_json_bytes", counting_canonical_json_bytes)

    def counting_recompute(*args, **kwargs):
        nonlocal structural_audits
        structural_audits += 1
        return recompute(*args, **kwargs)

    monkeypatch.setattr(provenance, "_recompute_candles", counting_recompute)
    snapshot = persist_historical_candle_snapshot(fetch, tmp_path)
    audit = prepare_historical_candle_audit(
        fetch,
        start_time=START,
        entry_time=START + timedelta(minutes=3),
    )
    first = evaluate_historical_barrier(
        asset="BTC",
        barrier_direction="up",
        threshold_price="102",
        entry_time=START + timedelta(minutes=3),
        window=manual_window(),
        fetch_result=fetch,
        output_dir=tmp_path,
        resolution_rules=UTC_RULES,
        candle_snapshot=snapshot,
        candle_audit=audit,
    )
    second = evaluate_historical_barrier(
        asset="BTC",
        barrier_direction="up",
        threshold_price="103",
        entry_time=START + timedelta(minutes=3),
        window=manual_window(),
        fetch_result=fetch,
        output_dir=tmp_path,
        resolution_rules=UTC_RULES,
        candle_snapshot=snapshot,
        candle_audit=audit,
    )

    assert candle_serializations == 1
    assert structural_audits == 1
    assert first.candle_snapshot_path == second.candle_snapshot_path
    assert first.candle_snapshot_sha256 == second.candle_snapshot_sha256
    assert first.evidence_path != second.evidence_path


def test_tampered_evidence_is_detected_and_cannot_be_overwritten(tmp_path: Path):
    evidence = evaluate(tmp_path)
    evidence_path = Path(evidence.evidence_path)
    evidence_path.write_bytes(b"tampered")
    row = verified_row(evidence)

    assert "historical_barrier_evidence_artifact_mismatch" in historical_evidence_integrity_reasons(
        row
    )
    with pytest.raises(HistoricalArtifactConflictError, match="conflicts"):
        evaluate(tmp_path)
    assert evidence_path.read_bytes() == b"tampered"


def test_candidate_field_tampering_breaks_artifact_binding(tmp_path: Path):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence, threshold_price="103")

    reasons = historical_evidence_integrity_reasons(row)

    assert "historical_barrier_evidence_threshold_mismatch" in reasons


def test_full_rules_expiry_and_gamma_manifest_is_bound_offline(tmp_path: Path):
    manifest = lifecycle_manifest()
    evidence = evaluate(tmp_path, manifest=manifest)
    row = verified_row(evidence, **manifest)

    assert historical_evidence_integrity_reasons(row, artifact_root=tmp_path) == []

    for field, tampered in (
        ("gamma_start_date", "2026-08-04T12:01:00Z"),
        ("gamma_end_date", "2026-08-05T00:10:00Z"),
        ("gamma_market_updated_at", "2026-08-04T12:00:00Z"),
        ("gamma_market_schema", "tampered"),
        ("gamma_market_version", "v2"),
        ("expiry_time_provenance_sha256", "0" * 64),
    ):
        tampered_row = dict(row)
        tampered_row[field] = tampered
        reasons = historical_evidence_integrity_reasons(
            tampered_row,
            artifact_root=tmp_path,
        )
        assert "historical_barrier_manifest_provenance_mismatch" in reasons


@pytest.mark.parametrize(
    ("field", "tampered", "expected"),
    [
        ("resolution_rules", UTC_RULES + " Tampered.", "resolution_rules_sha256_mismatch"),
        (
            "historical_barrier_evidence_start_time",
            "2026-08-04T12:01:00Z",
            "historical_barrier_evidence_start_mismatch",
        ),
        (
            "expiry_time",
            "2026-08-05T00:00:00Z",
            "rule_window_expiry_mismatch",
        ),
    ],
)
def test_rules_start_and_expiry_tampering_is_recomputed(
    tmp_path: Path,
    field: str,
    tampered: str,
    expected: str,
):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence)
    row[field] = tampered

    assert expected in historical_evidence_integrity_reasons(row, artifact_root=tmp_path)


def test_gamma_start_never_substitutes_for_missing_rule_start(tmp_path: Path):
    evidence = evaluate(tmp_path)
    rules_without_start = (
        "A Binance 1 minute High at or before 23:59 UTC on August 4, 2026 resolves Yes."
    )
    row = verified_row(
        evidence,
        resolution_rules=rules_without_start,
        resolution_rules_sha256=hashlib.sha256(rules_without_start.encode()).hexdigest(),
        gamma_start_date="2026-08-04T12:00:00Z",
    )

    reasons = historical_evidence_integrity_reasons(row, artifact_root=tmp_path)

    assert "missing_explicit_rule_start_time" in reasons


@pytest.mark.parametrize(
    ("field", "tampered", "candidate_field", "expected"),
    [
        (
            "expected_candle_count",
            4,
            "historical_barrier_expected_candle_count",
            "historical_barrier_evidence_expected_count_mismatch",
        ),
        (
            "candle_count",
            4,
            "historical_barrier_evidence_candle_count",
            "historical_barrier_evidence_candle_count_mismatch",
        ),
        (
            "min_low_price",
            "98",
            "historical_barrier_min_low_price",
            "historical_barrier_evidence_min_low_mismatch",
        ),
        (
            "max_high_price",
            "102",
            "historical_barrier_max_high_price",
            "historical_barrier_evidence_max_high_mismatch",
        ),
        (
            "tail_coverage_status",
            "claimed_complete",
            "historical_barrier_tail_coverage_status",
            "historical_barrier_evidence_tail_coverage_mismatch",
        ),
        (
            "tail_covered_through",
            "2026-08-04T12:04:00Z",
            "historical_barrier_tail_covered_through",
            "historical_barrier_evidence_tail_coverage_mismatch",
        ),
        (
            "first_touch_at",
            "2026-08-04T12:01:00Z",
            "historical_barrier_first_touch_at",
            "historical_barrier_evidence_first_touch_mismatch",
        ),
    ],
)
def test_evidence_self_reports_are_independently_recomputed(
    tmp_path: Path,
    field: str,
    tampered: object,
    candidate_field: str,
    expected: str,
):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence)
    payload = load_payload(evidence.evidence_path)
    payload[field] = tampered
    path, digest = write_payload(Path(evidence.evidence_path).parent, "evidence", payload)
    row["historical_barrier_evidence_path"] = str(path)
    row["historical_barrier_evidence_sha256"] = digest
    row[candidate_field] = tampered

    assert expected in historical_evidence_integrity_reasons(row, artifact_root=tmp_path)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("symbol", "historical_barrier_candle_snapshot_binding_mismatch"),
        ("interval", "historical_barrier_candle_snapshot_binding_mismatch"),
        ("start", "historical_barrier_candle_snapshot_binding_mismatch"),
        ("end", "historical_barrier_candle_snapshot_binding_mismatch"),
        ("gap", "partial_coverage"),
        ("duplicate", "duplicate_klines"),
        ("reversed", "non_monotonic_klines"),
        ("ohlc", "historical_barrier_candle_snapshot_invalid_kline_ohlc_bounds"),
    ],
)
def test_candle_artifact_contract_is_recomputed_from_raw_rows(
    tmp_path: Path,
    mutation: str,
    expected: str,
):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence)
    payload = load_payload(evidence.candle_snapshot_path)
    if mutation == "symbol":
        payload["symbol"] = "ETHUSDT"
    elif mutation == "interval":
        payload["interval"] = "5m"
    elif mutation == "start":
        payload["start_time"] = "2026-08-04T12:01:00Z"
    elif mutation == "end":
        payload["end_time"] = "2026-08-04T12:04:00Z"
    elif mutation == "gap":
        del payload["candles"][1]
    elif mutation == "duplicate":
        payload["candles"].insert(1, dict(payload["candles"][0]))
    elif mutation == "reversed":
        payload["candles"].reverse()
    else:
        payload["candles"][0]["high_price"] = "98"
    path, digest = write_payload(
        Path(evidence.candle_snapshot_path).parent,
        "binance_1m",
        payload,
    )
    row["historical_barrier_candle_snapshot_path"] = str(path)
    row["historical_barrier_candle_snapshot_sha256"] = digest

    assert expected in historical_evidence_integrity_reasons(row, artifact_root=tmp_path)


def test_candle_mutation_with_recomputed_file_hash_still_detects_touch(tmp_path: Path):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence)
    payload = load_payload(evidence.candle_snapshot_path)
    payload["candles"][1]["high_price"] = "102"
    path, digest = write_payload(
        Path(evidence.candle_snapshot_path).parent,
        "binance_1m",
        payload,
    )
    row["historical_barrier_candle_snapshot_path"] = str(path)
    row["historical_barrier_candle_snapshot_sha256"] = digest

    reasons = historical_evidence_integrity_reasons(row, artifact_root=tmp_path)

    assert "barrier_already_crossed" in reasons
    assert "historical_barrier_evidence_first_touch_mismatch" in reasons


@pytest.mark.parametrize("artifact_kind", ["evidence", "candles"])
def test_artifact_models_reject_unexpected_fields(tmp_path: Path, artifact_kind: str):
    evidence = evaluate(tmp_path)
    row = verified_row(evidence)
    if artifact_kind == "evidence":
        original_path = Path(evidence.evidence_path)
        prefix = "evidence"
        path_field = "historical_barrier_evidence_path"
        digest_field = "historical_barrier_evidence_sha256"
        expected = "invalid_historical_barrier_evidence_artifact"
    else:
        original_path = Path(evidence.candle_snapshot_path)
        prefix = "binance_1m"
        path_field = "historical_barrier_candle_snapshot_path"
        digest_field = "historical_barrier_candle_snapshot_sha256"
        expected = "invalid_historical_barrier_candle_snapshot"
    payload = load_payload(str(original_path))
    payload["unexpected"] = "not allowed"
    path, digest = write_payload(original_path.parent, prefix, payload)
    row[path_field] = str(path)
    row[digest_field] = digest

    assert expected in historical_evidence_integrity_reasons(row, artifact_root=tmp_path)


def test_artifact_paths_cannot_escape_root_or_follow_symlinks(tmp_path: Path):
    evidence = evaluate(tmp_path)
    escaped = verified_row(evidence)
    escaped["historical_barrier_evidence_path"] = str(
        tmp_path / ".." / Path(evidence.evidence_path).name
    )
    assert "historical_barrier_evidence_artifact_path_invalid" in (
        historical_evidence_integrity_reasons(escaped, artifact_root=tmp_path)
    )

    unsafe_root = tmp_path / "unsafe"
    unsafe_root.mkdir()
    (unsafe_root / "historical_barrier_evidence").symlink_to(
        Path(evidence.evidence_path).parent,
        target_is_directory=True,
    )
    (unsafe_root / "historical_barrier_candles").symlink_to(
        Path(evidence.candle_snapshot_path).parent,
        target_is_directory=True,
    )
    symlinked = verified_row(evidence)
    symlinked["historical_barrier_evidence_path"] = str(
        unsafe_root / "historical_barrier_evidence" / Path(evidence.evidence_path).name
    )
    symlinked["historical_barrier_candle_snapshot_path"] = str(
        unsafe_root / "historical_barrier_candles" / Path(evidence.candle_snapshot_path).name
    )
    reasons = historical_evidence_integrity_reasons(
        symlinked,
        artifact_root=unsafe_root,
    )
    assert "historical_barrier_evidence_artifact_path_invalid" in reasons
    assert "historical_barrier_candle_snapshot_path_invalid" in reasons


def test_writer_rejects_existing_symlink_artifact(tmp_path: Path):
    fetch = manual_fetch()
    content = canonical_json_bytes(fetch.model_dump(mode="json"))
    digest = hashlib.sha256(content).hexdigest()
    candle_dir = tmp_path / "historical_barrier_candles"
    candle_dir.mkdir()
    target = tmp_path / "external.json"
    target.write_bytes(content)
    (candle_dir / f"binance_1m_{digest}.json").symlink_to(target)

    with pytest.raises(HistoricalArtifactConflictError, match="unsafe"):
        evaluate(tmp_path, fetch=fetch)


def test_writer_rejects_symlink_parent_before_creating_subdirectories(tmp_path: Path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(HistoricalArtifactConflictError, match="symlink"):
        evaluate(linked)

    assert not (actual / "historical_barrier_candles").exists()


def test_entry_second_tail_cannot_use_unclosed_candle(tmp_path: Path):
    transport, _ = kline_transport()
    fetch = fetch_with_transport(transport, end=ENTRY)

    evidence = evaluate_historical_barrier(
        asset="BTC",
        barrier_direction="up",
        threshold_price=Decimal("102"),
        entry_time=ENTRY,
        window=manual_window(),
        fetch_result=fetch,
        output_dir=tmp_path,
        resolution_rules=UTC_RULES,
    )

    assert evidence.status == "historical_barrier_entry_not_minute_aligned"
    assert evidence.tail_coverage_status == "uncovered_entry_tail"


def test_settlement_contract_requires_not_required_status_only():
    fields = historical_evidence_candidate_fields(not_required_historical_evidence())

    assert (
        historical_evidence_integrity_reasons({"contract_kind": "settlement_threshold", **fields})
        == []
    )
    fields["historical_barrier_evidence_status"] = "verified_full_coverage"
    assert historical_evidence_integrity_reasons(
        {"contract_kind": "settlement_threshold", **fields}
    ) == ["invalid_settlement_historical_barrier_evidence_status"]
