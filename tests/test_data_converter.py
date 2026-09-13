"""
Tests for Data Converter

Tests the conversion of Polymarket API data to internal models.
"""


from polysignal.ingestion.api_types import (
    CLOBOrderbook,
    CLOBPriceLevel,
    GammaMarket,
    GammaToken,
)
from polysignal.ingestion.data_converter import DataConverter
from polysignal.models.market import MarketCategory, MarketStatus
from tests.fixtures.api_responses import (
    create_clob_orderbook_mispricing,
    create_clob_orderbook_response,
    create_gamma_market_response,
)


class TestDataConverter:
    """Test Data Converter"""

    # =========================================================================
    # Parse Float Tests
    # =========================================================================

    def test_parse_float_string(self):
        """Test parsing float from string"""
        assert DataConverter.parse_float("123.45") == 123.45
        assert DataConverter.parse_float("0.5") == 0.5

    def test_parse_float_number(self):
        """Test parsing float from number"""
        assert DataConverter.parse_float(123.45) == 123.45
        assert DataConverter.parse_float(100) == 100.0

    def test_parse_float_none(self):
        """Test parsing float from None"""
        assert DataConverter.parse_float(None) == 0.0
        assert DataConverter.parse_float(None, default=10.0) == 10.0

    def test_parse_float_invalid(self):
        """Test parsing float from invalid string"""
        assert DataConverter.parse_float("invalid") == 0.0
        assert DataConverter.parse_float("N/A") == 0.0

    # =========================================================================
    # Parse Datetime Tests
    # =========================================================================

    def test_parse_datetime_iso(self):
        """Test parsing ISO datetime"""
        result = DataConverter.parse_datetime("2024-01-15T12:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_none(self):
        """Test parsing None datetime"""
        assert DataConverter.parse_datetime(None) is None

    def test_parse_datetime_invalid(self):
        """Test parsing invalid datetime"""
        assert DataConverter.parse_datetime("invalid") is None
        assert DataConverter.parse_datetime("2024-13-45") is None

    # =========================================================================
    # Map Category Tests
    # =========================================================================

    def test_map_category_crypto(self):
        """Test mapping crypto category"""
        assert DataConverter.map_category("crypto") == MarketCategory.CRYPTO
        assert DataConverter.map_category("CRYPTO") == MarketCategory.CRYPTO

    def test_map_category_politics(self):
        """Test mapping politics category"""
        assert DataConverter.map_category("politics") == MarketCategory.POLITICS
        assert DataConverter.map_category("Politics") == MarketCategory.POLITICS

    def test_map_category_unknown(self):
        """Test mapping unknown category"""
        assert DataConverter.map_category("unknown") == MarketCategory.OTHER
        assert DataConverter.map_category("random") == MarketCategory.OTHER

    def test_map_category_none(self):
        """Test mapping None category"""
        assert DataConverter.map_category(None) == MarketCategory.OTHER

    def test_map_category_geopolitics(self):
        """Test mapping geopolitics category"""
        assert DataConverter.map_category("geopolitics") == MarketCategory.WAR_GEOPOLITICS
        assert DataConverter.map_category("war") == MarketCategory.WAR_GEOPOLITICS

    # =========================================================================
    # Determine Status Tests
    # =========================================================================

    def test_determine_status_resolved(self):
        """Test determining resolved status"""
        market = GammaMarket(resolved=True)
        assert DataConverter.determine_status(market) == MarketStatus.RESOLVED

    def test_determine_status_closed(self):
        """Test determining closed status"""
        market = GammaMarket(closed=True)
        assert DataConverter.determine_status(market) == MarketStatus.CLOSED

        market2 = GammaMarket(active=False)
        assert DataConverter.determine_status(market2) == MarketStatus.CLOSED

    def test_determine_status_open(self):
        """Test determining open status"""
        market = GammaMarket(active=True, closed=False, resolved=False)
        assert DataConverter.determine_status(market) == MarketStatus.OPEN

    # =========================================================================
    # Extract Token IDs Tests
    # =========================================================================

    def test_extract_token_ids_success(self):
        """Test extracting token IDs"""
        tokens = [
            GammaToken(token_id="yes_token", outcome="Yes"),
            GammaToken(token_id="no_token", outcome="No"),
        ]
        yes_id, no_id = DataConverter.extract_token_ids(tokens)
        assert yes_id == "yes_token"
        assert no_id == "no_token"

    def test_extract_token_ids_case_insensitive(self):
        """Test extracting token IDs case insensitive"""
        tokens = [
            GammaToken(token_id="yes_token", outcome="YES"),
            GammaToken(token_id="no_token", outcome="NO"),
        ]
        yes_id, no_id = DataConverter.extract_token_ids(tokens)
        assert yes_id == "yes_token"
        assert no_id == "no_token"

    def test_extract_token_ids_missing(self):
        """Test extracting token IDs with missing tokens"""
        tokens = [
            GammaToken(token_id="yes_token", outcome="Yes"),
        ]
        yes_id, no_id = DataConverter.extract_token_ids(tokens)
        assert yes_id == "yes_token"
        assert no_id is None

    def test_extract_token_ids_empty(self):
        """Test extracting token IDs from empty list"""
        yes_id, no_id = DataConverter.extract_token_ids([])
        assert yes_id is None
        assert no_id is None

    # =========================================================================
    # Gamma to Market Tests
    # =========================================================================

    def test_gamma_to_market_success(self):
        """Test converting Gamma market to Market"""
        gamma_data = create_gamma_market_response()
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.market_id == "test_market_001"
        assert market.title == "Will BTC reach $100k?"
        assert market.category == MarketCategory.CRYPTO
        assert market.status == MarketStatus.OPEN
        assert market.yes_token_address == "token_yes_001"
        assert market.no_token_address == "token_no_001"
        assert market.total_volume_usd == 5000000.0
        assert market.volume_24h_usd == 200000.0

    def test_gamma_to_market_missing_id(self):
        """Test converting Gamma market with missing ID"""
        gamma_market = GammaMarket(question="Test?")

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is None

    def test_gamma_to_market_politics_forbidden(self):
        """Test converting politics market is forbidden for auto"""
        gamma_data = create_gamma_market_response(category="politics")
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.category == MarketCategory.POLITICS
        assert market.is_forbidden_auto is True

    def test_gamma_to_market_crypto_allowed(self):
        """Test converting crypto market is allowed for auto"""
        gamma_data = create_gamma_market_response(category="crypto")
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.category == MarketCategory.CRYPTO
        assert market.is_forbidden_auto is False

    def test_gamma_to_market_closed(self):
        """Test converting closed market"""
        gamma_data = create_gamma_market_response(closed=True, active=False)
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.status == MarketStatus.CLOSED

    def test_gamma_to_market_resolved(self):
        """Test converting resolved market"""
        gamma_data = create_gamma_market_response(resolved=True)
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.status == MarketStatus.RESOLVED

    def test_gamma_to_market_missing_tokens(self):
        """Test converting market with missing tokens"""
        gamma_data = create_gamma_market_response()
        gamma_data["tokens"] = []
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.yes_token_address is None
        assert market.no_token_address is None

    def test_gamma_to_market_invalid_volume(self):
        """Test converting market with invalid volume"""
        gamma_data = create_gamma_market_response()
        gamma_data["volume"] = "invalid"
        gamma_data["volume_24h"] = None
        gamma_market = GammaMarket(**gamma_data)

        market = DataConverter.gamma_to_market(gamma_market)

        assert market is not None
        assert market.total_volume_usd == 0.0
        assert market.volume_24h_usd == 0.0

    # =========================================================================
    # CLOB Level to Price Level Tests
    # =========================================================================

    def test_clob_level_to_price_level_success(self):
        """Test converting CLOB price level"""
        level = CLOBPriceLevel(price="0.45", size="1000")

        result = DataConverter.clob_level_to_price_level(level)

        assert result is not None
        assert result.price == 0.45
        assert result.size == 1000.0
        assert result.total_usd == 450.0

    def test_clob_level_to_price_level_invalid_price(self):
        """Test converting CLOB level with invalid price"""
        level = CLOBPriceLevel(price="invalid", size="1000")

        result = DataConverter.clob_level_to_price_level(level)

        assert result is None

    def test_clob_level_to_price_level_negative_price(self):
        """Test converting CLOB level with negative price"""
        level = CLOBPriceLevel(price="-0.5", size="1000")

        result = DataConverter.clob_level_to_price_level(level)

        assert result is None

    def test_clob_level_to_price_level_price_over_one(self):
        """Test converting CLOB level with price > 1"""
        level = CLOBPriceLevel(price="1.5", size="1000")

        result = DataConverter.clob_level_to_price_level(level)

        assert result is None

    def test_clob_level_to_price_level_missing_fields(self):
        """Test converting CLOB level with missing fields"""
        level = CLOBPriceLevel()

        result = DataConverter.clob_level_to_price_level(level)

        assert result is None

    # =========================================================================
    # CLOB Orderbooks to Snapshot Tests
    # =========================================================================

    def test_clob_orderbooks_to_snapshot_success(self):
        """Test converting CLOB orderbooks to snapshot"""
        yes_data, no_data = create_clob_orderbook_mispricing("0.48", "0.48")
        yes_book = CLOBOrderbook(**yes_data)
        no_book = CLOBOrderbook(**no_data)

        snapshot = DataConverter.clob_orderbooks_to_snapshot(
            yes_orderbook=yes_book,
            no_orderbook=no_book,
            market_id="test_market",
        )

        assert snapshot is not None
        assert snapshot.market_id == "test_market"
        assert snapshot.source == "clob"
        assert snapshot.combined_ask is not None
        # combined_ask = 0.48 + 0.48 = 0.96 (mispricing)
        assert abs(snapshot.combined_ask - 0.96) < 0.01

    def test_clob_orderbooks_to_snapshot_yes_only(self):
        """Test converting with only YES orderbook"""
        yes_data = create_clob_orderbook_response()
        yes_book = CLOBOrderbook(**yes_data)

        snapshot = DataConverter.clob_orderbooks_to_snapshot(
            yes_orderbook=yes_book,
            no_orderbook=None,
            market_id="test_market",
        )

        assert snapshot is not None
        assert len(snapshot.yes_bids.levels) > 0
        assert len(snapshot.no_bids.levels) == 0

    def test_clob_orderbooks_to_snapshot_no_only(self):
        """Test converting with only NO orderbook"""
        no_data = create_clob_orderbook_response()
        no_book = CLOBOrderbook(**no_data)

        snapshot = DataConverter.clob_orderbooks_to_snapshot(
            yes_orderbook=None,
            no_orderbook=no_book,
            market_id="test_market",
        )

        assert snapshot is not None
        assert len(snapshot.yes_bids.levels) == 0
        assert len(snapshot.no_bids.levels) > 0

    def test_clob_orderbooks_to_snapshot_both_none(self):
        """Test converting with both orderbooks None"""
        snapshot = DataConverter.clob_orderbooks_to_snapshot(
            yes_orderbook=None,
            no_orderbook=None,
            market_id="test_market",
        )

        assert snapshot is None

    # =========================================================================
    # CLOB Orderbook to Update Tests
    # =========================================================================

    def test_clob_orderbook_to_update_yes(self):
        """Test converting YES orderbook to update"""
        yes_data = create_clob_orderbook_response()
        yes_book = CLOBOrderbook(**yes_data)

        update = DataConverter.clob_orderbook_to_update(
            orderbook=yes_book,
            market_id="test_market",
            is_yes=True,
        )

        assert update.market_id == "test_market"
        assert update.yes_best_bid is not None
        assert update.yes_best_ask is not None
        assert update.no_best_bid is None
        assert update.no_best_ask is None

    def test_clob_orderbook_to_update_no(self):
        """Test converting NO orderbook to update"""
        no_data = create_clob_orderbook_response()
        no_book = CLOBOrderbook(**no_data)

        update = DataConverter.clob_orderbook_to_update(
            orderbook=no_book,
            market_id="test_market",
            is_yes=False,
        )

        assert update.market_id == "test_market"
        assert update.yes_best_bid is None
        assert update.yes_best_ask is None
        assert update.no_best_bid is not None
        assert update.no_best_ask is not None
