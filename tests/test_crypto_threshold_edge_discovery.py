import argparse
import asyncio
import csv
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

import scripts.discover_crypto_threshold_edges as discovery
import scripts.run_shadow_paper_loop as shadow_loop
from polysignal.ingestion.api_types import CLOBOrderbook
from polysignal.shadow.historical_barrier_provenance import (
    BINANCE_INTERVAL_MS,
    BinanceKlineFetchResult,
    BinanceKlinePageAudit,
    parse_binance_kline,
)


class FakeGammaClient:
    def __init__(self, markets=None, error=None):
        self.markets = markets or []
        self.error = error
        self.page_calls = []
        self.search_calls = []

    async def fetch_active_markets(self, limit: int):
        if self.error:
            raise self.error
        return self.markets[:limit]


class FakeCoverageGammaClient(FakeGammaClient):
    def __init__(self, pages=None, search_results=None, error=None):
        super().__init__([], error)
        self.pages = pages or []
        self.search_results = search_results or {}

    async def fetch_active_markets_page(self, limit: int, offset: int = 0):
        self.page_calls.append((limit, offset))
        index = offset // max(limit, 1)
        if index >= len(self.pages):
            return []
        return self.pages[index][:limit]

    async def search_markets(self, keyword: str, limit: int):
        self.search_calls.append((keyword, limit))
        return self.search_results.get(keyword, [])[:limit]


