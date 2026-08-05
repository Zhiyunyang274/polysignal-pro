"""

Risk Governor - Central risk control and decision making

IMPORTANT: Risk Governor is the ONLY module that can approve execution.
All signals MUST pass through Risk Governor.

This module:
- Checks hard rejection conditions
- Calculates trade_score
- Decides final action
- Controls paper trading and live trading permissions
"""

from datetime import datetime
from typing import Any, Optional

from polysignal.models.signal import Signal, ComponentScores
from polysignal.models.risk import RiskAction, RiskDecision, RiskContext
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.market import Market


class RiskGovernor:
    """
    Risk Governor - Central risk control.

    This is the ONLY module that can approve execution.
    All signals must pass through Risk Governor.

    Decision Flow:
    1. Check hard rejection conditions
    2. If hard rejected -> RiskAction.HARD_REJECT
    3. Calculate trade_score from component scores
    4. Apply penalties
    5. Decide action based on thresholds
    """

    # Decision thresholds
    THRESHOLD_IGNORE = 70
    THRESHOLD_LOG_ONLY = 80
    THRESHOLD_ALERT = 90
    THRESHOLD_MANUAL_REVIEW = 95

    def __init__(
        self,
        live_trading_enabled: bool = False,
        allow_auto_execution: bool = False,
        paper_trading_enabled: bool = True,
        max_account_capital_usd: float = 100.0,
        max_position_pct: float = 0.01,
        max_market_exposure_pct: float = 0.03,
        max_strategy_exposure_pct: float = 0.08,
        daily_max_loss_pct: float = 0.03,
        weekly_max_loss_pct: float = 0.08,
        max_consecutive_losses: int = 3,
        min_total_volume_usd: float = 100000,
        min_depth_usd: float = 20,
        max_spread_pct: float = 0.05,
        scoring_weights: Optional[dict[str, float]] = None,
    ):
        """
        Initialize Risk Governor.

        Args:
            live_trading_enabled: Enable live trading (default False)
            allow_auto_execution: Allow auto execution (default False)
            paper_trading_enabled: Enable paper trading (default True)
            max_account_capital_usd: Maximum account capital
            max_position_pct: Maximum position as % of capital
            max_market_exposure_pct: Maximum exposure per market
            max_strategy_exposure_pct: Maximum exposure per strategy
            daily_max_loss_pct: Daily max loss as % of capital
            weekly_max_loss_pct: Weekly max loss as % of capital
            max_consecutive_losses: Maximum consecutive losses
            min_total_volume_usd: Minimum market volume
            min_depth_usd: Minimum orderbook depth
            max_spread_pct: Maximum spread percentage
            scoring_weights: Weights for component scores
        """
        self.live_trading_enabled = live_trading_enabled
        self.allow_auto_execution = allow_auto_execution
        self.paper_trading_enabled = paper_trading_enabled

        self.max_account_capital_usd = max_account_capital_usd
        self.max_position_pct = max_position_pct
        self.max_market_exposure_pct = max_market_exposure_pct
        self.max_strategy_exposure_pct = max_strategy_exposure_pct

        self.daily_max_loss_pct = daily_max_loss_pct
        self.weekly_max_loss_pct = weekly_max_loss_pct
        self.max_consecutive_losses = max_consecutive_losses

        self.min_total_volume_usd = min_total_volume_usd
        self.min_depth_usd = min_depth_usd
        self.max_spread_pct = max_spread_pct

        self.scoring_weights = scoring_weights or {
            "microstructure": 0.30,
            "liquidity": 0.20,
            "event": 0.20,
            "wallet": 0.15,
            "lifecycle": 0.15,
        }

    def evaluate(
        self,
        signal: Signal,
        context: RiskContext,
        orderbook: Optional[OrderBookSnapshot] = None,
        market: Optional[Market] = None,
    ) -> RiskDecision:
        """
        Evaluate a signal and make a decision.

        Args:
            signal: Signal to evaluate
            context: Risk context with system state
            orderbook: Optional orderbook snapshot
            market: Optional market info

        Returns:
            RiskDecision with action and details
        """
        # Step 1: Check hard rejection conditions
        hard_reject_reasons = self._check_hard_rejections(signal, context, orderbook, market)

        if hard_reject_reasons:
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.HARD_REJECT,
                trade_score=0.0,
                hard_reject_reasons=hard_reject_reasons,
                explanation=f"Hard rejected: {', '.join(hard_reject_reasons)}",
                risk_flags=signal.risk_flags + hard_reject_reasons,
            )

        # Step 2: Calculate trade score
        trade_score = self._calculate_trade_score(signal.component_scores)

        # Step 3: Apply penalties
        penalties = self._calculate_penalties(signal, context, orderbook)
        trade_score -= sum(penalties.values())
        trade_score = max(0, min(100, trade_score))

        # Step 4: Decide action based on score
        action = self._decide_action(trade_score, signal, context)

        # Step 5: Determine allowed actions
        allowed_actions = self._get_allowed_actions(action, context)

        # Create decision
        decision = RiskDecision(
            signal_id=signal.signal_id,
            action=action,
            trade_score=trade_score,
            hard_reject_reasons=[],
            component_scores={
                "microstructure": signal.component_scores.microstructure_score,
                "liquidity": signal.component_scores.liquidity_score,
                "event": signal.component_scores.event_score,
                "wallet": signal.component_scores.wallet_score,
                "lifecycle": signal.component_scores.lifecycle_score,
            },
            ambiguity_penalty=penalties.get("ambiguity_penalty", 0.0),
            slippage_penalty=penalties.get("slippage_penalty", 0.0),
            concentration_penalty=penalties.get("concentration_penalty", 0.0),
            copy_risk_penalty=penalties.get("copy_risk_penalty", 0.0),
            chase_risk_penalty=penalties.get("chase_risk_penalty", 0.0),
            timing_risk_penalty=penalties.get("timing_risk_penalty", 0.0),
            event_ambiguity_penalty=penalties.get("event_ambiguity_penalty", 0.0),
            event_weak_evidence_penalty=penalties.get("event_weak_evidence_penalty", 0.0),
            llm_failure_penalty=penalties.get("llm_failure_penalty", 0.0),
            allowed_actions=allowed_actions,
            explanation=self._generate_explanation(action, trade_score, signal),
            risk_flags=signal.risk_flags,
        )

        return decision

    def _check_hard_rejections(
        self,
        signal: Signal,
        context: RiskContext,
        orderbook: Optional[OrderBookSnapshot],
        market: Optional[Market],
    ) -> list[str]:
        """Check hard rejection conditions"""
        reasons = []

        # System-level checks
        if not context.live_trading_enabled and signal.side != "both":
            # Paper trading only - not a hard reject, just limit actions
            pass

        if not context.api_healthy:
            reasons.append("api_unhealthy")

        if not context.websocket_healthy:
            reasons.append("websocket_unhealthy")

        if context.price_stale:
            reasons.append("price_stale")

        # Market-level checks (DIRECT checks, not relying on signal.risk_flags)
        if market is not None:
            # Market status check - MUST be OPEN
            from polysignal.models.market import MarketStatus
            if market.status != MarketStatus.OPEN:
                reasons.append("market_not_open")

            # Ambiguity check - DIRECT
            if market.is_ambiguous:
                reasons.append("market_ambiguous")

            # Forbidden category check - DIRECT (dual safeguard)
            if not market.is_auto_allowed():
                reasons.append("forbidden_category")

            if market.total_volume_usd < self.min_total_volume_usd:
                reasons.append("volume_too_low")

        # Orderbook checks
        if orderbook is not None:
            orderbook.calculate_metrics()

            if orderbook.is_stale:
                reasons.append("orderbook_stale")

            if orderbook.spread_pct_yes is not None:
                if orderbook.spread_pct_yes > self.max_spread_pct:
                    reasons.append("spread_too_wide")

            # Check depth based on signal side
            # For YES/NO combined mispricing (BOTH), both ask sides must have sufficient depth
            # For YES signals, YES ask side must have sufficient depth
            # For NO signals, NO ask side must have sufficient depth
            from polysignal.models.signal import SignalSide
            if signal.side == SignalSide.BOTH:
                # Both YES and NO ask sides must have sufficient depth
                yes_ask_depth = orderbook.yes_asks.total_depth_usd
                no_ask_depth = orderbook.no_asks.total_depth_usd
                if yes_ask_depth < self.min_depth_usd or no_ask_depth < self.min_depth_usd:
                    reasons.append("depth_too_thin")
            elif signal.side == SignalSide.YES:
                # YES ask side must have sufficient depth
                yes_ask_depth = orderbook.yes_asks.total_depth_usd
                if yes_ask_depth < self.min_depth_usd:
                    reasons.append("depth_too_thin")
            elif signal.side == SignalSide.NO:
                # NO ask side must have sufficient depth
                no_ask_depth = orderbook.no_asks.total_depth_usd
                if no_ask_depth < self.min_depth_usd:
                    reasons.append("depth_too_thin")

        # Account-level checks
        daily_loss_limit = self.max_account_capital_usd * self.daily_max_loss_pct
        if context.daily_pnl_usd < -daily_loss_limit:
            reasons.append("daily_loss_limit_breached")

        weekly_loss_limit = self.max_account_capital_usd * self.weekly_max_loss_pct
        if context.weekly_pnl_usd < -weekly_loss_limit:
            reasons.append("weekly_loss_limit_breached")

        if context.consecutive_losses >= self.max_consecutive_losses:
            reasons.append("consecutive_loss_limit_breached")

        # Signal-level checks (from lifecycle engine or other engines)
        # These are SUPPLEMENTARY - the direct checks above are the primary safeguards
        # But we also check signal.risk_flags for additional context
        if "market_ambiguous" in signal.risk_flags and "market_ambiguous" not in reasons:
            reasons.append("market_ambiguous")

        if "market_not_open" in signal.risk_flags and "market_not_open" not in reasons:
            reasons.append("market_not_open")

        if "forbidden_category" in signal.risk_flags and "forbidden_category" not in reasons:
            reasons.append("forbidden_category")

        # Wallet signal only check - DUAL SAFEGUARD
        # 1. Check signal.risk_flags (from wallet engine)
        if "wallet_signal_only" in signal.risk_flags:
            reasons.append("wallet_signal_only_reason")

        # 2. DIRECT CHECK based on component_scores (primary safeguard)
        # If wallet_score is high but other scores are weak, this is wallet_signal_only
        if self._is_wallet_signal_only(signal.component_scores):
            if "wallet_signal_only_reason" not in reasons:
                reasons.append("wallet_signal_only_reason")

        # Event signal only check - DUAL SAFEGUARD
        # 1. Check signal.risk_flags (from event engine)
        if "event_signal_only" in signal.risk_flags:
            reasons.append("event_signal_only_reason")

        # 2. DIRECT CHECK based on component_scores (primary safeguard)
        # If event_score is high but other scores are weak, this is event_signal_only
        if self._is_event_signal_only(signal.component_scores):
            if "event_signal_only_reason" not in reasons:
                reasons.append("event_signal_only_reason")

        # Event forbidden category check
        # If event engine detects forbidden category, hard reject
        if "event_forbidden_category" in signal.risk_flags:
            if "forbidden_category" not in reasons:
                reasons.append("forbidden_category")

        return reasons

    def _is_wallet_signal_only(self, scores: ComponentScores) -> bool:
        """
        Check if this is a wallet-signal-only scenario.

        A wallet-signal-only scenario is when:
        - wallet_score >= 80 (strong wallet signal)
        - microstructure_score < 60 (weak market signal)
        - event_score < 60 (weak event signal)
        - liquidity_score < 60 (weak liquidity signal)

        This should trigger hard reject.
        """
        return (
            scores.wallet_score >= 80
            and scores.microstructure_score < 60
            and scores.event_score < 60
            and scores.liquidity_score < 60
        )

    def _is_event_signal_only(self, scores: ComponentScores) -> bool:
        """
        Check if this is an event-signal-only scenario.

        An event-signal-only scenario is when:
        - event_score >= 80 (strong event signal)
        - microstructure_score < 60 (weak market signal)
        - wallet_score < 60 (weak wallet signal)
        - liquidity_score < 60 (weak liquidity signal)

        This should trigger hard reject.

        IMPORTANT: Event signal cannot be the only reason to trade.
        """
        return (
            scores.event_score >= 80
            and scores.microstructure_score < 60
            and scores.wallet_score < 60
            and scores.liquidity_score < 60
        )

    def _calculate_trade_score(self, component_scores: ComponentScores) -> float:
        """
        Calculate trade_score from component scores.

        Formula:
        trade_score =
            0.30 * microstructure_score
            + 0.20 * liquidity_score
            + 0.20 * event_score
            + 0.15 * wallet_score
            + 0.15 * lifecycle_score
        """
        score = (
            self.scoring_weights.get("microstructure", 0.30) * component_scores.microstructure_score
            + self.scoring_weights.get("liquidity", 0.20) * component_scores.liquidity_score
            + self.scoring_weights.get("event", 0.20) * component_scores.event_score
            + self.scoring_weights.get("wallet", 0.15) * component_scores.wallet_score
            + self.scoring_weights.get("lifecycle", 0.15) * component_scores.lifecycle_score
        )
        return score

    def _calculate_penalties(
        self,
        signal: Signal,
        context: RiskContext,
        orderbook: Optional[OrderBookSnapshot],
    ) -> dict[str, float]:
        """Calculate penalty scores"""
        penalties = {}

        # Ambiguity penalty
        if "ambiguous_market" in signal.risk_flags:
            penalties["ambiguity_penalty"] = 10.0

        # Slippage penalty (based on spread)
        if orderbook is not None and orderbook.spread_pct_yes is not None:
            if orderbook.spread_pct_yes > 0.03:
                penalties["slippage_penalty"] = (orderbook.spread_pct_yes - 0.03) * 100

        # Concentration penalty (based on exposure)
        if context.current_market_exposure_usd > self.max_account_capital_usd * self.max_market_exposure_pct:
            penalties["concentration_penalty"] = 5.0

        # Copy risk penalty (from wallet engine)
        # copy_risk_high flag indicates high copy trading risk
        if "copy_risk_high" in signal.risk_flags:
            penalties["copy_risk_penalty"] = 15.0
        elif "copy_risk_medium" in signal.risk_flags:
            penalties["copy_risk_penalty"] = 8.0
        elif "copy_risk_low" in signal.risk_flags:
            penalties["copy_risk_penalty"] = 3.0

        # Chase risk penalty (追高风险)
        if "chase_risk_high" in signal.risk_flags:
            penalties["chase_risk_penalty"] = 10.0

        # Timing risk penalty
        if "timing_risk_high" in signal.risk_flags:
            penalties["timing_risk_penalty"] = 5.0

        # Event-related penalties
        # High ambiguity risk from event engine
        if "event_high_ambiguity" in signal.risk_flags:
            penalties["event_ambiguity_penalty"] = 10.0

        # Weak evidence from event engine
        if "event_weak_evidence" in signal.risk_flags:
            penalties["event_weak_evidence_penalty"] = 5.0

        # LLM failure penalties (not hard reject, but reduce score)
        if "llm_invalid_json" in signal.risk_flags:
            penalties["llm_failure_penalty"] = 5.0
        elif "llm_low_confidence" in signal.risk_flags:
            penalties["llm_failure_penalty"] = 3.0
        elif "llm_error" in signal.risk_flags:
            penalties["llm_failure_penalty"] = 5.0

        return penalties

    def _decide_action(
        self,
        trade_score: float,
        signal: Signal,
        context: RiskContext,
    ) -> RiskAction:
        """Decide action based on trade score"""
        if trade_score < self.THRESHOLD_IGNORE:
            return RiskAction.IGNORE
        elif trade_score < self.THRESHOLD_LOG_ONLY:
            return RiskAction.LOG_ONLY
        elif trade_score < self.THRESHOLD_ALERT:
            return RiskAction.ALERT
        elif trade_score < self.THRESHOLD_MANUAL_REVIEW:
            # Check if manual review is needed
            if "forbidden_auto_category" in signal.risk_flags:
                return RiskAction.MANUAL_REVIEW
            return RiskAction.PAPER_TRADE
        else:
            # High score
            if self.live_trading_enabled and self.allow_auto_execution:
                return RiskAction.LIVE_EXECUTE
            return RiskAction.PAPER_TRADE

    def _get_allowed_actions(
        self,
        action: RiskAction,
        context: RiskContext,
    ) -> list[RiskAction]:
        """Get list of allowed actions"""
        allowed = []

        if action == RiskAction.HARD_REJECT:
            return []

        if action in {RiskAction.LOG_ONLY, RiskAction.IGNORE}:
            return [action]

        # Alert is always allowed for non-hard-rejected
        allowed.append(RiskAction.ALERT)

        # Paper trading
        if self.paper_trading_enabled and action in {
            RiskAction.ALERT,
            RiskAction.PAPER_TRADE,
            RiskAction.MANUAL_REVIEW,
        }:
            allowed.append(RiskAction.PAPER_TRADE)

        # Manual review
        if action == RiskAction.MANUAL_REVIEW:
            allowed.append(RiskAction.MANUAL_REVIEW)

        # Live execution (only if explicitly enabled)
        if self.live_trading_enabled and action == RiskAction.LIVE_EXECUTE:
            allowed.append(RiskAction.LIVE_EXECUTE)

        return list(set(allowed))

    def _generate_explanation(
        self,
        action: RiskAction,
        trade_score: float,
        signal: Signal,
    ) -> str:
        """Generate human-readable explanation"""
        return (
            f"Risk Governor decision: {action.value} "
            f"| Score: {trade_score:.1f} "
            f"| Strategy: {signal.strategy_name} "
            f"| Market: {signal.market_title[:30]}..."
        )

    def allows_paper_trade(self, decision: RiskDecision) -> bool:
        """Check if paper trade is allowed"""
        return RiskAction.PAPER_TRADE in decision.allowed_actions

    def allows_live_execute(self, decision: RiskDecision) -> bool:
        """Check if live execution is allowed"""
        return RiskAction.LIVE_EXECUTE in decision.allowed_actions
