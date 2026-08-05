"""Tradable candidate pool construction for offline shadow trading.

tradable_score is a research/shadow priority score, not a trading signal.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


TRADABLE_SCORE_DISCLAIMER = (
    "tradable_score is a research/shadow priority score, not a trading signal."
)


@dataclass
class TradableCandidate:
    market_id: str
    question: str
    category: str = ""
    source: str = ""
    combined_ask: float = 0.0
    ambiguity_risk: float = 0.0
    liquidity_score: float = 0.0
    spread: float = 0.0
    orderbook_depth: float = 0.0
    near_miss_tier: str = ""
    appearances: int = 0
    evidence_level: str = ""
    is_avoid_candidate: bool = False
    near_miss_score: float = 0.0
    liquidity_score_component: float = 0.0
    ambiguity_penalty: float = 0.0
    spread_penalty: float = 0.0
    repeat_observation_score: float = 0.0
    watchlist_persistence_score: float = 0.0
    tradable_score: float = 0.0
    entry_decision_hint: str = "watch_only"
    reasons: list[str] = field(default_factory=list)
    alpha_score: float = 0.0
    run_ids: str = ""
    yes_token_id: str = ""
    no_token_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradableCandidateBuilderConfig:
    max_ambiguity_risk: float = 30.0
    min_liquidity_score: float = 1.0
    max_spread: float = 0.05
    min_orderbook_depth: float = 1.0
    top_n: int = 50


class TradableCandidateScorer:
    """Scores candidates for offline shadow-priority ordering only."""

    def near_miss_score(self, tier: str) -> float:
        normalized = (tier or "").lower()
        if normalized in {"tier1", "tier1_mispricing"}:
            return 40.0
        if normalized in {"tier2", "tier2_strong_near_miss"}:
            return 25.0
        if normalized in {"tier3", "tier3_weak_near_miss", "weak_near_miss"}:
            return 10.0
        return 0.0

    def liquidity_component(self, liquidity_score: float) -> float:
        return round(min(max(liquidity_score, 0.0) * 5.0, 20.0), 4)

    def ambiguity_penalty(self, ambiguity_risk: float) -> float:
        return round(min(max(ambiguity_risk, 0.0) / 2.0, 30.0), 4)

    def spread_penalty(self, spread: float) -> float:
        return round(min(max(spread, 0.0) * 100.0, 20.0), 4)

    def repeat_observation_score(self, appearances: int) -> float:
        return round(min(max(appearances, 0) * 2.0, 15.0), 4)

    def watchlist_persistence_score(self, evidence_level: str, appearances: int) -> float:
        level = (evidence_level or "").lower()
        if level == "strong":
            return 15.0
        if level == "moderate":
            return 8.0
        if level == "weak":
            return 3.0
        if appearances >= 5:
            return 10.0
        if appearances >= 2:
            return 5.0
        return 0.0

    def score(self, candidate: TradableCandidate) -> TradableCandidate:
        candidate.near_miss_score = self.near_miss_score(candidate.near_miss_tier)
        candidate.liquidity_score_component = self.liquidity_component(candidate.liquidity_score)
        candidate.ambiguity_penalty = self.ambiguity_penalty(candidate.ambiguity_risk)
        candidate.spread_penalty = self.spread_penalty(candidate.spread)
        candidate.repeat_observation_score = self.repeat_observation_score(candidate.appearances)
        candidate.watchlist_persistence_score = self.watchlist_persistence_score(
            candidate.evidence_level,
            candidate.appearances,
        )
        candidate.tradable_score = round(
            candidate.near_miss_score
            + candidate.liquidity_score_component
            + candidate.repeat_observation_score
            + candidate.watchlist_persistence_score
            - candidate.ambiguity_penalty
            - candidate.spread_penalty,
            4,
        )
        return candidate


class TradableCandidateBuilder:
    def __init__(
        self,
        config: Optional[TradableCandidateBuilderConfig] = None,
        scorer: Optional[TradableCandidateScorer] = None,
    ):
        self.config = config or TradableCandidateBuilderConfig()
        self.scorer = scorer or TradableCandidateScorer()
        self.exclusion_summary: Counter[str] = Counter()
        self.considered_count = 0

    def build(
        self,
        watchlist_rows: list[dict[str, Any]],
        alpha_rows: list[dict[str, Any]],
        avoid_rows: list[dict[str, Any]],
        trajectory_items: list[dict[str, Any]],
        control_group_rows: list[dict[str, Any]],
        alpha_validation_rows: Optional[list[dict[str, Any]]] = None,
        watchlist_validation_rows: Optional[list[dict[str, Any]]] = None,
    ) -> list[TradableCandidate]:
        self.exclusion_summary = Counter()
        self.considered_count = 0
        avoid_ids = self._avoid_ids(avoid_rows)
        alpha_validation = self._index_rows(alpha_validation_rows or [])
        watchlist_validation = self._index_rows(watchlist_validation_rows or [])

        raw_candidates: list[TradableCandidate] = []
        raw_candidates.extend(self._from_watchlist(watchlist_rows, avoid_ids, watchlist_validation))
        raw_candidates.extend(self._from_alpha(alpha_rows, avoid_ids, alpha_validation))
        raw_candidates.extend(self._from_trajectories(trajectory_items, avoid_ids))
        raw_candidates.extend(self._from_control_group(control_group_rows, avoid_ids))

        accepted: dict[str, TradableCandidate] = {}
        for candidate in raw_candidates:
            self.considered_count += 1
            exclusion_reasons = self._hard_exclusion_reasons(candidate)
            if exclusion_reasons:
                self.exclusion_summary.update(exclusion_reasons)
                continue

            scored = self.scorer.score(candidate)
            existing = accepted.get(scored.market_id)
            if existing is None or scored.tradable_score > existing.tradable_score:
                accepted[scored.market_id] = scored

        ordered = sorted(
            accepted.values(),
            key=lambda item: (item.tradable_score, item.appearances, item.market_id),
            reverse=True,
        )
        return ordered[: self.config.top_n]

    def _hard_exclusion_reasons(self, candidate: TradableCandidate) -> list[str]:
        reasons: list[str] = []
        if candidate.is_avoid_candidate:
            reasons.append("avoid_candidate")
        if candidate.ambiguity_risk > self.config.max_ambiguity_risk:
            reasons.append("high_ambiguity")
        if candidate.liquidity_score < self.config.min_liquidity_score:
            reasons.append("low_liquidity")
        if candidate.combined_ask <= 0:
            reasons.append("missing_combined_ask")
        if candidate.spread > self.config.max_spread:
            reasons.append("spread_too_wide")
        if candidate.orderbook_depth < self.config.min_orderbook_depth:
            reasons.append("insufficient_orderbook_depth")
        if "stale" in candidate.reasons:
            reasons.append("stale_data")
        if "llm_only" in candidate.reasons:
            reasons.append("llm_only")
        if "risk_hard_reject" in candidate.reasons:
            reasons.append("risk_hard_reject")
        if candidate.source == "alpha_score_only":
            reasons.append("alpha_score_only")
        return reasons

    def _from_watchlist(
        self,
        rows: list[dict[str, Any]],
        avoid_ids: set[str],
        validation: dict[str, dict[str, Any]],
    ) -> list[TradableCandidate]:
        candidates = []
        for row in rows:
            market_id = self._text(row.get("market_id"))
            if not market_id:
                continue
            appearances = self._int(row.get("appearances") or row.get("total_appearances"))
            combined_ask = self._float(row.get("avg_combined_ask"))
            tier = self._normalize_tier(row.get("near_miss_tier_mode") or row.get("near_miss_tier"))
            validation_row = validation.get(market_id, {})
            if not tier and self._int(validation_row.get("near_miss_hits")) > 0:
                tier = "tier2_strong_near_miss"
            reasons = ["non_avoid_watchlist", "watchlist_persistence"]
            hint = "eligible_shadow_entry" if tier in {"tier1_mispricing", "tier2_strong_near_miss"} else "watch_only"
            candidates.append(TradableCandidate(
                market_id=market_id,
                question=self._text(row.get("question")),
                category=self._text(row.get("category")),
                source="watchlist",
                combined_ask=combined_ask,
                ambiguity_risk=self._float(row.get("avg_ambiguity_risk")),
                liquidity_score=max(float(appearances), self._float(row.get("avg_volume"))),
                spread=max(0.0, combined_ask - 1.0),
                orderbook_depth=max(float(appearances), self._float(row.get("avg_volume"))),
                near_miss_tier=tier,
                appearances=appearances,
                evidence_level=self._text(row.get("evidence_level")),
                is_avoid_candidate=market_id in avoid_ids,
                entry_decision_hint=hint,
                reasons=reasons,
                run_ids=self._text(row.get("run_ids")),
            ))
        return candidates

    def _from_alpha(
        self,
        rows: list[dict[str, Any]],
        avoid_ids: set[str],
        validation: dict[str, dict[str, Any]],
    ) -> list[TradableCandidate]:
        candidates = []
        for row in rows:
            market_id = self._text(row.get("market_id"))
            if not market_id:
                continue
            validation_row = validation.get(market_id, {})
            appearances = self._int(row.get("appearances") or validation_row.get("num_observations"))
            combined_ask = self._float(row.get("avg_combined_ask") or validation_row.get("last_combined_ask"))
            liquidity = max(float(appearances), self._float(row.get("avg_volume")))
            reasons = ["alpha_quality_passed"]
            candidates.append(TradableCandidate(
                market_id=market_id,
                question=self._text(row.get("question")),
                category=self._text(row.get("category")),
                source="alpha_candidate",
                combined_ask=combined_ask,
                ambiguity_risk=self._float(row.get("avg_ambiguity_risk")),
                liquidity_score=liquidity,
                spread=max(0.0, combined_ask - 1.0),
                orderbook_depth=liquidity,
                near_miss_tier=self._normalize_tier(row.get("near_miss_tier")),
                appearances=appearances,
                evidence_level=self._text(row.get("evidence_level")),
                is_avoid_candidate=market_id in avoid_ids,
                entry_decision_hint="watch_only",
                reasons=reasons,
                alpha_score=self._float(row.get("alpha_score")),
                run_ids=self._text(row.get("run_ids")),
            ))
        return candidates

    def _from_trajectories(
        self,
        items: list[dict[str, Any]],
        avoid_ids: set[str],
    ) -> list[TradableCandidate]:
        candidates = []
        for item in items:
            if not isinstance(item, dict):
                continue
            market_id = self._text(item.get("market_id"))
            trajectory = item.get("trajectory", [])
            if not market_id or not isinstance(trajectory, list) or not trajectory:
                continue
            first = self._first_valid_observation(trajectory)
            last = self._last_valid_observation(trajectory)
            if not last:
                continue
            combined_ask = self._float(last.get("combined_ask"))
            first_combined_ask = self._float(first.get("combined_ask")) if first else combined_ask
            ambiguity_values = [self._float(obs.get("ambiguity_risk"), -1.0) for obs in trajectory if isinstance(obs, dict)]
            ambiguity_values = [value for value in ambiguity_values if value >= 0]
            ambiguity = sum(ambiguity_values) / len(ambiguity_values) if ambiguity_values else 0.0
            tier = self._normalize_tier(last.get("near_miss_tier") or item.get("near_miss_tier"))
            improving = combined_ask > 0 and first_combined_ask > 0 and combined_ask <= first_combined_ask
            if not tier:
                mode = self._text(last.get("suggested_mode"))
                if mode in {"alert", "alert_only"}:
                    tier = "tier2_strong_near_miss"
            if not tier and not improving:
                continue
            reasons = ["near_miss_trajectory"]
            hint = "watch_only"
            if tier in {"tier1_mispricing", "tier2_strong_near_miss"}:
                hint = "eligible_shadow_entry"
            elif tier == "tier3_weak_near_miss" and improving:
                reasons.append("tier3_improving_watch_only")
            elif improving:
                reasons.append("improving_combined_ask")
            candidates.append(TradableCandidate(
                market_id=market_id,
                question=self._text(item.get("question")),
                category=self._text(item.get("category")),
                source="near_miss_trajectory",
                combined_ask=combined_ask,
                ambiguity_risk=ambiguity,
                liquidity_score=float(len(trajectory)),
                spread=max(0.0, combined_ask - 1.0),
                orderbook_depth=float(len(trajectory)),
                near_miss_tier=tier,
                appearances=len(trajectory),
                evidence_level="trajectory",
                is_avoid_candidate=market_id in avoid_ids,
                entry_decision_hint=hint,
                reasons=reasons,
            ))
        return candidates

    def _from_control_group(
        self,
        rows: list[dict[str, Any]],
        avoid_ids: set[str],
    ) -> list[TradableCandidate]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            market_id = self._text(row.get("market_id"))
            if market_id:
                grouped.setdefault(market_id, []).append(row)

        candidates = []
        for market_id, market_rows in grouped.items():
            combined_values = [self._float(row.get("combined_ask")) for row in market_rows]
            ambiguity_values = [self._float(row.get("ambiguity_risk"), -1.0) for row in market_rows]
            ambiguity_values = [value for value in ambiguity_values if value >= 0]
            combined_ask = sum(combined_values) / len(combined_values) if combined_values else 0.0
            ambiguity = sum(ambiguity_values) / len(ambiguity_values) if ambiguity_values else 0.0
            first = market_rows[0]
            candidates.append(TradableCandidate(
                market_id=market_id,
                question=self._text(first.get("question")),
                category=self._text(first.get("category")),
                source="control_group",
                combined_ask=combined_ask,
                ambiguity_risk=ambiguity,
                liquidity_score=float(len(market_rows)),
                spread=max(0.0, combined_ask - 1.0),
                orderbook_depth=float(len(market_rows)),
                near_miss_tier="",
                appearances=len(market_rows),
                evidence_level="control_group",
                is_avoid_candidate=market_id in avoid_ids,
                entry_decision_hint="watch_only",
                reasons=["low_risk_control_group"],
            ))
        return candidates

    @staticmethod
    def _avoid_ids(rows: list[dict[str, Any]]) -> set[str]:
        return {str(row.get("market_id") or "") for row in rows if row.get("market_id")}

    @staticmethod
    def _index_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(row.get("market_id") or ""): row for row in rows if row.get("market_id")}

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        if value in (None, ""):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _int(value: Any, default: int = 0) -> int:
        if value in (None, ""):
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_tier(cls, value: Any) -> str:
        raw = cls._text(value).lower()
        mapping = {
            "tier1": "tier1_mispricing",
            "tier 1": "tier1_mispricing",
            "tier2": "tier2_strong_near_miss",
            "tier 2": "tier2_strong_near_miss",
            "tier3": "tier3_weak_near_miss",
            "tier 3": "tier3_weak_near_miss",
        }
        return mapping.get(raw, raw)

    @staticmethod
    def _first_valid_observation(trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        for observation in trajectory:
            if isinstance(observation, dict) and observation.get("combined_ask") not in (None, ""):
                return observation
        return {}

    @staticmethod
    def _last_valid_observation(trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        for observation in reversed(trajectory):
            if isinstance(observation, dict) and observation.get("combined_ask") not in (None, ""):
                return observation
        return {}