class FakeCLOBClient:
    def __init__(self, yes_book=None, no_book=None, error=None):
        self.yes_book = yes_book
        self.no_book = no_book
        self.error = error
        self.calls = 0

    async def get_market_orderbook(self, yes_token_id: str, no_token_id: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.yes_book, self.no_book

    async def close(self):
        return None


class FakeSpotProvider:
    def __init__(self, prices, timestamp: str | None = None):
        self.prices = prices
        self.timestamp = timestamp
        self.calls = []

    async def get_spot_prices(self, assets):
        self.calls.append(list(assets))
        observed_at = self.timestamp or datetime.now(UTC).isoformat().replace(
            "+00:00", "Z"
        )
        return {
            asset: discovery.SpotPrice(
                asset=asset,
                price=self.prices.get(asset, 0.0),
                timestamp=observed_at,
                source="mock_spot",
                error="" if self.prices.get(asset, 0.0) else "missing_spot_price",
            )
            for asset in assets
        }


class FakeClock:
    def __init__(self, current: datetime):
        self.current = current
        self.sleep_calls: list[float] = []

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.current += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def avoid_real_minute_waits(monkeypatch):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(discovery.asyncio, "sleep", no_wait)


class FakeHistoricalKlineClient:
    def __init__(self, *, high_price: str = "100001", low_price: str = "99999"):
        self.high_price = high_price
        self.low_price = low_price
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def fetch_klines(self, *, symbol, start_time, end_time):
        self.calls.append((symbol, start_time, end_time))
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        candles = []
        for open_ms in range(start_ms, end_ms, BINANCE_INTERVAL_MS):
            raw = [
                open_ms,
                "100000",
                self.high_price,
                self.low_price,
                "100000",
                "1",
                open_ms + BINANCE_INTERVAL_MS - 1,
                "100000",
                1,
                "0.5",
                "50000",
                "0",
            ]
            candle, error = parse_binance_kline(raw)
            assert error == ""
            assert candle is not None
            candles.append(candle)
        return BinanceKlineFetchResult(
            status="complete",
            symbol=symbol,
            start_time=start_time.isoformat().replace("+00:00", "Z"),
            end_time=end_time.isoformat().replace("+00:00", "Z"),
            server_time_before=(end_time + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            server_time_after=(end_time + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            pages=(
                BinanceKlinePageAudit(
                    sequence=1,
                    requested_start_ms=start_ms,
                    requested_end_ms=end_ms,
                    expected_candle_count=len(candles),
                    received_candle_count=len(candles),
                    attempts=1,
                    status="complete",
                ),
            ),
            candles=tuple(candles),
        )


def market(**overrides):
    market_question = str(
        overrides.get("question") or "Will Bitcoin hit $100k by December 31 2026?"
    )
    year_match = re.search(r"\b(20\d{2})\b", market_question)
    expiry_year = int(year_match.group(1)) if year_match else 2026
    asset, asset_name, source_path = (
        ("ETH", "Ethereum", "ethereum")
        if re.search(r"\b(?:ETH|Ethereum)\b", market_question, re.IGNORECASE)
        else (
            ("SOL", "Solana", "solana")
            if re.search(r"\b(?:SOL|Solana)\b", market_question, re.IGNORECASE)
            else ("BTC", "Bitcoin", "bitcoin")
        )
    )
    payload = {
        "id": "m1",
        "question": market_question,
        "active": True,
        "closed": False,
        "resolved": False,
        "volume": "10000",
        "category": "crypto",
        "clobTokenIds": '["yes1","no1"]',
        "outcomes": '["Yes","No"]',
        "resolutionSource": f"https://www.coinbase.com/price/{source_path}",
        "resolutionCriteria": (
            f"Coinbase {asset_name} ({asset}) price determines resolution. Resolves Yes if "
            "the price reaches the threshold at any time before expiry or if the closing "
            "price at expiration satisfies the market question. The cutoff is "
            f"December 31, {expiry_year}, 23:59 ET."
        ),
        "endDate": f"{expiry_year + 1:04d}-01-01T05:00:00Z",
        "updatedAt": "2026-08-04T07:00:00Z",
        "$schema": "https://gamma-api.polymarket.com/schemas/Market.json",
        "version": "v1",
    }
    payload.update(overrides)
    return payload


def explicit_history_market(**overrides):
    payload = market(
        question="Will BTC reach $110000 before December 31 2099?",
        resolutionSource="https://www.binance.com/en/trade/BTC_USDT",
        resolutionCriteria=(
            "This market resolves Yes if any Binance 1 minute candle for Bitcoin "
            "(BTC/USDT) between August 4, 2026, 12:00 and December 31, 2099, "
            "23:59 in the UTC timezone has a final High price equal to or greater "
            "than the title threshold."
        ),
        endDate="2100-01-01T00:00:00Z",
    )
    payload.update(overrides)
    return payload


def orderbook(
    asset_id: str,
    bid: float = 0.45,
    ask: float = 0.47,
    size: float = 25.0,
    timestamp: str | None = None,
) -> CLOBOrderbook:
    return CLOBOrderbook(
        asset_id=asset_id,
        bids=[{"price": str(bid), "size": str(size)}],
        asks=[{"price": str(ask), "size": str(size)}],
        timestamp=timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def args(tmp_path: Path, **overrides):
    payload = {
        "assets": "BTC,ETH,SOL",
        "max_markets": 500,
        "min_volume": 1000.0,
        "min_edge": 0.02,
        "min_confidence": 0.6,
        "output_dir": str(tmp_path / "runs"),
        "avoid_candidates_file": str(tmp_path / "runs" / "avoid_candidates.csv"),
        "dry_run": False,
        "data_mode": "real_readonly",
        "page_size": 100,
        "enable_keyword_search": True,
        "search_keywords": "bitcoin,btc,ethereum,eth,solana,sol,crypto,price,above,hit,reach",
    }
    payload.update(overrides)
    return argparse.Namespace(**payload)


def test_parser_recognizes_btc_eth_sol():
    btc = discovery.parse_crypto_threshold_market(
        market(question="Will BTC be above $100,000 on December 31 2026?"), ["BTC", "ETH", "SOL"]
    )
    eth = discovery.parse_crypto_threshold_market(
        market(question="Will Ethereum reach $5k before end of year?"), ["BTC", "ETH", "SOL"]
    )
    sol = discovery.parse_crypto_threshold_market(
        market(question="Will SOL hit $250 this week?"), ["BTC", "ETH", "SOL"]
    )

    assert btc.asset == "BTC"
    assert eth.asset == "ETH"
    assert sol.asset == "SOL"


def test_parser_extracts_threshold_price():
    parsed = discovery.parse_crypto_threshold_market(
        market(question="Will Bitcoin hit $100k by December 31 2026?"), ["BTC"]
    )

    assert parsed.threshold_price == 100000
    assert parsed.parser_confidence >= 0.75


def test_price_parser_supports_k_comma_and_m():
    assert discovery.parse_threshold_price("BTC to $100k")[0] == 100000
    assert discovery.parse_threshold_price("BTC above $100,000")[0] == 100000
    assert discovery.parse_threshold_price("BTC to 0.1M")[0] == 100000
    assert discovery.parse_threshold_price("Bitcoin reserve before 2027")[0] == 0


def test_parser_does_not_treat_non_price_crypto_questions_as_thresholds():
    parsed = discovery.parse_crypto_threshold_market(
        market(question="US national Bitcoin reserve before 2027?"),
        ["BTC"],
    )

    assert parsed is None


def test_description_prices_cannot_turn_non_threshold_titles_into_candidates():
    description = (
        "Resolution examples mention Bitcoin and a hypothetical $1 million price, "
        "but neither is the market's price threshold."
    )
    bitcoin_performance = discovery.parse_crypto_threshold_market(
        market(
            question="Will Bitcoin have the best performance in 2026?",
            description=description,
        ),
        ["BTC"],
    )
    gold_performance = discovery.parse_crypto_threshold_market(
        market(
            question="Will Gold have the best performance in 2026?",
            description=description,
        ),
        ["BTC"],
    )
    unspecified_ath = discovery.parse_crypto_threshold_market(
        market(
            question="Bitcoin all time high by December 31, 2026?",
            description=description,
        ),
        ["BTC"],
    )

    assert bitcoin_performance is None
    assert gold_performance is None
    assert unspecified_ath is not None
    assert unspecified_ath.threshold_price == 0
    assert unspecified_ath.parser_confidence < 0.75
    assert "missing_threshold" in unspecified_ath.parse_notes


def test_parser_identifies_directions():
    above = discovery.parse_crypto_threshold_market(
        market(question="Will BTC be above $100000 on December 31 2026?"), ["BTC"]
    )
    below = discovery.parse_crypto_threshold_market(
        market(question="Will BTC be below $80000 on December 31 2026?"), ["BTC"]
    )
    hit = discovery.parse_crypto_threshold_market(
        market(question="Will BTC hit $100000 before December 31 2026?"), ["BTC"]
    )
    reach = discovery.parse_crypto_threshold_market(
        market(question="Will BTC reach $100000 before December 31 2026?"), ["BTC"]
    )
    dip = discovery.parse_crypto_threshold_market(
        market(question="Will BTC dip to $80000 before December 31 2026?"), ["BTC"]
    )

    assert above.direction == "above"
    assert above.contract_kind == "settlement_threshold"
    assert above.barrier_direction == "up"
    assert below.direction == "below"
    assert below.contract_kind == "settlement_threshold"
    assert below.barrier_direction == "down"
    assert hit.direction == "hit_before_expiry"
    assert hit.contract_kind == "touch_before_expiry"
    assert hit.barrier_direction == "unknown"
    assert reach.contract_kind == "touch_before_expiry"
    assert reach.barrier_direction == "up"
    assert dip.contract_kind == "touch_before_expiry"
    assert dip.barrier_direction == "down"
    assert above.parser_version == discovery.PARSER_VERSION
    assert above.model_version == discovery.MODEL_VERSION


def test_contract_semantics_cover_directional_touch_verbs():
    cases = [
        ("Will BTC reach $120000 before Friday?", "touch_before_expiry", "up"),
        ("Will BTC break $120000 before Friday?", "touch_before_expiry", "up"),
        ("Will BTC set an all-time high of $120000?", "touch_before_expiry", "up"),
        ("Will BTC dip to $80000 before Friday?", "touch_before_expiry", "down"),
        ("Will BTC drop to $80000 before Friday?", "touch_before_expiry", "down"),
        ("Will BTC fall to $80000 before Friday?", "touch_before_expiry", "down"),
        ("Will BTC touch $120000 before Friday?", "touch_before_expiry", "unknown"),
        ("Will BTC touch above $120000 before Friday?", "touch_before_expiry", "unknown"),
        ("Will BTC break below $80000 before Friday?", "touch_before_expiry", "unknown"),
    ]

    for text, contract_kind, barrier_direction in cases:
        assert discovery.parse_contract_semantics(text) == (
            contract_kind,
            barrier_direction,
        )


def test_expiry_parsing():
    parsed = discovery.parse_crypto_threshold_market(
        market(question="Will BTC be above $100000 at end of week?"), ["BTC"]
    )

    assert parsed.expiry_time
    assert parsed.parser_confidence >= 0.75


def test_expiry_parsing_more_time_expressions():
    friday = discovery.parse_crypto_threshold_market(
        market(question="Will SOL be above $250 by Friday?"), ["SOL"]
    )
    end_year = discovery.parse_crypto_threshold_market(
        market(question="Will ETH reach $5000 by end of 2026?"), ["ETH"]
    )
    before_date = discovery.parse_crypto_threshold_market(
        market(question="Will BTC to $100k before December 31 2026?"), ["BTC"]
    )

    assert friday.expiry_time
    assert end_year.expiry_time.startswith("2026-12-31")
    assert before_date.expiry_time.startswith("2026-12-31")


def test_hours_until_requires_canonical_aware_expiry():
    now = datetime(2026, 12, 31, 23, 59)

    assert discovery.hours_until("2027-01-01T04:59:00Z", now) == 5.0
    assert discovery.hours_until("2026-12-31T23:59:00", now) == 0.0


def test_gamma_pagination_and_deduplication(tmp_path: Path):
    gamma = FakeCoverageGammaClient(
        pages=[
            [
                market(id="m1", question="Will BTC be above $100k by December 31 2026?"),
                market(id="m2", question="Will ETH reach $5k before December 31 2026?"),
            ],
            [
                market(id="m2", question="Will ETH reach $5k before December 31 2026?"),
                market(id="m3", question="Will SOL be above $250 by Friday?"),
            ],
        ]
    )

    markets, unique_count, errors = asyncio.run(
        discovery.fetch_market_universe(
            args(tmp_path, max_markets=5, page_size=2, enable_keyword_search=False), gamma
        )
    )

    assert unique_count == 3
    assert [item["id"] for item in markets] == ["m1", "m2", "m3"]
    assert errors == []


def test_gamma_fetch_records_raw_occurrences_and_manifest(tmp_path: Path):
    first = market(
        id="m1",
        question="Will BTC be above $100k by December 31 2026?",
        events=[{"id": "event-1", "rank": 1}],
    )
    duplicate = market(
        id="m1",
        question="Will BTC be above $100k by December 31 2026?",
        events=[{"id": "event-1", "rank": 2}],
    )
    gamma = FakeCoverageGammaClient(pages=[[first], [duplicate]])
    recorder = discovery.GammaRawSnapshotRecorder(tmp_path / "run")

    markets, unique_count, errors = asyncio.run(
        discovery.fetch_market_universe(
            args(
                tmp_path,
                max_markets=3,
                page_size=1,
                enable_keyword_search=False,
            ),
            gamma,
            recorder,
        )
    )
    result = recorder.finalize(terminal_status="complete", created_at=datetime.now().astimezone())

    assert unique_count == 1
    assert markets == [first]
    assert errors == []
    assert result.payload_count == 2
    assert result.unique_market_count == 1
    assert result.duplicate_market_id_count == 1
    first_snapshot = recorder.snapshot_for_payload(first)
    duplicate_snapshot = recorder.snapshot_for_payload(duplicate)
    assert first_snapshot is not None
    assert duplicate_snapshot is not None
    assert first_snapshot.snapshot_sha256 != duplicate_snapshot.snapshot_sha256
    manifest_bytes = Path(result.manifest_path).read_bytes()
    assert result.manifest_sha256 == hashlib.sha256(manifest_bytes).hexdigest()


def test_keyword_search_mock(tmp_path: Path):
    gamma = FakeCoverageGammaClient(
        pages=[],
        search_results={
            "bitcoin": [market(id="m1", question="Will Bitcoin hit $100k by December 31 2026?")]
        },
    )

    markets, unique_count, _ = asyncio.run(
        discovery.fetch_market_universe(
            args(tmp_path, max_markets=5, search_keywords="bitcoin"), gamma
        )
    )

    assert unique_count == 1
    assert markets[0]["id"] == "m1"
    assert gamma.search_calls


def test_mock_spot_provider_and_discovery(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1", 0.50, 0.52), orderbook("no1", 0.45, 0.47))
    spot = FakeSpotProvider({"BTC": 99000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert summary["crypto_markets_detected"] == 1
    assert summary["spot_prices_loaded"] == 1
    assert summary["candidates_generated"] == 1
    assert candidates[0]["spot_price"] == 99000.0
    assert candidates[0]["edge_type"] == "crypto_price_threshold_v1"
    assert candidates[0]["contract_kind"] == "touch_before_expiry"
    assert candidates[0]["barrier_direction"] == "unknown"
    assert candidates[0]["parser_version"] == discovery.PARSER_VERSION
    assert candidates[0]["parser_version"] == "crypto_threshold_parser_v4"
    assert candidates[0]["model_version"] == discovery.MODEL_VERSION
    assert candidates[0]["schema_version"] == discovery.DISCOVERY_SCHEMA_VERSION
    assert candidates[0]["expiry_time"] == "2027-01-01T04:59:00Z"
    assert candidates[0]["expiry_local_time"] == "2026-12-31T23:59:00"
    assert candidates[0]["expiry_timezone"] == "America/New_York"
    assert candidates[0]["expiry_time_adapter_version"] == "gamma_expiry_adapter_v1"
    assert len(candidates[0]["expiry_time_provenance_sha256"]) == 64
    assert candidates[0]["expiry_status"] == "verified"
    assert summary["expiry_status_distribution"] == {"verified": 1}
    raw_snapshot_path = Path(candidates[0]["gamma_raw_market_snapshot_path"])
    assert raw_snapshot_path.is_file()
    assert len(candidates[0]["gamma_raw_market_snapshot_sha256"]) == 64
    assert (
        hashlib.sha256(raw_snapshot_path.read_bytes()).hexdigest()
        == candidates[0]["gamma_raw_market_snapshot_sha256"]
    )
    manifest_path = Path(summary["gamma_raw_snapshot_manifest_path"])
    assert manifest_path.is_file()
    assert summary["gamma_raw_snapshot_payload_count"] == 1
    assert summary["gamma_raw_snapshot_unique_market_count"] == 1
    assert summary["gamma_raw_snapshot_terminal_status"] == "complete"
    assert (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == summary["gamma_raw_snapshot_manifest_sha256"]
    )


def test_entry_timestamp_is_causal_and_preserves_quote_provenance(tmp_path: Path):
    class TimestampedSpotProvider:
        def __init__(self):
            self.timestamp = ""

        async def get_spot_prices(self, assets):
            self.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            return {
                asset: discovery.SpotPrice(
                    asset=asset,
                    price=99000.0,
                    timestamp=self.timestamp,
                    source="mock_spot",
                )
                for asset in assets
            }

    class DelayedCLOBClient(FakeCLOBClient):
        async def get_market_orderbook(self, yes_token_id: str, no_token_id: str):
            await asyncio.sleep(0.01)
            return await super().get_market_orderbook(yes_token_id, no_token_id)

    yes_book = orderbook("yes1", 0.50, 0.52)
    no_book = orderbook("no1", 0.45, 0.47)
    yes_book.timestamp = "2026-08-04T04:00:00"
    no_book.timestamp = "2026-08-04T04:00:01"
    gamma = FakeGammaClient([market()])
    clob = DelayedCLOBClient(yes_book, no_book)
    spot = TimestampedSpotProvider()

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    candidate_row = candidates[0]
    entry_time = datetime.fromisoformat(candidate_row["timestamp"])
    spot_time = datetime.fromisoformat(candidate_row["spot_timestamp"])
    started_at = datetime.fromisoformat(summary["started_at"])
    assert entry_time >= spot_time > started_at
    quote_time = datetime.fromisoformat(
        candidate_row["entry_quote_timestamp"].replace("Z", "+00:00")
    )
    assert quote_time <= entry_time
    assert entry_time.second == 0
    assert entry_time.microsecond == 0
    assert candidate_row["yes_orderbook_timestamp"] == yes_book.timestamp
    assert candidate_row["no_orderbook_timestamp"] == no_book.timestamp


def test_dry_run_does_not_load_spot_or_orderbooks(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 99000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path, dry_run=True), gamma, clob, spot)
    )

    assert candidates == []
    assert summary["crypto_markets_detected"] == 1
    assert clob.calls == 0
    assert spot.calls == []
    assert summary["gamma_raw_snapshot_terminal_status"] == "not_recorded"
    assert not (tmp_path / "runs" / "gamma_raw_markets").exists()


def test_gamma_fetch_error_is_manifested_and_fails_closed(tmp_path: Path):
    gamma = FakeGammaClient(error=RuntimeError("gamma unavailable"))
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 99000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert candidates == []
    assert summary["api_error_count"] == 1
    assert summary["gamma_raw_snapshot_terminal_status"] == "pagination_error"
    assert summary["gamma_raw_snapshot_error_count"] == 1
    assert summary["gamma_raw_snapshot_payload_count"] == 0
    assert Path(summary["gamma_raw_snapshot_manifest_path"]).is_file()


def test_avoid_candidate_excluded_but_diagnostic_recorded(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    avoid_file = runs / "avoid_candidates.csv"
    avoid_file.write_text("market_id\nm1\n")
    nested_output = runs / "run_20990101_000000"
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(
                tmp_path,
                output_dir=str(nested_output),
                avoid_candidates_file=str(avoid_file),
            ),
            gamma,
            clob,
            spot,
        )
    )

    assert candidates == []
    assert summary["excluded_avoid_candidates"] == 1
    assert summary["diagnostics"][0]["diagnostic_reason"] == "avoid_candidate"


def test_avoid_file_cli_alias_and_default():
    assert discovery.parse_args([]).avoid_candidates_file == "runs/avoid_candidates.csv"
    parsed = discovery.parse_args(["--avoid_file", "custom/avoid.csv"])
    canonical = discovery.parse_args(["--avoid_candidates_file", "custom/canonical-avoid.csv"])

    assert parsed.avoid_candidates_file == "custom/avoid.csv"
    assert canonical.avoid_candidates_file == "custom/canonical-avoid.csv"


def test_cli_configuration_requires_existing_avoid_file(tmp_path: Path):
    parsed = args(
        tmp_path,
        output_dir=str(tmp_path / "isolated-run"),
        avoid_candidates_file=str(tmp_path / "missing-avoid.csv"),
    )

    with pytest.raises(FileNotFoundError, match="avoid_candidates_file not found"):
        asyncio.run(discovery.run_async(parsed))


def test_cli_configuration_protects_legacy_runs_output(tmp_path: Path):
    avoid_file = tmp_path / "avoid.csv"
    avoid_file.write_text("market_id\n")
    parsed = args(
        tmp_path,
        output_dir=str(discovery.REPO_ROOT / "runs"),
        avoid_candidates_file=str(avoid_file),
    )

    with pytest.raises(ValueError, match="isolated crypto-threshold run directory"):
        asyncio.run(discovery.run_async(parsed))


def test_missing_token_diagnostics(tmp_path: Path):
    gamma = FakeGammaClient([market(clobTokenIds="", outcomes="")])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert candidates == []
    assert summary["excluded_missing_token"] == 1
    assert summary["diagnostics"][0]["diagnostic_reason"] == "missing_token_id"


def test_missing_orderbook_diagnostics(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(None, orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert summary["excluded_missing_orderbook"] == 1
    assert summary["diagnostics"][0]["orderbook_loaded"] is False


def test_low_parser_confidence_diagnostics(tmp_path: Path):
    gamma = FakeGammaClient([market(question="Will BTC hit $100k?")])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert candidates == []
    assert summary["excluded_parse_low_confidence"] == 1
    assert summary["diagnostics"][0]["diagnostic_reason"] == "parse_low_confidence"


def test_probability_estimator_distance_time_behavior():
    parsed = discovery.ParsedCryptoThreshold(
        asset="BTC",
        threshold_price=100000.0,
        direction="hit_before_expiry",
        expiry_time="2026-12-31T23:59:00",
        parser_confidence=1.0,
        parse_notes=[],
        contract_kind="touch_before_expiry",
        barrier_direction="up",
    )

    close_prob, _, _ = discovery.estimate_probability(parsed, 99000.0, 100.0)
    far_prob, _, _ = discovery.estimate_probability(parsed, 70000.0, 100.0)
    long_prob, _, _ = discovery.estimate_probability(parsed, 99000.0, 1000.0)

    assert close_prob > far_prob
    assert long_prob >= close_prob


def test_ambiguous_touch_barrier_is_watch_only(tmp_path: Path):
    gamma = FakeGammaClient([market(question="Will BTC hit $110000 before December 31 2099?")])
    clob = FakeCLOBClient(orderbook("yes1", 0.09, 0.10), orderbook("no1", 0.88, 0.90))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    row = candidates[0]
    assert row["barrier_direction"] == "unknown"
    assert row["recommended_action"] == "watch_only"
    assert row["edge_failure_reason"] == "unverifiable_barrier_direction"
    assert row["edge_pass"] is False
    assert row["entry_decision_hint"] == "watch_only"

    shadow_runs = tmp_path / "shadow_runs"
    discovery.write_csv(shadow_runs / "crypto_threshold_edge_candidates.csv", candidates)
    loaded = shadow_loop.load_candidates(shadow_runs)

    assert loaded[0].edge_pass is False
    assert loaded[0].entry_decision_hint == "watch_only"
    assert shadow_loop.filter_shadow_entries(loaded) == []


def test_already_crossed_touch_barriers_are_watch_only(tmp_path: Path):
    cases = [
        ("Will BTC reach $90000 before December 31 2099?", 100000.0, "up"),
        ("Will BTC dip to $90000 before December 31 2099?", 80000.0, "down"),
    ]

    for question_text, spot_price, barrier_direction in cases:
        gamma = FakeGammaClient([market(question=question_text)])
        clob = FakeCLOBClient(
            orderbook("yes1", 0.09, 0.10),
            orderbook("no1", 0.88, 0.90),
        )
        spot = FakeSpotProvider({"BTC": spot_price})

        candidates, _ = asyncio.run(
            discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
        )

        row = candidates[0]
        assert row["barrier_direction"] == barrier_direction
        assert row["recommended_action"] == "watch_only"
        assert row["edge_failure_reason"] == "already_crossed_barrier"
        assert row["edge_pass"] is False
        assert row["entry_decision_hint"] == "watch_only"


def test_uncrossed_directional_touch_barriers_require_full_history(tmp_path: Path):
    cases = [
        ("Will BTC reach $110000 before December 31 2099?", "up"),
        ("Will BTC dip to $90000 before December 31 2099?", "down"),
    ]

    for question_text, barrier_direction in cases:
        gamma = FakeGammaClient([market(question=question_text)])
        clob = FakeCLOBClient(
            orderbook("yes1", 0.09, 0.10),
            orderbook("no1", 0.88, 0.90),
        )
        spot = FakeSpotProvider({"BTC": 100000.0})
        historical = FakeHistoricalKlineClient()

        candidates, summary = asyncio.run(
            discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot, historical)
        )

        row = candidates[0]
        assert row["barrier_direction"] == barrier_direction
        assert row["recommended_action"] == "watch_only"
        assert row["edge_failure_reason"] == "missing_rule_barrier_start"
        assert row["edge_pass"] is False
        assert row["entry_decision_hint"] == "watch_only"
        assert row["historical_barrier_evidence_status"] == "missing_rule_barrier_start"
        assert row["historical_barrier_evidence_source"] == ""
        assert row["historical_barrier_evidence_start_time"] == ""
        assert row["historical_barrier_evidence_end_time"] == ""
        assert row["historical_barrier_evidence_sha256"] == ""
        assert row["resolution_source_origin"] == "market_field"
        assert row["resolution_source_locator"] == "market.resolutionSource"
        assert row["resolution_source_adapter_version"] == "resolution_source_adapter_v1"
        assert len(row["resolution_source_provenance_sha256"]) == 64
        assert summary["resolution_status_distribution"] == {"verified": 1}
        assert summary["expiry_status_distribution"] == {"verified": 1}
        assert summary["expiry_timezone_distribution"] == {"America/New_York": 1}
        assert summary["expiry_time_adapter_distribution"] == {"gamma_expiry_adapter_v1": 1}
        assert summary["historical_barrier_evidence_status_distribution"] == {
            "missing_rule_barrier_start": 1
        }
        assert historical.calls == []
        assert summary["historical_barrier_preload_request_count"] == 0
        assert summary["historical_barrier_tail_request_count"] == 0
        assert summary["missing_historical_barrier_evidence_candidates"] == 0
        assert summary["shadow_entry_candidates"] == 0


def test_explicit_history_preload_is_deduplicated_and_tail_is_verified(tmp_path: Path):
    markets = [
        explicit_history_market(id="m1", clobTokenIds='["yes1","no1"]'),
        explicit_history_market(
            id="m2",
            question="Will BTC reach $120000 before December 31 2099?",
            clobTokenIds='["yes2","no2"]',
        ),
    ]
    gamma = FakeGammaClient(markets)
    quote_time = "2026-08-04T12:02:30Z"
    clob = FakeCLOBClient(
        orderbook("yes", 0.09, 0.10, size=25, timestamp=quote_time),
        orderbook("no", 0.88, 0.90, size=25, timestamp=quote_time),
    )
    spot = FakeSpotProvider({"BTC": 100000.0}, timestamp=quote_time)
    historical = FakeHistoricalKlineClient()
    clock = FakeClock(datetime(2026, 8, 4, 12, 2, 30, tzinfo=UTC))
    preload_time = datetime(2026, 8, 4, 12, 2, tzinfo=UTC)
    entry_time = datetime(2026, 8, 4, 12, 3, tzinfo=UTC)

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(tmp_path),
            gamma,
            clob,
            spot,
            historical,
            clock.now,
            clock.sleep,
        )
    )

    assert len(candidates) == 2
    assert len(historical.calls) == 2
    assert historical.calls[0] == (
        "BTCUSDT",
        datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        preload_time,
    )
    assert historical.calls[1][1] == datetime(2026, 8, 4, 12, 1, tzinfo=UTC)
    assert historical.calls[1][2] == entry_time
    assert clock.sleep_calls == [30.0]
    for row in candidates:
        assert row["historical_barrier_evidence_status"] == "verified_full_coverage"
        assert row["historical_barrier_evidence_start_time"] == "2026-08-04T12:00:00Z"
        assert row["historical_barrier_evidence_end_time"] == "2026-08-04T12:03:00Z"
        assert row["historical_barrier_evidence_candle_count"] == 3
        assert row["historical_barrier_expected_candle_count"] == 3
        assert row["historical_barrier_tail_coverage_status"] == "closed_through_entry"
        assert row["historical_barrier_evidence_missing_ranges"] == "[]"
        assert Path(row["historical_barrier_evidence_path"]).is_file()
        assert Path(row["historical_barrier_candle_snapshot_path"]).is_file()
        assert row["recommended_action"] == "shadow_entry"
        assert row["edge_pass"] is True
    assert summary["historical_barrier_preload_request_count"] == 1
    assert summary["historical_barrier_tail_request_count"] == 1
    assert summary["historical_barrier_candle_snapshot_count"] == 1
    assert summary["historical_barrier_evidence_manifest_count"] == 2
    assert summary["verified_historical_barrier_evidence_candidates"] == 2
    assert summary["historical_barrier_candle_count"] == 6
    assert summary["historical_barrier_evidence_symbol_distribution"] == {"BTCUSDT": 2}
    assert summary["tiny_live_recommendation"] == "NO"


def test_historical_high_boundary_cross_is_watch_only(tmp_path: Path):
    gamma = FakeGammaClient([explicit_history_market()])
    quote_time = "2026-08-04T12:02:30Z"
    clob = FakeCLOBClient(
        orderbook("yes1", 0.09, 0.10, timestamp=quote_time),
        orderbook("no1", 0.88, 0.90, timestamp=quote_time),
    )
    spot = FakeSpotProvider({"BTC": 100000.0}, timestamp=quote_time)
    historical = FakeHistoricalKlineClient(high_price="110000")
    clock = FakeClock(datetime(2026, 8, 4, 12, 2, 30, tzinfo=UTC))

    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(tmp_path),
            gamma,
            clob,
            spot,
            historical,
            clock.now,
            clock.sleep,
        )
    )

    row = candidates[0]
    assert row["historical_barrier_evidence_status"] == "barrier_already_crossed"
    assert row["historical_barrier_crossed_at"] == "2026-08-04T12:00:00Z"
    assert row["recommended_action"] == "watch_only"
    assert row["edge_failure_reason"] == "barrier_already_crossed"
    assert row["edge_pass"] is False


def test_nonzero_second_clock_schedules_valid_minute_batch_entry(tmp_path: Path):
    gamma = FakeGammaClient([explicit_history_market()])
    quote_time = "2026-08-04T12:02:17Z"
    clob = FakeCLOBClient(
        orderbook("yes1", 0.09, 0.10, timestamp=quote_time),
        orderbook("no1", 0.88, 0.90, timestamp=quote_time),
    )
    spot = FakeSpotProvider({"BTC": 100000.0}, timestamp=quote_time)
    historical = FakeHistoricalKlineClient()
    clock = FakeClock(datetime(2026, 8, 4, 12, 2, 17, tzinfo=UTC))

    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(tmp_path),
            gamma,
            clob,
            spot,
            historical,
            clock.now,
            clock.sleep,
        )
    )

    row = candidates[0]
    assert row["timestamp"] == "2026-08-04T12:03:00Z"
    assert row["entry_quote_timestamp"] == quote_time
    assert row["spot_timestamp"] == quote_time
    entry = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    for field in (
        "spot_timestamp",
        "entry_quote_timestamp",
        "yes_orderbook_timestamp",
        "no_orderbook_timestamp",
    ):
        observed = datetime.fromisoformat(str(row[field]).replace("Z", "+00:00"))
        assert 0 <= (entry - observed).total_seconds() <= 60
    assert row["historical_barrier_evidence_status"] == "verified_full_coverage"
    assert row["historical_barrier_tail_coverage_status"] == "closed_through_entry"
    assert row["recommended_action"] == "shadow_entry"
    assert row["edge_pass"] is True
    assert clock.sleep_calls == [43.0]


