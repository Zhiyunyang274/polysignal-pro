"""Versioned, fail-closed resolution-source provenance for shadow research.

The adapter only parses already-fetched Gamma fields. It never follows a rule
URL, authenticates, or treats a referenced web page as independently verified.
Discovery and offline validation share this module so provenance checks cannot
drift between the two stages.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

RESOLUTION_SOURCE_ADAPTER_VERSION = "resolution_source_adapter_v1"
RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD = "market_field"
RESOLUTION_SOURCE_ORIGIN_RULES_URL = "resolution_rules_url"
RESOLUTION_SOURCE_STATUS_VERIFIED = "verified"

DIRECT_SOURCE_FIELDS = (
    "resolutionSource",
    "resolution_source",
    "resolutionUrl",
    "resolution_url",
)
RULE_FIELDS = (
    "resolutionCriteria",
    "resolution_criteria",
    "resolution_rules",
    "rules",
    "description",
)

# Exact hosts only. A suffix check would also trust delegated or attacker-like
# hosts without establishing that they are the intended public market page.
TRUSTED_CRYPTO_SOURCE_HOSTS = frozenset(
    {
        "binance.com",
        "www.binance.com",
        "coinbase.com",
        "www.coinbase.com",
        "exchange.coinbase.com",
        "kraken.com",
        "www.kraken.com",
        "coingecko.com",
        "www.coingecko.com",
        "coinmarketcap.com",
        "www.coinmarketcap.com",
        "okx.com",
        "www.okx.com",
        "bybit.com",
        "www.bybit.com",
    }
)
RESOLUTION_AMBIGUITY_KEYWORDS = frozenset(
    {
        "might",
        "maybe",
        "possibly",
        "subjective",
        "opinion",
        "unclear",
        "disputed",
        "tbd",
        "unknown",
        "pending",
        "to be announced",
    }
)

_URL_RE = re.compile(r"https?://[^\s<>\"'\u201c\u201d\u2018\u2019]+", re.IGNORECASE)
_SOURCE_SECTION_RE = re.compile(
    r"\b(?:the\s+)?resolution\s+source\s+for\s+(?:this|the)\s+market\s+is\b"
    r".{0,700}?(?=\n\s*\n|$)",
    re.IGNORECASE | re.DOTALL,
)
_ANY_SOURCE_CONTEXT_RE = re.compile(
    r"resolution\s+source|source\s+for\s+(?:this\s+)?market|"
    r"data\s+source|price\s+source|official\s+(?:source|price\s+feed)",
    re.IGNORECASE,
)
_BINANCE_PATH_RE = re.compile(r"/en/trade/(BTC|ETH|SOL)_USDT/?", re.IGNORECASE)
_SOURCE_PROVIDER_BY_HOST = {
    host: provider
    for provider, hosts in {
        "binance": ("binance.com", "www.binance.com"),
        "coinbase": ("coinbase.com", "www.coinbase.com", "exchange.coinbase.com"),
        "kraken": ("kraken.com", "www.kraken.com"),
        "coingecko": ("coingecko.com", "www.coingecko.com"),
        "coinmarketcap": ("coinmarketcap.com", "www.coinmarketcap.com"),
        "okx": ("okx.com", "www.okx.com"),
        "bybit": ("bybit.com", "www.bybit.com"),
    }.items()
    for host in hosts
}
_PROVIDER_RULE_ALIASES = {
    "binance": ("binance",),
    "coinbase": ("coinbase",),
    "kraken": ("kraken",),
    "coingecko": ("coingecko", "coin gecko"),
    "coinmarketcap": ("coinmarketcap", "coin market cap"),
    "okx": ("okx",),
    "bybit": ("bybit",),
}
_ASSET_SOURCE_ALIASES = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum"),
    "SOL": ("sol", "solana"),
}


class ResolutionProvenance(BaseModel):
    """Auditable source and rules evidence shared by discovery and validator."""

    model_config = ConfigDict(frozen=True)

    source: str = ""
    source_origin: str = ""
    source_locator: str = ""
    source_adapter_version: str = RESOLUTION_SOURCE_ADAPTER_VERSION
    source_provenance_sha256: str = ""
    rules: str = ""
    rules_sha256: str = ""
    status: str = ""


def normalize_resolution_text(value: Any) -> str:
    """Normalize serialized text for deterministic hashing and comparison."""

    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def resolution_rules_sha256(value: Any) -> str:
    normalized = normalize_resolution_text(value)
    return hashlib.sha256(normalized.encode()).hexdigest() if normalized else ""


def _has_semantic_alias(text: str, alias: str) -> bool:
    """Match entity names as standalone tokens, not incidental substrings."""

    pattern = re.escape(alias).replace(r"\ ", r"[\s_-]+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text, re.IGNORECASE) is not None


def _mentioned_entities(text: str, aliases: Mapping[str, tuple[str, ...]]) -> set[str]:
    return {
        entity
        for entity, entity_aliases in aliases.items()
        if any(_has_semantic_alias(text, alias) for alias in entity_aliases)
    }


def _market_string_values(
    market: dict[str, Any], fields: tuple[str, ...]
) -> tuple[list[tuple[str, str]], str]:
    """Return all non-empty strings and the first invalid non-string field."""

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


def _strip_terminal_url_punctuation(raw: str) -> str:
    candidate = raw.strip().rstrip(".,;:!?")
    pairs = (("(", ")"), ("[", "]"), ("{", "}"))
    for opening, closing in pairs:
        while candidate.endswith(closing) and candidate.count(closing) > candidate.count(opening):
            candidate = candidate[:-1]
    return candidate


def _canonicalize_https_url(raw: str) -> tuple[str, str]:
    candidate = _strip_terminal_url_punctuation(raw)
    if not candidate or any(character.isspace() or ord(character) < 32 for character in candidate):
        return "", "invalid_resolution_source_url"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "", "invalid_resolution_source_url"
    if parsed.scheme.lower() != "https":
        return "", "non_https_resolution_source"
    if not hostname or parsed.username or parsed.password:
        return "", "invalid_resolution_source_url"
    if port not in (None, 443):
        return "", "invalid_resolution_source_url"
    try:
        host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return "", "invalid_resolution_source_url"
    if host not in TRUSTED_CRYPTO_SOURCE_HOSTS:
        return "", "untrusted_resolution_source_domain"
    netloc = host
    canonical = SplitResult(
        scheme="https",
        netloc=netloc,
        path=parsed.path or "/",
        query=parsed.query,
        fragment=parsed.fragment,
    )
    return urlunsplit(canonical), ""


def _explicit_rules_url(rules: str, rules_field: str) -> tuple[str, str, str]:
    if not rules:
        return "", "", "missing_resolution_source"

    sections = list(_SOURCE_SECTION_RE.finditer(rules))
    if not sections:
        # A URL elsewhere in the description is not source evidence.
        if _URL_RE.search(rules) or _ANY_SOURCE_CONTEXT_RE.search(rules):
            return (
                "",
                f"market.{rules_field}:explicit-resolution-source",
                ("unverified_resolution_source_context"),
            )
        return "", "", "missing_resolution_source"

    urls: list[re.Match[str]] = []
    for section in sections:
        urls.extend(_URL_RE.finditer(section.group(0)))
    locator = f"market.{rules_field}:explicit-resolution-source"
    if not urls:
        return "", locator, "resolution_source_url_not_found"
    if len(urls) != 1:
        return "", locator, "multiple_resolution_source_urls"
    source, error = _canonicalize_https_url(urls[0].group(0))
    return source, locator, error


def _source_rule_status(
    source: str,
    rules: str,
    contract_kind: str,
    asset: str,
    barrier_direction: str,
) -> str:
    if not source:
        return "missing_resolution_source"
    if not rules or len(normalize_resolution_text(rules)) < 20:
        return "missing_or_insufficient_resolution_rules"

    normalized_rules = normalize_resolution_text(rules).lower()
    if any(keyword in source.lower() for keyword in RESOLUTION_AMBIGUITY_KEYWORDS):
        return "ambiguous_resolution_source"
    if any(keyword in normalized_rules for keyword in RESOLUTION_AMBIGUITY_KEYWORDS):
        return "ambiguous_resolution_rules"
    if resolution_semantics_conflict(contract_kind, rules):
        return "resolution_semantics_conflict"

    parsed = urlsplit(source)
    hostname = parsed.hostname or ""
    provider = _SOURCE_PROVIDER_BY_HOST.get(hostname, "")
    # The URL cannot corroborate its own prose semantics. Provider and asset
    # mentions must also exist in the surrounding rules after URLs are removed.
    rules_semantics = _URL_RE.sub(" ", normalized_rules)
    provider_mentions = _mentioned_entities(rules_semantics, _PROVIDER_RULE_ALIASES)
    if not provider or provider_mentions != {provider}:
        return "resolution_source_provider_mismatch"

    normalized_asset = asset.strip().upper()
    source_location = f"{parsed.path}?{parsed.query}".lower()
    rules_asset_mentions = _mentioned_entities(rules_semantics, _ASSET_SOURCE_ALIASES)
    source_asset_mentions = _mentioned_entities(source_location, _ASSET_SOURCE_ALIASES)
    if (
        normalized_asset not in _ASSET_SOURCE_ALIASES
        or rules_asset_mentions != {normalized_asset}
        or source_asset_mentions != {normalized_asset}
    ):
        return "resolution_source_asset_mismatch"

    if hostname in {"binance.com", "www.binance.com"}:
        path_match = _BINANCE_PATH_RE.fullmatch(parsed.path)
        if not path_match:
            return "invalid_resolution_source_path"
        path_asset = path_match.group(1).upper()
        if path_asset != normalized_asset:
            return "resolution_source_asset_mismatch"
        if f"{normalized_asset.lower()}/usdt" not in normalized_rules:
            return "resolution_source_asset_mismatch"
        if not any(marker in normalized_rules for marker in ("1 minute", "one-minute", '"1m"')):
            return "resolution_source_interval_mismatch"
        if barrier_direction == "up" and not (
            "high" in normalized_rules and "equal to or greater" in normalized_rules
        ):
            return "resolution_source_rule_semantics_mismatch"
        if barrier_direction == "down" and not (
            "low" in normalized_rules and "equal to or lower" in normalized_rules
        ):
            return "resolution_source_rule_semantics_mismatch"
    return RESOLUTION_SOURCE_STATUS_VERIFIED


def resolution_semantics_conflict(contract_kind: str, rules: str) -> bool:
    normalized = normalize_resolution_text(rules).lower()
    if contract_kind == "touch_before_expiry":
        terminal_only = any(
            phrase in normalized
            for phrase in (
                "closing price",
                "price at expiry",
                "price at expiration",
                "as of the expiration",
            )
        )
        touch_rule = any(
            phrase in normalized
            for phrase in ("at any time", "reaches", "hits", "touches", "trades at")
        )
        return terminal_only and not touch_rule
    if contract_kind == "settlement_threshold":
        intraperiod_only = any(
            phrase in normalized for phrase in ("at any time", "hits before", "touches before")
        )
        terminal_rule = any(
            phrase in normalized
            for phrase in ("closing price", "price at expiry", "price at expiration", "as of")
        )
        return intraperiod_only and not terminal_rule
    return False


def _provenance_digest(provenance: ResolutionProvenance) -> str:
    material = "\x1f".join(
        (
            provenance.source_adapter_version,
            provenance.source_origin,
            provenance.source_locator,
            provenance.source,
            provenance.rules_sha256,
            provenance.status,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest() if provenance.source else ""


def resolve_resolution_provenance(
    market: dict[str, Any],
    contract_kind: str,
    asset: str = "",
    barrier_direction: str = "",
) -> ResolutionProvenance:
    """Resolve a structured or explicit rule-embedded source without I/O."""

    rule_values, invalid_rules_field = _market_string_values(market, RULE_FIELDS)
    rules, rules_field = rule_values[0] if rule_values else ("", "")
    rules_hash = resolution_rules_sha256(rules)
    direct_values, invalid_direct_field = _market_string_values(market, DIRECT_SOURCE_FIELDS)
    direct_raw, direct_field = direct_values[0] if direct_values else ("", "")
    rules_source, rules_locator, rules_source_error = _explicit_rules_url(rules, rules_field)

    source = ""
    source_origin = ""
    source_locator = ""
    status = ""
    if invalid_rules_field:
        status = "invalid_resolution_rules"
    elif len({normalize_resolution_text(value) for value, _ in rule_values}) > 1:
        status = "conflicting_resolution_rules"
    elif invalid_direct_field:
        source_origin = RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD
        source_locator = f"market.{invalid_direct_field}"
        status = "invalid_structured_resolution_source"
    elif direct_raw:
        source_origin = RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD
        source_locator = f"market.{direct_field}"
        source, direct_error = _canonicalize_https_url(direct_raw)
        canonical_direct_values = [_canonicalize_https_url(value) for value, _ in direct_values]
        if direct_error or any(error for _, error in canonical_direct_values):
            status = "invalid_structured_resolution_source"
        elif len({canonical for canonical, _ in canonical_direct_values}) > 1:
            status = "conflicting_resolution_sources"
        elif rules_source_error not in {"", "missing_resolution_source"}:
            status = rules_source_error
        elif rules_source and rules_source != source:
            status = "conflicting_resolution_sources"
    else:
        source = rules_source
        source_origin = RESOLUTION_SOURCE_ORIGIN_RULES_URL if rules_locator else ""
        source_locator = rules_locator
        status = rules_source_error

    if not status:
        status = _source_rule_status(source, rules, contract_kind, asset, barrier_direction)

    provenance = ResolutionProvenance(
        source=source,
        source_origin=source_origin,
        source_locator=source_locator,
        source_adapter_version=RESOLUTION_SOURCE_ADAPTER_VERSION,
        rules=rules,
        rules_sha256=rules_hash,
        status=status,
    )
    return provenance.model_copy(
        update={"source_provenance_sha256": _provenance_digest(provenance)}
    )


def resolution_integrity_reasons(row: dict[str, Any]) -> list[str]:
    """Validate serialized provenance without network access."""

    source = normalize_resolution_text(row.get("resolution_source"))
    origin = normalize_resolution_text(row.get("resolution_source_origin"))
    locator = normalize_resolution_text(row.get("resolution_source_locator"))
    adapter_version = normalize_resolution_text(row.get("resolution_source_adapter_version"))
    recorded_digest = normalize_resolution_text(
        row.get("resolution_source_provenance_sha256")
    ).lower()
    raw_rules = row.get("resolution_rules")
    rules = raw_rules if isinstance(raw_rules, str) else ""
    recorded_rules_hash = normalize_resolution_text(row.get("resolution_rules_sha256")).lower()
    status = normalize_resolution_text(row.get("resolution_status"))
    contract_kind = normalize_resolution_text(row.get("contract_kind"))
    asset = normalize_resolution_text(row.get("asset"))
    barrier_direction = normalize_resolution_text(row.get("barrier_direction"))
    reasons: list[str] = []

    if not source:
        reasons.append("missing_resolution_source")
    canonical_source, source_error = _canonicalize_https_url(source) if source else ("", "")
    if source and source_error:
        reasons.append(source_error)
    elif source and canonical_source != source:
        reasons.append("noncanonical_resolution_source")
    if not rules or len(normalize_resolution_text(rules)) < 20:
        reasons.append("missing_or_insufficient_resolution_rules")
    expected_rules_hash = resolution_rules_sha256(rules)
    if not recorded_rules_hash:
        reasons.append("missing_resolution_rules_sha256")
    elif recorded_rules_hash != expected_rules_hash:
        reasons.append("resolution_rules_sha256_mismatch")
    if adapter_version != RESOLUTION_SOURCE_ADAPTER_VERSION:
        reasons.append("resolution_source_adapter_version_mismatch")
    if origin not in {RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD, RESOLUTION_SOURCE_ORIGIN_RULES_URL}:
        reasons.append("missing_or_invalid_resolution_source_origin")
    if not locator:
        reasons.append("missing_resolution_source_locator")
    if not recorded_digest:
        reasons.append("missing_resolution_source_provenance_sha256")

    if origin == RESOLUTION_SOURCE_ORIGIN_MARKET_FIELD:
        if locator not in {f"market.{field}" for field in DIRECT_SOURCE_FIELDS}:
            reasons.append("invalid_resolution_source_locator")
        embedded_source, _, embedded_error = _explicit_rules_url(rules, "resolution_rules")
        if embedded_error not in {"", "missing_resolution_source"}:
            reasons.append(embedded_error)
        if embedded_source and embedded_source != source:
            reasons.append("conflicting_resolution_sources")
    elif origin == RESOLUTION_SOURCE_ORIGIN_RULES_URL:
        field_prefix = locator.removeprefix("market.").split(":", 1)[0]
        if field_prefix not in RULE_FIELDS or locator != (
            f"market.{field_prefix}:explicit-resolution-source"
        ):
            reasons.append("invalid_resolution_source_locator")
        else:
            extracted_source, extracted_locator, extraction_error = _explicit_rules_url(
                rules, field_prefix
            )
            if extraction_error:
                reasons.append(extraction_error)
            if extracted_source != source or extracted_locator != locator:
                reasons.append("resolution_source_rules_evidence_mismatch")

    expected_status = _source_rule_status(
        canonical_source or source,
        rules,
        contract_kind,
        asset,
        barrier_direction,
    )
    if expected_status != RESOLUTION_SOURCE_STATUS_VERIFIED:
        reasons.append(expected_status)
    if status != expected_status:
        reasons.append("resolution_status_mismatch")
    if status != RESOLUTION_SOURCE_STATUS_VERIFIED:
        reasons.append(status if status else "resolution_status_not_verified")

    expected_digest = _provenance_digest(
        ResolutionProvenance(
            source=source,
            source_origin=origin,
            source_locator=locator,
            source_adapter_version=adapter_version,
            rules=rules,
            rules_sha256=recorded_rules_hash,
            status=status,
        )
    )
    if recorded_digest and recorded_digest != expected_digest:
        reasons.append("resolution_source_provenance_sha256_mismatch")
    return list(dict.fromkeys(reason for reason in reasons if reason))
