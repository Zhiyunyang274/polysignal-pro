"""
Tests for Wallet Intelligence Engine
"""

import pytest

from datetime import datetime, timedelta

from polysignal.models.wallet import WalletSpecialization
from polysignal.models.market import MarketCategory
from polysignal.engines.wallet_intelligence import WalletIntelligenceEngine
from tests.fixtures.wallets import (
    create_mock_watchlist,
    create_mock_wallet_profile,
    create_high_quality_wallet,
    create_medium_quality_wallet,
    create_high_copy_risk_wallet,
    create_wallet_market,
    create_politics_market,
    create_profiles_dict,
    create_consensus_activities_yes,
    create_consensus_activities_mixed,
    create_wallet_market_activity,
    MOCK_WALLET_ADDRESSES,
)


class TestWalletIntelligenceEngine:
    """Test Wallet Intelligence Engine"""

    @pytest.fixture
    def engine(self) -> WalletIntelligenceEngine:
        """Create engine with default settings"""
        watchlist = create_mock_watchlist()
        profiles = create_profiles_dict()
        return WalletIntelligenceEngine(watchlist=watchlist, profiles=profiles)

    # =========================================================================
    # Basic Tests
    # =========================================================================

    def test_default_settings(self, engine: WalletIntelligenceEngine):
        """Test default settings"""
        assert len(engine.watchlist) == 3
        assert engine.MIN_WALLETS_FOR_CONSENSUS == 2
        assert engine.MIN_SAME_DIRECTION_RATIO == 0.66

    def test_get_status(self, engine: WalletIntelligenceEngine):
        """Test get_status returns correct info"""
        status = engine.get_status()

        assert status["engine"] == "WalletIntelligenceEngine"
        assert status["watchlist_count"] == 3
        assert status["profiles_count"] == 3

    # =========================================================================
    # Wallet Score Tests
    # =========================================================================

    def test_wallet_score_calculation(self, engine: WalletIntelligenceEngine):
        """Test wallet_score is calculated correctly"""
        market = create_wallet_market()
        assessment = engine.assess(market)

        # Should have a valid wallet_score
        assert 0 <= assessment.wallet_score <= 100

    def test_wallet_score_with_specialization_match(self, engine: WalletIntelligenceEngine):
        """Test wallet_score is higher when specialization matches market"""
        crypto_market = create_wallet_market()
        assessment = engine.assess(crypto_market)

        # All test wallets are CRYPTO specialized, market is CRYPTO
        # Should get full specialization factor (1.0)
        assert assessment.wallet_score > 0

    def test_wallet_score_with_specialization_mismatch(self):
        """Test wallet_score is lower when specialization mismatches market"""
        # Create wallet with CRYPTO specialization
        crypto_wallet = create_mock_wallet_profile(
            primary_category=WalletSpecialization.CRYPTO,
        )

        watchlist = [
            __import__("polysignal.models.wallet", fromlist=["WatchlistEntry"]).WatchlistEntry(
                address=crypto_wallet.wallet_address,
                alias="crypto_wallet",
                is_active=True,
            )
        ]

        engine = WalletIntelligenceEngine(
            watchlist=watchlist,
            profiles={crypto_wallet.wallet_address: crypto_wallet},
        )

        # Test against POLITICS market (mismatch)
        politics_market = create_politics_market()
        assessment = engine.assess(politics_market)

        # Should have reduced score due to mismatch (0.7 factor)
        assert assessment.wallet_score < crypto_wallet.wallet_score

    def test_wallet_score_generalist(self):
        """Test generalist wallet gets moderate specialization factor"""
        generalist_wallet = create_mock_wallet_profile(
            primary_category=WalletSpecialization.GENERALIST,
        )

        watchlist = [
            __import__("polysignal.models.wallet", fromlist=["WatchlistEntry"]).WatchlistEntry(
                address=generalist_wallet.wallet_address,
                alias="generalist",
                is_active=True,
            )
        ]

        engine = WalletIntelligenceEngine(
            watchlist=watchlist,
            profiles={generalist_wallet.wallet_address: generalist_wallet},
        )

        market = create_wallet_market()
        assessment = engine.assess(market)

        # Generalist should get 0.9 factor
        assert assessment.wallet_score > 0

    # =========================================================================
    # Consensus Tests
    # =========================================================================

    def test_consensus_same_direction(self, engine: WalletIntelligenceEngine):
        """Test consensus detection with same direction"""
        market = create_wallet_market()
        activities = create_consensus_activities_yes()

        assessment = engine.assess(market, recent_activities=activities)

        # Should have consensus
        assert assessment.consensus is not None
        assert assessment.consensus.direction == "yes"
        assert assessment.consensus.consensus_score > 0
        assert assessment.wallet_consensus_score > 0

    def test_consensus_mixed_direction(self, engine: WalletIntelligenceEngine):
        """Test consensus with mixed directions"""
        market = create_wallet_market()
        activities = create_consensus_activities_mixed()

        assessment = engine.assess(market, recent_activities=activities)

        # Should not have strong consensus (only 50% same direction)
        assert assessment.consensus is not None
        # Consensus score should be low or 0
        assert assessment.wallet_consensus_score < 50

    def test_consensus_insufficient_wallets(self, engine: WalletIntelligenceEngine):
        """Test consensus with insufficient wallets"""
        market = create_wallet_market()
        # Only 1 activity
        activities = [
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
                side="yes",
            )
        ]

        assessment = engine.assess(market, recent_activities=activities)

        # Should not have consensus (need at least 2)
        assert assessment.consensus is not None
        assert assessment.consensus.active_wallet_count < 2
        assert assessment.wallet_consensus_score == 0

    def test_consensus_ratio_threshold(self, engine: WalletIntelligenceEngine):
        """Test consensus requires 66% same direction"""
        market = create_wallet_market()
        # 2 yes, 1 no = 66.7% yes (just above threshold)
        now = datetime.utcnow()
        activities = [
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
                side="yes",
                timestamp=now - timedelta(hours=1),
            ),
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_2"],
                side="yes",
                timestamp=now - timedelta(hours=2),
            ),
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["researcher_1"],
                side="no",
                timestamp=now - timedelta(hours=3),
            ),
        ]

        assessment = engine.assess(market, recent_activities=activities)

        # Should have consensus (2/3 = 66.7% >= 66%)
        assert assessment.consensus is not None
        assert assessment.consensus.direction == "yes"

    # =========================================================================
    # Copy Risk Tests
    # =========================================================================

    def test_copy_risk_low(self, engine: WalletIntelligenceEngine):
        """Test low copy risk detection"""
        market = create_wallet_market()
        assessment = engine.assess(market)

        # Test profiles have low copy ratio
        # copy_risk_score should be low
        assert assessment.copy_risk_score < 50

    def test_copy_risk_high(self):
        """Test high copy risk detection"""
        high_copy_wallet = create_high_copy_risk_wallet()

        watchlist = [
            __import__("polysignal.models.wallet", fromlist=["WatchlistEntry"]).WatchlistEntry(
                address=high_copy_wallet.wallet_address,
                alias="high_copy",
                is_active=True,
            )
        ]

        engine = WalletIntelligenceEngine(
            watchlist=watchlist,
            profiles={high_copy_wallet.wallet_address: high_copy_wallet},
        )

        market = create_wallet_market()
        assessment = engine.assess(market)

        # High copy ratio (0.8) should result in high copy_risk_score
        assert assessment.copy_risk_score >= 70
        assert "copy_risk_high" in assessment.risk_flags

    def test_copy_risk_penalty_calculation(self, engine: WalletIntelligenceEngine):
        """Test copy risk penalty is calculated correctly"""
        market = create_wallet_market()
        assessment = engine.assess(market)

        # Penalty = copy_risk_score * 0.30
        expected_penalty = assessment.copy_risk_score * 0.30
        assert abs(assessment.get_copy_risk_penalty() - expected_penalty) < 0.01

    # =========================================================================
    # Chase Risk Tests
    # =========================================================================

    def test_chase_risk_detection(self, engine: WalletIntelligenceEngine):
        """Test chase risk detection"""
        market = create_wallet_market()
        now = datetime.utcnow()

        # Activity at price 0.5, current price 0.55 (10% move)
        activities = [
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
                side="yes",
                price=0.5,
                timestamp=now - timedelta(minutes=30),
            )
        ]

        assessment = engine.assess(market, recent_activities=activities, current_price=0.55)

        # 10% price move > 5% threshold
        assert "chase_risk_high" in assessment.risk_flags

    def test_no_chase_risk_small_move(self, engine: WalletIntelligenceEngine):
        """Test no chase risk for small price moves"""
        market = create_wallet_market()
        now = datetime.utcnow()

        # Activity at price 0.5, current price 0.51 (2% move)
        activities = [
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
                side="yes",
                price=0.5,
                timestamp=now - timedelta(minutes=30),
            )
        ]

        assessment = engine.assess(market, recent_activities=activities, current_price=0.51)

        # 2% price move < 5% threshold
        assert "chase_risk_high" not in assessment.risk_flags

    # =========================================================================
    # Timing Risk Tests
    # =========================================================================

    def test_timing_risk_rapid_entries(self, engine: WalletIntelligenceEngine):
        """Test timing risk for rapid sequential entries"""
        market = create_wallet_market()
        now = datetime.utcnow()

        # 3 entries within 1 hour
        activities = [
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_1"],
                side="yes",
                timestamp=now - timedelta(minutes=10),
            ),
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["whale_2"],
                side="yes",
                timestamp=now - timedelta(minutes=20),
            ),
            create_wallet_market_activity(
                wallet_address=MOCK_WALLET_ADDRESSES["researcher_1"],
                side="yes",
                timestamp=now - timedelta(minutes=30),
            ),
        ]

        assessment = engine.assess(market, recent_activities=activities)

        assert "timing_risk_high" in assessment.risk_flags

    # =========================================================================
    # Wallet Signal Only Tests
    # =========================================================================

    def test_wallet_signal_only_detection(self, engine: WalletIntelligenceEngine):
        """Test wallet_signal_only detection"""
        # wallet_score >= 80, other scores < 60
        is_wallet_only = engine.is_wallet_signal_only(
            wallet_score=85,
            microstructure_score=50,
            event_score=55,
            liquidity_score=45,
        )

        assert is_wallet_only is True

    def test_wallet_signal_not_only_with_strong_microstructure(self, engine: WalletIntelligenceEngine):
        """Test not wallet_signal_only when microstructure is strong"""
        is_wallet_only = engine.is_wallet_signal_only(
            wallet_score=85,
            microstructure_score=70,  # Strong
            event_score=55,
            liquidity_score=45,
        )

        assert is_wallet_only is False

    def test_wallet_signal_not_only_with_weak_wallet(self, engine: WalletIntelligenceEngine):
        """Test not wallet_signal_only when wallet score is weak"""
        is_wallet_only = engine.is_wallet_signal_only(
            wallet_score=70,  # Not strong enough
            microstructure_score=50,
            event_score=55,
            liquidity_score=45,
        )

        assert is_wallet_only is False

    # =========================================================================
    # Inactive Wallet Tests
    # =========================================================================

    def test_inactive_wallet_ignored(self):
        """Test inactive wallets are ignored"""
        watchlist = [
            __import__("polysignal.models.wallet", fromlist=["WatchlistEntry"]).WatchlistEntry(
                address="0x1111",
                alias="active",
                is_active=True,
            ),
            __import__("polysignal.models.wallet", fromlist=["WatchlistEntry"]).WatchlistEntry(
                address="0x2222",
                alias="inactive",
                is_active=False,
            ),
        ]

        profiles = {
            "0x1111": create_high_quality_wallet(),
            "0x2222": create_high_quality_wallet(),
        }

        engine = WalletIntelligenceEngine(watchlist=watchlist, profiles=profiles)
        market = create_wallet_market()
        assessment = engine.assess(market)

        # Only active wallet should be counted
        assert len(assessment.active_wallets) == 1
        assert "0x1111" in assessment.active_wallets
        assert "0x2222" not in assessment.active_wallets

    # =========================================================================
    # Summary Tests
    # =========================================================================

    def test_get_summary(self, engine: WalletIntelligenceEngine):
        """Test assessment summary"""
        market = create_wallet_market()
        assessment = engine.assess(market)

        summary = assessment.get_summary()

        assert "Wallet" in summary
        assert "score=" in summary
        assert "consensus=" in summary
        assert "copy_risk=" in summary