def test_stale_batch_evidence_fails_closed_at_discovery(tmp_path: Path):
    stale_time = "2026-08-04T12:01:59Z"
    clock = FakeClock(datetime(2026, 8, 4, 12, 2, 30, tzinfo=UTC))
    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(tmp_path),
            FakeGammaClient([explicit_history_market()]),
            FakeCLOBClient(
                orderbook("yes1", 0.09, 0.10, timestamp=stale_time),
                orderbook("no1", 0.88, 0.90, timestamp=stale_time),
            ),
            FakeSpotProvider({"BTC": 100000.0}, timestamp=stale_time),
            FakeHistoricalKlineClient(),
            clock.now,
            clock.sleep,
        )
    )

    row = candidates[0]
    assert row["historical_barrier_evidence_status"] == "verified_full_coverage"
    assert row["recommended_action"] == "watch_only"
    assert row["edge_failure_reason"] == "stale_spot_snapshot"
    assert "stale_spot_snapshot" in row["risk_flags"]


def test_historical_preload_exception_fails_closed_without_crashing(tmp_path: Path):
    class FailingHistoricalClient:
        def __init__(self):
            self.calls = 0

        async def fetch_klines(self, **kwargs):
            self.calls += 1
            raise RuntimeError("offline")

    historical = FailingHistoricalClient()
    quote_time = "2026-08-04T12:02:30Z"
    clock = FakeClock(datetime(2026, 8, 4, 12, 2, 30, tzinfo=UTC))

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(tmp_path),
            FakeGammaClient([explicit_history_market()]),
            FakeCLOBClient(
                orderbook("yes1", 0.09, 0.10, timestamp=quote_time),
                orderbook("no1", 0.88, 0.90, timestamp=quote_time),
            ),
            FakeSpotProvider({"BTC": 100000.0}, timestamp=quote_time),
            historical,
            clock.now,
            clock.sleep,
        )
    )

    assert historical.calls == 1
    assert candidates[0]["recommended_action"] == "watch_only"
    assert (
        candidates[0]["historical_barrier_evidence_status"]
        == "historical_preload_error:RuntimeError"
    )
    assert summary["api_error_count"] == 1
    assert summary["historical_barrier_preload_failure_count"] == 1
    assert summary["tiny_live_recommendation"] == "NO"


