import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysignal.shadow.gamma_raw_snapshot import (
    GAMMA_PUBLIC_REST_ADAPTER_VERSION,
    GAMMA_RAW_SNAPSHOT_SCHEMA_VERSION,
    GammaRawSnapshotRecorder,
    GammaSnapshotConflictError,
    canonical_json_bytes,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _record(recorder: GammaRawSnapshotRecorder, payloads: list[dict]) -> None:
    recorder.record_success(
        kind="page",
        endpoint="https://gamma-api.polymarket.com/markets",
        query={"active": True, "closed": False, "limit": 100, "offset": 0},
        payloads=payloads,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )


def test_raw_snapshot_preserves_nested_payload_and_hashes_exact_bytes(tmp_path: Path):
    payload = {
        "id": 701486,
        "active": True,
        "volume": 123.45,
        "events": [{"id": "event-1", "tags": ["crypto", "threshold"]}],
        "resolutionSource": "",
    }
    recorder = GammaRawSnapshotRecorder(tmp_path)

    _record(recorder, [payload])

    snapshot = recorder.latest_snapshot_for_market("701486")
    assert snapshot is not None
    content = Path(snapshot.snapshot_path).read_bytes()
    assert content == canonical_json_bytes(payload)
    assert hashlib.sha256(content).hexdigest() == snapshot.snapshot_sha256
    assert json.loads(content) == payload


def test_canonical_hash_is_independent_of_object_key_order():
    first = {"id": "m1", "events": [{"b": 2, "a": 1}]}
    second = {"events": [{"a": 1, "b": 2}], "id": "m1"}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_manifest_records_duplicate_ids_requests_and_terminal_error(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)
    _record(recorder, [{"id": "m1", "value": 1}, {"id": "m1", "value": 2}])
    recorder.record_error(
        kind="page",
        endpoint="https://gamma-api.polymarket.com/markets",
        query={"limit": 100, "offset": 100},
        error="422 terminal page",
        started_at=NOW + timedelta(seconds=2),
        completed_at=NOW + timedelta(seconds=3),
    )

    result = recorder.finalize(
        terminal_status="pagination_error",
        created_at=NOW + timedelta(seconds=4),
    )

    manifest_bytes = Path(result.manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    assert result.schema_version == GAMMA_RAW_SNAPSHOT_SCHEMA_VERSION
    assert result.adapter_version == GAMMA_PUBLIC_REST_ADAPTER_VERSION
    assert result.request_count == 2
    assert result.error_count == 1
    assert result.payload_count == 2
    assert result.unique_market_count == 1
    assert result.duplicate_market_id_count == 1
    assert result.manifest_sha256 == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest["requests"][0]["query"] == [
        {"name": "active", "value": True},
        {"name": "closed", "value": False},
        {"name": "limit", "value": 100},
        {"name": "offset", "value": 0},
    ]
    assert manifest["requests"][1]["status"] == "error"
    assert manifest["requests"][1]["error"] == "422 terminal page"
    assert manifest["terminal_status"] == "pagination_error"


def test_snapshot_lookup_matches_exact_duplicate_payload(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)
    first = {"id": "m1", "value": 1}
    second = {"id": "m1", "value": 2}
    _record(recorder, [first, second])

    first_snapshot = recorder.snapshot_for_payload(first)
    second_snapshot = recorder.snapshot_for_payload(second)

    assert first_snapshot is not None
    assert second_snapshot is not None
    assert first_snapshot.snapshot_sha256 != second_snapshot.snapshot_sha256


def test_terminal_empty_request_is_explicit(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)
    request = recorder.record_success(
        kind="search",
        endpoint="https://gamma-api.polymarket.com/markets",
        query={"search": "bitcoin", "limit": 100},
        payloads=[],
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        terminal=True,
    )

    assert request.status == "terminal"
    assert request.payload_count == 0


def test_content_addressed_snapshot_refuses_tampered_existing_file(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)
    payload = {"id": "m1", "events": [{"id": "e1"}]}
    _record(recorder, [payload])
    snapshot = recorder.latest_snapshot_for_market("m1")
    assert snapshot is not None
    path = Path(snapshot.snapshot_path)
    path.write_bytes(b"tampered")

    with pytest.raises(GammaSnapshotConflictError, match="snapshot conflicts"):
        _record(recorder, [payload])

    assert path.read_bytes() == b"tampered"


def test_non_json_and_non_finite_values_are_rejected(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)

    with pytest.raises(ValueError, match="canonical JSON"):
        _record(recorder, [{"id": "m1", "bad": {1, 2}}])
    with pytest.raises(ValueError, match="canonical JSON"):
        _record(recorder, [{"id": "m1", "bad": float("nan")}])


def test_naive_fetch_timestamps_are_rejected(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        recorder.record_success(
            kind="page",
            endpoint="https://gamma-api.polymarket.com/markets",
            query={"limit": 1},
            payloads=[],
            started_at=datetime(2026, 8, 4, 12, 0),
            completed_at=NOW,
        )

    assert list(tmp_path.rglob("*.json")) == []


def test_invalid_later_payload_does_not_write_partial_batch(tmp_path: Path):
    recorder = GammaRawSnapshotRecorder(tmp_path)

    with pytest.raises(ValueError, match="canonical JSON"):
        _record(recorder, [{"id": "valid"}, {"id": "invalid", "bad": {1, 2}}])

    assert list(tmp_path.rglob("*.json")) == []
