"""Versioned historical barrier evidence for crypto-threshold shadow research."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from polysignal.shadow.expiry_provenance import expiry_integrity_reasons
from polysignal.shadow.gamma_raw_snapshot import canonical_json_bytes
from polysignal.shadow.resolution_provenance import resolution_rules_sha256
from polysignal.utils.time import utc_now

HISTORICAL_BARRIER_ADAPTER_VERSION = "binance_1m_barrier_adapter_v1"
RULE_WINDOW_ADAPTER_VERSION = "explicit_rule_window_adapter_v1"
HISTORICAL_BARRIER_SCHEMA_VERSION = "historical_barrier_evidence_v1"
HISTORICAL_BARRIER_STATUS_VERIFIED = "verified_full_coverage"
HISTORICAL_BARRIER_STATUS_NOT_REQUIRED = "not_required"
HISTORICAL_BARRIER_SOURCE = "binance_public_klines"
COINBASE_HISTORICAL_BARRIER_SOURCE = "coinbase_exchange_candles"
# ADR-027 (user-approved 2026-09-12): historical barrier candle evidence may come
# from Binance (primary) or Coinbase (fallback) — both public, 1-minute OHLC,
# allowlisted hosts. Provenance records which source served the data.
VERIFIED_HISTORICAL_BARRIER_SOURCES = {
    HISTORICAL_BARRIER_SOURCE,
    COINBASE_HISTORICAL_BARRIER_SOURCE,
}
HISTORICAL_BARRIER_ORIGIN = "resolution_rules_explicit_window+binance_public_klines"
BINANCE_KLINES_LOCATOR = "https://api.binance.com/api/v3/klines"
COINBASE_SYMBOLS = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "XRP": "XRP-USD", "DOGE": "DOGE-USD", "BNB": "BNB-USD", "LINK": "LINK-USD",
}
COINBASE_KLINES_LOCATOR_TEMPLATE = (
    "https://api.exchange.coinbase.com/products/{pair}/candles"
)
BINANCE_TIME_LOCATOR = "https://api.binance.com/api/v3/time"
BINANCE_INTERVAL = "1m"
BINANCE_INTERVAL_MS = 60_000
BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "XRP": "XRPUSDT", "DOGE": "DOGEUSDT", "BNB": "BNBUSDT", "LINK": "LINKUSDT",
}

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_PATTERN = "|".join(_MONTHS)


def _window_time_pattern(prefix: str) -> str:
    return (
        rf"(?P<{prefix}_month>{_MONTH_PATTERN})\s+"
        rf"(?P<{prefix}_day>\d{{1,2}}),?\s+"
        rf"(?P<{prefix}_year>\d{{4}}),?\s+"
        rf"(?P<{prefix}_clock>\d{{1,2}}:\d{{2}}(?:\s*[AaPp]\.?[Mm]\.?)?)"
    )


_EXPLICIT_WINDOW_RE = re.compile(
    rf"\bbetween\s+{_window_time_pattern('start')}\s+and\s+"
    rf"{_window_time_pattern('end')}\s+in\s+(?:the\s+)?"
    rf"(?P<timezone>ET|UTC)\s+timezone\b",
    re.IGNORECASE,
)
_ET_RE = re.compile(r"\b(?:ET|EST|EDT)\b|America/New_York", re.IGNORECASE)
_UTC_RE = re.compile(r"\bUTC\b", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RuleObservationWindow(BaseModel):
    """Explicit rules-local observation window normalized to UTC."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_time: str = ""
    end_time: str = ""
    timezone: str = ""
    start_text: str = ""
    end_text: str = ""
    origin: str = "resolution_rules.explicit_between_window"
    locator: str = "resolution_rules:between-window"
    adapter_version: str = RULE_WINDOW_ADAPTER_VERSION
    rules_sha256: str = ""
    provenance_sha256: str = ""
    status: str = ""


class BinanceKline(BaseModel):
    """One validated Binance 1-minute kline row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    open_time_ms: int
    open_price: str
    high_price: str
    low_price: str
    close_price: str
    volume: str
    close_time_ms: int
    quote_asset_volume: str
    trade_count: int
    taker_buy_base_volume: str
    taker_buy_quote_volume: str
    ignore: str


class BinanceKlinePageAudit(BaseModel):
    """Request metadata and validation outcome for one fixed candle range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    requested_start_ms: int
    requested_end_ms: int
    expected_candle_count: int
    received_candle_count: int
    attempts: int
    status: str
    error: str = ""


class BinanceKlineFetchResult(BaseModel):
    """Typed result of a complete public kline coverage request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    source: str = HISTORICAL_BARRIER_SOURCE
    locator: str = BINANCE_KLINES_LOCATOR
    symbol: str
    interval: str = BINANCE_INTERVAL
    start_time: str
    end_time: str
    server_time_before: str = ""
    server_time_after: str = ""
    pages: tuple[BinanceKlinePageAudit, ...] = ()
    candles: tuple[BinanceKline, ...] = ()
    missing_ranges: tuple[str, ...] = ()
    error: str = ""


class HistoricalBarrierEvidence(BaseModel):
    """Candidate-facing historical barrier evidence and artifact provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    source: str = ""
    start_time: str = ""
    end_time: str = ""
    sha256: str = ""
    adapter_version: str = HISTORICAL_BARRIER_ADAPTER_VERSION
    origin: str = ""
    locator: str = ""
    interval: str = ""
    symbol: str = ""
    candle_count: int = 0
    missing_ranges: tuple[str, ...] = ()
    evidence_path: str = ""
    candle_snapshot_path: str = ""
    candle_snapshot_sha256: str = ""
    rule_window_adapter_version: str = RULE_WINDOW_ADAPTER_VERSION
    rule_window_provenance_sha256: str = ""
    barrier_crossed_at: str = ""
    expected_candle_count: int = 0
    min_low_price: str = ""
    max_high_price: str = ""
    tail_coverage_status: str = ""
    tail_covered_through: str = ""
    first_touch_at: str = ""


@dataclass(frozen=True)
class HistoricalCandleSnapshotReference:
    """In-process reference to one persisted, content-addressed candle snapshot."""

    path: Path
    sha256: str
    fetch_result_identity: int


class HistoricalArtifactConflictError(RuntimeError):
    """A content-addressed evidence file was modified in place."""


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    normalized = _aware_utc(value)
    timespec = "milliseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


def _ms_iso(value: int) -> str:
    return _iso_utc(datetime.fromtimestamp(value / 1000.0, tz=UTC))