@pytest.mark.parametrize(
    ("market_overrides", "expected_status"),
    [
        (
            {"resolutionSource": "", "resolutionCriteria": ""},
            "missing_resolution_source",
        ),
        (
            {"resolutionCriteria": "too short"},
            "missing_or_insufficient_resolution_rules",
        ),
        (
            {
                "resolutionCriteria": (
                    "Resolves using the closing price at expiry, not an intraperiod touch."
                )
            },
            "resolution_semantics_conflict",
        ),
    ],
)
def test_unverified_resolution_provenance_is_watch_only_at_discovery(
    tmp_path: Path,
    market_overrides: dict[str, str],
    expected_status: str,
) -> None:
    gamma = FakeGammaClient(
        [market(question="Will BTC reach $110000 before December 31 2099?", **market_overrides)]
    )
    clob = FakeCLOBClient(orderbook("yes1", 0.09, 0.10), orderbook("no1", 0.88, 0.90))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    row = candidates[0]
    assert row["resolution_status"] == expected_status
    assert row["recommended_action"] == "watch_only"
    assert row["edge_failure_reason"] == expected_status
    assert row["edge_pass"] is False
    assert row["entry_decision_hint"] == "watch_only"
    assert expected_status in row["risk_flags"]
    assert summary["shadow_entry_candidates"] == 0


