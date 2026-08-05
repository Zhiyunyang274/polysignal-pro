"""Immutable raw Gamma snapshots for read-only shadow research."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

GAMMA_RAW_SNAPSHOT_SCHEMA_VERSION = "gamma_raw_snapshot_v1"
GAMMA_PUBLIC_REST_ADAPTER_VERSION = "gamma_public_rest_v1"

JsonScalar = str | int | float | bool | None
RequestKind = Literal["page", "search"]
RequestStatus = Literal["ok", "terminal", "error"]


class GammaSnapshotConflictError(RuntimeError):
    """An existing content-addressed file does not match its digest path."""


class GammaQueryParam(BaseModel):
    """One normalized public Gamma query parameter."""

    model_config = ConfigDict(frozen=True)

    name: str
    value: JsonScalar


class GammaFetchRequest(BaseModel):
    """Auditable result of one public Gamma request."""

    model_config = ConfigDict(frozen=True)

    sequence: int
    kind: RequestKind
    endpoint: str
    query: tuple[GammaQueryParam, ...]
    started_at: str
    completed_at: str
    status: RequestStatus
    payload_count: int
    error: str = ""


class GammaRawPayloadSnapshot(BaseModel):
    """Content-addressed snapshot of one raw market payload occurrence."""

    model_config = ConfigDict(frozen=True)

    request_sequence: int
    payload_index: int
    market_id: str
    fetched_at: str
    snapshot_path: str
    snapshot_sha256: str


class GammaSnapshotManifest(BaseModel):
    """Complete fetch and payload manifest for one isolated discovery run."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = GAMMA_RAW_SNAPSHOT_SCHEMA_VERSION
    adapter_version: str = GAMMA_PUBLIC_REST_ADAPTER_VERSION
    created_at: str
    terminal_status: str
    request_count: int
    error_count: int
    payload_count: int
    unique_market_count: int
    duplicate_market_id_count: int
    requests: tuple[GammaFetchRequest, ...]
    payloads: tuple[GammaRawPayloadSnapshot, ...]