def _parse_utc(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _parse_clock(value: str) -> tuple[int, int] | None:
    normalized = re.sub(r"[.\s]", "", value).upper()
    for pattern in ("%H:%M", "%I:%M%p"):
        try:
            parsed = datetime.strptime(normalized, pattern)
        except ValueError:
            continue
        return parsed.hour, parsed.minute
    return None


def _match_datetime(match: re.Match[str], prefix: str, timezone_name: str) -> datetime | None:
    clock = _parse_clock(match.group(f"{prefix}_clock"))
    if clock is None:
        return None
    try:
        local = datetime(
            int(match.group(f"{prefix}_year")),
            _MONTHS[match.group(f"{prefix}_month").lower()],
            int(match.group(f"{prefix}_day")),
            clock[0],
            clock[1],
            tzinfo=ZoneInfo(timezone_name),
        )
    except (KeyError, ValueError):
        return None
    return local.astimezone(UTC)


def _window_digest(window: RuleObservationWindow) -> str:
    material = "\x1f".join(
        (
            window.adapter_version,
            window.origin,
            window.locator,
            window.rules_sha256,
            window.start_text,
            window.end_text,
            window.timezone,
            window.start_time,
            window.end_time,
            window.status,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest() if window.rules_sha256 else ""


def parse_rule_observation_window(
    rules: str,
    expected_expiry_time: str,
) -> RuleObservationWindow:
    """Parse only an explicit rules-local between-window; never Gamma startDate."""

    rules_hash = resolution_rules_sha256(rules)
    base = RuleObservationWindow(rules_sha256=rules_hash)
    if not isinstance(rules, str):
        result = base.model_copy(update={"status": "invalid_resolution_rules_type"})
        return result.model_copy(update={"provenance_sha256": _window_digest(result)})
    if not rules.strip():
        result = base.model_copy(update={"status": "missing_resolution_rules"})
        return result.model_copy(update={"provenance_sha256": _window_digest(result)})
    if _ET_RE.search(rules) and _UTC_RE.search(rules):
        result = base.model_copy(update={"status": "conflicting_rule_window_timezone"})
        return result.model_copy(update={"provenance_sha256": _window_digest(result)})

    matches = list(_EXPLICIT_WINDOW_RE.finditer(rules))
    if not matches:
        result = base.model_copy(update={"status": "missing_explicit_rule_start_time"})
        return result.model_copy(update={"provenance_sha256": _window_digest(result)})
    normalized_matches = {re.sub(r"\s+", " ", match.group(0)).strip() for match in matches}
    if len(normalized_matches) != 1 or len(matches) != 1:
        result = base.model_copy(update={"status": "conflicting_explicit_rule_windows"})
        return result.model_copy(update={"provenance_sha256": _window_digest(result)})

    match = matches[0]
    timezone_marker = match.group("timezone").upper()
    timezone_name = "America/New_York" if timezone_marker == "ET" else "UTC"
    start = _match_datetime(match, "start", timezone_name)
    end = _match_datetime(match, "end", timezone_name)
    start_text = (
        f"{match.group('start_month')} {match.group('start_day')}, "
        f"{match.group('start_year')}, {match.group('start_clock')}"
    )
    end_text = (
        f"{match.group('end_month')} {match.group('end_day')}, "
        f"{match.group('end_year')}, {match.group('end_clock')}"
    )
    status = "verified"
    if start is None or end is None:
        status = "invalid_explicit_rule_window"
    elif start >= end:
        status = "invalid_explicit_rule_window_range"
    elif start.second or start.microsecond:
        status = "rule_window_start_not_minute_aligned"
    else:
        expected_expiry = _parse_utc(expected_expiry_time)
        if expected_expiry is None:
            status = "missing_or_invalid_expected_expiry"
        elif end != expected_expiry:
            status = "rule_window_expiry_mismatch"

    result = RuleObservationWindow(
        start_time=_iso_utc(start) if start else "",
        end_time=_iso_utc(end) if end else "",
        timezone=timezone_name,
        start_text=start_text,
        end_text=end_text,
        rules_sha256=rules_hash,
        status=status,
    )
    return result.model_copy(update={"provenance_sha256": _window_digest(result)})


def _decimal(raw: Any, *, allow_zero: bool = False) -> Decimal | None:
    if not isinstance(raw, str):
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
        return None
    return value


def parse_binance_kline(raw: Any) -> tuple[BinanceKline | None, str]:
    """Validate the exact public Binance 12-field kline contract."""

    if not isinstance(raw, list) or len(raw) != 12:
        return None, "invalid_kline_row_shape"
    if (
        isinstance(raw[0], bool)
        or not isinstance(raw[0], int)
        or isinstance(raw[6], bool)
        or not isinstance(raw[6], int)
        or isinstance(raw[8], bool)
        or not isinstance(raw[8], int)
    ):
        return None, "invalid_kline_timestamp_or_trade_count"
    if raw[0] % BINANCE_INTERVAL_MS != 0 or raw[6] != raw[0] + BINANCE_INTERVAL_MS - 1:
        return None, "invalid_kline_interval"

    open_price = _decimal(raw[1])
    high_price = _decimal(raw[2])
    low_price = _decimal(raw[3])
    close_price = _decimal(raw[4])
    numeric_tail = [
        _decimal(raw[5], allow_zero=True),
        _decimal(raw[7], allow_zero=True),
        _decimal(raw[9], allow_zero=True),
        _decimal(raw[10], allow_zero=True),
        _decimal(raw[11], allow_zero=True),
    ]
    if None in (open_price, high_price, low_price, close_price) or any(
        value is None for value in numeric_tail
    ):
        return None, "invalid_kline_numeric_value"
    assert open_price is not None
    assert high_price is not None
    assert low_price is not None
    assert close_price is not None
    if high_price < max(open_price, low_price, close_price) or low_price > min(
        open_price, high_price, close_price
    ):
        return None, "invalid_kline_ohlc_bounds"

    return (
        BinanceKline(
            open_time_ms=raw[0],
            open_price=raw[1],
            high_price=raw[2],
            low_price=raw[3],
            close_price=raw[4],
            volume=raw[5],
            close_time_ms=raw[6],
            quote_asset_volume=raw[7],
            trade_count=raw[8],
            taker_buy_base_volume=raw[9],
            taker_buy_quote_volume=raw[10],
            ignore=raw[11],
        ),
        "",
    )


def _missing_ranges(open_times: Sequence[int], end_ms: int) -> tuple[str, ...]:
    if not open_times:
        return ()
    ranges: list[str] = []
    range_start = open_times[0]
    previous = open_times[0]
    for current in open_times[1:]:
        if current != previous + BINANCE_INTERVAL_MS:
            ranges.append(
                f"{_ms_iso(range_start)}/{_ms_iso(min(previous + BINANCE_INTERVAL_MS, end_ms))}"
            )
            range_start = current
        previous = current
    ranges.append(f"{_ms_iso(range_start)}/{_ms_iso(min(previous + BINANCE_INTERVAL_MS, end_ms))}")
    return tuple(ranges)


class BinanceHistoricalKlineClient:
    """Read-only, retrying Binance 1m client with fixed-range pagination."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.binance.com",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        page_limit: int = 1000,
        max_pages: int = 2000,
        max_concurrency: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.page_limit = max(1, min(1000, page_limit))
        self.max_pages = max(1, max_pages)
        self.max_concurrency = max(1, max_concurrency)
        self.transport = transport

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, str | int] | None = None,
    ) -> tuple[Any | None, str, int]:
        last_error = "binance_request_failed"
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(path, params=params)
            except httpx.TimeoutException:
                last_error = "binance_timeout"
            except httpx.RequestError:
                last_error = "binance_request_error"
            else:
                if response.status_code < 400:
                    try:
                        return response.json(), "", attempt + 1
                    except ValueError:
                        return None, "binance_invalid_json", attempt + 1
                last_error = f"binance_http_{response.status_code}"
                if response.status_code != 429 and response.status_code < 500:
                    return None, last_error, attempt + 1
            if attempt < self.max_retries and self.retry_backoff_seconds:
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
        return None, last_error, self.max_retries + 1

    async def _server_time(self, client: httpx.AsyncClient) -> tuple[int | None, str, int]:
        payload, error, attempts = await self._get_json(client, "/api/v3/time")
        if error:
            return None, error, attempts
        if not isinstance(payload, dict):
            return None, "invalid_binance_server_time", attempts
        value = payload.get("serverTime")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None, "invalid_binance_server_time", attempts
        return value, "", attempts

    async def fetch_klines(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> BinanceKlineFetchResult:
        start = _aware_utc(start_time)
        end = _aware_utc(end_time)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        normalized_start = _iso_utc(start)
        normalized_end = _iso_utc(end)

        def empty_result(status: str, error: str = "") -> BinanceKlineFetchResult:
            return BinanceKlineFetchResult(
                status=status,
                symbol=symbol,
                start_time=normalized_start,
                end_time=normalized_end,
                error=error,
            )

        if symbol not in set(BINANCE_SYMBOLS.values()):
            return empty_result("unsupported_binance_symbol")
        if start >= end:
            return empty_result("invalid_kline_fetch_range")
        if start_ms % BINANCE_INTERVAL_MS:
            return empty_result("kline_start_not_minute_aligned")

        expected_total = math.ceil((end_ms - start_ms) / BINANCE_INTERVAL_MS)
        page_count = math.ceil(expected_total / self.page_limit)
        if page_count > self.max_pages:
            return empty_result("kline_page_limit_exceeded")

        chunks: list[tuple[int, int, tuple[int, ...]]] = []
        cursor = start_ms
        while cursor < end_ms:
            chunk_end = min(cursor + self.page_limit * BINANCE_INTERVAL_MS, end_ms)
            expected = tuple(range(cursor, chunk_end, BINANCE_INTERVAL_MS))
            chunks.append((cursor, chunk_end, expected))
            cursor = chunk_end if chunk_end % BINANCE_INTERVAL_MS == 0 else end_ms

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            server_before, server_error, _ = await self._server_time(client)
            if server_error or server_before is None:
                return empty_result(server_error, server_error)

            semaphore = asyncio.Semaphore(self.max_concurrency)

            async def fetch_chunk(
                sequence: int,
                chunk: tuple[int, int, tuple[int, ...]],
            ) -> tuple[BinanceKlinePageAudit, tuple[BinanceKline, ...], tuple[int, ...]]:
                chunk_start, chunk_end, expected = chunk
                params: dict[str, str | int] = {
                    "symbol": symbol,
                    "interval": BINANCE_INTERVAL,
                    "startTime": chunk_start,
                    "endTime": chunk_end - 1,
                    "limit": len(expected),
                }
                async with semaphore:
                    payload, error, attempts = await self._get_json(
                        client, "/api/v3/klines", params
                    )
                if error:
                    return (
                        BinanceKlinePageAudit(
                            sequence=sequence,
                            requested_start_ms=chunk_start,
                            requested_end_ms=chunk_end,
                            expected_candle_count=len(expected),
                            received_candle_count=0,
                            attempts=attempts,
                            status="error",
                            error=error,
                        ),
                        (),
                        expected,
                    )
                if not isinstance(payload, list):
                    error = "invalid_kline_page_payload"
                    return (
                        BinanceKlinePageAudit(
                            sequence=sequence,
                            requested_start_ms=chunk_start,
                            requested_end_ms=chunk_end,
                            expected_candle_count=len(expected),
                            received_candle_count=0,
                            attempts=attempts,
                            status="error",
                            error=error,
                        ),
                        (),
                        expected,
                    )

                candles: list[BinanceKline] = []
                row_error = ""
                for raw in payload:
                    candle, row_error = parse_binance_kline(raw)
                    if row_error or candle is None:
                        break
                    candles.append(candle)
                received_opens = tuple(candle.open_time_ms for candle in candles)
                missing = tuple(
                    open_time for open_time in expected if open_time not in received_opens
                )
                if row_error:
                    status = "error"
                elif len(set(received_opens)) != len(received_opens):
                    row_error = "duplicate_klines"
                    status = "error"
                elif received_opens != tuple(sorted(received_opens)):
                    row_error = "non_monotonic_klines"
                    status = "error"
                elif any(open_time not in expected for open_time in received_opens):
                    row_error = "out_of_range_klines"
                    status = "error"
                elif missing:
                    row_error = "partial_kline_page"
                    status = "partial"
                else:
                    status = "complete"
                return (
                    BinanceKlinePageAudit(
                        sequence=sequence,
                        requested_start_ms=chunk_start,
                        requested_end_ms=chunk_end,
                        expected_candle_count=len(expected),
                        received_candle_count=len(payload),
                        attempts=attempts,
                        status=status,
                        error=row_error,
                    ),
                    tuple(candles),
                    missing,
                )

            fetched = await asyncio.gather(
                *(fetch_chunk(index, chunk) for index, chunk in enumerate(chunks, start=1))
            )
            server_after, after_error, _ = await self._server_time(client)

        pages = tuple(item[0] for item in fetched)
        candles = tuple(candle for item in fetched for candle in item[1])
        missing_opens = tuple(sorted({value for item in fetched for value in item[2]}))
        errors = [page.error for page in pages if page.error]
        if after_error or server_after is None:
            status = after_error
            error = after_error
        elif server_after < server_before:
            status = "binance_server_time_regressed"
            error = status
        elif end_ms > server_after:
            status = "entry_after_binance_server_time"
            error = status
        elif errors:
            status = (
                "partial_coverage"
                if all(item == "partial_kline_page" for item in errors)
                else errors[0]
            )
            error = errors[0]
        elif missing_opens:
            status = "partial_coverage"
            error = status
        else:
            all_opens = tuple(candle.open_time_ms for candle in candles)
            expected_opens = tuple(range(start_ms, end_ms, BINANCE_INTERVAL_MS))
            if all_opens != expected_opens:
                status = "non_contiguous_kline_coverage"
                error = status
            else:
                status = "complete"
                error = ""

        return BinanceKlineFetchResult(
            status=status,
            server_time_before=_ms_iso(server_before),
            server_time_after=_ms_iso(server_after) if server_after else "",
            pages=pages,
            candles=candles,
            missing_ranges=_missing_ranges(missing_opens, end_ms),
            error=error,
            symbol=symbol,
            start_time=normalized_start,
            end_time=normalized_end,
        )


COINBASE_CANDLES_PAGE_LIMIT = 300  # Coinbase returns max 300 candles per request


def _expected_symbol_for_source(asset: str, source: str) -> str:
    normalized = asset.strip().upper()
    if source == COINBASE_HISTORICAL_BARRIER_SOURCE:
        return COINBASE_SYMBOLS.get(normalized, "")
    return BINANCE_SYMBOLS.get(normalized, "")


def _verified_locator_for_source(source: str, symbol: str) -> str:
    if source == COINBASE_HISTORICAL_BARRIER_SOURCE:
        return COINBASE_KLINES_LOCATOR_TEMPLATE.format(pair=symbol)
    return BINANCE_KLINES_LOCATOR


def _parse_coinbase_candle(raw: Any) -> tuple[BinanceKline | None, str]:
    """Map one Coinbase candle [time, low, high, open, close, volume] to the
    unified 1-minute row shape. Coinbase does not provide quote volume or
    trade counts; those fields persist as "0" (barrier verification uses only
    open/high/low/close prices)."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 6:
        return None, "invalid_coinbase_candle_row"
    try:
        time_seconds = int(raw[0])
        low = Decimal(str(raw[1]))
        high = Decimal(str(raw[2]))
        open_price = Decimal(str(raw[3]))
        close_price = Decimal(str(raw[4]))
        volume = Decimal(str(raw[5]))
    except (TypeError, ValueError, InvalidOperation):
        return None, "invalid_coinbase_candle_values"
    for value in (low, high, open_price, close_price, volume):
        if not value.is_finite() or value < 0:
            return None, "invalid_coinbase_candle_values"
    if time_seconds <= 0 or time_seconds % 60 != 0:
        return None, "invalid_coinbase_candle_time"
    open_time_ms = time_seconds * 1000
    return (
        BinanceKline(
            open_time_ms=open_time_ms,
            open_price=str(open_price),
            high_price=str(high),
            low_price=str(low),
            close_price=str(close_price),
            volume=str(volume),
            close_time_ms=open_time_ms + 59_999,
            quote_asset_volume="0",
            trade_count=0,
            taker_buy_base_volume="0",
            taker_buy_quote_volume="0",
            ignore="0",
        ),
        "",
    )


class CoinbaseHistoricalCandleClient:
    """Read-only Coinbase Exchange 1m candle client with fixed-range pagination.

    Implements the same fetch_klines contract as BinanceHistoricalKlineClient
    (same validation rules: minute alignment, contiguity, monotonicity,
    in-range rows) so the multi-source failover can compare like with like.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://api.exchange.coinbase.com",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        page_limit: int = COINBASE_CANDLES_PAGE_LIMIT,
        max_pages: int = 5000,
        max_concurrency: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.page_limit = max(1, min(COINBASE_CANDLES_PAGE_LIMIT, page_limit))
        self.max_pages = max(1, max_pages)
        self.max_concurrency = max(1, max_concurrency)
        self.transport = transport

    async def _get_candles(
        self,
        client: httpx.AsyncClient,
        pair: str,
        start_iso: str,
        end_iso: str,
    ) -> tuple[Any | None, str, int]:
        last_error = "coinbase_request_failed"
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(
                    f"/products/{pair}/candles",
                    params={"granularity": 60, "start": start_iso, "end": end_iso},
                )
            except httpx.TimeoutException:
                last_error = "coinbase_timeout"
            except httpx.RequestError:
                last_error = "coinbase_request_error"
            else:
                if response.status_code < 400:
                    try:
                        return response.json(), "", attempt + 1
                    except ValueError:
                        return None, "coinbase_invalid_json", attempt + 1
                last_error = f"coinbase_http_{response.status_code}"
                if response.status_code != 429 and response.status_code < 500:
                    return None, last_error, attempt + 1
            if attempt < self.max_retries and self.retry_backoff_seconds:
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
        return None, last_error, self.max_retries + 1

    async def fetch_klines(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> BinanceKlineFetchResult:
        start = _aware_utc(start_time)
        end = _aware_utc(end_time)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        normalized_start = _iso_utc(start)
        normalized_end = _iso_utc(end)
        locator = COINBASE_KLINES_LOCATOR_TEMPLATE.format(pair=symbol)

        def empty_result(status: str, error: str = "") -> BinanceKlineFetchResult:
            return BinanceKlineFetchResult(
                status=status,
                source=COINBASE_HISTORICAL_BARRIER_SOURCE,
                locator=locator,
                symbol=symbol,
                start_time=normalized_start,
                end_time=normalized_end,
                error=error,
            )

        if symbol not in set(COINBASE_SYMBOLS.values()):
            return empty_result("unsupported_coinbase_symbol")
        if start >= end:
            return empty_result("invalid_kline_fetch_range")
        if start_ms % BINANCE_INTERVAL_MS:
            return empty_result("kline_start_not_minute_aligned")

        expected_total = math.ceil((end_ms - start_ms) / BINANCE_INTERVAL_MS)
        page_count = math.ceil(expected_total / self.page_limit)
        if page_count > self.max_pages:
            return empty_result("kline_page_limit_exceeded")

        chunks: list[tuple[int, int, tuple[int, ...]]] = []
        cursor = start_ms
        while cursor < end_ms:
            chunk_end = min(cursor + self.page_limit * BINANCE_INTERVAL_MS, end_ms)
            expected = tuple(range(cursor, chunk_end, BINANCE_INTERVAL_MS))
            chunks.append((cursor, chunk_end, expected))
            cursor = chunk_end if chunk_end % BINANCE_INTERVAL_MS == 0 else end_ms

        request_started = utc_now()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            semaphore = asyncio.Semaphore(self.max_concurrency)

            async def fetch_chunk(
                sequence: int,
                chunk: tuple[int, int, tuple[int, ...]],
            ) -> tuple[BinanceKlinePageAudit, tuple[BinanceKline, ...], tuple[int, ...]]:
                chunk_start, chunk_end, expected = chunk
                start_iso = _iso_utc(datetime.fromtimestamp(chunk_start / 1000, tz=UTC))
                end_iso = _iso_utc(datetime.fromtimestamp((chunk_end - 1) / 1000, tz=UTC))
                async with semaphore:
                    payload, error, attempts = await self._get_candles(
                        client, symbol, start_iso, end_iso
                    )
                if error:
                    return (
                        BinanceKlinePageAudit(
                            sequence=sequence,
                            requested_start_ms=chunk_start,
                            requested_end_ms=chunk_end,
                            expected_candle_count=len(expected),
                            received_candle_count=0,
                            attempts=attempts,
                            status="error",
                            error=error,
                        ),
                        (),
                        expected,
                    )
                if not isinstance(payload, list):
                    error = "invalid_candle_page_payload"
                    return (
                        BinanceKlinePageAudit(
                            sequence=sequence,
                            requested_start_ms=chunk_start,
                            requested_end_ms=chunk_end,
                            expected_candle_count=len(expected),
                            received_candle_count=0,
                            attempts=attempts,
                            status="error",
                            error=error,
                        ),
                        (),
                        expected,
                    )

                candles: list[BinanceKline] = []
                row_error = ""
                for raw in payload:
                    candle, row_error = _parse_coinbase_candle(raw)
                    if row_error or candle is None:
                        break
                    candles.append(candle)
                received_opens = tuple(candle.open_time_ms for candle in candles)
                missing = tuple(
                    open_time for open_time in expected if open_time not in received_opens
                )
                if row_error:
                    status = "error"
                elif len(set(received_opens)) != len(received_opens):
                    row_error = "duplicate_klines"
                    status = "error"
                elif any(open_time not in expected for open_time in received_opens):
                    row_error = "out_of_range_klines"
                    status = "error"
                elif missing:
                    status = "partial"
                else:
                    status = "complete"
                return (
                    BinanceKlinePageAudit(
                        sequence=sequence,
                        requested_start_ms=chunk_start,
                        requested_end_ms=chunk_end,
                        expected_candle_count=len(expected),
                        received_candle_count=len(candles),
                        attempts=attempts,
                        status=status,
                        error=row_error,
                    ),
                    tuple(candles),
                    missing,
                )

            pages: list[BinanceKlinePageAudit] = []
            candle_lists: list[tuple[BinanceKline, ...]] = []
            missing_lists: list[tuple[int, ...]] = []
            errors: list[str] = []

            results = await asyncio.gather(
                *(fetch_chunk(i, chunk) for i, chunk in enumerate(chunks))
            )
            for page_audit, page_candles, page_missing in results:
                pages.append(page_audit)
                candle_lists.append(page_candles)
                missing_lists.append(page_missing)
                if page_audit.error:
                    errors.append(page_audit.error)

        request_finished = utc_now()
        candles = tuple(
            candle
            for page in candle_lists
            for candle in sorted(page, key=lambda c: c.open_time_ms)
        )
        missing_opens = tuple(
            open_time for page in missing_lists for open_time in page
        )
        if errors:
            error = errors[0]
            status = "error"
        elif missing_opens:
            status = "partial_coverage"
            error = status
        else:
            all_opens = tuple(candle.open_time_ms for candle in candles)
            expected_opens = tuple(range(start_ms, end_ms, BINANCE_INTERVAL_MS))
            if all_opens != expected_opens:
                status = "non_contiguous_kline_coverage"
                error = status
            else:
                status = "complete"
                error = ""

        return BinanceKlineFetchResult(
            status=status,
            source=COINBASE_HISTORICAL_BARRIER_SOURCE,
            locator=locator,
            server_time_before=_iso_utc(request_started),
            server_time_after=_iso_utc(request_finished),
            pages=pages,
            candles=candles,
            missing_ranges=_missing_ranges(missing_opens, end_ms),
            error=error,
            symbol=symbol,
            start_time=normalized_start,
            end_time=normalized_end,
        )


class MultiSourceHistoricalKlineClient:
    """Failover kline client: Binance primary, Coinbase fallback (ADR-027).

    Failover triggers ONLY on source-level failures (HTTP errors, timeouts,
    invalid responses). Range-level outcomes (partial coverage, contiguity
    problems) are data properties that would fail identically on the fallback,
    so the primary result is returned unchanged for auditability.
    """

    def __init__(
        self,
        *,
        binance: BinanceHistoricalKlineClient | None = None,
        coinbase: CoinbaseHistoricalCandleClient | None = None,
    ):
        self.binance = binance or BinanceHistoricalKlineClient()
        self.coinbase = coinbase or CoinbaseHistoricalCandleClient()
        self._asset_by_binance_symbol = {v: k for k, v in BINANCE_SYMBOLS.items()}

    async def fetch_klines(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> BinanceKlineFetchResult:
        primary = await self.binance.fetch_klines(
            symbol=symbol, start_time=start_time, end_time=end_time
        )
        if primary.status == "complete":
            return primary
        source_failure = primary.error.startswith("binance_http_") or primary.error in {
            "binance_timeout",
            "binance_request_error",
            "binance_request_failed",
            "binance_invalid_json",
            "invalid_binance_server_time",
        }
        if not source_failure:
            return primary
        asset = self._asset_by_binance_symbol.get(symbol)
        if asset is None:
            return primary
        fallback = await self.coinbase.fetch_klines(
            symbol=COINBASE_SYMBOLS[asset], start_time=start_time, end_time=end_time
        )
        return fallback if fallback.status == "complete" else primary


def _write_content_addressed(
    directory: Path,
    prefix: str,
    content: bytes,
) -> tuple[Path, str]:
    digest = hashlib.sha256(content).hexdigest()
    directory = directory.absolute()
    path = directory / f"{prefix}_{digest}.json"
    if any(candidate.is_symlink() for candidate in (directory, *directory.parents)):
        raise HistoricalArtifactConflictError(
            f"historical artifact directory contains a symlink: {directory}"
        )
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir() or path.is_symlink():
        raise HistoricalArtifactConflictError(
            f"content-addressed historical artifact path is unsafe: {path}"
        )
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise HistoricalArtifactConflictError(
                f"content-addressed historical artifact conflicts with existing file: {path}"
            ) from exc
    return path, digest


def persist_historical_candle_snapshot(
    fetch_result: BinanceKlineFetchResult,
    output_dir: Path,
) -> HistoricalCandleSnapshotReference:
    """Serialize and persist one shared fetch result exactly once per discovery batch."""

    content = canonical_json_bytes(fetch_result.model_dump(mode="json"))
    path, digest = _write_content_addressed(
        output_dir / "historical_barrier_candles",
        "binance_1m",
        content,
    )
    return HistoricalCandleSnapshotReference(
        path=path.resolve(),
        sha256=digest,
        fetch_result_identity=id(fetch_result),
    )


class _CandleRecomputation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    expected_candle_count: int = 0
    observed_candle_count: int = 0
    missing_ranges: tuple[str, ...] = ()
    duplicate_open_times: tuple[str, ...] = ()
    ordering_status: str = ""
    ohlc_status: str = ""
    min_low_price: str = ""
    max_high_price: str = ""
    tail_coverage_status: str = ""
    tail_covered_through: str = ""
    first_touch_at: str = ""


@dataclass(frozen=True)
class HistoricalCandleAuditReference:
    """Reusable structural candle audit bound to one in-memory fetch result."""

    fetch_result_identity: int
    start_time: str
    entry_time: str
    structural_audit: _CandleRecomputation
    open_times: tuple[int, ...]
    lows: tuple[Decimal, ...]
    highs: tuple[Decimal, ...]


def _candle_as_raw_row(candle: BinanceKline | Mapping[str, Any]) -> list[Any] | None:
    if isinstance(candle, BinanceKline):
        values = candle.model_dump(mode="python")
    elif isinstance(candle, Mapping):
        values = dict(candle)
    else:
        return None
    expected_fields = tuple(BinanceKline.model_fields)
    if set(values) != set(expected_fields):
        return None
    return [
        values["open_time_ms"],
        values["open_price"],
        values["high_price"],
        values["low_price"],
        values["close_price"],
        values["volume"],
        values["close_time_ms"],
        values["quote_asset_volume"],
        values["trade_count"],
        values["taker_buy_base_volume"],
        values["taker_buy_quote_volume"],
        values["ignore"],
    ]


def _recompute_candles(
    *,
    candles: Sequence[BinanceKline],
    start: datetime | None,
    entry: datetime | None,
    barrier_direction: str,
    threshold: Decimal | None,
) -> _CandleRecomputation:
    observed_count = len(candles)
    if start is None or entry is None or start >= entry:
        return _CandleRecomputation(
            status="invalid_historical_barrier_evidence_range",
            observed_candle_count=observed_count,
        )
    if start.second or start.microsecond:
        return _CandleRecomputation(
            status="historical_barrier_start_not_minute_aligned",
            observed_candle_count=observed_count,
            tail_coverage_status="invalid_start_grid",
        )
    if entry.second or entry.microsecond:
        return _CandleRecomputation(
            status="historical_barrier_entry_not_minute_aligned",
            observed_candle_count=observed_count,
            tail_coverage_status="uncovered_entry_tail",
        )

    start_ms = int(start.timestamp() * 1000)
    entry_ms = int(entry.timestamp() * 1000)
    expected_opens = tuple(range(start_ms, entry_ms, BINANCE_INTERVAL_MS))
    expected_count = len(expected_opens)
    parsed: list[BinanceKline] = []
    ohlc_status = "valid"
    for candle in candles:
        raw_row = _candle_as_raw_row(candle)
        parsed_candle, error = parse_binance_kline(raw_row)
        if error or parsed_candle is None:
            ohlc_status = error or "invalid_kline_row"
            break
        parsed.append(parsed_candle)

    opens = tuple(candle.open_time_ms for candle in parsed)
    counts: dict[int, int] = {}
    for open_time in opens:
        counts[open_time] = counts.get(open_time, 0) + 1
    duplicates = tuple(_ms_iso(value) for value, count in sorted(counts.items()) if count > 1)
    ordering_status = "strictly_increasing"
    if duplicates:
        ordering_status = "duplicate_open_times"
    elif opens != tuple(sorted(opens)):
        ordering_status = "non_monotonic_open_times"
    missing_opens = tuple(value for value in expected_opens if value not in counts)
    missing_ranges = _missing_ranges(missing_opens, entry_ms)
    expected_open_set = set(expected_opens)
    out_of_range = tuple(value for value in opens if value not in expected_open_set)

    min_low = ""
    max_high = ""
    first_touch_at = ""
    if parsed:
        lows = [Decimal(candle.low_price) for candle in parsed]
        highs = [Decimal(candle.high_price) for candle in parsed]
        min_low = str(min(lows))
        max_high = str(max(highs))
        if threshold is not None and threshold.is_finite() and threshold > 0:
            for candle, low, high in zip(parsed, lows, highs, strict=True):
                touched = high >= threshold if barrier_direction == "up" else low <= threshold
                if touched:
                    first_touch_at = _ms_iso(candle.open_time_ms)
                    break

    tail_status = "closed_through_entry"
    tail_covered_through = _iso_utc(entry)
    status = "complete"
    if ohlc_status != "valid":
        status = ohlc_status
        tail_status = "invalid_candle_data"
        tail_covered_through = ""
    elif duplicates:
        status = "duplicate_klines"
        tail_status = "invalid_candle_grid"
        tail_covered_through = ""
    elif ordering_status != "strictly_increasing":
        status = "non_monotonic_klines"
        tail_status = "invalid_candle_grid"
        tail_covered_through = ""
    elif out_of_range:
        status = "out_of_range_klines"
        tail_status = "invalid_candle_grid"
        tail_covered_through = ""
    elif missing_opens or len(opens) != expected_count:
        status = "partial_coverage"
        tail_status = "missing_closed_candle_tail"
        tail_covered_through = ""
    elif not parsed or parsed[-1].close_time_ms != entry_ms - 1:
        status = "historical_barrier_uncovered_entry_tail"
        tail_status = "missing_closed_candle_tail"
        tail_covered_through = ""

    return _CandleRecomputation(
        status=status,
        expected_candle_count=expected_count,
        observed_candle_count=observed_count,
        missing_ranges=missing_ranges,
        duplicate_open_times=duplicates,
        ordering_status=ordering_status,
        ohlc_status=ohlc_status,
        min_low_price=min_low,
        max_high_price=max_high,
        tail_coverage_status=tail_status,
        tail_covered_through=tail_covered_through,
        first_touch_at=first_touch_at,
    )


def prepare_historical_candle_audit(
    fetch_result: BinanceKlineFetchResult,
    *,
    start_time: datetime,
    entry_time: datetime,
) -> HistoricalCandleAuditReference:
    """Validate a shared candle grid once before threshold-specific evaluations."""

    start = _aware_utc(start_time)
    entry = _aware_utc(entry_time)
    audit = _recompute_candles(
        candles=fetch_result.candles,
        start=start,
        entry=entry,
        barrier_direction="up",
        threshold=None,
    )
    try:
        lows = tuple(Decimal(candle.low_price) for candle in fetch_result.candles)
        highs = tuple(Decimal(candle.high_price) for candle in fetch_result.candles)
    except InvalidOperation:
        lows = ()
        highs = ()
    return HistoricalCandleAuditReference(
        fetch_result_identity=id(fetch_result),
        start_time=_iso_utc(start),
        entry_time=_iso_utc(entry),
        structural_audit=audit,
        open_times=tuple(candle.open_time_ms for candle in fetch_result.candles),
        lows=lows,
        highs=highs,
    )


_MANIFEST_BINDING_FIELDS = (
    "resolution_rules",
    "resolution_rules_sha256",
    "expected_expiry_time",
    "expiry_local_time",
    "expiry_timezone",
    "expiry_time_origin",
    "expiry_time_adapter_version",
    "expiry_time_provenance_sha256",
    "expiry_status",
    "gamma_start_date",
    "gamma_end_date",
    "gamma_market_updated_at",
    "gamma_market_schema",
    "gamma_market_version",
)


def _manifest_binding(
    *,
    window: RuleObservationWindow,
    resolution_rules: str,
    manifest: Mapping[str, Any] | None,
) -> dict[str, str]:
    source = manifest or {}
    rules = str(source.get("resolution_rules") or resolution_rules or "")
    gamma_start = source.get("gamma_start_date") or source.get("startDate") or ""
    values = {
        "resolution_rules": rules,
        "resolution_rules_sha256": window.rules_sha256,
        "expected_expiry_time": str(source.get("expiry_time") or window.end_time or ""),
        "expiry_local_time": str(source.get("expiry_local_time") or ""),
        "expiry_timezone": str(source.get("expiry_timezone") or ""),
        "expiry_time_origin": str(source.get("expiry_time_origin") or ""),
        "expiry_time_adapter_version": str(source.get("expiry_time_adapter_version") or ""),
        "expiry_time_provenance_sha256": str(source.get("expiry_time_provenance_sha256") or ""),
        "expiry_status": str(source.get("expiry_status") or ""),
        "gamma_start_date": str(gamma_start),
        "gamma_end_date": str(source.get("gamma_end_date") or ""),
        "gamma_market_updated_at": str(source.get("gamma_market_updated_at") or ""),
        "gamma_market_schema": str(source.get("gamma_market_schema") or ""),
        "gamma_market_version": str(source.get("gamma_market_version") or ""),
    }
    return {field: values[field] for field in _MANIFEST_BINDING_FIELDS}


def not_required_historical_evidence() -> HistoricalBarrierEvidence:
    return HistoricalBarrierEvidence(
        status=HISTORICAL_BARRIER_STATUS_NOT_REQUIRED,
        adapter_version=HISTORICAL_BARRIER_ADAPTER_VERSION,
        rule_window_adapter_version=RULE_WINDOW_ADAPTER_VERSION,
    )


def unavailable_historical_evidence(
    window: RuleObservationWindow,
    status: str | None = None,
) -> HistoricalBarrierEvidence:
    return HistoricalBarrierEvidence(
        status=status or window.status or "missing_historical_barrier_evidence",
        start_time=window.start_time,
        adapter_version=HISTORICAL_BARRIER_ADAPTER_VERSION,
        rule_window_adapter_version=window.adapter_version,
        rule_window_provenance_sha256=window.provenance_sha256,
    )


def merge_kline_fetch_results(
    base: BinanceKlineFetchResult,
    tail: BinanceKlineFetchResult,
    *,
    start_time: datetime,
    end_time: datetime,
) -> BinanceKlineFetchResult:
    """Merge an expensive preload with a fresh overlapping entry-time tail."""

    start = _aware_utc(start_time)
    end = _aware_utc(end_time)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    base_start = _parse_utc(base.start_time)
    base_end = _parse_utc(base.end_time)
    tail_start = _parse_utc(tail.start_time)
    tail_end = _parse_utc(tail.end_time)
    base_server_before = _parse_utc(base.server_time_before)
    base_server_after = _parse_utc(base.server_time_after)
    tail_server_before = _parse_utc(tail.server_time_before)
    tail_server_after = _parse_utc(tail.server_time_after)
    status = "complete"
    error = ""
    if start.second or start.microsecond:
        status = "historical_barrier_start_not_minute_aligned"
        error = status
    elif end.second or end.microsecond:
        status = "historical_barrier_entry_not_minute_aligned"
        error = status
    elif base.status != "complete":
        status = base.status
        error = base.error or base.status
    elif tail.status != "complete":
        status = tail.status
        error = tail.error or tail.status
    elif base.symbol != tail.symbol:
        status = "merged_kline_symbol_mismatch"
        error = status
    elif base.interval != BINANCE_INTERVAL or tail.interval != BINANCE_INTERVAL:
        status = "merged_kline_interval_mismatch"
        error = status
    elif (
        not base.source
        or base.source != tail.source
        or base.source not in VERIFIED_HISTORICAL_BARRIER_SOURCES
        or base.locator != tail.locator
        or base.locator != _verified_locator_for_source(base.source, base.symbol)
    ):
        status = "merged_kline_source_mismatch"
        error = status
    elif base_start != start:
        status = "merged_kline_start_mismatch"
        error = status
    elif tail_end != end:
        status = "merged_kline_end_mismatch"
        error = status
    elif (
        base_end is None
        or tail_start is None
        or tail_start < start
        or tail_start > base_end
        or base_end > end
    ):
        status = "merged_kline_overlap_range_mismatch"
        error = status
    elif (
        base_server_before is None
        or base_server_after is None
        or tail_server_before is None
        or tail_server_after is None
        or base_server_after < base_server_before
        or tail_server_after < tail_server_before
        or tail_server_after < base_server_after
        or tail_server_after < end
    ):
        status = "merged_kline_server_time_mismatch"
        error = status

    base_by_open = {candle.open_time_ms: candle for candle in base.candles}
    tail_by_open = {candle.open_time_ms: candle for candle in tail.candles}
    if status == "complete" and (
        len(base_by_open) != len(base.candles) or len(tail_by_open) != len(tail.candles)
    ):
        status = "merged_kline_duplicate_klines"
        error = status
    overlap = set(base_by_open).intersection(tail_by_open)
    if status == "complete" and any(
        base_by_open[open_time] != tail_by_open[open_time] for open_time in overlap
    ):
        status = "merged_kline_overlap_conflict"
        error = status
    by_open_time = dict(base_by_open)
    by_open_time.update(tail_by_open)
    expected_opens = tuple(range(start_ms, end_ms, BINANCE_INTERVAL_MS))
    missing_opens = tuple(
        open_time for open_time in expected_opens if open_time not in by_open_time
    )
    candles = tuple(
        by_open_time[open_time] for open_time in expected_opens if open_time in by_open_time
    )
    if status == "complete" and missing_opens:
        status = "partial_coverage"
        error = status

    pages = tuple(
        page.model_copy(update={"sequence": sequence})
        for sequence, page in enumerate((*base.pages, *tail.pages), start=1)
    )
    return BinanceKlineFetchResult(
        status=status,
        source=base.source,
        locator=base.locator,
        symbol=base.symbol,
        interval=BINANCE_INTERVAL,
        start_time=_iso_utc(start),
        end_time=_iso_utc(end),
        server_time_before=base.server_time_before,
        server_time_after=tail.server_time_after,
        pages=pages,
        candles=candles,
        missing_ranges=_missing_ranges(missing_opens, end_ms),
        error=error,
    )


def evaluate_historical_barrier(
    *,
    asset: str,
    barrier_direction: Literal["up", "down"],
    threshold_price: Decimal | str | float,
    entry_time: datetime,
    window: RuleObservationWindow,
    fetch_result: BinanceKlineFetchResult,
    output_dir: Path,
    resolution_rules: str = "",
    manifest: Mapping[str, Any] | None = None,
    candle_snapshot: HistoricalCandleSnapshotReference | None = None,
    candle_audit: HistoricalCandleAuditReference | None = None,
) -> HistoricalBarrierEvidence:
    """Persist source/evaluation artifacts and fail closed on any incomplete evidence."""

    entry = _aware_utc(entry_time)
    expected_symbol = _expected_symbol_for_source(asset.strip().upper(), fetch_result.source)
    try:
        threshold = Decimal(str(threshold_price))
    except InvalidOperation:
        threshold = Decimal(0)
    window_end = _parse_utc(window.end_time)
    window_start = _parse_utc(window.start_time)
    fetch_end = _parse_utc(fetch_result.end_time)
    fetch_server_after = _parse_utc(fetch_result.server_time_after)
    manifest_binding = _manifest_binding(
        window=window,
        resolution_rules=resolution_rules,
        manifest=manifest,
    )
    raw_rules = manifest_binding["resolution_rules"]
    expected_expiry = manifest_binding["expected_expiry_time"]
    reparsed_window = (
        parse_rule_observation_window(raw_rules, expected_expiry) if raw_rules else None
    )
    if candle_audit is None:
        audit = _recompute_candles(
            candles=fetch_result.candles,
            start=window_start,
            entry=entry,
            barrier_direction=barrier_direction,
            threshold=threshold,
        )
    else:
        if (
            candle_audit.fetch_result_identity != id(fetch_result)
            or candle_audit.start_time != window.start_time
            or candle_audit.entry_time != _iso_utc(entry)
        ):
            raise ValueError("candle audit reference does not match fetch result range")
        first_touch_at = ""
        if (
            threshold.is_finite()
            and threshold > 0
            and barrier_direction in {"up", "down"}
            and len(candle_audit.open_times) == len(candle_audit.lows) == len(candle_audit.highs)
        ):
            for open_time, low, high in zip(
                candle_audit.open_times,
                candle_audit.lows,
                candle_audit.highs,
                strict=True,
            ):
                touched = high >= threshold if barrier_direction == "up" else low <= threshold
                if touched:
                    first_touch_at = _ms_iso(open_time)
                    break
        audit = candle_audit.structural_audit.model_copy(update={"first_touch_at": first_touch_at})

    status = HISTORICAL_BARRIER_STATUS_VERIFIED
    if window.status != "verified":
        status = window.status or "rule_window_not_verified"
    elif reparsed_window is None:
        status = "missing_resolution_rules"
    elif reparsed_window != window:
        status = "historical_barrier_rule_window_manifest_mismatch"
    elif not expected_symbol or fetch_result.symbol != expected_symbol:
        status = "historical_evidence_symbol_mismatch"
    elif barrier_direction not in {"up", "down"}:
        status = "unverifiable_barrier_direction"
    elif not threshold.is_finite() or threshold <= 0:
        status = "invalid_barrier_threshold"
    elif fetch_result.status != "complete":
        status = fetch_result.status or "partial_coverage"
    elif fetch_result.interval != BINANCE_INTERVAL:
        status = "historical_evidence_interval_mismatch"
    elif fetch_result.source not in VERIFIED_HISTORICAL_BARRIER_SOURCES:
        status = "historical_evidence_source_mismatch"
    elif fetch_result.locator != _verified_locator_for_source(
        fetch_result.source, fetch_result.symbol
    ):
        status = "historical_evidence_locator_mismatch"
    elif fetch_result.start_time != window.start_time:
        status = "historical_evidence_start_mismatch"
    elif fetch_end != entry:
        status = "historical_evidence_end_mismatch"
    elif window_end is None:
        status = "invalid_rule_window_end_time"
    elif entry > window_end:
        status = "historical_evidence_after_expiry"
    elif fetch_server_after is None or fetch_server_after < entry:
        status = "historical_evidence_server_time_before_entry"
    elif fetch_result.missing_ranges:
        status = "partial_coverage"
    elif audit.status != "complete":
        status = audit.status

    if candle_snapshot is None:
        candle_snapshot = persist_historical_candle_snapshot(fetch_result, output_dir)
    expected_candle_dir = (output_dir / "historical_barrier_candles").resolve()
    if (
        candle_snapshot.fetch_result_identity != id(fetch_result)
        or candle_snapshot.path.parent != expected_candle_dir
        or candle_snapshot.path.name != f"binance_1m_{candle_snapshot.sha256}.json"
        or not _SHA256_RE.fullmatch(candle_snapshot.sha256)
        or not candle_snapshot.path.is_file()
        or candle_snapshot.path.is_symlink()
    ):
        raise ValueError("candle snapshot reference does not match fetch result")
    candle_path = candle_snapshot.path
    candle_digest = candle_snapshot.sha256

    barrier_crossed_at = audit.first_touch_at
    if status == HISTORICAL_BARRIER_STATUS_VERIFIED and barrier_crossed_at:
        status = "barrier_already_crossed"

    evidence_material = {
        "schema_version": HISTORICAL_BARRIER_SCHEMA_VERSION,
        "adapter_version": HISTORICAL_BARRIER_ADAPTER_VERSION,
        "origin": HISTORICAL_BARRIER_ORIGIN,
        "source": fetch_result.source,
        "locator": fetch_result.locator,
        "asset": asset.strip().upper(),
        "symbol": fetch_result.symbol,
        "interval": fetch_result.interval,
        "barrier_direction": barrier_direction,
        "threshold_price": str(threshold),
        "entry_time": _iso_utc(entry),
        "window": window.model_dump(mode="json"),
        "manifest_binding": manifest_binding,
        "fetch_status": fetch_result.status,
        "candle_snapshot_sha256": candle_digest,
        "expected_candle_count": audit.expected_candle_count,
        "candle_count": len(fetch_result.candles),
        "missing_ranges": list(fetch_result.missing_ranges),
        "recomputed_missing_ranges": list(audit.missing_ranges),
        "duplicate_open_times": list(audit.duplicate_open_times),
        "ordering_status": audit.ordering_status,
        "ohlc_status": audit.ohlc_status,
        "min_low_price": audit.min_low_price,
        "max_high_price": audit.max_high_price,
        "tail_coverage_status": audit.tail_coverage_status,
        "tail_covered_through": audit.tail_covered_through,
        "first_touch_at": audit.first_touch_at,
        "barrier_crossed_at": barrier_crossed_at,
        "status": status,
    }
    evidence_content = canonical_json_bytes(evidence_material)
    evidence_path, evidence_digest = _write_content_addressed(
        output_dir / "historical_barrier_evidence",
        "evidence",
        evidence_content,
    )
    return HistoricalBarrierEvidence(
        status=status,
        source=HISTORICAL_BARRIER_SOURCE,
        start_time=window.start_time,
        end_time=_iso_utc(entry),
        sha256=evidence_digest,
        origin=HISTORICAL_BARRIER_ORIGIN,
        locator=BINANCE_KLINES_LOCATOR,
        interval=fetch_result.interval,
        symbol=fetch_result.symbol,
        candle_count=len(fetch_result.candles),
        missing_ranges=fetch_result.missing_ranges,
        evidence_path=str(evidence_path.resolve()),
        candle_snapshot_path=str(candle_path.resolve()),
        candle_snapshot_sha256=candle_digest,
        rule_window_provenance_sha256=window.provenance_sha256,
        barrier_crossed_at=barrier_crossed_at,
        expected_candle_count=audit.expected_candle_count,
        min_low_price=audit.min_low_price,
        max_high_price=audit.max_high_price,
        tail_coverage_status=audit.tail_coverage_status,
        tail_covered_through=audit.tail_covered_through,
        first_touch_at=audit.first_touch_at,
    )


def historical_evidence_candidate_fields(evidence: HistoricalBarrierEvidence) -> dict[str, Any]:
    return {
        "historical_barrier_evidence_status": evidence.status,
        "historical_barrier_evidence_source": evidence.source,
        "historical_barrier_evidence_start_time": evidence.start_time,
        "historical_barrier_evidence_end_time": evidence.end_time,
        "historical_barrier_evidence_sha256": evidence.sha256,
        "historical_barrier_evidence_adapter_version": evidence.adapter_version,
        "historical_barrier_evidence_origin": evidence.origin,
        "historical_barrier_evidence_locator": evidence.locator,
        "historical_barrier_evidence_interval": evidence.interval,
        "historical_barrier_evidence_symbol": evidence.symbol,
        "historical_barrier_evidence_candle_count": evidence.candle_count,
        "historical_barrier_evidence_missing_ranges": json.dumps(
            list(evidence.missing_ranges), separators=(",", ":")
        ),
        "historical_barrier_evidence_path": evidence.evidence_path,
        "historical_barrier_candle_snapshot_path": evidence.candle_snapshot_path,
        "historical_barrier_candle_snapshot_sha256": evidence.candle_snapshot_sha256,
        "historical_barrier_rule_window_adapter_version": (evidence.rule_window_adapter_version),
        "historical_barrier_rule_window_provenance_sha256": (
            evidence.rule_window_provenance_sha256
        ),
        "historical_barrier_crossed_at": evidence.barrier_crossed_at,
        "historical_barrier_expected_candle_count": evidence.expected_candle_count,
        "historical_barrier_min_low_price": evidence.min_low_price,
        "historical_barrier_max_high_price": evidence.max_high_price,
        "historical_barrier_tail_coverage_status": evidence.tail_coverage_status,
        "historical_barrier_tail_covered_through": evidence.tail_covered_through,
        "historical_barrier_first_touch_at": evidence.first_touch_at,
    }


class _ManifestBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution_rules: str
    resolution_rules_sha256: str
    expected_expiry_time: str
    expiry_local_time: str
    expiry_timezone: str
    expiry_time_origin: str
    expiry_time_adapter_version: str
    expiry_time_provenance_sha256: str
    expiry_status: str
    gamma_start_date: str
    gamma_end_date: str
    gamma_market_updated_at: str
    gamma_market_schema: str
    gamma_market_version: str


class _HistoricalEvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    adapter_version: str
    origin: str
    source: str
    locator: str
    asset: str
    symbol: str
    interval: str
    barrier_direction: str
    threshold_price: str
    entry_time: str
    window: RuleObservationWindow
    manifest_binding: _ManifestBinding
    fetch_status: str
    candle_snapshot_sha256: str
    expected_candle_count: int
    candle_count: int
    missing_ranges: tuple[str, ...]
    recomputed_missing_ranges: tuple[str, ...]
    duplicate_open_times: tuple[str, ...]
    ordering_status: str
    ohlc_status: str
    min_low_price: str
    max_high_price: str
    tail_coverage_status: str
    tail_covered_through: str
    first_touch_at: str
    barrier_crossed_at: str
    status: str


def _inferred_artifact_root(row: Mapping[str, Any]) -> Path | None:
    try:
        evidence = Path(str(row.get("historical_barrier_evidence_path") or ""))
        candles = Path(str(row.get("historical_barrier_candle_snapshot_path") or ""))
    except (TypeError, ValueError):
        return None
    if not evidence.is_absolute() or not candles.is_absolute():
        return None
    if ".." in evidence.parts or ".." in candles.parts:
        return None
    if evidence.parent.name != "historical_barrier_evidence":
        return None
    if candles.parent.name != "historical_barrier_candles":
        return None
    if evidence.parent.parent != candles.parent.parent:
        return None
    return evidence.parent.parent


def _read_hashed_json(
    path_value: Any,
    digest_value: Any,
    *,
    artifact_root: Path,
    expected_subdirectory: str,
    expected_prefix: str,
) -> tuple[dict[str, Any] | None, str]:
    digest = str(digest_value or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        return None, "invalid_digest"
    raw_path = str(path_value or "")
    if not raw_path or "\x00" in raw_path:
        return None, "invalid_path"
    try:
        supplied = Path(raw_path)
    except (TypeError, ValueError):
        return None, "invalid_path"
    if ".." in supplied.parts:
        return None, "unsafe_path"

    root = artifact_root.absolute()
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = candidate.absolute()
    expected_directory = root / expected_subdirectory
    if candidate.parent != expected_directory:
        return None, "unsafe_path"
    if candidate.name != f"{expected_prefix}_{digest}.json":
        return None, "digest_filename_mismatch"
    try:
        if not root.is_dir() or root.is_symlink():
            return None, "unsafe_root"
        if not expected_directory.is_dir() or expected_directory.is_symlink():
            return None, "unsafe_path"
        if candidate.is_symlink() or not candidate.is_file():
            return None, "unsafe_path"
        resolved_root = root.resolve(strict=True)
        resolved_directory = expected_directory.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        if (
            resolved_directory.parent != resolved_root
            or resolved_candidate.parent != resolved_directory
        ):
            return None, "unsafe_path"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "rb") as handle:
            content = handle.read()
    except (OSError, RuntimeError, ValueError):
        return None, "read_error"
    if hashlib.sha256(content).hexdigest() != digest:
        return None, "content_digest_mismatch"
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_json_shape"
    try:
        if canonical_json_bytes(payload) != content:
            return None, "noncanonical_json"
    except ValueError:
        return None, "invalid_json"
    return payload, ""


def _decimal_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return False


def _independently_parse_candles(
    candle_artifact: Mapping[str, Any],
) -> tuple[BinanceKlineFetchResult | None, tuple[BinanceKline, ...], list[str]]:
    reasons: list[str] = []
    try:
        fetch_result = BinanceKlineFetchResult.model_validate(candle_artifact)
    except ValidationError:
        return None, (), ["invalid_historical_barrier_candle_snapshot"]

    raw_candles = candle_artifact.get("candles")
    if not isinstance(raw_candles, list):
        return fetch_result, (), ["invalid_historical_barrier_candle_snapshot"]
    parsed: list[BinanceKline] = []
    for raw_candle in raw_candles:
        raw_row = _candle_as_raw_row(raw_candle) if isinstance(raw_candle, Mapping) else None
        candle, error = parse_binance_kline(raw_row)
        if error or candle is None:
            reasons.append(f"historical_barrier_candle_snapshot_{error or 'invalid_kline_row'}")
            break
        parsed.append(candle)
    if len(parsed) != len(fetch_result.candles) or any(
        parsed_candle != modeled_candle
        for parsed_candle, modeled_candle in zip(parsed, fetch_result.candles, strict=True)
    ):
        reasons.append("invalid_historical_barrier_candle_snapshot")
    return fetch_result, tuple(parsed), reasons


def _page_audit_reasons(
    fetch_result: BinanceKlineFetchResult,
    *,
    start_ms: int,
    end_ms: int,
    open_times: Sequence[int],
) -> list[str]:
    pages = fetch_result.pages
    if not pages:
        return ["historical_barrier_candle_page_audit_mismatch"]
    covered: set[int] = set()
    expected_opens = set(range(start_ms, end_ms, BINANCE_INTERVAL_MS))
    for expected_sequence, page in enumerate(pages, start=1):
        page_duration = page.requested_end_ms - page.requested_start_ms
        page_received = sum(
            page.requested_start_ms <= value < page.requested_end_ms for value in open_times
        )
        if (
            page.sequence != expected_sequence
            or page.requested_start_ms < start_ms
            or page.requested_end_ms <= page.requested_start_ms
            or page.requested_end_ms > end_ms
            or page.requested_start_ms % BINANCE_INTERVAL_MS
            or page.requested_end_ms % BINANCE_INTERVAL_MS
            or page_duration % BINANCE_INTERVAL_MS
            or page.expected_candle_count != page_duration // BINANCE_INTERVAL_MS
            or page.received_candle_count != page_received
            or page.attempts < 1
            or page.status != "complete"
            or page.error
        ):
            return ["historical_barrier_candle_page_audit_mismatch"]
        covered.update(range(page.requested_start_ms, page.requested_end_ms, BINANCE_INTERVAL_MS))
    if covered != expected_opens:
        return ["historical_barrier_candle_page_audit_mismatch"]
    return []


def _manifest_binding_reasons(
    row: Mapping[str, Any],
    artifact: _HistoricalEvidenceArtifact,
) -> tuple[RuleObservationWindow | None, list[str]]:
    reasons: list[str] = []
    raw_rules_value = row.get("resolution_rules")
    raw_rules = raw_rules_value if isinstance(raw_rules_value, str) else ""
    expected_expiry_value = row.get("expiry_time")
    expected_expiry = expected_expiry_value if isinstance(expected_expiry_value, str) else ""
    rules_digest = resolution_rules_sha256(raw_rules)
    recorded_rules_digest = str(row.get("resolution_rules_sha256") or "").lower()
    if not raw_rules:
        reasons.append("missing_resolution_rules")
    if not _SHA256_RE.fullmatch(recorded_rules_digest) or recorded_rules_digest != rules_digest:
        reasons.append("resolution_rules_sha256_mismatch")

    reparsed = parse_rule_observation_window(raw_rules, expected_expiry)
    if reparsed.status != "verified":
        reasons.append(reparsed.status or "historical_barrier_rule_window_not_verified")
    if reparsed != artifact.window:
        reasons.append("historical_barrier_rule_window_artifact_binding_mismatch")

    expected_binding = {
        "resolution_rules": raw_rules,
        "resolution_rules_sha256": recorded_rules_digest,
        "expected_expiry_time": expected_expiry,
        "expiry_local_time": str(row.get("expiry_local_time") or ""),
        "expiry_timezone": str(row.get("expiry_timezone") or ""),
        "expiry_time_origin": str(row.get("expiry_time_origin") or ""),
        "expiry_time_adapter_version": str(row.get("expiry_time_adapter_version") or ""),
        "expiry_time_provenance_sha256": str(row.get("expiry_time_provenance_sha256") or ""),
        "expiry_status": str(row.get("expiry_status") or ""),
        "gamma_start_date": str(row.get("gamma_start_date") or ""),
        "gamma_end_date": str(row.get("gamma_end_date") or ""),
        "gamma_market_updated_at": str(row.get("gamma_market_updated_at") or ""),
        "gamma_market_schema": str(row.get("gamma_market_schema") or ""),
        "gamma_market_version": str(row.get("gamma_market_version") or ""),
    }
    if artifact.manifest_binding.model_dump(mode="python") != expected_binding:
        reasons.append("historical_barrier_manifest_provenance_mismatch")

    gamma_start_raw = expected_binding["gamma_start_date"]
    if gamma_start_raw:
        gamma_start = _parse_utc(gamma_start_raw)
        explicit_start = _parse_utc(reparsed.start_time)
        if gamma_start is None:
            reasons.append("invalid_gamma_start_date")
        elif explicit_start is None:
            reasons.append("gamma_start_date_cannot_substitute_rule_start")

    if expected_binding["expiry_time_adapter_version"]:
        reasons.extend(expiry_integrity_reasons(dict(row)))
    return (reparsed if reparsed.status == "verified" else None), reasons


def _row_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if str(value).strip() == str(parsed) else None


def historical_evidence_integrity_reasons(
    row: dict[str, Any],
    artifact_root: Path | None = None,
) -> list[str]:
    """Independently reconstruct historical barrier evidence without network access."""

    status = str(row.get("historical_barrier_evidence_status") or "").strip()
    contract_kind = str(row.get("contract_kind") or "").strip()
    reasons: list[str] = []
    if contract_kind != "touch_before_expiry":
        if status != HISTORICAL_BARRIER_STATUS_NOT_REQUIRED:
            reasons.append("invalid_settlement_historical_barrier_evidence_status")
        return reasons
    if status != HISTORICAL_BARRIER_STATUS_VERIFIED:
        return [status or "missing_historical_barrier_evidence"]

    expected_metadata = (
        (
            "historical_barrier_evidence_adapter_version",
            HISTORICAL_BARRIER_ADAPTER_VERSION,
            "historical_barrier_evidence_adapter_version_mismatch",
        ),
        (
            "historical_barrier_evidence_origin",
            HISTORICAL_BARRIER_ORIGIN,
            "historical_barrier_evidence_origin_mismatch",
        ),
        (
            "historical_barrier_evidence_source",
            HISTORICAL_BARRIER_SOURCE,
            "historical_barrier_evidence_source_mismatch",
        ),
        (
            "historical_barrier_evidence_locator",
            BINANCE_KLINES_LOCATOR,
            "historical_barrier_evidence_locator_mismatch",
        ),
        (
            "historical_barrier_evidence_interval",
            BINANCE_INTERVAL,
            "historical_barrier_evidence_interval_mismatch",
        ),
        (
            "historical_barrier_rule_window_adapter_version",
            RULE_WINDOW_ADAPTER_VERSION,
            "historical_barrier_rule_window_adapter_version_mismatch",
        ),
    )
    for field, expected, reason in expected_metadata:
        if str(row.get(field) or "") != expected:
            reasons.append(reason)

    asset = str(row.get("asset") or "").strip().upper()
    expected_symbol = BINANCE_SYMBOLS.get(asset)
    recorded_symbol = str(row.get("historical_barrier_evidence_symbol") or "")
    if not expected_symbol or recorded_symbol != expected_symbol:
        reasons.append("historical_barrier_evidence_symbol_mismatch")
    direction = str(row.get("barrier_direction") or "").strip()
    if direction not in {"up", "down"}:
        reasons.append("unverifiable_barrier_direction")
    try:
        threshold = Decimal(str(row.get("threshold_price")))
    except InvalidOperation:
        threshold = Decimal(0)
    if not threshold.is_finite() or threshold <= 0:
        reasons.append("invalid_barrier_threshold")

    start = _parse_utc(row.get("historical_barrier_evidence_start_time"))
    entry = _parse_utc(row.get("historical_barrier_evidence_end_time"))
    expiry = _parse_utc(row.get("expiry_time"))
    if start is None or entry is None or start >= entry:
        reasons.append("invalid_historical_barrier_evidence_range")
    if expiry is None or entry is None or entry > expiry:
        reasons.append("historical_barrier_evidence_after_expiry")
    for entry_field in ("entry_time", "timestamp"):
        candidate_entry = row.get(entry_field)
        if candidate_entry not in (None, ""):
            parsed_candidate_entry = _parse_utc(candidate_entry)
            if parsed_candidate_entry is None or parsed_candidate_entry != entry:
                reasons.append("historical_barrier_entry_time_mismatch")
            break

    candle_count = _row_integer(row.get("historical_barrier_evidence_candle_count"))
    expected_count = _row_integer(row.get("historical_barrier_expected_candle_count"))
    if candle_count is None or candle_count <= 0:
        reasons.append("invalid_historical_barrier_evidence_candle_count")
        candle_count = 0
    if expected_count is None or expected_count <= 0:
        reasons.append("invalid_historical_barrier_expected_candle_count")
        expected_count = 0
    raw_missing_ranges = row.get("historical_barrier_evidence_missing_ranges")
    try:
        missing_ranges = (
            json.loads(raw_missing_ranges)
            if isinstance(raw_missing_ranges, str)
            else raw_missing_ranges
        )
    except json.JSONDecodeError:
        missing_ranges = None
    if missing_ranges != []:
        reasons.append("historical_barrier_evidence_has_missing_ranges")
        missing_ranges = [] if missing_ranges is None else missing_ranges

    window_digest = str(row.get("historical_barrier_rule_window_provenance_sha256") or "").lower()
    if not _SHA256_RE.fullmatch(window_digest):
        reasons.append("invalid_historical_barrier_rule_window_provenance_sha256")
    if str(row.get("historical_barrier_crossed_at") or "").strip():
        reasons.append("verified_historical_barrier_evidence_has_crossing")
    if str(row.get("historical_barrier_first_touch_at") or "").strip():
        reasons.append("verified_historical_barrier_evidence_has_crossing")

    trusted_root = artifact_root or _inferred_artifact_root(row)
    if trusted_root is None:
        reasons.extend(
            (
                "historical_barrier_evidence_artifact_path_invalid",
                "historical_barrier_candle_snapshot_path_invalid",
            )
        )
        return list(dict.fromkeys(reasons))

    evidence_payload, evidence_read_error = _read_hashed_json(
        row.get("historical_barrier_evidence_path"),
        row.get("historical_barrier_evidence_sha256"),
        artifact_root=trusted_root,
        expected_subdirectory="historical_barrier_evidence",
        expected_prefix="evidence",
    )
    if evidence_read_error:
        if evidence_read_error in {"invalid_path", "unsafe_path", "unsafe_root", "read_error"}:
            reasons.append("historical_barrier_evidence_artifact_path_invalid")
        reasons.append("historical_barrier_evidence_artifact_mismatch")
    candle_payload, candle_read_error = _read_hashed_json(
        row.get("historical_barrier_candle_snapshot_path"),
        row.get("historical_barrier_candle_snapshot_sha256"),
        artifact_root=trusted_root,
        expected_subdirectory="historical_barrier_candles",
        expected_prefix="binance_1m",
    )
    if candle_read_error:
        if candle_read_error in {"invalid_path", "unsafe_path", "unsafe_root", "read_error"}:
            reasons.append("historical_barrier_candle_snapshot_path_invalid")
        reasons.append("historical_barrier_candle_snapshot_mismatch")
    if evidence_payload is None or candle_payload is None:
        return list(dict.fromkeys(reasons))

    try:
        artifact = _HistoricalEvidenceArtifact.model_validate(evidence_payload)
    except ValidationError:
        reasons.append("invalid_historical_barrier_evidence_artifact")
        return list(dict.fromkeys(reasons))

    reparsed_window, manifest_reasons = _manifest_binding_reasons(row, artifact)
    reasons.extend(manifest_reasons)
    if reparsed_window is not None:
        if start != _parse_utc(reparsed_window.start_time):
            reasons.append("historical_barrier_evidence_start_mismatch")
        if expiry != _parse_utc(reparsed_window.end_time):
            reasons.append("historical_barrier_rule_window_expiry_mismatch")
        if artifact.window.provenance_sha256 != window_digest:
            reasons.append("historical_barrier_rule_window_artifact_binding_mismatch")

    expected_artifact_values: tuple[tuple[str, Any, Any], ...] = (
        ("schema_version", artifact.schema_version, HISTORICAL_BARRIER_SCHEMA_VERSION),
        ("adapter_version", artifact.adapter_version, HISTORICAL_BARRIER_ADAPTER_VERSION),
        ("origin", artifact.origin, HISTORICAL_BARRIER_ORIGIN),
        ("source", artifact.source, HISTORICAL_BARRIER_SOURCE),
        ("locator", artifact.locator, BINANCE_KLINES_LOCATOR),
        ("asset", artifact.asset, asset),
        ("symbol", artifact.symbol, recorded_symbol),
        ("interval", artifact.interval, BINANCE_INTERVAL),
        ("barrier_direction", artifact.barrier_direction, direction),
        (
            "entry_time",
            artifact.entry_time,
            str(row.get("historical_barrier_evidence_end_time") or ""),
        ),
        (
            "candle_snapshot_sha256",
            artifact.candle_snapshot_sha256,
            str(row.get("historical_barrier_candle_snapshot_sha256") or ""),
        ),
        ("expected_candle_count", artifact.expected_candle_count, expected_count),
        ("candle_count", artifact.candle_count, candle_count),
        ("missing_ranges", list(artifact.missing_ranges), missing_ranges),
        ("barrier_crossed_at", artifact.barrier_crossed_at, ""),
        ("first_touch_at", artifact.first_touch_at, ""),
        ("status", artifact.status, status),
    )
    if any(actual != expected for _, actual, expected in expected_artifact_values):
        reasons.append("historical_barrier_evidence_artifact_binding_mismatch")
    if not _decimal_equal(artifact.threshold_price, row.get("threshold_price")):
        reasons.append("historical_barrier_evidence_threshold_mismatch")

    fetch_result, parsed_candles, candle_reasons = _independently_parse_candles(candle_payload)
    reasons.extend(candle_reasons)
    if fetch_result is None:
        return list(dict.fromkeys(reasons))

    fetch_start = _parse_utc(fetch_result.start_time)
    fetch_end = _parse_utc(fetch_result.end_time)
    server_before = _parse_utc(fetch_result.server_time_before)
    server_after = _parse_utc(fetch_result.server_time_after)
    if (
        fetch_result.source != HISTORICAL_BARRIER_SOURCE
        or fetch_result.locator != BINANCE_KLINES_LOCATOR
        or fetch_result.symbol != expected_symbol
        or fetch_result.interval != BINANCE_INTERVAL
        or fetch_start != start
        or fetch_end != entry
        or fetch_result.error
    ):
        reasons.append("historical_barrier_candle_snapshot_binding_mismatch")
    if (
        server_before is None
        or server_after is None
        or server_after < server_before
        or entry is None
        or server_after < entry
    ):
        reasons.append("historical_barrier_candle_server_time_mismatch")

    if start is not None and entry is not None:
        start_ms = int(start.timestamp() * 1000)
        entry_ms = int(entry.timestamp() * 1000)
        reasons.extend(
            _page_audit_reasons(
                fetch_result,
                start_ms=start_ms,
                end_ms=entry_ms,
                open_times=tuple(candle.open_time_ms for candle in parsed_candles),
            )
        )

    audit = _recompute_candles(
        candles=parsed_candles,
        start=start,
        entry=entry,
        barrier_direction=direction,
        threshold=threshold,
    )
    if audit.status != "complete":
        reasons.append(audit.status)
    if fetch_result.status != audit.status or artifact.fetch_status != fetch_result.status:
        reasons.append("historical_barrier_candle_snapshot_status_mismatch")
    if tuple(fetch_result.missing_ranges) != audit.missing_ranges:
        reasons.append("historical_barrier_candle_snapshot_missing_ranges_mismatch")

    if artifact.expected_candle_count != audit.expected_candle_count:
        reasons.append("historical_barrier_evidence_expected_count_mismatch")
    if artifact.candle_count != audit.observed_candle_count:
        reasons.append("historical_barrier_evidence_candle_count_mismatch")
    if (
        artifact.missing_ranges != audit.missing_ranges
        or artifact.recomputed_missing_ranges != audit.missing_ranges
    ):
        reasons.append("historical_barrier_evidence_missing_ranges_mismatch")
    if artifact.duplicate_open_times != audit.duplicate_open_times:
        reasons.append("historical_barrier_evidence_duplicate_report_mismatch")
    if artifact.ordering_status != audit.ordering_status:
        reasons.append("historical_barrier_evidence_ordering_report_mismatch")
    if artifact.ohlc_status != audit.ohlc_status:
        reasons.append("historical_barrier_evidence_ohlc_report_mismatch")
    if not _decimal_equal(artifact.min_low_price, audit.min_low_price):
        reasons.append("historical_barrier_evidence_min_low_mismatch")
    if not _decimal_equal(artifact.max_high_price, audit.max_high_price):
        reasons.append("historical_barrier_evidence_max_high_mismatch")
    if (
        artifact.tail_coverage_status != audit.tail_coverage_status
        or artifact.tail_covered_through != audit.tail_covered_through
    ):
        reasons.append("historical_barrier_evidence_tail_coverage_mismatch")
    if (
        artifact.first_touch_at != audit.first_touch_at
        or artifact.barrier_crossed_at != audit.first_touch_at
    ):
        reasons.append("historical_barrier_evidence_first_touch_mismatch")
    if audit.first_touch_at:
        reasons.append("barrier_already_crossed")

    candidate_recomputed_values: tuple[tuple[Any, Any, str], ...] = (
        (
            row.get("historical_barrier_expected_candle_count"),
            audit.expected_candle_count,
            "historical_barrier_candidate_expected_count_mismatch",
        ),
        (
            row.get("historical_barrier_evidence_candle_count"),
            audit.observed_candle_count,
            "historical_barrier_candidate_candle_count_mismatch",
        ),
        (
            row.get("historical_barrier_tail_coverage_status"),
            audit.tail_coverage_status,
            "historical_barrier_candidate_tail_coverage_mismatch",
        ),
        (
            row.get("historical_barrier_tail_covered_through"),
            audit.tail_covered_through,
            "historical_barrier_candidate_tail_coverage_mismatch",
        ),
        (
            row.get("historical_barrier_first_touch_at"),
            audit.first_touch_at,
            "historical_barrier_candidate_first_touch_mismatch",
        ),
    )
    for actual, expected, reason in candidate_recomputed_values:
        if actual != expected:
            reasons.append(reason)
    if not _decimal_equal(row.get("historical_barrier_min_low_price"), audit.min_low_price):
        reasons.append("historical_barrier_candidate_min_low_mismatch")
    if not _decimal_equal(row.get("historical_barrier_max_high_price"), audit.max_high_price):
        reasons.append("historical_barrier_candidate_max_high_mismatch")

    return list(dict.fromkeys(reasons))