def test_unverified_expiry_provenance_is_watch_only_at_discovery(tmp_path: Path):
    gamma = FakeGammaClient(
        [
            market(
                question="Will BTC be above $90000 on December 31 2026?",
                endDate="2026-12-31T23:59:00Z",
            )
        ]
    )
    clob = FakeCLOBClient(orderbook("yes1", 0.40, 0.42), orderbook("no1", 0.50, 0.52))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    row = candidates[0]
    assert row["expiry_time"] == "2027-01-01T04:59:00Z"
    assert row["expiry_status"] == "gamma_end_date_mismatch"
    assert row["recommended_action"] == "watch_only"
    assert row["edge_failure_reason"] == "gamma_end_date_mismatch"
    assert "gamma_end_date_mismatch" in row["risk_flags"]
    assert summary["expiry_status_distribution"] == {"gamma_end_date_mismatch": 1}
    assert summary["verified_expiry_candidates"] == 0


def test_expected_edge_calculation(tmp_path: Path):
    gamma = FakeGammaClient([market(question="Will BTC be above $90000 on December 31 2026?")])
    clob = FakeCLOBClient(orderbook("yes1", 0.40, 0.42), orderbook("no1", 0.50, 0.52))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    row = candidates[0]
    assert row["side"] == "YES"
    assert row["expected_edge"] == row["model_estimated_probability"] - row["yes_best_ask"] - 0.01
    assert row["historical_barrier_evidence_status"] == "not_required"
    assert row["recommended_action"] == "shadow_entry"


