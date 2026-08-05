"""
Wallet Intelligence Engine - Analyze wallet behavior and calculate wallet scores

This engine operates in the SLOW path and does NOT call LLM.

Responsibilities:
- Load wallet watchlist from config
- Generate wallet profiles from activity history
- Calculate wallet_score
- Calculate wallet_consensus_score
- Detect copy trading risk
- Detect chase (追高) risk

Output:
- wallet_score (0-100)
- wallet_consensus_score (0-100)
- copy_risk_score (0-100)
- risk_flags

IMPORTANT: This engine does NOT:
- Trigger trades
- Bypass Risk Governor
- Connect to real APIs
- Process real private keys
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from polysignal.models.wallet import (
    WalletAssessment,
    WalletConsensus,
    WalletMarketActivity,
    WalletProfile,
    WalletSpecialization,
    WatchlistEntry,
)
from polysignal.models.market import Market, MarketCategory


class WalletIntelligenceEngine:
    """
    Wallet Intelligence Engine.

    Analyzes wallet behavior and provides auxiliary scoring.
    Does NOT trigger trades directly.
    """

    # Score weights
    RELIABILITY_WEIGHT = 0.30
    PERFORMANCE_WEIGHT = 0.35
    SPECIALIZATION_WEIGHT = 0.20
    DISCIPLINE_WEIGHT = 0.15

    # Copy risk thresholds
    COPY_RISK_LOW = 0.3
    COPY_RISK_MEDIUM = 0.5
    COPY_RISK_HIGH = 0.7

    # Consensus thresholds
    MIN_WALLETS_FOR_CONSENSUS = 2
    MIN_SAME_DIRECTION_RATIO = 0.66

    # Chase detection thresholds
    CHASE_PRICE_THRESHOLD = 0.05  # 5% price movement
    CHASE_TIME_WINDOW_HOURS = 1
    CHASE_PRICE_MOVE_THRESHOLD = 0.03  # 3% fast move

    def __init__(
        self,
        watchlist: Optional[list[WatchlistEntry]] = None,
        profiles: Optional[dict[str, WalletProfile]] = None,
        copy_risk_threshold: float = 0.5,
        chase_price_threshold: float = 0.05,
    ):
        """
        Initialize Wallet Intelligence Engine.

        Args:
            watchlist: List of wallets to monitor
            profiles: Pre-computed wallet profiles
            copy_risk_threshold: Threshold for copy_risk_high flag
            chase_price_threshold: Threshold for chase_risk_high flag
        """
        self.watchlist = watchlist or []
        self.profiles = profiles or {}
        self.copy_risk_threshold = copy_risk_threshold
        self.chase_price_threshold = chase_price_threshold

    def assess(
        self,
        market: Market,
        recent_activities: Optional[list[WalletMarketActivity]] = None,
        current_price: Optional[float] = None,
    ) -> WalletAssessment:
        """
        Assess wallet signals for a market.

        Args:
            market: Market to assess
            recent_activities: Recent wallet activities in this market
            current_price: Current market price (for chase detection)

        Returns:
            WalletAssessment with scores and flags
        """
        risk_flags = []

        # Step 1: Calculate average wallet_score from active wallets
        wallet_score = self._calculate_average_wallet_score(market)

        # Step 2: Calculate consensus score
        consensus = self._calculate_consensus(market, recent_activities)
        wallet_consensus_score = consensus.consensus_score if consensus else 0.0

        # Step 3: Calculate copy risk score
        copy_risk_score = self._calculate_copy_risk_score(market)

        # Step 4: Detect risks
        risk_flags.extend(self._detect_copy_risk(copy_risk_score))
        risk_flags.extend(self._detect_chase_risk(recent_activities, current_price))
        risk_flags.extend(self._detect_timing_risk(recent_activities))

        # Step 5: Check for wallet_signal_only condition
        # (This will be re-checked by Risk Governor as well)
        if wallet_score >= 80:
            risk_flags.append("high_wallet_score")

        # Generate explanation
        explanation = self._generate_explanation(
            wallet_score=wallet_score,
            consensus_score=wallet_consensus_score,
            copy_risk_score=copy_risk_score,
            risk_flags=risk_flags,
        )

        # Get active wallet addresses
        active_wallets = [
            entry.address for entry in self.watchlist
            if entry.is_active and entry.address in self.profiles
        ]

        return WalletAssessment(
            market_id=market.market_id,
            wallet_score=wallet_score,
            wallet_consensus_score=wallet_consensus_score,
            copy_risk_score=copy_risk_score,
            consensus=consensus,
            risk_flags=risk_flags,
            active_wallets=active_wallets,
            explanation=explanation,
        )

    def _calculate_average_wallet_score(self, market: Market) -> float:
        """Calculate average wallet_score from active watchlist wallets."""
        active_profiles = [
            self.profiles[entry.address]
            for entry in self.watchlist
            if entry.is_active and entry.address in self.profiles
        ]

        if not active_profiles:
            return 50.0  # Default neutral score

        # Calculate specialization-adjusted scores
        adjusted_scores = []
        for profile in active_profiles:
            base_score = profile.wallet_score

            # Apply specialization adjustment
            specialization_factor = self._get_specialization_factor(profile, market)

            adjusted_score = base_score * specialization_factor
            adjusted_scores.append(adjusted_score)

        return sum(adjusted_scores) / len(adjusted_scores)

    def _get_specialization_factor(
        self,
        profile: WalletProfile,
        market: Market,
    ) -> float:
        """
        Get specialization factor based on wallet's primary category vs market category.

        Returns:
            1.0 if wallet specializes in this category
            0.9 if wallet is generalist
            0.7 if wallet specializes in different category
        """
        wallet_category = profile.primary_category.value
        market_category = market.category.value

        if wallet_category == market_category:
            return 1.0  # Perfect match
        elif wallet_category == WalletSpecialization.GENERALIST.value:
            return 0.9  # Generalist - moderate
        else:
            return 0.7  # Mismatch - lower confidence

    def _calculate_consensus(
        self,
        market: Market,
        recent_activities: Optional[list[WalletMarketActivity]],
    ) -> Optional[WalletConsensus]:
        """
        Calculate wallet consensus for a market.

        Consensus requires:
        - At least MIN_WALLETS_FOR_CONSENSUS wallets with activity
        - At least MIN_SAME_DIRECTION_RATIO (66%) in same direction
        """
        if not recent_activities:
            return WalletConsensus(market_id=market.market_id)

        # Filter to active wallets only
        active_addresses = {
            entry.address for entry in self.watchlist if entry.is_active
        }
        filtered_activities = [
            a for a in recent_activities
            if a.wallet_address in active_addresses
        ]

        if len(filtered_activities) < self.MIN_WALLETS_FOR_CONSENSUS:
            return WalletConsensus(
                market_id=market.market_id,
                active_wallet_count=len(filtered_activities),
            )

        # Count directions
        yes_count = sum(1 for a in filtered_activities if a.side == "yes")
        no_count = sum(1 for a in filtered_activities if a.side == "no")
        total = len(filtered_activities)

        # Determine consensus direction
        yes_ratio = yes_count / total
        no_ratio = no_count / total

        if yes_ratio >= self.MIN_SAME_DIRECTION_RATIO:
            direction = "yes"
            same_direction_count = yes_count
            same_direction_ratio = yes_ratio
        elif no_ratio >= self.MIN_SAME_DIRECTION_RATIO:
            direction = "no"
            same_direction_count = no_count
            same_direction_ratio = no_ratio
        else:
            # No consensus
            return WalletConsensus(
                market_id=market.market_id,
                active_wallet_count=total,
                same_direction_count=max(yes_count, no_count),
                same_direction_ratio=max(yes_ratio, no_ratio),
            )

        # Calculate consensus score
        # Weight by wallet scores
        direction_activities = [
            a for a in filtered_activities if a.side == direction
        ]
        weighted_score = sum(a.wallet_score for a in direction_activities)
        consensus_score = weighted_score / len(direction_activities)

        return WalletConsensus(
            market_id=market.market_id,
            direction=direction,
            consensus_score=consensus_score,
            active_wallet_count=total,
            same_direction_count=same_direction_count,
            same_direction_ratio=same_direction_ratio,
            participating_wallets=[a.wallet_address for a in direction_activities],
        )

    def _calculate_copy_risk_score(self, market: Market) -> float:
        """
        Calculate copy risk score (0-100).

        Higher score = more risky (more copy trading behavior).
        """
        active_profiles = [
            self.profiles[entry.address]
            for entry in self.watchlist
            if entry.is_active and entry.address in self.profiles
        ]

        if not active_profiles:
            return 0.0

        # Average copy ratio across active wallets
        avg_copy_ratio = sum(p.copy_ratio for p in active_profiles) / len(active_profiles)

        # Convert to 0-100 scale
        copy_risk_score = avg_copy_ratio * 100

        return copy_risk_score

    def _detect_copy_risk(self, copy_risk_score: float) -> list[str]:
        """Detect copy trading risk flags."""
        flags = []

        if copy_risk_score >= 70:  # copy_ratio >= 0.7
            flags.append("copy_risk_high")
        elif copy_risk_score >= 50:  # copy_ratio >= 0.5
            flags.append("copy_risk_medium")
        elif copy_risk_score >= 30:  # copy_ratio >= 0.3
            flags.append("copy_risk_low")

        return flags

    def _detect_chase_risk(
        self,
        recent_activities: Optional[list[WalletMarketActivity]],
        current_price: Optional[float],
    ) -> list[str]:
        """
        Detect chase (追高) risk.

        Chase risk occurs when wallets enter after price has already moved significantly.
        """
        if not recent_activities or current_price is None:
            return []

        flags = []

        # Check each activity for chase behavior
        now = datetime.utcnow()
        for activity in recent_activities:
            # Check if activity is recent (within time window)
            time_diff = now - activity.timestamp
            if time_diff > timedelta(hours=self.CHASE_TIME_WINDOW_HOURS):
                continue

            # Check price movement from entry
            if activity.price > 0:
                price_move = abs(current_price - activity.price) / activity.price

                if price_move >= self.chase_price_threshold:
                    flags.append("chase_risk_high")
                    break  # Only add once

        return flags

    def _detect_timing_risk(
        self,
        recent_activities: Optional[list[WalletMarketActivity]],
    ) -> list[str]:
        """Detect timing risk (entering after fast price moves)."""
        if not recent_activities:
            return []

        flags = []

        # Sort activities by timestamp
        sorted_activities = sorted(recent_activities, key=lambda a: a.timestamp)

        # Check for rapid sequential entries (could indicate FOMO)
        if len(sorted_activities) >= 3:
            # Check if multiple wallets entered within short time window
            time_window = timedelta(hours=self.CHASE_TIME_WINDOW_HOURS)

            for i in range(len(sorted_activities) - 2):
                window_start = sorted_activities[i].timestamp
                window_end = sorted_activities[i + 2].timestamp

                if window_end - window_start <= time_window:
                    # 3+ entries in 1 hour = timing risk
                    flags.append("timing_risk_high")
                    break

        return flags

    def _generate_explanation(
        self,
        wallet_score: float,
        consensus_score: float,
        copy_risk_score: float,
        risk_flags: list[str],
    ) -> str:
        """Generate human-readable explanation."""
        parts = [
            f"Wallet Score: {wallet_score:.1f}",
            f"Consensus: {consensus_score:.1f}",
            f"Copy Risk: {copy_risk_score:.1f}",
        ]

        if risk_flags:
            parts.append(f"Flags: {', '.join(risk_flags)}")

        return " | ".join(parts)

    def get_status(self) -> dict[str, Any]:
        """Get engine status"""
        return {
            "engine": "WalletIntelligenceEngine",
            "watchlist_count": len(self.watchlist),
            "active_watchlist_count": sum(1 for e in self.watchlist if e.is_active),
            "profiles_count": len(self.profiles),
            "copy_risk_threshold": self.copy_risk_threshold,
            "chase_price_threshold": self.chase_price_threshold,
        }

    def is_wallet_signal_only(
        self,
        wallet_score: float,
        microstructure_score: float,
        event_score: float,
        liquidity_score: float,
    ) -> bool:
        """
        Check if this is a wallet-signal-only scenario.

        A wallet-signal-only scenario is when:
        - wallet_score >= 80 (strong wallet signal)
        - microstructure_score < 60 (weak market signal)
        - event_score < 60 (weak event signal)
        - liquidity_score < 60 (weak liquidity signal)

        This should trigger hard reject in Risk Governor.
        """
        return (
            wallet_score >= 80
            and microstructure_score < 60
            and event_score < 60
            and liquidity_score < 60
        )
