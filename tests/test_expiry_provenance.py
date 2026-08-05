"""Tests for fail-closed title/rules/Gamma expiry reconciliation."""

from __future__ import annotations

import pytest

from polysignal.shadow.expiry_provenance import (
    EXPIRY_TIME_ADAPTER_VERSION,
    expiry_integrity_reasons,
    resolve_expiry_provenance,
)

RULES_ET = (
    "The market runs through December 31, 2026, 23:59 in the ET timezone. "
    "The resolution source for this market is Binance."
)


def market(**overrides):
    payload = {
        "endDate": "2027-01-01T05:00:00Z",
        "updatedAt": "2026-08-04T07:00:00Z",
        "$schema": "https://gamma-api.polymarket.com/schemas/Market.json",
        "version": "v1",
    }
    payload.update(overrides)
    return payload


def row(provenance, **overrides):
    payload = {
        "expiry_time": provenance.expiry_time,
        "expiry_local_time": provenance.expiry_local_time,
        "expiry_timezone": provenance.expiry_timezone,
        "expiry_time_origin": provenance.expiry_time_origin,
        "expiry_time_adapter_version": provenance.expiry_time_adapter_version,
        "expiry_time_provenance_sha256": provenance.expiry_time_provenance_sha256,
        "gamma_end_date": provenance.gamma_end_date,
        "gamma_market_updated_at": provenance.gamma_market_updated_at,
        "gamma_market_schema": provenance.gamma_market_schema,
        "gamma_market_version": provenance.gamma_market_version,
        "expiry_status": provenance.status,
        "resolution_rules": RULES_ET,
    }
    payload.update(overrides)
    return payload


def test_et_title_cutoff_is_converted_to_utc_and_corroborated_by_gamma():
    provenance = resolve_expiry_provenance(market(), "2026-12-31T23:59:00", RULES_ET)

    assert provenance.expiry_time == "2027-01-01T04:59:00Z"
    assert provenance.expiry_timezone == "America/New_York"
    assert provenance.expiry_time_adapter_version == EXPIRY_TIME_ADAPTER_VERSION
    assert provenance.status == "verified"
    assert expiry_integrity_reasons(row(provenance)) == []


def test_utc_rules_do_not_apply_et_offset():
    rules = RULES_ET.replace("ET timezone", "UTC")
    provenance = resolve_expiry_provenance(
        market(endDate="2027-01-01T00:00:00Z"),
        "2026-12-31T23:59:00",
        rules,
    )

    assert provenance.expiry_time == "2026-12-31T23:59:00Z"
    assert provenance.status == "verified"


@pytest.mark.parametrize(
    ("market_overrides", "rules", "status"),
    [
        ({"endDate": ""}, RULES_ET, "missing_gamma_end_date"),
        (
            {"endDate": "2026-12-31T23:59:00Z"},
            RULES_ET,
            "gamma_end_date_mismatch",
        ),
        ({}, RULES_ET.replace("ET timezone", "local time"), "missing_resolution_rules_timezone"),
        (
            {},
            f"{RULES_ET} Times are not expressed in UTC.",
            "conflicting_resolution_rules_timezone",
        ),
        ({}, RULES_ET.replace("23:59", "at day's end"), "missing_resolution_rules_expiry_cutoff"),
        ({"endDate": ["2027-01-01T05:00:00Z"]}, RULES_ET, "invalid_endDate"),
        ({"endDate": "2027-01-01T05:00:00"}, RULES_ET, "invalid_gamma_end_date"),
    ],
)
def test_missing_or_conflicting_expiry_evidence_fails_closed(
    market_overrides: dict, rules: str, status: str
):
    provenance = resolve_expiry_provenance(market(**market_overrides), "2026-12-31T23:59:00", rules)

    assert provenance.status == status


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("expiry_time", "2026-12-31T23:59:00Z", "expiry_timezone_conversion_mismatch"),
        ("gamma_end_date", "2027-01-02T05:00:00Z", "gamma_end_date_mismatch"),
        (
            "expiry_time_adapter_version",
            "gamma_expiry_adapter_v0",
            "expiry_time_adapter_version_mismatch",
        ),
        (
            "expiry_time_provenance_sha256",
            "0" * 64,
            "expiry_time_provenance_sha256_mismatch",
        ),
    ],
)
def test_serialized_expiry_tampering_is_rejected(field: str, value: str, reason: str):
    provenance = resolve_expiry_provenance(market(), "2026-12-31T23:59:00", RULES_ET)

    assert reason in expiry_integrity_reasons(row(provenance, **{field: value}))