def test_confidence_gate(tmp_path: Path):
    gamma = FakeGammaClient([market(question="Will BTC be above $90000 on December 31 2026?")])
    clob = FakeCLOBClient(
        orderbook("yes1", 0.40, 0.42, size=0.1), orderbook("no1", 0.50, 0.52, size=0.1)
    )
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(
            args(tmp_path, min_confidence=0.99), gamma, clob, spot
        )
    )

    assert candidates[0]["recommended_action"] == "watch_only"
    assert candidates[0]["edge_failure_reason"] == "confidence_too_low"


def test_low_parser_confidence_watch_only(tmp_path: Path):
    gamma = FakeGammaClient([market(question="Will BTC hit $100k?")])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 100000.0})

    candidates, summary = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert candidates == []
    assert summary["excluded_parse_low_confidence"] == 1


def test_missing_spot_price_reject_or_watch(tmp_path: Path):
    gamma = FakeGammaClient([market()])
    clob = FakeCLOBClient(orderbook("yes1"), orderbook("no1"))
    spot = FakeSpotProvider({"BTC": 0.0})

    candidates, _ = asyncio.run(
        discovery.discover_crypto_threshold_edges(args(tmp_path), gamma, clob, spot)
    )

    assert candidates[0]["recommended_action"] in {"reject", "watch_only"}
    assert candidates[0]["edge_failure_reason"] == "missing_spot_price"
    assert _["excluded_missing_spot"] == 1


