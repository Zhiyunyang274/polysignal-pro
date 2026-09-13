"""
Exposure Guard - Hard exposure limits checked before any execution.

IMPORTANT:
- Wired into Risk Governor's hard-rejection chain (Iteration 006):
  a signal that would be evaluated while market- or strategy-level exposure
  already sits at/above its configured cap is hard rejected.
- These are PRE-TRADE checks on state carried in RiskContext, so every runner
  must feed real exposure values (see polysignal/execution/account_state.py).
- Semantics: the caps bound EXISTING exposure before adding a new entry. The
  requested order size is not known to the Governor; position sizing is
  enforced by PaperTrader/SimBroker and the AccountState cash guard.
- max_position_pct is likewise a sizing parameter consumed by the execution
  layer, not a pre-trade hard reject.
"""

from polysignal.models.risk import RiskContext

MARKET_EXPOSURE_LIMIT = "market_exposure_limit"
STRATEGY_EXPOSURE_LIMIT = "strategy_exposure_limit"


class ExposureGuard:
    """Hard per-market and per-strategy exposure limits."""

    def __init__(
        self,
        max_account_capital_usd: float = 100.0,
        max_market_exposure_pct: float = 0.03,
        max_strategy_exposure_pct: float = 0.08,
    ):
        if max_account_capital_usd <= 0:
            raise ValueError("max_account_capital_usd must be positive")
        for name, pct in (
            ("max_market_exposure_pct", max_market_exposure_pct),
            ("max_strategy_exposure_pct", max_strategy_exposure_pct),
        ):
            if not 0 < pct <= 1:
                raise ValueError(f"{name} must be in (0, 1]")

        self.max_account_capital_usd = max_account_capital_usd
        self.max_market_exposure_pct = max_market_exposure_pct
        self.max_strategy_exposure_pct = max_strategy_exposure_pct

    def check_exposure(self, context: RiskContext) -> list[str]:
        """Return hard-reject reasons for exposure caps already reached."""
        reasons: list[str] = []

        market_limit = self.max_account_capital_usd * self.max_market_exposure_pct
        if context.current_market_exposure_usd >= market_limit:
            reasons.append(MARKET_EXPOSURE_LIMIT)

        strategy_limit = self.max_account_capital_usd * self.max_strategy_exposure_pct
        if context.current_strategy_exposure_usd >= strategy_limit:
            reasons.append(STRATEGY_EXPOSURE_LIMIT)

        return reasons