class GammaSnapshotResult(BaseModel):
    """Small summary safe to include in the discovery summary artifact."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = GAMMA_RAW_SNAPSHOT_SCHEMA_VERSION
    adapter_version: str = GAMMA_PUBLIC_REST_ADAPTER_VERSION
    terminal_status: str
    request_count: int
    error_count: int
    payload_count: int
    unique_market_count: int
    duplicate_market_id_count: int
    manifest_path: str
    manifest_sha256: str


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON data deterministically and reject non-JSON values."""

    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not valid canonical JSON data") from exc
    return serialized.encode("utf-8")


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("snapshot timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _query_params(query: Mapping[str, JsonScalar]) -> tuple[GammaQueryParam, ...]:
    return tuple(
        GammaQueryParam(name=str(name), value=value)
        for name, value in sorted(query.items(), key=lambda item: str(item[0]))
    )


def _market_id(payload: Mapping[str, Any]) -> str:
    for field in ("id", "market_id", "conditionId", "condition_id"):
        value = payload.get(field)
        if value is not None and value != "":
            return str(value)
    return ""


def _write_content_addressed(directory: Path, prefix: str, content: bytes) -> tuple[Path, str]:
    digest = bytes_sha256(content)
    path = directory / f"{prefix}_{digest}.json"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        if not path.is_file() or path.read_bytes() != content:
            raise GammaSnapshotConflictError(
                f"content-addressed snapshot conflicts with existing file: {path}"
            ) from exc
    return path, digest


class GammaRawSnapshotRecorder:
    """Record public Gamma requests without mutating or normalizing raw payloads."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self._requests: list[GammaFetchRequest] = []
        self._payloads: list[GammaRawPayloadSnapshot] = []
        self._market_occurrences: Counter[str] = Counter()

    def record_success(
        self,
        *,
        kind: RequestKind,
        endpoint: str,
        query: Mapping[str, JsonScalar],
        payloads: Sequence[Mapping[str, Any]],
        started_at: datetime,
        completed_at: datetime,
        terminal: bool = False,
    ) -> GammaFetchRequest:
        sequence = len(self._requests) + 1
        started = _utc_iso(started_at)
        completed = _utc_iso(completed_at)
        normalized_query = _query_params(query)
        prepared_payloads = [(payload, canonical_json_bytes(dict(payload))) for payload in payloads]
        snapshots: list[GammaRawPayloadSnapshot] = []
        for payload_index, (payload, content) in enumerate(prepared_payloads):
            path, digest = _write_content_addressed(
                self.output_dir / "gamma_raw_markets",
                "market",
                content,
            )
            identifier = _market_id(payload)
            snapshots.append(
                GammaRawPayloadSnapshot(
                    request_sequence=sequence,
                    payload_index=payload_index,
                    market_id=identifier,
                    fetched_at=completed,
                    snapshot_path=str(path.resolve()),
                    snapshot_sha256=digest,
                )
            )
            if identifier:
                self._market_occurrences[identifier] += 1

        request = GammaFetchRequest(
            sequence=sequence,
            kind=kind,
            endpoint=endpoint,
            query=normalized_query,
            started_at=started,
            completed_at=completed,
            status="terminal" if terminal else "ok",
            payload_count=len(snapshots),
        )
        self._requests.append(request)
        self._payloads.extend(snapshots)
        return request

    def record_error(
        self,
        *,
        kind: RequestKind,
        endpoint: str,
        query: Mapping[str, JsonScalar],
        error: str,
        started_at: datetime,
        completed_at: datetime,
    ) -> GammaFetchRequest:
        request = GammaFetchRequest(
            sequence=len(self._requests) + 1,
            kind=kind,
            endpoint=endpoint,
            query=_query_params(query),
            started_at=_utc_iso(started_at),
            completed_at=_utc_iso(completed_at),
            status="error",
            payload_count=0,
            error=str(error),
        )
        self._requests.append(request)
        return request

    def latest_snapshot_for_market(self, market_id: str) -> GammaRawPayloadSnapshot | None:
        for snapshot in reversed(self._payloads):
            if snapshot.market_id == str(market_id):
                return snapshot
        return None

    def snapshot_for_payload(self, payload: Mapping[str, Any]) -> GammaRawPayloadSnapshot | None:
        digest = bytes_sha256(canonical_json_bytes(dict(payload)))
        identifier = _market_id(payload)
        for snapshot in self._payloads:
            if snapshot.snapshot_sha256 == digest and snapshot.market_id == identifier:
                return snapshot
        return None

    def finalize(self, *, terminal_status: str, created_at: datetime) -> GammaSnapshotResult:
        duplicate_count = sum(max(0, count - 1) for count in self._market_occurrences.values())
        manifest = GammaSnapshotManifest(
            created_at=_utc_iso(created_at),
            terminal_status=terminal_status,
            request_count=len(self._requests),
            error_count=sum(request.status == "error" for request in self._requests),
            payload_count=len(self._payloads),
            unique_market_count=len(self._market_occurrences),
            duplicate_market_id_count=duplicate_count,
            requests=tuple(self._requests),
            payloads=tuple(self._payloads),
        )
        content = canonical_json_bytes(manifest.model_dump(mode="json"))
        path, digest = _write_content_addressed(
            self.output_dir / "gamma_fetch_manifests",
            "manifest",
            content,
        )
        return GammaSnapshotResult(
            terminal_status=terminal_status,
            request_count=manifest.request_count,
            error_count=manifest.error_count,
            payload_count=manifest.payload_count,
            unique_market_count=manifest.unique_market_count,
            duplicate_market_id_count=manifest.duplicate_market_id_count,
            manifest_path=str(path.resolve()),
            manifest_sha256=digest,
        )
