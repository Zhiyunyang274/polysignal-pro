"""Entry filtering for offline shadow trades."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from polysignal.shadow.models import CandidateSnapshot


NEAR_MISS_TIERS_ALLOWED = {"tier1_mispricing", "tier2_strong_near_miss", "tier1", "tier2"}
NEAR_MISS_TIERS_WATCH = {"tier3_weak_near_miss", "tier3", "weak_near_miss"}
TRADABLE_SUPPORT_REASONS = {
    "non_avoid_watchlist",
    "watchlist_persistence",
    "near_miss_trajectory",
    "tier3_improving_watch_only",
    "improving_combined_ask",
    "low_risk_control_group",
    "alpha_quality_passed",
    "microstructure_edge",
    "executable_edge_discovery",
    "probability_edge_v1",
    "microstructure_probability_edge",
    "probability_edge_v2",
    "calibrated_microstructure_probability_edge",
    "cross_market_consistency_v1",
    "same_event_duplicate",
    "near_duplicate_price_gap",
            "cross_market_price_gap",
            "high_confidence_duplicate",
            "relationship_calibrated",
            "convergence_gate_passed",
            "cross_market_convergence_observed",
            "crypto_price_threshold_v1",
            "crypto_threshold_edge",
            "external_spot_price",
            "threshold_parser_high_confidence",
            "spot_price_fresh",
}
PROBABILITY_EDGE_TYPES = {"price_dislocation_probability_v1", "price_dislocation_probability_v2"}


class EntryDecision(str, Enum):
    ELIGIBLE_SHADOW_ENTRY = "eligible_shadow_entry"
    WATCH_ONLY = "watch_only"
    REJECTED = "rejected"


@dataclass
class EntryFilterConfig:
    min_alpha_score: float = 35.0
    min_watch_alpha_score: float = 30.0
    max_ambiguity_risk: float = 30.0
    watch_max_ambiguity_risk: float = 45.0
    min_liquidity_score: float = 1.0
    max_spread: float = 0.05
    min_combined_ask: float = 0.99
    max_combined_ask: float = 1.03
    min_orderbook_depth: float = 1.0
    watch_tier3: bool = True
    min_tradable_score: float = 15.0
    min_repeated_evidence_appearances: int = 2
    spread_buffer: float = 0.01
    min_confidence: float = 0.6


@dataclass
class EntryFilterResult:
    entry_decision: EntryDecision
    reason: str
    reject_reasons: list[str]
    watch_reasons: list[str]

    @property
    def allowed(self) -> bool:
        return self.entry_decision == EntryDecision.ELIGIBLE_SHADOW_ENTRY

    @property
    def is_watch_only(self) -> bool:
        return self.entry_decision == EntryDecision.WATCH_ONLY


class ShadowEntryFilter:
    """Decides whether an offline candidate can become a shadow trade."""

    def __init__(self, config: Optional[EntryFilterConfig] = None):
        self.config = config or EntryFilterConfig()

    def evaluate(self, candidate: CandidateSnapshot) -> EntryFilterResult:
        reject_reasons = self._reject_reasons(candidate)
        feedback_gate_reasons = self._feedback_gate_reasons(candidate)
        if feedback_gate_reasons:
            return EntryFilterResult(
                EntryDecision.WATCH_ONLY,
                feedback_gate_reasons[0],
                reject_reasons,
                feedback_gate_reasons,
            )
        relationship_gate_reasons = self._relationship_gate_reasons(candidate)
        if relationship_gate_reasons:
            if "likely_false_match" in relationship_gate_reasons:
                return EntryFilterResult(
                    EntryDecision.REJECTED,
                    "likely_false_match",
                    list(dict.fromkeys(reject_reasons + ["likely_false_match"])),
                    [],
                )
            return EntryFilterResult(
                EntryDecision.WATCH_ONLY,
                relationship_gate_reasons[0],
                reject_reasons,
                relationship_gate_reasons,
            )

        fatal_reasons = {
            "avoid_candidate",
            "stale_data",
            "missing_combined_ask",
            "risk_hard_reject",
            "llm_only_signal",
            "likely_false_match",
        }
        fatal_high_ambiguity = (
            "high_ambiguity" in reject_reasons
            and candidate.ambiguity_risk > self.config.watch_max_ambiguity_risk
        )
        if fatal_high_ambiguity or any(reason in fatal_reasons for reason in reject_reasons):
            return EntryFilterResult(
                EntryDecision.REJECTED,
                reject_reasons[0] if reject_reasons else "unknown",
                reject_reasons or ["unknown"],
                [],
            )

        tier = candidate.near_miss_tier.lower()
        alpha_ok = candidate.alpha_score >= self.config.min_alpha_score
        combined_ask_ok = self.config.min_combined_ask <= candidate.combined_ask <= self.config.max_combined_ask
        market_quality_ok = self._quality_gates_passed(candidate, reject_reasons, combined_ask_ok)
        expected_edge_ok = self._expected_edge_ok(candidate)
        strong_near_miss = tier in NEAR_MISS_TIERS_ALLOWED

        if strong_near_miss and market_quality_ok and expected_edge_ok:
            return EntryFilterResult(
                EntryDecision.ELIGIBLE_SHADOW_ENTRY,
                f"near_miss_{tier}",
                [],
                [],
            )

        if self._is_tradable_candidate(candidate) and market_quality_ok:
            tradable_evidence = self._tradable_evidence_reasons(candidate, combined_ask_ok, expected_edge_ok)
            if tradable_evidence:
                return EntryFilterResult(
                    EntryDecision.ELIGIBLE_SHADOW_ENTRY,
                    "tradable_candidate_evidence_passed",
                    [],
                    ["tradable_candidate_quality_passed"] + tradable_evidence,
                )

        if (
            alpha_ok
            and combined_ask_ok
            and market_quality_ok
            and expected_edge_ok
            and candidate.source != "alpha_score_only"
            and "near_miss_tier_not_eligible" not in reject_reasons
            and "alpha_score_only_not_allowed" not in reject_reasons
        ):
            return EntryFilterResult(
                EntryDecision.ELIGIBLE_SHADOW_ENTRY,
                "alpha_supported_by_market_quality",
                [],
                [],
            )

        watch_reasons = self._watch_reasons(candidate, reject_reasons)
        if watch_reasons:
            return EntryFilterResult(
                EntryDecision.WATCH_ONLY,
                watch_reasons[0],
                reject_reasons,
                watch_reasons,
            )

        if reject_reasons:
            return EntryFilterResult(
                EntryDecision.REJECTED,
                reject_reasons[0],
                reject_reasons,
                [],
            )

        return EntryFilterResult(
            EntryDecision.REJECTED,
            "unknown",
            ["unknown"],
            [],
        )

    def _reject_reasons(self, candidate: CandidateSnapshot) -> list[str]:
        reasons: list[str] = []
        if candidate.is_avoid_candidate:
            reasons.append("avoid_candidate")
        if candidate.ambiguity_risk > self.config.max_ambiguity_risk:
            reasons.append("high_ambiguity")
        if candidate.liquidity_score < self.config.min_liquidity_score:
            reasons.append("low_liquidity")
        if candidate.orderbook_spread > self.config.max_spread:
            reasons.append("spread_too_wide")
        if candidate.is_stale:
            reasons.append("stale_data")
        if candidate.combined_ask <= 0:
            reasons.append("missing_combined_ask")
        if candidate.side_entry_ask() <= 0:
            reasons.append("missing_side_ask")
            reasons.append("invalid_entry_price_model")
        if (
            candidate.alpha_score <= 0
            and not candidate.near_miss_tier
            and not self._is_tradable_candidate(candidate)
        ):
            reasons.append("missing_alpha_score")
        if candidate.near_miss_tier and candidate.near_miss_tier.lower() not in NEAR_MISS_TIERS_ALLOWED:
            reasons.append("near_miss_tier_not_eligible")
        if "hard_reject" in candidate.risk_decision.lower():
            reasons.append("risk_hard_reject")
        if candidate.orderbook_depth < self.config.min_orderbook_depth:
            reasons.append("insufficient_orderbook_depth")
        if candidate.is_llm_only:
            reasons.append("llm_only_signal")
        support = self._supporting_reasons(candidate)
        if "likely_false_match" in support or candidate.edge_failure_reason == "likely_false_match":
            reasons.append("likely_false_match")
        if candidate.alpha_score >= self.config.min_alpha_score and candidate.source == "alpha_score_only":
            reasons.append("alpha_score_only_not_allowed")
        if (
            candidate.expected_edge > 0
            and candidate.expected_edge <= candidate.orderbook_spread + self.config.spread_buffer
        ):
            reasons.append("expected_edge_too_low")
        if candidate.confidence and candidate.confidence < self.config.min_confidence:
            reasons.append("confidence_too_low")
        return reasons

    def _feedback_gate_reasons(self, candidate: CandidateSnapshot) -> list[str]:
        if candidate.edge_type not in PROBABILITY_EDGE_TYPES:
            return []
        status = (candidate.feedback_gate_status or "").strip().lower()
        reason_text = (candidate.feedback_gate_reason or "").strip().lower()
        if candidate.gate_passed is True and status in {"", "enabled"}:
            return []
        if not status and candidate.gate_passed is not False:
            return []

        reasons: list[str] = ["feedback_gate_failed"]
        if status == "quarantined":
            reasons.insert(0, "edge_type_quarantined")
        elif status == "watch_only":
            reasons.insert(0, "edge_type_watch_only_by_feedback")
        if "expected_edge_negative_correlation" in reason_text:
            reasons.append("expected_edge_negative_correlation")
        if "confidence_not_predictive" in reason_text:
            reasons.append("confidence_not_predictive")
        if "insufficient_feedback_data" in reason_text:
            reasons.append("insufficient_feedback_data")
        return list(dict.fromkeys(reasons))

    def _relationship_gate_reasons(self, candidate: CandidateSnapshot) -> list[str]:
        if candidate.edge_type != "cross_market_consistency_v1":
            return []
        support = self._supporting_reasons(candidate)
        if "likely_false_match" in support or candidate.edge_failure_reason == "likely_false_match":
            return ["likely_false_match"]
        reasons: list[str] = []
        for reason in [
            "mutually_exclusive_watch",
            "ambiguous_relationship",
            "relationship_confidence_too_low",
            "convergence_not_observed",
            "price_gap_not_converging",
            "insufficient_convergence_observations",
        ]:
            if reason in support or candidate.edge_failure_reason == reason:
                reasons.append(reason)
        if candidate.relationship_status == "high_confidence_duplicate":
            if candidate.convergence_gate_passed is not True:
                if candidate.convergence_reason:
                    reasons.append(candidate.convergence_reason)
                elif candidate.convergence_status:
                    reasons.append(candidate.convergence_status)
                else:
                    reasons.append("convergence_not_observed")
        return reasons

    def _watch_reasons(self, candidate: CandidateSnapshot, reject_reasons: list[str]) -> list[str]:
        reasons: list[str] = []
        tier = candidate.near_miss_tier.lower()
        moderate_ambiguity = (
            self.config.max_ambiguity_risk < candidate.ambiguity_risk <= self.config.watch_max_ambiguity_risk
        )
        if self._is_tradable_candidate(candidate):
            reasons.extend(self._tradable_watch_reasons(candidate, reject_reasons))
        if (
            candidate.alpha_score >= self.config.min_watch_alpha_score
            and "avoid_candidate" not in reject_reasons
            and not candidate.is_llm_only
        ):
            if "low_liquidity" in reject_reasons or "insufficient_orderbook_depth" in reject_reasons:
                reasons.append("high_alpha_but_insufficient_liquidity")
            elif moderate_ambiguity:
                reasons.append("high_alpha_but_moderate_ambiguity")
            elif "alpha_score_only_not_allowed" in reject_reasons:
                reasons.append("alpha_score_only_watch")
            elif "near_miss_tier_not_eligible" in reject_reasons:
                reasons.append("high_alpha_but_near_miss_not_eligible")
            elif not candidate.observations:
                reasons.append("missing_forward_data_but_interesting")
        if self.config.watch_tier3 and tier in NEAR_MISS_TIERS_WATCH:
            reasons.append("tier3_near_miss_watch")
        return reasons

    def _quality_gates_passed(
        self,
        candidate: CandidateSnapshot,
        reject_reasons: list[str],
        combined_ask_ok: bool,
    ) -> bool:
        quality_failures = {
            "avoid_candidate",
            "high_ambiguity",
            "low_liquidity",
            "spread_too_wide",
            "stale_data",
            "missing_combined_ask",
            "missing_side_ask",
            "invalid_entry_price_model",
            "risk_hard_reject",
            "insufficient_orderbook_depth",
            "llm_only_signal",
            "confidence_too_low",
            "likely_false_match",
        }
        return (
            not any(reason in quality_failures for reason in reject_reasons)
            and candidate.liquidity_score >= self.config.min_liquidity_score
            and candidate.orderbook_depth >= self.config.min_orderbook_depth
        )

    @staticmethod
    def _is_tradable_candidate(candidate: CandidateSnapshot) -> bool:
        return candidate.source == "tradable_candidate" or bool(candidate.tradable_source)

    @staticmethod
    def _supporting_reasons(candidate: CandidateSnapshot) -> set[str]:
        return {reason.strip() for reason in candidate.tradable_reasons if reason.strip()}

    def _expected_edge_ok(self, candidate: CandidateSnapshot) -> bool:
        numerical_pass = (
            candidate.expected_edge > 0
            and candidate.expected_edge > candidate.orderbook_spread + self.config.spread_buffer
        )
        if candidate.edge_pass is not None:
            return bool(candidate.edge_pass) and numerical_pass
        return numerical_pass

    def _tradable_evidence_reasons(
        self,
        candidate: CandidateSnapshot,
        combined_ask_ok: bool,
        expected_edge_ok: bool,
    ) -> list[str]:
        support = self._supporting_reasons(candidate)
        reasons: list[str] = []
        tier = candidate.near_miss_tier.lower()
        control_group_only = candidate.tradable_source == "control_group" and tier not in NEAR_MISS_TIERS_ALLOWED
        if control_group_only:
            return reasons
        has_support = bool(support & TRADABLE_SUPPORT_REASONS)
        score_with_support = (
            candidate.tradable_score >= self.config.min_tradable_score
            and has_support
            and expected_edge_ok
        )
        repeated_evidence = (
            candidate.evidence_level in {"strong", "moderate"}
            and candidate.orderbook_depth >= self.config.min_repeated_evidence_appearances
            and candidate.liquidity_score >= self.config.min_repeated_evidence_appearances
            and has_support
            and expected_edge_ok
        )
        if tier in NEAR_MISS_TIERS_ALLOWED and expected_edge_ok:
            reasons.append("near_miss_strong_enough")
        if expected_edge_ok and has_support:
            reasons.append("expected_edge_with_supporting_tradable_reasons")
        if repeated_evidence:
            reasons.append("repeated_watchlist_control_group_evidence")
        if score_with_support:
            reasons.append("tradable_score_with_supporting_evidence")
        return reasons

    def _tradable_watch_reasons(self, candidate: CandidateSnapshot, reject_reasons: list[str]) -> list[str]:
        reasons: list[str] = []
        support = self._supporting_reasons(candidate)
        quality_failures = {
            "avoid_candidate",
            "high_ambiguity",
            "low_liquidity",
            "spread_too_wide",
            "stale_data",
            "missing_combined_ask",
            "missing_side_ask",
            "invalid_entry_price_model",
            "risk_hard_reject",
            "insufficient_orderbook_depth",
            "llm_only_signal",
        }
        if candidate.alpha_score <= 0:
            reasons.append("missing_alpha_score_but_not_required")
        if "avoid_candidate" in reject_reasons:
            return reasons
        if not any(reason in quality_failures for reason in reject_reasons):
            reasons.append("tradable_candidate_quality_passed")
        if candidate.tradable_source == "control_group" and candidate.near_miss_tier.lower() not in NEAR_MISS_TIERS_ALLOWED:
            reasons.append("control_group_only_watch")
        relationship_reasons = {
            "relationship_confidence_too_low",
            "ambiguous_relationship",
            "likely_false_match",
            "mutually_exclusive_watch",
            "high_confidence_duplicate",
            "convergence_not_observed",
            "price_gap_not_converging",
            "insufficient_convergence_observations",
            "convergence_gate_passed",
        }
        reasons.extend(reason for reason in relationship_reasons if reason in support)
        if candidate.entry_decision_hint == EntryDecision.WATCH_ONLY.value:
            reasons.append("tradable_candidate_watch_only")
        if candidate.expected_edge <= 0:
            if candidate.edge_failure_reason:
                reasons.append(candidate.edge_failure_reason)
            elif candidate.expected_edge_status:
                reasons.append(candidate.expected_edge_status)
            else:
                reasons.append("missing_expected_edge")
        elif candidate.expected_edge <= candidate.orderbook_spread + self.config.spread_buffer:
            reasons.append(candidate.edge_failure_reason or "edge_too_low")
        elif candidate.edge_pass is False:
            reasons.append(candidate.edge_failure_reason or candidate.expected_edge_status or "edge_too_low")
        if candidate.tradable_score < self.config.min_tradable_score:
            reasons.append("tradable_score_too_low")
        if candidate.near_miss_tier and candidate.near_miss_tier.lower() not in NEAR_MISS_TIERS_ALLOWED:
            reasons.append("near_miss_not_strong_enough")
        if candidate.tradable_score >= self.config.min_tradable_score and not support:
            reasons.append("tradable_score_only_not_allowed")
        if not (support & TRADABLE_SUPPORT_REASONS):
            reasons.append("insufficient_tradable_evidence")
        return reasons


def filter_shadow_entries(
    candidates: list[CandidateSnapshot],
    config: Optional[EntryFilterConfig] = None,
) -> list[tuple[CandidateSnapshot, EntryFilterResult]]:
    entry_filter = ShadowEntryFilter(config)
    accepted: list[tuple[CandidateSnapshot, EntryFilterResult]] = []
    for candidate in candidates:
        result = entry_filter.evaluate(candidate)
        if result.allowed:
            accepted.append((candidate, result))
    return accepted
