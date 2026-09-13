"""Versioned expiry-time provenance for crypto-threshold shadow research."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict

EXPIRY_TIME_ADAPTER_VERSION = "gamma_expiry_adapter_v1"
EXPIRY_TIME_STATUS_VERIFIED = "verified"
EXPIRY_TIME_ORIGIN = "title_date+resolution_rules_timezone+gamma.endDate"

_END_DATE_FIELDS = ("endDate", "end_date")
_UPDATED_AT_FIELDS = ("updatedAt", "updated_at")
_SCHEMA_FIELDS = ("$schema", "schema")
_VERSION_FIELDS = ("version",)
_ET_RE = re.compile(r"\b(?:ET|EST|EDT)\b|America/New_York", re.IGNORECASE)
_UTC_RE = re.compile(r"\bUTC\b", re.IGNORECASE)
_CUTOFF_RE = re.compile(r"\b23:59\b|\b11:59\s*P\.?M\.?\b", re.IGNORECASE)


class ExpiryProvenance(BaseModel):
    """Canonical cutoff and the Gamma/rules evidence used to derive it."""

    model_config = ConfigDict(frozen=True)

    expiry_time: str = ""
    expiry_local_time: str = ""
    expiry_timezone: str = ""
    expiry_time_origin: str = EXPIRY_TIME_ORIGIN
    expiry_time_adapter_version: str = EXPIRY_TIME_ADAPTER_VERSION
    expiry_time_provenance_sha256: str = ""
    gamma_end_date: str = ""
    gamma_market_updated_at: str = ""
    gamma_market_schema: str = ""
    gamma_market_version: str = ""
    status: str = ""


def _market_string_values(
    market: dict[str, Any], fields: tuple[str, ...]
) -> tuple[list[tuple[str, str]], str]:
    values: list[tuple[str, str]] = []
    for field in fields:
        value = market.get(field)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            return values, field
        if value.strip():
            values.append((value.strip(), field))
    return values, ""


def _one_market_string(market: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, str]:
    values, invalid_field = _market_string_values(market, fields)
    if invalid_field:
        return "", f"invalid_{invalid_field}"
    if len({value for value, _ in values}) > 1:
        return "", "conflicting_gamma_expiry_metadata"
    return (values[0][0], "") if values else ("", "")


def _parse_iso_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rules_timezone(rules: str) -> tuple[str, str]:
    has_et = bool(_ET_RE.search(rules))
    has_utc = bool(_UTC_RE.search(rules))
    if has_et and has_utc:
        return "", "conflicting_resolution_rules_timezone"
    if has_et:
        return "America/New_York", ""
    if has_utc:
        return "UTC", ""
    return "", "missing_resolution_rules_timezone"


def _expiry_status(
    expiry_time: str,
    expiry_local_time: str,
    expiry_timezone: str,
    gamma_end_date: str,
    rules: str,
) -> str:
    if not expiry_local_time:
        return "missing_title_expiry_time"
    if not expiry_timezone:
        return "missing_resolution_rules_timezone"
    if not _CUTOFF_RE.search(rules):
        return "missing_resolution_rules_expiry_cutoff"
    if not gamma_end_date:
        return "missing_gamma_end_date"

    local = _parse_iso_time(expiry_local_time)
    gamma_end = _parse_iso_time(gamma_end_date)
    canonical = _parse_iso_time(expiry_time)
    if local is None or local.tzinfo is not None:
        return "invalid_title_expiry_time"
    if gamma_end is None or gamma_end.tzinfo is None:
        return "invalid_gamma_end_date"
    if canonical is None or canonical.tzinfo is None:
        return "invalid_canonical_expiry_time"
    try:
        expected = local.replace(tzinfo=ZoneInfo(expiry_timezone)).astimezone(UTC)
    except ZoneInfoNotFoundError:
        return "invalid_resolution_rules_timezone"
    if canonical != expected:
        return "expiry_timezone_conversion_mismatch"
    gamma_delta_seconds = (gamma_end - canonical).total_seconds()
    if not 0 <= gamma_delta_seconds <= 120:
        return "gamma_end_date_mismatch"
    return EXPIRY_TIME_STATUS_VERIFIED


def _provenance_digest(provenance: ExpiryProvenance) -> str:
    material = "\x1f".join(
        (
            provenance.expiry_time_adapter_version,
            provenance.expiry_time_origin,
            provenance.expiry_local_time,
            provenance.expiry_timezone,
            provenance.expiry_time,
            provenance.gamma_end_date,
            provenance.gamma_market_updated_at,
            provenance.gamma_market_schema,
            provenance.gamma_market_version,
            provenance.status,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest() if provenance.expiry_time else ""


def resolve_expiry_provenance(
    market: dict[str, Any], title_expiry_time: str, rules: str
) -> ExpiryProvenance:
    """Resolve a title date using explicit rules timezone and Gamma endDate."""

    gamma_end_date, end_error = _one_market_string(market, _END_DATE_FIELDS)
    updated_at, updated_error = _one_market_string(market, _UPDATED_AT_FIELDS)
    schema, schema_error = _one_market_string(market, _SCHEMA_FIELDS)
    version, version_error = _one_market_string(market, _VERSION_FIELDS)
    metadata_error = next(
        (error for error in (end_error, updated_error, schema_error, version_error) if error),
        "",
    )
    expiry_timezone, timezone_error = _rules_timezone(rules)
    local = _parse_iso_time(title_expiry_time)
    expiry_time = ""
    if local is not None and local.tzinfo is None and expiry_timezone:
        try:
            expiry_time = _iso_utc(
                local.replace(tzinfo=ZoneInfo(expiry_timezone)).astimezone(UTC)
            )
        except ZoneInfoNotFoundError:
            expiry_time = ""

    status = metadata_error or timezone_error
    if not status:
        status = _expiry_status(
            expiry_time,
            title_expiry_time,
            expiry_timezone,
            gamma_end_date,
            rules,
        )
    provenance = ExpiryProvenance(
        expiry_time=expiry_time,
        expiry_local_time=title_expiry_time,
        expiry_timezone=expiry_timezone,
        gamma_end_date=gamma_end_date,
        gamma_market_updated_at=updated_at,
        gamma_market_schema=schema,
        gamma_market_version=version,
        status=status,
    )
    return provenance.model_copy(
        update={"expiry_time_provenance_sha256": _provenance_digest(provenance)}
    )


def expiry_integrity_reasons(row: dict[str, Any]) -> list[str]:
    """Validate serialized expiry evidence without external I/O."""

    provenance = ExpiryProvenance(
        expiry_time=str(row.get("expiry_time") or "").strip(),
        expiry_local_time=str(row.get("expiry_local_time") or "").strip(),
        expiry_timezone=str(row.get("expiry_timezone") or "").strip(),
        expiry_time_origin=str(row.get("expiry_time_origin") or "").strip(),
        expiry_time_adapter_version=str(row.get("expiry_time_adapter_version") or "").strip(),
        expiry_time_provenance_sha256=str(row.get("expiry_time_provenance_sha256") or "").strip(),
        gamma_end_date=str(row.get("gamma_end_date") or "").strip(),
        gamma_market_updated_at=str(row.get("gamma_market_updated_at") or "").strip(),
        gamma_market_schema=str(row.get("gamma_market_schema") or "").strip(),
        gamma_market_version=str(row.get("gamma_market_version") or "").strip(),
        status=str(row.get("expiry_status") or "").strip(),
    )
    rules = str(row.get("resolution_rules") or "")
    reasons: list[str] = []
    expected_status = _expiry_status(
        provenance.expiry_time,
        provenance.expiry_local_time,
        provenance.expiry_timezone,
        provenance.gamma_end_date,
        rules,
    )
    if provenance.expiry_time_adapter_version != EXPIRY_TIME_ADAPTER_VERSION:
        reasons.append("expiry_time_adapter_version_mismatch")
    if provenance.expiry_time_origin != EXPIRY_TIME_ORIGIN:
        reasons.append("missing_or_invalid_expiry_time_origin")
    if expected_status != EXPIRY_TIME_STATUS_VERIFIED:
        reasons.append(expected_status)
    if provenance.status != expected_status:
        reasons.append("expiry_status_mismatch")
    if provenance.status != EXPIRY_TIME_STATUS_VERIFIED:
        reasons.append(provenance.status or "expiry_status_not_verified")
    recorded_digest = provenance.expiry_time_provenance_sha256.lower()
    if not recorded_digest:
        reasons.append("missing_expiry_time_provenance_sha256")
    elif recorded_digest != _provenance_digest(
        provenance.model_copy(update={"expiry_time_provenance_sha256": ""})
    ):
        reasons.append("expiry_time_provenance_sha256_mismatch")
    return list(dict.fromkeys(reason for reason in reasons if reason))
