"""
Resolution & Lifecycle Engine - Market lifecycle and resolution risk assessment

This engine operates in the FAST path and does NOT call LLM.

Responsibilities:
- Track market lifecycle phase
- Calculate close_time_risk
- Detect ambiguity risk
- Detect resolution risk
- Check forbidden category
- Calculate lifecycle_score

Output:
- lifecycle_score (0-100)
- is_tradable
- risk_flags
- hard_reject_reasons (for Risk Governor)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.lifecycle import (
    LifecycleAssessment,
    LifecyclePhase,
    AmbiguityLevel,
    ResolutionRiskLevel,
)


# Default ambiguity keywords (can be overridden by config)
DEFAULT_AMBIGUITY_KEYWORDS = [
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
]

# Resolution source reliability levels
HIGH_RELIABILITY_SOURCES = ["polymarket", "uma", "oracle", "chainlink", "pyth"]
MEDIUM_RELIABILITY_SOURCES = ["manual", "admin", "committee"]


class ResolutionLifecycleEngine:
    """
    Resolution & Lifecycle Engine.

    Assesses market lifecycle phase, ambiguity risk, resolution risk,
    and calculates lifecycle_score.

    This engine does NOT:
    - Call LLM
    - Access external APIs
    - Trigger trades
    - Bypass Risk Governor
    """

    # Phase thresholds
    EARLY_THRESHOLD = 0.90      # > 90% time remaining = EARLY
    LATE_THRESHOLD = 0.20       # < 20% time remaining = LATE
    CLOSING_THRESHOLD = 0.05    # < 5% time remaining = CLOSING

    # Score base values per phase
    PHASE_BASE_SCORES = {
        LifecyclePhase.EARLY: 80,
        LifecyclePhase.MID: 90,
        LifecyclePhase.LATE: 70,
        LifecyclePhase.CLOSING: 50,
        LifecyclePhase.CLOSED: 0,
        LifecyclePhase.RESOLVED: 0,
    }

    # Penalty multipliers
    AMBIGUITY_PENALTY_MULTIPLIER = 40
    RESOLUTION_PENALTY_MULTIPLIER = 25
    CLOSE_TIME_PENALTY_MULTIPLIER = 20

    def __init__(
        self,
        ambiguity_keywords: Optional[list[str]] = None,
        early_threshold: float = 0.90,
        late_threshold: float = 0.20,
        closing_threshold: float = 0.05,
        close_time_risk_threshold: float = 0.7,
    ):
        """
        Initialize Resolution & Lifecycle Engine.

        Args:
            ambiguity_keywords: Keywords indicating ambiguity (from config)
            early_threshold: Time remaining % for EARLY phase
            late_threshold: Time remaining % for LATE phase
            closing_threshold: Time remaining % for CLOSING phase
            close_time_risk_threshold: Threshold for close_time_risk warning
        """
        self.ambiguity_keywords = ambiguity_keywords or DEFAULT_AMBIGUITY_KEYWORDS
        self.early_threshold = early_threshold
        self.late_threshold = late_threshold
        self.closing_threshold = closing_threshold
        self.close_time_risk_threshold = close_time_risk_threshold

    def assess(self, market: Market) -> LifecycleAssessment:
        """
        Assess a market's lifecycle and resolution risk.

        Args:
            market: Market to assess

        Returns:
            LifecycleAssessment with scores and flags
        """
        now = datetime.utcnow()

        # Step 1: Determine phase and close_time_risk
        phase, close_time_risk, time_remaining_pct = self._calculate_phase(
            now=now,
            close_time=market.close_time,
            created_at=market.created_at,
            status=market.status,
        )

        # Step 2: Detect ambiguity risk
        ambiguity_risk, ambiguity_level, ambiguity_flags = self._detect_ambiguity_risk(market)

        # Step 3: Detect resolution risk
        resolution_risk, resolution_level, resolution_flags = self._detect_resolution_risk(market)

        # Step 4: Check forbidden category
        is_auto_allowed, forbidden_flags = self._check_forbidden_category(market)

        # Step 5: Calculate lifecycle_score
        lifecycle_score = self._calculate_lifecycle_score(
            phase=phase,
            ambiguity_risk=ambiguity_risk,
            resolution_risk=resolution_risk,
            close_time_risk=close_time_risk,
        )

        # Step 6: Determine hard reject reasons
        hard_reject_reasons = []
        risk_flags = []

        # Market status check
        if market.status != MarketStatus.OPEN:
            hard_reject_reasons.append("market_not_open")

        # Ambiguity check
        if ambiguity_level == AmbiguityLevel.CRITICAL:
            hard_reject_reasons.append("market_ambiguous")

        # Forbidden category (for info, Risk Governor will also check directly)
        if not is_auto_allowed:
            risk_flags.append("forbidden_category")

        # Combine all risk flags
        risk_flags.extend(ambiguity_flags)
        risk_flags.extend(resolution_flags)
        risk_flags.extend(forbidden_flags)

        # Determine is_tradable
        is_tradable = (
            market.status == MarketStatus.OPEN
            and ambiguity_level != AmbiguityLevel.CRITICAL
            and lifecycle_score > 0
        )

        # Generate explanation
        explanation = self._generate_explanation(
            phase=phase,
            lifecycle_score=lifecycle_score,
            ambiguity_level=ambiguity_level,
            resolution_level=resolution_level,
            is_tradable=is_tradable,
        )

        return LifecycleAssessment(
            market_id=market.market_id,
            phase=phase,
            time_remaining_pct=time_remaining_pct,
            lifecycle_score=lifecycle_score,
            ambiguity_risk=ambiguity_risk,
            resolution_risk=resolution_risk,
            close_time_risk=close_time_risk,
            is_tradable=is_tradable,
            is_auto_allowed=is_auto_allowed,
            hard_reject_reasons=hard_reject_reasons,
            risk_flags=risk_flags,
            ambiguity_level=ambiguity_level,
            resolution_risk_level=resolution_level,
            explanation=explanation,
        )

    def _calculate_phase(
        self,
        now: datetime,
        close_time: Optional[datetime],
        created_at: Optional[datetime],
        status: MarketStatus,
    ) -> tuple[LifecyclePhase, float, Optional[float]]:
        """
        Calculate lifecycle phase and close time risk.

        Returns:
            (phase, close_time_risk, time_remaining_pct)
        """
        # Handle non-OPEN status
        if status == MarketStatus.CLOSED:
            return LifecyclePhase.CLOSED, 1.0, 0.0

        if status == MarketStatus.RESOLVED:
            return LifecyclePhase.RESOLVED, 1.0, 0.0

        if status == MarketStatus.CANCELLED:
            return LifecyclePhase.CLOSED, 1.0, 0.0

        # No close_time: treat as long-term market
        if close_time is None:
            return LifecyclePhase.MID, 0.0, None

        # Calculate time remaining
        time_to_close = (close_time - now).total_seconds()

        # Market already past close time
        if time_to_close <= 0:
            return LifecyclePhase.CLOSED, 1.0, 0.0

        # If we have created_at, calculate percentage
        if created_at is not None:
            total_duration = (close_time - created_at).total_seconds()

            if total_duration <= 0:
                # Invalid duration, use absolute time
                return LifecyclePhase.MID, 0.0, None

            time_remaining_pct = time_to_close / total_duration

            # Determine phase based on percentage
            if time_remaining_pct >= self.early_threshold:
                phase = LifecyclePhase.EARLY
                close_time_risk = 0.1
            elif time_remaining_pct <= self.closing_threshold:
                phase = LifecyclePhase.CLOSING
                close_time_risk = 0.9
            elif time_remaining_pct <= self.late_threshold:
                phase = LifecyclePhase.LATE
                close_time_risk = 0.5
            else:
                phase = LifecyclePhase.MID
                close_time_risk = 0.0

            return phase, close_time_risk, time_remaining_pct

        # No created_at: use absolute remaining time to estimate
        # If < 1 hour remaining, treat as CLOSING
        # If < 24 hours remaining, treat as LATE
        # Otherwise, treat as MID
        hours_remaining = time_to_close / 3600

        if hours_remaining <= 1:
            return LifecyclePhase.CLOSING, 0.9, None
        elif hours_remaining <= 24:
            return LifecyclePhase.LATE, 0.5, None
        else:
            return LifecyclePhase.MID, 0.0, None

    def _detect_ambiguity_risk(
        self,
        market: Market,
    ) -> tuple[float, AmbiguityLevel, list[str]]:
        """
        Detect ambiguity risk from market data.

        Returns:
            (ambiguity_risk, level, risk_flags)
        """
        flags = []

        # 1. Explicit flag - CRITICAL
        if market.is_ambiguous:
            return 1.0, AmbiguityLevel.CRITICAL, ["explicitly_ambiguous"]

        # 2. Resolution source check
        if not market.resolution_source:
            flags.append("no_resolution_source")
            return 0.8, AmbiguityLevel.HIGH, flags

        source_lower = market.resolution_source.lower()
        for keyword in self.ambiguity_keywords:
            if keyword in source_lower:
                flags.append(f"ambiguous_source_keyword:{keyword}")
                return 0.5, AmbiguityLevel.MEDIUM, flags

        # 3. Resolution criteria check
        if not market.resolution_criteria or len(market.resolution_criteria) < 20:
            flags.append("insufficient_criteria")
            return 0.2, AmbiguityLevel.LOW, flags

        # 4. Title/Description check for ambiguity keywords
        title_lower = market.title.lower()
        for keyword in self.ambiguity_keywords:
            if keyword in title_lower:
                flags.append(f"ambiguous_title_keyword:{keyword}")
                return 0.5, AmbiguityLevel.MEDIUM, flags

        if market.description:
            desc_lower = market.description.lower()
            for keyword in self.ambiguity_keywords:
                if keyword in desc_lower:
                    flags.append(f"ambiguous_desc_keyword:{keyword}")
                    return 0.3, AmbiguityLevel.LOW, flags

        return 0.0, AmbiguityLevel.NONE, []

    def _detect_resolution_risk(
        self,
        market: Market,
    ) -> tuple[float, ResolutionRiskLevel, list[str]]:
        """
        Detect resolution risk.

        Returns:
            (resolution_risk, level, risk_flags)
        """
        flags = []

        # Category-based resolution risk
        high_risk_categories = {
            MarketCategory.POLITICS,
            MarketCategory.WAR_GEOPOLITICS,
            MarketCategory.LEGAL,
            MarketCategory.CELEBRITY,
            MarketCategory.SUBJECTIVE,
        }

        if market.category in high_risk_categories:
            flags.append(f"high_resolution_risk_category:{market.category.value}")
            return 0.7, ResolutionRiskLevel.HIGH, flags

        # Resolution source reliability
        if market.resolution_source:
            source_lower = market.resolution_source.lower()

            # Check for high reliability sources
            for src in HIGH_RELIABILITY_SOURCES:
                if src in source_lower:
                    return 0.0, ResolutionRiskLevel.NONE, []

            # Check for medium reliability sources
            for src in MEDIUM_RELIABILITY_SOURCES:
                if src in source_lower:
                    flags.append("medium_reliability_source")
                    return 0.3, ResolutionRiskLevel.LOW, flags

            # Unknown source
            flags.append("unknown_resolution_source")
            return 0.5, ResolutionRiskLevel.MEDIUM, flags

        # No resolution source
        flags.append("no_resolution_source")
        return 0.6, ResolutionRiskLevel.MEDIUM, flags

    def _check_forbidden_category(
        self,
        market: Market,
    ) -> tuple[bool, list[str]]:
        """
        Check if market is in forbidden category.

        Returns:
            (is_auto_allowed, risk_flags)
        """
        forbidden_categories = {
            MarketCategory.POLITICS,
            MarketCategory.WAR_GEOPOLITICS,
            MarketCategory.LEGAL,
            MarketCategory.CELEBRITY,
            MarketCategory.SUBJECTIVE,
        }

        if market.category in forbidden_categories:
            return False, [f"forbidden_category:{market.category.value}"]

        if market.is_forbidden_auto:
            return False, ["forbidden_auto_flag"]

        return True, []

    def _calculate_lifecycle_score(
        self,
        phase: LifecyclePhase,
        ambiguity_risk: float,
        resolution_risk: float,
        close_time_risk: float,
    ) -> float:
        """
        Calculate lifecycle_score.

        Formula:
            lifecycle_score = base_score
                              - ambiguity_risk * 40
                              - resolution_risk * 25
                              - close_time_risk * 20
        """
        base_score = self.PHASE_BASE_SCORES.get(phase, 50)

        ambiguity_penalty = ambiguity_risk * self.AMBIGUITY_PENALTY_MULTIPLIER
        resolution_penalty = resolution_risk * self.RESOLUTION_PENALTY_MULTIPLIER
        close_time_penalty = close_time_risk * self.CLOSE_TIME_PENALTY_MULTIPLIER

        score = base_score - ambiguity_penalty - resolution_penalty - close_time_penalty

        return max(0.0, min(100.0, score))

    def _generate_explanation(
        self,
        phase: LifecyclePhase,
        lifecycle_score: float,
        ambiguity_level: AmbiguityLevel,
        resolution_level: ResolutionRiskLevel,
        is_tradable: bool,
    ) -> str:
        """Generate human-readable explanation"""
        parts = [
            f"Phase: {phase.value}",
            f"Score: {lifecycle_score:.1f}",
        ]

        if ambiguity_level != AmbiguityLevel.NONE:
            parts.append(f"Ambiguity: {ambiguity_level.value}")

        if resolution_level != ResolutionRiskLevel.NONE:
            parts.append(f"Resolution Risk: {resolution_level.value}")

        if is_tradable:
            parts.append("Status: TRADABLE")
        else:
            parts.append("Status: NOT TRADABLE")

        return " | ".join(parts)

    def get_status(self) -> dict[str, Any]:
        """Get engine status"""
        return {
            "engine": "ResolutionLifecycleEngine",
            "ambiguity_keywords_count": len(self.ambiguity_keywords),
            "early_threshold": self.early_threshold,
            "late_threshold": self.late_threshold,
            "closing_threshold": self.closing_threshold,
        }
