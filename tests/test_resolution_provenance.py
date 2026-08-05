"""Fail-closed tests for the versioned Gamma resolution-source adapter."""

from __future__ import annotations

import hashlib

import pytest

from polysignal.shadow.resolution_provenance import (
    RESOLUTION_SOURCE_ADAPTER_VERSION,
    RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD,
    RESOLUTION_SOURCE_ORIGIN_RULES_URL,
    resolution_integrity_reasons,
    resolution_rules_sha256,
    resolve_resolution_provenance,
)


def binance_rules(asset: str = "BTC", direction: str = "up") -> str:
    candle = (
        'a final "High" price equal to or greater than the price specified in the title'
        if direction == "up"
        else 'a final "Low" price equal to or lower than the price specified in the title'
    )
    return (
        f'This market resolves "Yes" if any Binance 1 minute candle for {asset}/USDT has '
        f"{candle}. Otherwise it resolves No.\n\n"
        f"The resolution source for this market is Binance, specifically the {asset}/USDT "
        f"prices available at https://www.binance.com/en/trade/{asset}_USDT, with the "
        'chart settings on "1m" for one-minute candles.'
    )


def settlement_rules(provider: str, asset: str, asset_name: str) -> str:
    return (
        f"This market resolves Yes when the {provider} closing price for "
        f"{asset_name} ({asset}) is equal to or greater than the threshold at expiry. "
        f"The sole price provider used for resolution is {provider}."
    )


def serialized_row(provenance, **overrides):
    row = {
        "asset": "BTC",
        "contract_kind": "touch_before_expiry",
        "barrier_direction": "up",
        "resolution_source": provenance.source,
        "resolution_source_origin": provenance.source_origin,
        "resolution_source_locator": provenance.source_locator,
        "resolution_source_adapter_version": provenance.source_adapter_version,
        "resolution_source_provenance_sha256": provenance.source_provenance_sha256,
        "resolution_rules": provenance.rules,
        "resolution_rules_sha256": provenance.rules_sha256,
        "resolution_status": provenance.status,
    }
    row.update(overrides)
    return row


def test_explicit_binance_source_is_verified_without_fetching_url():
    provenance = resolve_resolution_provenance(
        {"resolutionSource": "", "description": binance_rules()},
        "touch_before_expiry",
        "BTC",
        "up",
    )

    assert provenance.source == "https://www.binance.com/en/trade/BTC_USDT"
    assert provenance.source_origin == RESOLUTION_SOURCE_ORIGIN_RULES_URL
    assert provenance.source_locator == "market.description:explicit-resolution-source"
    assert provenance.source_adapter_version == RESOLUTION_SOURCE_ADAPTER_VERSION
    assert provenance.rules_sha256 == resolution_rules_sha256(provenance.rules)
    assert len(provenance.source_provenance_sha256) == 64
    assert provenance.status == "verified"
    assert resolution_integrity_reasons(serialized_row(provenance)) == []


def test_down_market_requires_matching_low_semantics_and_asset_pair():
    provenance = resolve_resolution_provenance(
        {"description": binance_rules("ETH", "down")},
        "touch_before_expiry",
        "ETH",
        "down",
    )

    assert provenance.source.endswith("/ETH_USDT")
    assert provenance.status == "verified"
    assert (
        resolution_integrity_reasons(
            serialized_row(
                provenance,
                asset="ETH",
                barrier_direction="down",
            )
        )
        == []
    )


def test_structured_url_is_used_and_matching_rules_url_corroborates_it():
    source = "https://www.binance.com/en/trade/SOL_USDT"
    provenance = resolve_resolution_provenance(
        {"resolutionSource": source, "description": binance_rules("SOL")},
        "touch_before_expiry",
        "SOL",
        "up",
    )

    assert provenance.source == source
    assert provenance.source_origin == RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD
    assert provenance.source_locator == "market.resolutionSource"
    assert provenance.status == "verified"


def test_non_binance_coinbase_eth_source_requires_provider_and_asset_semantics():
    provenance = resolve_resolution_provenance(
        {
            "resolutionSource": "https://www.coinbase.com/price/ethereum",
            "resolutionCriteria": settlement_rules("Coinbase", "ETH", "Ethereum"),
        },
        "settlement_threshold",
        "ETH",
        "up",
    )

    assert provenance.source == "https://www.coinbase.com/price/ethereum"
    assert provenance.source_origin == RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD
    assert provenance.status == "verified"
    assert (
        resolution_integrity_reasons(
            serialized_row(
                provenance,
                asset="ETH",
                contract_kind="settlement_threshold",
            )
        )
        == []
    )