def test_output_csv_json_summary_report(tmp_path: Path):
    row = {
        "edge_type": "crypto_price_threshold_v1",
        "market_id": "m1",
        "question": "Will BTC be above $90000 on December 31 2026?",
        "contract_kind": "settlement_threshold",
        "barrier_direction": "up",
        "schema_version": discovery.DISCOVERY_SCHEMA_VERSION,
        "parser_version": discovery.PARSER_VERSION,
        "model_version": discovery.MODEL_VERSION,
        "expiry_status": "verified",
        "expiry_timezone": "America/New_York",
        "expiry_time_origin": "title_date+resolution_rules_timezone+gamma.endDate",
        "expiry_time_adapter_version": "gamma_expiry_adapter_v1",
        "historical_barrier_evidence_status": "not_required",
        "recommended_action": "watch_only",
    }
    summary = discovery.build_summary(
        started=__import__("datetime").datetime.utcnow(),
        markets=[market()],
        crypto_markets_detected=1,
        parsed_threshold_markets=1,
        spot_prices={"BTC": discovery.SpotPrice("BTC", 100000.0, "now", "mock")},
        candidates=[row],
        api_error_count=0,
        errors=[],
        orderbooks_fetched=2,
    )
    output_dir = tmp_path / "runs"

    discovery.write_csv(output_dir / "crypto_threshold_edge_candidates.csv", [row])
    discovery.write_json(output_dir / "crypto_threshold_edge_candidates.json", [row])
    discovery.write_summary(output_dir / "crypto_threshold_edge_discovery_summary.json", summary)
    discovery.write_report(output_dir / "crypto_threshold_edge_discovery_report.md", summary)
    discovery.write_diagnostics_csv(
        output_dir / "crypto_threshold_market_diagnostics.csv",
        [
            discovery.diagnostic_row(
                market(),
                discovery.parse_crypto_threshold_market(market(), ["BTC"]),
                "excluded",
                "avoid_candidate",
            )
        ],
    )

    with open(output_dir / "crypto_threshold_edge_candidates.csv") as candidate_file:
        csv_rows = list(csv.DictReader(candidate_file))
    json_rows = json.loads((output_dir / "crypto_threshold_edge_candidates.json").read_text())[
        "crypto_threshold_edge_candidates"
    ]
    assert csv_rows[0]["contract_kind"] == "settlement_threshold"
    assert csv_rows[0]["barrier_direction"] == "up"
    assert csv_rows[0]["parser_version"] == discovery.PARSER_VERSION
    assert csv_rows[0]["schema_version"] == discovery.DISCOVERY_SCHEMA_VERSION
    assert csv_rows[0]["model_version"] == discovery.MODEL_VERSION
    assert json_rows[0]["contract_kind"] == "settlement_threshold"
    assert json_rows[0]["barrier_direction"] == "up"
    assert json_rows[0]["parser_version"] == discovery.PARSER_VERSION
    assert json_rows[0]["schema_version"] == discovery.DISCOVERY_SCHEMA_VERSION
    assert json_rows[0]["model_version"] == discovery.MODEL_VERSION
    summary_payload = json.loads(
        (output_dir / "crypto_threshold_edge_discovery_summary.json").read_text()
    )
    assert summary_payload["tiny_live_recommendation"] == "NO"
    assert summary_payload["expiry_status_distribution"] == {"verified": 1}
    assert summary_payload["historical_barrier_evidence_status_distribution"] == {"not_required": 1}
    assert (
        "Crypto Threshold Edge Discovery Report"
        in (output_dir / "crypto_threshold_edge_discovery_report.md").read_text()
    )
    assert (
        "Expiry And Historical Barrier Evidence"
        in (output_dir / "crypto_threshold_edge_discovery_report.md").read_text()
    )
    with open(output_dir / "crypto_threshold_market_diagnostics.csv") as diagnostics_file:
        diagnostic_rows = list(csv.DictReader(diagnostics_file))
    assert diagnostic_rows[0]["expiry_status"] == "verified"
    assert diagnostic_rows[0]["expiry_time_adapter_version"] == "gamma_expiry_adapter_v1"
    assert diagnostic_rows[0]["historical_barrier_evidence_status"] == "missing_rule_barrier_start"


