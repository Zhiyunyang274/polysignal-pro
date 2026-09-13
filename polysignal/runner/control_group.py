"""
Control-group sampling domain (Phase 6.5A).

Verbatim extraction from scripts/run_paper.py (Iteration 007). The mixin holds
the runner methods unchanged; PaperTradingRunner inherits them.
"""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING, Any

from polysignal.models.market import Market
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.utils.time import utc_now


class ControlGroupMixin:
    """Runner methods for control-group sampling and reports."""

    if TYPE_CHECKING:
        from polysignal.runner.run_state import RunConfig, RunStatistics
        # Runner surface required by this mixin. Transitional: annotated
        # as Any until RunConfig/RunStatistics move into polysignal/runner.
        _alpha_ids: Any
        _avoid_ids: Any
        _control_group_ids: Any
        _control_group_samples: Any
        _log_event: Any
        _perform_llm_sampling: Any
        _watchlist_ids: Any
        run_config: RunConfig
        run_dir: Any
        stats: RunStatistics

    def _select_control_group_candidates(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> list[tuple[Market, OrderBookSnapshot]]:
        """
        Select control group markets for non-avoid comparison.

        IMPORTANT: This is for RESEARCH only - NO TRADING.

        Selection criteria:
        - Market status is OPEN
        - Not in forbidden category
        - Not ambiguous
        - Has valid orderbook
        - NOT in avoid_candidates (if exclude_avoid_from_control_group)
        - NOT in alpha_candidates
        - NOT in persistent_watchlist
        - Sufficient volume

        Category diversity:
        - Try to cover multiple categories
        - At least 1 market per category if available
        """
        if self.run_config.control_group_sampling_ratio <= 0:
            return []

        # Determine max control group size
        max_cg = max(1, int(self.run_config.max_markets * self.run_config.control_group_sampling_ratio))

        candidates: list[tuple[Market, OrderBookSnapshot, str]] = []

        for market in markets:
            # Check market eligibility
            status_ok = market.status == "open" or (hasattr(market.status, 'value') and market.status.value == "open")
            if not status_ok:
                continue
            if market.is_ambiguous:
                continue

            # Check forbidden
            if not market.is_auto_allowed():
                continue

            # Check orderbook
            orderbook = orderbooks.get(market.market_id)
            if not orderbook:
                continue

            # Check exclusions
            if self.run_config.exclude_avoid_from_control_group and market.market_id in self._avoid_ids:
                continue
            if market.market_id in self._alpha_ids:
                continue
            if market.market_id in self._watchlist_ids:
                continue

            # Skip if already in control group (avoid duplicates across scans)
            if market.market_id in self._control_group_ids:
                continue

            # Get category
            category = getattr(market, 'category', None) or 'Other'
            candidates.append((market, orderbook, category))

        if not candidates:
            return []

        # Group by category for diversity
        by_category: dict[str, list[tuple[Market, OrderBookSnapshot, str]]] = {}
        for item in candidates:
            cat = item[2]
            by_category.setdefault(cat, []).append(item)

        # Select diverse candidates: 1 per category first, then fill remaining
        selected: list[tuple[Market, OrderBookSnapshot]] = []
        categories_used: list[str] = []

        # Round-robin: one from each category
        for cat in sorted(by_category.keys()):
            if len(selected) >= max_cg:
                break
            items = by_category[cat]
            selected.append((items[0][0], items[0][1]))
            categories_used.append(cat)

        # Fill remaining from any category
        for cat in sorted(by_category.keys()):
            for item in by_category[cat][1:]:
                if len(selected) >= max_cg:
                    break
                selected.append((item[0], item[1]))
                if cat not in categories_used:
                    categories_used.append(cat)

        return selected[:max_cg]

    async def _run_control_group_sampling(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> None:
        """
        Run control group sampling for Phase 6.5A.

        This is research/intelligence logging only - NO TRADING.
        Uses the same LLM provider as regular sampling, subject to rate limits.
        """
        candidates = self._select_control_group_candidates(markets, orderbooks)

        if not candidates:
            return

        self._log_event("control_group_sampling_start", "control_group",
                        f"Starting control group sampling for {len(candidates)} markets")

        for market, orderbook in candidates:
            # Check rate limit
            if self.stats.llm_calls_this_hour >= self.run_config.max_llm_calls_per_hour:
                self._log_event("control_group_rate_limit", "control_group",
                                "Rate limit reached, stopping control group sampling")
                break

            # Use the same _perform_llm_sampling method (same rate limit, same provider)
            result = await self._perform_llm_sampling(market, orderbook)

            # Track control group
            self._control_group_ids.add(market.market_id)
            category = getattr(market, 'category', None) or 'Other'

            # Store sample
            sample = {
                "market_id": market.market_id,
                "question": market.title[:200] if market.title else "",
                "category": category,
                "combined_ask": orderbook.combined_ask,
                "event_score": result.get("event_score"),
                "ambiguity_risk": result.get("ambiguity_risk"),
                "suggested_mode": result.get("suggested_mode"),
                "confidence": result.get("confidence"),
                "success": result.get("success", False),
                "timestamp": utc_now().isoformat(),
            }
            self._control_group_samples.append(sample)

            # Update stats
            self.stats.control_group_samples += 1
            self.stats.control_group_unique_markets = len(self._control_group_ids)
            self.stats.control_group_llm_calls += 1
            self.stats.control_group_categories[category] = \
                self.stats.control_group_categories.get(category, 0) + 1

            # Log event
            self._log_event(
                "control_group_assessment",
                "control_group",
                f"Control group assessment for {market.market_id}: {'success' if result.get('success') else 'failed'}",
                {
                    "market_id": market.market_id,
                    "question": market.title[:200] if market.title else "",
                    "category": category,
                    "combined_ask": orderbook.combined_ask,
                    "event_score": result.get("event_score"),
                    "ambiguity_risk": result.get("ambiguity_risk"),
                    "suggested_mode": result.get("suggested_mode"),
                    "confidence": result.get("confidence"),
                    "success": result.get("success", False),
                    "latency_seconds": result.get("latency_seconds"),
                    "group": "control",
                }
            )

        self._log_event("control_group_sampling_complete", "control_group",
                        f"Control group sampling complete: {len(self._control_group_samples)} samples, "
                        f"{len(self._control_group_ids)} unique markets")

    def _generate_control_group_reports(self) -> None:
        """
        Generate control group output files.

        IMPORTANT: This is for RESEARCH only.
        """
        if not self.run_dir:
            return

        if not self._control_group_samples:
            self._log_event("control_group_report_skip", "control_group", "No control group samples to report")
            return

        # Write control_group_samples.csv
        csv_path = self.run_dir / "control_group_samples.csv"
        fields = [
            "market_id", "question", "category", "combined_ask",
            "event_score", "ambiguity_risk", "suggested_mode",
            "confidence", "success", "timestamp",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for sample in self._control_group_samples:
                writer.writerow({k: sample.get(k) for k in fields})

        # Write validation_loop_summary.json
        summary_path = self.run_dir / "validation_loop_summary.json"
        summary = {
            "run_id": self.stats.run_id if self.stats else "unknown",
            "phase": "6.5A",
            "control_group_samples": len(self._control_group_samples),
            "unique_control_group_markets": len(self._control_group_ids),
            "control_group_categories": dict(self.stats.control_group_categories) if self.stats else {},
            "llm_calls_used_for_control_group": self.stats.control_group_llm_calls if self.stats else 0,
            "safety_verification": {
                "live_trading_enabled": False,
                "allow_auto_execution": False,
                "real_api_calls": False,
                "trading_actions": False,
            },
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        print("\n=== Control Group Reports Generated ===")
        print(f"  {csv_path}")
        print(f"  {summary_path}")