def test_non_binance_kraken_sol_rules_url_requires_provider_and_asset_semantics():
    rules = (
        settlement_rules("Kraken", "SOL", "Solana")
        + "\n\nThe resolution source for this market is Kraken, specifically the Solana "
        "price at https://www.kraken.com/prices/solana."
    )
    provenance = resolve_resolution_provenance(
        {"description": rules},
        "settlement_threshold",
        "SOL",
        "up",
    )

    assert provenance.source == "https://www.kraken.com/prices/solana"
    assert provenance.source_origin == RESOLUTION_SOURCE_ORIGIN_RULES_URL
    assert provenance.status == "verified"
    assert (
        resolution_integrity_reasons(
            serialized_row(
                provenance,
                asset="SOL",
                contract_kind="settlement_threshold",
            )
        )
        == []
    )


def test_non_binance_source_rejects_conflicting_rule_provider():
    rules = (
        settlement_rules("Coinbase", "ETH", "Ethereum")
        + " Kraken is also used as an alternate resolution provider."
    )
    provenance = resolve_resolution_provenance(
        {
            "resolutionSource": "https://www.coinbase.com/price/ethereum",
            "resolutionCriteria": rules,
        },
        "settlement_threshold",
        "ETH",
        "up",
    )

    assert provenance.status == "resolution_source_provider_mismatch"


@pytest.mark.parametrize(
    ("rules", "expected_status"),
    [
        (
            "This market resolves Yes when the Ethereum (ETH) closing price is above the "
            "threshold at expiry. The resolution source for this market is "
            "https://www.coinbase.com/price/ethereum.",
            "resolution_source_provider_mismatch",
        ),
        (
            "This market resolves Yes when the Coinbase closing price is above the threshold "
            "at expiry. The resolution source for this market is Coinbase at "
            "https://www.coinbase.com/price/ethereum.",
            "resolution_source_asset_mismatch",
        ),
    ],
)
def test_non_binance_url_cannot_supply_missing_rule_semantics(rules: str, expected_status: str):
    provenance = resolve_resolution_provenance(
        {"description": rules},
        "settlement_threshold",
        "ETH",
        "up",
    )

    assert provenance.status == expected_status


@pytest.mark.parametrize(
    ("market_overrides", "expected_status"),
    [
        (
            {
                "resolutionSource": "https://www.coinbase.com/price/ethereum",
                "resolution_url": "https://www.kraken.com/prices/ethereum",
            },
            "conflicting_resolution_sources",
        ),
        (
            {
                "resolutionCriteria": settlement_rules("Coinbase", "ETH", "Ethereum"),
                "resolution_rules": settlement_rules("Kraken", "ETH", "Ethereum"),
            },
            "conflicting_resolution_rules",
        ),
    ],
)
def test_conflicting_structured_aliases_fail_closed(
    market_overrides: dict[str, str], expected_status: str
):
    market = {
        "resolutionSource": "https://www.coinbase.com/price/ethereum",
        "resolutionCriteria": settlement_rules("Coinbase", "ETH", "Ethereum"),
    }
    market.update(market_overrides)

    provenance = resolve_resolution_provenance(
        market,
        "settlement_threshold",
        "ETH",
        "up",
    )

    assert provenance.status == expected_status


def test_equivalent_duplicate_structured_aliases_are_accepted():
    rules = settlement_rules("Coinbase", "ETH", "Ethereum")
    provenance = resolve_resolution_provenance(
        {
            "resolutionSource": "https://www.coinbase.com/price/ethereum",
            "resolution_url": "https://WWW.COINBASE.COM/price/ethereum",
            "resolutionCriteria": rules,
            "resolution_rules": f"  {rules}\n",
        },
        "settlement_threshold",
        "ETH",
        "up",
    )

    assert provenance.status == "verified"