def test_run_shadow_paper_loop_reads_crypto_threshold_candidates(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    path = runs_dir / "crypto_threshold_edge_candidates.csv"
    fields = [
        "market_id",
        "question",
        "edge_type",
        "recommended_action",
        "side",
        "expected_edge",
        "confidence",
        "yes_best_ask",
        "no_best_ask",
        "yes_best_bid",
        "no_best_bid",
        "combined_ask",
        "liquidity_score",
        "spread",
        "orderbook_depth",
        "edge_pass",
        "reasons",
        "source",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "market_id": "m1",
                "question": "Will BTC be above $90000 on December 31 2026?",
                "edge_type": "crypto_price_threshold_v1",
                "recommended_action": "shadow_entry",
                "side": "YES",
                "expected_edge": "0.08",
                "confidence": "0.9",
                "yes_best_ask": "0.40",
                "no_best_ask": "0.58",
                "yes_best_bid": "0.39",
                "no_best_bid": "0.57",
                "combined_ask": "0.98",
                "liquidity_score": "50",
                "spread": "0.01",
                "orderbook_depth": "4",
                "edge_pass": "true",
                "reasons": (
                    "crypto_price_threshold_v1|external_spot_price|threshold_parser_high_confidence"
                ),
                "source": "crypto_threshold_edge",
            }
        )

    candidates = shadow_loop.load_candidates(runs_dir)

    assert len(candidates) == 1
    assert candidates[0].edge_type == "crypto_price_threshold_v1"
    assert candidates[0].side_entry_ask() == 0.40


def test_no_forbidden_imports():
    source = Path("scripts/discover_crypto_threshold_edges.py").read_text()

    assert "LiveTrader" not in source
    assert "PaperTrader" not in source
    assert "RiskGovernor" not in source


def test_live_trading_enabled_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False


class TestThresholdPriceLowPricedAssets:
    """ADR-028: dollar-anchored thresholds of any magnitude are explicit prices."""

    def test_xrp_sub_dollar_threshold(self):
        value, confidence = discovery.parse_threshold_price("Will XRP dip to $0.80 by December 31, 2026?")
        assert value == pytest.approx(0.80)
        assert confidence == pytest.approx(0.25)

    def test_doge_sub_dollar_threshold(self):
        value, _ = discovery.parse_threshold_price("Will Dogecoin reach $0.20 by December 31, 2026?")
        assert value == pytest.approx(0.20)

    def test_dollar_anchored_year_band_is_a_price(self):
        # "ETH reach $2000" — dollar-anchored values in the 1900-2100 band are
        # genuine asset prices, not years.
        value, _ = discovery.parse_threshold_price("Will ETH reach $2000 by December 31, 2026?")
        assert value == pytest.approx(2000.0)

    def test_bare_number_year_band_still_excluded(self):
        value, _ = discovery.parse_threshold_price("Will the asset hit 2027 before December?")
        assert value == 0.0

    def test_large_price_unchanged(self):
        value, _ = discovery.parse_threshold_price("Will Bitcoin reach $100,000 by December 31, 2026?")
        assert value == pytest.approx(100_000.0)
