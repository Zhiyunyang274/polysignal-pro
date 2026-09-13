"""
Alpha repeated-observation domain (Phase 6.5B).

Verbatim extraction from scripts/run_paper.py (Iteration 007). The mixin holds
the runner methods unchanged; PaperTradingRunner inherits them.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from polysignal.models.market import Market
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.risk import RiskAction, RiskContext, RiskDecision
from polysignal.models.signal import Signal
from polysignal.utils.time import utc_now


class AlphaRepeatMixin:
    """Runner methods for alpha repeated-observation runs and reports."""

    if TYPE_CHECKING:
        from polysignal.runner.run_state import RunConfig, RunStatistics
        # Runner surface required by this mixin. Transitional: annotated
        # as Any until RunConfig/RunStatistics move into polysignal/runner.
        _alpha_ids: Any
        _alpha_observation_counts: Any
        _log_event: Any
        _ws_connected: Any
        config: Any
        db: Any
        paper_trader: Any
        risk_governor: Any
        run_config: RunConfig
        run_dir: Any
        stats: RunStatistics
        watchlist_loader: Any
        watchlist_stats: Any

    def _generate_alpha_repeat_reports(self) -> None:
        """
        Generate alpha repeat observation output files.

        IMPORTANT: This is for RESEARCH only.
        """
        if not self.run_dir:
            return

        if self.run_config.alpha_priority_ratio <= 0:
            return

        alpha_candidates_loaded = (
            self.watchlist_stats.alpha_candidates_loaded
            if self.watchlist_stats
            else len(self._alpha_ids)
        )

        if not self._alpha_observation_counts and alpha_candidates_loaded == 0:
            self._log_event("alpha_repeat_report_skip", "alpha_repeat",
                            "No alpha observations to report")
            return

        alpha_ids = set(self._alpha_ids)
        if self.watchlist_loader:
            alpha_ids.update(self.watchlist_loader.alpha_candidates.keys())
        alpha_ids.update(self._alpha_observation_counts.keys())

        alpha_counts = {
            market_id: self._alpha_observation_counts.get(market_id, 0)
            for market_id in sorted(alpha_ids)
        }

        # Count alpha observation distribution
        obs_distribution: dict[int, int] = {}
        for _market_id, count in alpha_counts.items():
            obs_distribution[count] = obs_distribution.get(count, 0) + 1

        # Count alphas at or above target
        at_target = sum(1 for c in alpha_counts.values()
                        if c >= self.run_config.alpha_repeat_target)
        with_1 = sum(1 for c in alpha_counts.values() if c == 1)
        with_2 = sum(1 for c in alpha_counts.values() if c == 2)
        with_3_or_more = sum(1 for c in alpha_counts.values() if c >= 3)
        with_5_or_more = sum(1 for c in alpha_counts.values() if c >= 5)
        alpha_candidates_scanned = (
            self.watchlist_stats.alpha_markets_scanned
            if self.watchlist_stats
            else sum(alpha_counts.values())
        )

        # Update stats
        if self.stats:
            self.stats.alpha_priority_ratio = self.run_config.alpha_priority_ratio
            self.stats.alpha_repeat_target = self.run_config.alpha_repeat_target
            self.stats.alpha_observations_total = sum(alpha_counts.values())
            self.stats.alpha_markets_at_target = at_target

        # Write alpha_repeat_observation_summary.json
        summary_path = self.run_dir / "alpha_repeat_observation_summary.json"
        summary = {
            "run_id": self.stats.run_id if self.stats else "unknown",
            "phase": "6.5B",
            "alpha_candidates_loaded": alpha_candidates_loaded,
            "alpha_candidates_scanned": alpha_candidates_scanned,
            "alpha_candidates_with_1_observation": with_1,
            "alpha_candidates_with_2_observations": with_2,
            "alpha_candidates_with_3_or_more_observations": with_3_or_more,
            "alpha_candidates_with_5_or_more_observations": with_5_or_more,
            "alpha_priority_ratio": self.run_config.alpha_priority_ratio,
            "alpha_repeat_target": self.run_config.alpha_repeat_target,
            "alpha_markets_tracked": len(alpha_counts),
            "alpha_observations_total": sum(alpha_counts.values()),
            "alpha_markets_at_target": at_target,
            "observation_distribution": {
                str(k): v for k, v in sorted(obs_distribution.items())
            },
            "per_market_observations": {
                mid: count for mid, count in sorted(
                    alpha_counts.items(),
                    key=lambda x: x[1], reverse=True
                )
            },
            "safety_verification": {
                "live_trading_enabled": self.config.env.live_trading_enabled if self.config else False,
                "allow_auto_execution": self.config.env.allow_auto_execution if self.config else False,
                "paper_trading_enabled": self.config.env.paper_trading_enabled if self.config else True,
                "real_api_calls": False,
                "trading_actions": False,
                "alpha_score_triggers_trade": False,
                "alpha_score_changes_risk_governor_score": False,
                "alpha_score_adds_hard_reject_reason": False,
            },
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # Write alpha_repeat_observation_report.md
        report_path = self.run_dir / "alpha_repeat_observation_report.md"
        with open(report_path, "w") as f:
            f.write("# Alpha Repeated Observation Report\n\n")
            f.write("**Phase:** 6.5B\n")
            f.write(f"**Run ID:** {self.stats.run_id if self.stats else 'unknown'}\n\n")
            f.write("## Configuration\n\n")
            f.write(f"- **Alpha Priority Ratio:** {self.run_config.alpha_priority_ratio}\n")
            f.write(f"- **Alpha Repeat Target:** {self.run_config.alpha_repeat_target}\n\n")
            f.write("## Results\n\n")
            f.write(f"- **Alpha Candidates Loaded:** {alpha_candidates_loaded}\n")
            f.write(f"- **Alpha Candidates Scanned:** {alpha_candidates_scanned}\n")
            f.write(f"- **Alpha Markets Tracked:** {len(alpha_counts)}\n")
            f.write(f"- **Total Alpha Observations:** {sum(alpha_counts.values())}\n")
            f.write(f"- **Markets at Target (>= {self.run_config.alpha_repeat_target}):** {at_target}\n\n")

            f.write("## Observation Distribution\n\n")
            f.write("| Observations | Markets |\n")
            f.write("|---|---|\n")
            for obs_count in sorted(obs_distribution.keys()):
                market_count = obs_distribution[obs_count]
                f.write(f"| {obs_count} | {market_count} |\n")

            f.write("\n## Per-Market Observations\n\n")
            f.write("| Market ID | Observations |\n")
            f.write("|---|---|\n")
            for mid, count in sorted(alpha_counts.items(),
                                     key=lambda x: x[1], reverse=True):
                f.write(f"| {mid} | {count} |\n")

            f.write("\n## Safety Verification\n\n")
            f.write("- alpha_score does NOT trigger trades\n")
            f.write("- alpha_score does NOT affect Risk Governor\n")
            f.write("- alpha candidates are monitoring priority ONLY\n")
            f.write("- live_trading_enabled remains false\n")

        print("\n=== Alpha Repeat Observation Reports Generated ===")
        print(f"  {summary_path}")
        print(f"  {report_path}")

    async def _process_signal(self, signal: Signal, market: Market | None, orderbook: OrderBookSnapshot | None) -> None:
        """Process signal through Risk Governor"""
        # Construct RiskContext with current system state
        context = RiskContext(
            live_trading_enabled=self.config.env.live_trading_enabled,
            allow_auto_execution=self.config.env.allow_auto_execution,
            api_healthy=True,
            websocket_healthy=self._ws_connected,
            price_stale=orderbook.is_stale if orderbook else True,
            market_tradable=market.is_tradable() if market else False,
            market_ambiguous=market.is_ambiguous if market else False,
            market_forbidden=not market.is_auto_allowed() if market else True,
        )

        # Run through Risk Governor (synchronous call - no await)
        decision = self.risk_governor.evaluate(
            signal=signal,
            context=context,
            orderbook=orderbook,
            market=market,
        )

        # Track decision using enum comparison (not string comparison)
        if decision.action == RiskAction.IGNORE:
            self.stats.signals_ignored += 1
        elif decision.action == RiskAction.LOG_ONLY:
            self.stats.signals_log_only += 1
        elif decision.action == RiskAction.ALERT:
            self.stats.signals_alert += 1
        elif decision.action == RiskAction.PAPER_TRADE:
            self.stats.signals_paper_trade += 1

            # Execute paper trade
            await self._execute_paper_trade(signal, decision, orderbook)

        elif decision.action == RiskAction.HARD_REJECT:
            self.stats.signals_hard_reject += 1

            # Track reject reasons
            for reason in decision.hard_reject_reasons:
                self.stats.hard_reject_reasons[reason] = self.stats.hard_reject_reasons.get(reason, 0) + 1

        # Save signal and decision to database
        await self.db.save_signal(signal)
        await self.db.save_risk_decision(decision)

    async def _execute_paper_trade(self, signal: Signal, decision: RiskDecision, orderbook: OrderBookSnapshot | None) -> None:
        """Execute a paper trade"""
        try:
            if not orderbook:
                self._log_event("paper_trade_error", "error", f"No orderbook for {signal.market_id}")
                return

            # Execute paper trade
            order, position, message = self.paper_trader.execute(
                signal=signal,
                risk_decision=decision,
                orderbook=orderbook,
            )

            if order:
                self.stats.paper_trades_created += 1
                self._log_event("paper_trade", "trade", f"Paper trade created: {order.order_id}", {
                    "order_id": order.order_id,
                    "market_id": signal.market_id,
                    "side": signal.side.value,
                    "price": signal.price,
                    "message": message,
                })

                # Save order to database
                await self.db.save_paper_order(order)

        except Exception as e:
            self._log_event("paper_trade_error", "error", f"Paper trade error: {e}")
            self.stats.errors.append({
                "time": utc_now().isoformat(),
                "type": "paper_trade_error",
                "message": str(e),
            })