@pytest.mark.parametrize(
    ("description", "expected_status"),
    [
        (
            "Documentation is at https://www.binance.com/en/trade/BTC_USDT. "
            "The market resolves from a closing price.",
            "unverified_resolution_source_context",
        ),
        (
            binance_rules().replace(
                "with the chart settings",
                "and https://www.coinbase.com/price/bitcoin, with the chart settings",
            ),
            "multiple_resolution_source_urls",
        ),
        (
            binance_rules().replace("https://", "http://"),
            "non_https_resolution_source",
        ),
        (
            binance_rules().replace("www.binance.com", "prices.example.com"),
            "untrusted_resolution_source_domain",
        ),
        (
            binance_rules().replace("www.binance.com", "user@www.binance.com"),
            "invalid_resolution_source_url",
        ),
        (
            binance_rules().replace("/en/trade/BTC_USDT", "/en/markets/BTC_USDT"),
            "invalid_resolution_source_path",
        ),
    ],
)
def test_rule_url_fallback_rejects_ambiguous_or_untrusted_evidence(
    description: str, expected_status: str
):
    provenance = resolve_resolution_provenance(
        {"description": description}, "touch_before_expiry", "BTC", "up"
    )

    assert provenance.status == expected_status


def test_rule_url_asset_mismatch_is_rejected():
    provenance = resolve_resolution_provenance(
        {"description": binance_rules("ETH")},
        "touch_before_expiry",
        "BTC",
        "up",
    )

    assert provenance.status == "resolution_source_asset_mismatch"


def test_wrong_high_low_semantics_are_rejected():
    provenance = resolve_resolution_provenance(
        {"description": binance_rules("BTC", "down")},
        "touch_before_expiry",
        "BTC",
        "up",
    )

    assert provenance.status == "resolution_source_rule_semantics_mismatch"


def test_structured_source_conflict_and_invalid_value_do_not_fallback():
    conflict = resolve_resolution_provenance(
        {
            "resolutionSource": "https://www.coinbase.com/price/bitcoin",
            "description": binance_rules(),
        },
        "touch_before_expiry",
        "BTC",
        "up",
    )
    invalid = resolve_resolution_provenance(
        {"resolutionSource": "Binance", "description": binance_rules()},
        "touch_before_expiry",
        "BTC",
        "up",
    )
    non_string = resolve_resolution_provenance(
        {"resolutionSource": {"url": "https://www.binance.com"}, "description": binance_rules()},
        "touch_before_expiry",
        "BTC",
        "up",
    )

    assert conflict.status == "conflicting_resolution_sources"
    assert "conflicting_resolution_sources" in resolution_integrity_reasons(
        serialized_row(conflict)
    )
    assert invalid.status == "invalid_structured_resolution_source"
    assert invalid.source == ""
    assert non_string.status == "invalid_structured_resolution_source"


def test_unicode_quotes_and_terminal_punctuation_are_canonicalized():
    rules = binance_rules().replace(
        "https://www.binance.com/en/trade/BTC_USDT,",
        "“https://www.binance.com/en/trade/BTC_USDT”.",
    )
    provenance = resolve_resolution_provenance(
        {"description": rules}, "touch_before_expiry", "BTC", "up"
    )

    assert provenance.source == "https://www.binance.com/en/trade/BTC_USDT"
    assert provenance.status == "verified"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"resolution_rules_sha256": "0" * 64}, "resolution_rules_sha256_mismatch"),
        (
            {"resolution_source_locator": "market.description:url@1:2"},
            "invalid_resolution_source_locator",
        ),
        (
            {"resolution_source_adapter_version": "resolution_source_adapter_v0"},
            "resolution_source_adapter_version_mismatch",
        ),
        (
            {"resolution_source_provenance_sha256": "f" * 64},
            "resolution_source_provenance_sha256_mismatch",
        ),
    ],
)
def test_serialized_provenance_tampering_fails_closed(overrides: dict[str, str], reason: str):
    provenance = resolve_resolution_provenance(
        {"description": binance_rules()}, "touch_before_expiry", "BTC", "up"
    )

    assert reason in resolution_integrity_reasons(serialized_row(provenance, **overrides))


def test_hashes_are_deterministic_and_rules_hash_does_not_include_source_metadata():
    rules = binance_rules()
    first = resolve_resolution_provenance(
        {"description": rules}, "touch_before_expiry", "BTC", "up"
    )
    second = resolve_resolution_provenance(
        {"description": rules}, "touch_before_expiry", "BTC", "up"
    )

    assert first == second
    assert first.rules_sha256 == hashlib.sha256(" ".join(rules.split()).encode()).hexdigest()
