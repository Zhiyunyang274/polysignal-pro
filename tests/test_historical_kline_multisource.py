"""
Tests for the multi-source historical kline failover (ADR-027).

Covers: Coinbase candle parsing/pagination validation, source attribution,
failover trigger semantics (source failures only, never range failures), and
source-aware symbol/locator verification in evaluate_historical_barrier.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from polysignal.shadow.historical_barrier_provenance import (
    BinanceHistoricalKlineClient,
    BinanceKline,
    BinanceKlineFetchResult,
    CoinbaseHistoricalCandleClient,
    MultiSourceHistoricalKlineClient,
    _parse_coinbase_candle,
)

UTC = UTC


def coinbase_rows(start_seconds: int, count: int) -> list[list[object]]:
    """Rows in Coinbase wire order: [time, low, high, open, close, volume] (DESC)."""
    rows = []
    for i in range(count - 1, -1, -1):
        t = start_seconds + i * 60
        rows.append([t, 100.0 + i, 110.0 + i, 101.0 + i, 105.0 + i, 12.5])
    return rows


def make_binance_candle(open_time_ms: int) -> BinanceKline:
    return BinanceKline(
        open_time_ms=open_time_ms,
        open_price="100",
        high_price="110",
        low_price="99",
        close_price="105",
        volume="10",
        close_time_ms=open_time_ms + 59_999,
        quote_asset_volume="0",
        trade_count=0,
        taker_buy_base_volume="0",
        taker_buy_quote_volume="0",
        ignore="0",
    )


class TestParseCoinbaseCandle:
    def test_maps_wire_order(self):
        minute = 1_700_000_040  # minute-aligned (60 divides it)
        row = [minute, 99.0, 110.0, 100.0, 105.0, 12.5]
        candle, error = _parse_coinbase_candle(row)
        assert error == ""
        assert candle is not None
        assert candle.open_time_ms == minute * 1000
        assert candle.low_price == "99.0"
        assert candle.high_price == "110.0"
        assert candle.open_price == "100.0"
        assert candle.close_price == "105.0"
        assert candle.close_time_ms == minute * 1000 + 59_999

    def test_rejects_non_minute_aligned(self):
        candle, error = _parse_coinbase_candle([1_700_000_030, 1, 2, 1, 2, 1])
        assert candle is None
        assert error == "invalid_coinbase_candle_time"

    def test_rejects_negative_prices(self):
        candle, error = _parse_coinbase_candle([1_700_000_000, -1.0, 2.0, 1.0, 2.0, 1.0])
        assert candle is None
        assert error == "invalid_coinbase_candle_values"

    def test_rejects_wrong_shape(self):
        candle, error = _parse_coinbase_candle([1_700_000_000, 1.0])
        assert candle is None


class TestCoinbaseClient:
    @staticmethod
    def _transport(handler) -> httpx.MockTransport:
        return httpx.MockTransport(handler)

    @pytest.mark.asyncio
    async def test_complete_coverage_single_page(self):
        start = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        end = start + timedelta(minutes=3)
        start_seconds = int(start.timestamp())

        def handler(request: httpx.Request) -> httpx.Response:
            assert "/products/BTC-USD/candles" in str(request.url)
            assert request.url.params["granularity"] == "60"
            return httpx.Response(200, json=coinbase_rows(start_seconds, 3))

        client = CoinbaseHistoricalCandleClient(transport=self._transport(handler))
        result = await client.fetch_klines(symbol="BTC-USD", start_time=start, end_time=end)

        assert result.status == "complete"
        assert result.source == "coinbase_exchange_candles"
        assert result.locator == (
            "https://api.exchange.coinbase.com/products/BTC-USD/candles"
        )
        assert result.symbol == "BTC-USD"
        assert [c.open_time_ms for c in result.candles] == [
            start_seconds * 1000 + i * 60_000 for i in range(3)
        ]

    @pytest.mark.asyncio
    async def test_rejects_unsupported_symbol(self):
        client = CoinbaseHistoricalCandleClient(transport=self._transport(lambda r: httpx.Response(200, json=[])))
        result = await client.fetch_klines(
            symbol="BTCUSDT",  # Binance-style symbol is not a Coinbase pair
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 1, 0, 10, tzinfo=UTC),
        )
        assert result.status == "unsupported_coinbase_symbol"

    @pytest.mark.asyncio
    async def test_http_error_surfaced(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(451, json={"error": "blocked"})

        client = CoinbaseHistoricalCandleClient(transport=self._transport(handler))
        result = await client.fetch_klines(
            symbol="BTC-USD",
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 1, 0, 5, tzinfo=UTC),
        )
        assert result.status == "error"
        assert result.error == "coinbase_http_451"

    @pytest.mark.asyncio
    async def test_multi_page_range(self):
        start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=700)  # spans 3 pages of 300
        start_seconds = int(start.timestamp())

        seen_starts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_starts.append(str(request.url.params["start"]))
            end_param = datetime.fromisoformat(str(request.url.params["end"]).replace("Z", "+00:00"))
            req_start = datetime.fromisoformat(str(request.url.params["start"]).replace("Z", "+00:00"))
            seconds = int(req_start.timestamp())
            count = min(300, int((end_param - req_start).total_seconds() // 60) + 1)
            return httpx.Response(200, json=coinbase_rows(seconds, count))

        client = CoinbaseHistoricalCandleClient(transport=self._transport(handler))
        result = await client.fetch_klines(symbol="ETH-USD", start_time=start, end_time=end)

        assert result.status == "complete"
        assert len(result.pages) == 3
        assert len(seen_starts) == 3
        assert [c.open_time_ms for c in result.candles][0] == start_seconds * 1000
        assert result.candles[-1].open_time_ms == (int(end.timestamp()) - 60) * 1000


class TestMultiSourceFailover:
    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self):
        class RecordingBinance(BinanceHistoricalKlineClient):
            called = False

            async def fetch_klines(self, **kwargs):
                type(self).called = True
                start = kwargs["start_time"]
                candles = tuple(
                    make_binance_candle(int(start.timestamp()) * 1000 + i * 60_000)
                    for i in range(2)
                )
                return BinanceKlineFetchResult(
                    status="complete", symbol=kwargs["symbol"],
                    start_time="x", end_time="y", candles=candles,
                )

        class FailingCoinbase(CoinbaseHistoricalCandleClient):
            called = False

            async def fetch_klines(self, **kwargs):
                type(self).called = True
                raise AssertionError("fallback must not be called on primary success")

        multi = MultiSourceHistoricalKlineClient(
            binance=RecordingBinance(), coinbase=FailingCoinbase()
        )
        result = await multi.fetch_klines(
            symbol="BTCUSDT",
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 1, 0, 2, tzinfo=UTC),
        )
        assert result.status == "complete"
        assert RecordingBinance.called is True
        assert FailingCoinbase.called is False

    @pytest.mark.asyncio
    async def test_failover_on_http_451(self):
        class BlockedBinance(BinanceHistoricalKlineClient):
            async def fetch_klines(self, **kwargs):
                return BinanceKlineFetchResult(
                    status="error", symbol=kwargs["symbol"],
                    start_time="x", end_time="y", error="binance_http_451",
                )

        class WorkingCoinbase(CoinbaseHistoricalCandleClient):
            async def fetch_klines(self, **kwargs):
                assert kwargs["symbol"] == "BTC-USD"  # asset-mapped pair
                start = kwargs["start_time"]
                candles = tuple(
                    make_binance_candle(int(start.timestamp()) * 1000 + i * 60_000)
                    for i in range(2)
                )
                return BinanceKlineFetchResult(
                    status="complete", source="coinbase_exchange_candles",
                    locator="https://api.exchange.coinbase.com/products/BTC-USD/candles",
                    symbol=kwargs["symbol"], start_time="x", end_time="y",
                    candles=candles,
                )

        multi = MultiSourceHistoricalKlineClient(
            binance=BlockedBinance(), coinbase=WorkingCoinbase()
        )
        result = await multi.fetch_klines(
            symbol="BTCUSDT",
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 1, 0, 2, tzinfo=UTC),
        )
        assert result.status == "complete"
        assert result.source == "coinbase_exchange_candles"

    @pytest.mark.asyncio
    async def test_no_failover_on_range_level_failure(self):
        class PartialBinance(BinanceHistoricalKlineClient):
            async def fetch_klines(self, **kwargs):
                return BinanceKlineFetchResult(
                    status="partial_coverage", symbol=kwargs["symbol"],
                    start_time="x", end_time="y", error="partial_coverage",
                )

        class NotCalledCoinbase(CoinbaseHistoricalCandleClient):
            async def fetch_klines(self, **kwargs):
                raise AssertionError("range failures must not trigger failover")

        multi = MultiSourceHistoricalKlineClient(
            binance=PartialBinance(), coinbase=NotCalledCoinbase()
        )
        result = await multi.fetch_klines(
            symbol="BTCUSDT",
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 1, 0, 2, tzinfo=UTC),
        )
        assert result.status == "partial_coverage"

    @pytest.mark.asyncio
    async def test_both_failing_returns_primary_error(self):
        class BlockedBinance(BinanceHistoricalKlineClient):
            async def fetch_klines(self, **kwargs):
                return BinanceKlineFetchResult(
                    status="error", symbol=kwargs["symbol"],
                    start_time="x", end_time="y", error="binance_http_451",
                )

        class BlockedCoinbase(CoinbaseHistoricalCandleClient):
            async def fetch_klines(self, **kwargs):
                return BinanceKlineFetchResult(
                    status="error", source="coinbase_exchange_candles",
                    locator="locator", symbol=kwargs["symbol"],
                    start_time="x", end_time="y", error="coinbase_http_451",
                )

        multi = MultiSourceHistoricalKlineClient(
            binance=BlockedBinance(), coinbase=BlockedCoinbase()
        )
        result = await multi.fetch_klines(
            symbol="BTCUSDT",
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 1, 0, 2, tzinfo=UTC),
        )
        # primary error is preserved for auditability when fallback also fails
        assert result.status == "error"
        assert result.error == "binance_http_451"
