"""A/B strategy comparison — baseline vs candidate through the risk chain.

READ-ONLY research tool (user phase 4 requirement). Both variants run through
the SAME production risk chain (MockDataProvider(regime) → MicrostructureEngine
→ RiskGovernor → SimBroker → AccountState) with the SAME seed and data
windows; the only difference is the variant's strategy parameters. Because the
stress harness is deterministic, any performance difference is attributable to
the parameter change, not noise or data leakage.

Verdict rule (conservative, per house rules — "no obvious advantage, no merge"):
a candidate is KEEP-eligible only if ALL of:
- R1 aggregate return strictly better than baseline (equality = no advantage)
- R2 worst-regime drawdown is not materially worse than baseline (>20% relative)
- R3 generalization: candidate improves (or is flat within a small tolerance)
  in at least half of the regimes where either variant traded
- R4 the candidate introduces no breaker-condition bypass
  (fills-while-breaker-active must stay 0)
- R5 the aggregate advantage exceeds a minimum magnitude (5% of |baseline|
  PnL) so marginal noise-level improvements cannot merge
Otherwise the verdict is REJECT with the failed rules listed. Probe PnL is a
stress-vehicle metric, not a claim about real-market profitability.

Usage:
    uv run python scripts/run_ab_comparison.py --dry_run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

from polysignal.ingestion.market_regimes import MarketRegime
from scripts.run_regime_stress_test import (
    OUTPUT_DIR as STRESS_OUTPUT_DIR,
)
from scripts.run_regime_stress_test import (
    StressConfig,
    run_regime_stress,
    summarize,
)

AB_OUTPUT_DIR = STRESS_OUTPUT_DIR / "ab"

# Generalization tolerance: a relative return delta within this band counts as
# "flat" rather than better/worse when counting regime-level improvements.
FLAT_TOLERANCE = 0.05
# Drawdown degradation allowed before R2 fails (relative, e.g. 0.20 = +20%).
DRAWDOWN_TOLERANCE = 0.20
# Minimum aggregate advantage for R5 ("obvious advantage"), relative to |baseline|.
MIN_ADVANTAGE_PCT = 0.05


@dataclass
class StrategyVariant:
    """One variant's strategy parameters (the only A/B difference)."""

    name: str
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_steps: int
    entry_notional_usd: float = 50.0
    entry_mode: str = "always"
    threshold_level: float = 0.50
    threshold_proximity_pct: float = 0.10


@dataclass
class ABResult:
    baseline_name: str
    candidate_name: str
    per_regime: list[dict] = field(default_factory=list)
    baseline_total_pnl: float = 0.0
    candidate_total_pnl: float = 0.0
    rules: dict[str, bool] = field(default_factory=dict)
    verdict: str = "REJECT"
    reasons: list[str] = field(default_factory=list)


def _regime_config(variant: StrategyVariant, config: StressConfig) -> StressConfig:
    return StressConfig(
        steps=config.steps,
        markets=config.markets,
        starting_capital_usd=config.starting_capital_usd,
        entry_notional_usd=variant.entry_notional_usd,
        stop_loss_pct=variant.stop_loss_pct,
        take_profit_pct=variant.take_profit_pct,
        max_holding_steps=variant.max_holding_steps,
        fee_bps=config.fee_bps,
        latency_seconds=config.latency_seconds,
        seed=config.seed,
        entry_mode=variant.entry_mode,
        threshold_level=variant.threshold_level,
        threshold_proximity_pct=variant.threshold_proximity_pct,
    )


def run_ab_comparison(
    baseline: StrategyVariant,
    candidate: StrategyVariant,
    config: StressConfig | None = None,
    regimes: list[MarketRegime] | None = None,
) -> ABResult:
    """Run both variants over identical regime windows and apply the rules."""
    config = config or StressConfig()
    regimes = regimes or list(MarketRegime)
    result = ABResult(
        baseline_name=baseline.name,
        candidate_name=candidate.name,
    )

    for regime in regimes:
        base_run = run_regime_stress(regime, _regime_config(baseline, config))
        cand_run = run_regime_stress(regime, _regime_config(candidate, config))
        result.per_regime.append(
            {
                "regime": regime.value,
                "baseline": summarize(base_run, _regime_config(baseline, config)),
                "candidate": summarize(cand_run, _regime_config(candidate, config)),
            }
        )
        result.baseline_total_pnl += base_run.total_pnl_usd
        result.candidate_total_pnl += cand_run.total_pnl_usd

    _apply_verdict_rules(result)
    return result


def _apply_verdict_rules(result: ABResult) -> None:
    """Evaluate the conservative keep/merge rules (see module docstring)."""
    reasons: list[str] = []

    # R1 strict aggregate advantage (equality = no advantage = no merge)
    r1 = result.candidate_total_pnl > result.baseline_total_pnl
    result.rules["R1_aggregate_return"] = r1
    if not r1:
        reasons.append(
            f"R1 no aggregate advantage: {result.candidate_total_pnl:.2f} vs "
            f"{result.baseline_total_pnl:.2f} (equality is not an advantage)"
        )

    # R2 worst-regime drawdown not materially worse
    r2 = True
    for row in result.per_regime:
        base_dd = row["baseline"]["max_drawdown_pct"] or 0.0
        cand_dd = row["candidate"]["max_drawdown_pct"] or 0.0
        # drawdowns are <= 0; degradation means more negative
        if base_dd < 0 and cand_dd < base_dd * (1.0 + DRAWDOWN_TOLERANCE):
            r2 = False
            reasons.append(
                f"R2 drawdown degraded in {row['regime']}: {cand_dd:.2f}% vs {base_dd:.2f}%"
            )
    result.rules["R2_drawdown_not_worse"] = r2

    # R3 generalization across regimes where either variant traded
    regime_windows = [
        row
        for row in result.per_regime
        if row["baseline"]["entries_filled"] > 0 or row["candidate"]["entries_filled"] > 0
    ]
    better = 0
    flat = 0
    worse = 0
    for row in regime_windows:
        base_pnl = row["baseline"]["total_pnl_usd"]
        cand_pnl = row["candidate"]["total_pnl_usd"]
        scale = max(abs(base_pnl), 1.0)
        delta = (cand_pnl - base_pnl) / scale
        if delta > FLAT_TOLERANCE:
            better += 1
        elif delta >= -FLAT_TOLERANCE:
            flat += 1
        else:
            worse += 1
    r3 = bool(regime_windows) and (better + flat) >= (len(regime_windows) + 1) // 2
    result.rules["R3_generalization"] = r3
    result.rules["R3_detail"] = {"better": better, "flat": flat, "worse": worse}  # type: ignore[assignment]
    if not r3:
        reasons.append(
            f"R3 generalization failed: better={better} flat={flat} worse={worse} "
            f"(need better+flat >= {(len(regime_windows) + 1) // 2})"
        )

    # R4 no breaker bypass in either run
    r4 = all(
        row[side]["entries_filled_while_breaker_active"] == 0
        for row in result.per_regime
        for side in ("baseline", "candidate")
    )
    result.rules["R4_no_breaker_bypass"] = r4
    if not r4:
        reasons.append("R4 breaker bypass detected (fills while breaker active)")

    # R5 advantage must exceed the minimum magnitude to count as "obvious"
    improvement = result.candidate_total_pnl - result.baseline_total_pnl
    scale = max(abs(result.baseline_total_pnl), 1.0)
    r5 = improvement > MIN_ADVANTAGE_PCT * scale
    result.rules["R5_obvious_advantage"] = r5
    if not r5:
        reasons.append(
            f"R5 advantage below minimum: {improvement:.2f} "
            f"({MIN_ADVANTAGE_PCT:.0%} of |baseline| required)"
        )

    result.verdict = "KEEP_ELIGIBLE" if all(
        result.rules[name]
        for name in (
            "R1_aggregate_return",
            "R2_drawdown_not_worse",
            "R3_generalization",
            "R4_no_breaker_bypass",
            "R5_obvious_advantage",
        )
    ) else "REJECT"
    result.reasons = reasons


def build_report(result: ABResult, config: StressConfig) -> str:
    lines = [
        "# A/B Strategy Comparison Report",
        "",
        f"- Baseline: {result.baseline_name}",
        f"- Candidate: {result.candidate_name}",
        f"- Steps per regime: {config.steps}; seed: {config.seed} (identical windows)",
        f"- Aggregate PnL: baseline {result.baseline_total_pnl:.2f} vs "
        f"candidate {result.candidate_total_pnl:.2f}",
        "- Rules: " + ", ".join(
            f"{name}={'PASS' if ok else 'FAIL'}"
            for name, ok in result.rules.items()
            if name != "R3_detail"
        ),
        f"- Verdict: **{result.verdict}**",
    ]
    if result.reasons:
        lines += ["", "## Failure Reasons", ""]
        lines += [f"- {reason}" for reason in result.reasons]
    lines += [
        "",
        "## Per-Regime Detail",
        "",
        "| regime | variant | entries | W/L | total PnL | max DD% | final equity | breakers |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in result.per_regime:
        for side in ("baseline", "candidate"):
            s = row[side]
            lines.append(
                f"| {row['regime']} | {side} | {s['entries_filled']} "
                f"| {s['wins']}/{s['losses']} | {s['total_pnl_usd']:.2f} "
                f"| {s['max_drawdown_pct'] if s['max_drawdown_pct'] is not None else 'n/a'} "
                f"| {s['final_equity_usd']:.2f} "
                f"| {', '.join(s['breakers_fired']) or 'none'} |"
            )
    lines += [
        "",
        "_Synthetic stress-vehicle PnL; not a real-market profitability claim._",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--markets", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--baseline",
        default="always-enter",
        help="baseline variant id: always-enter | tight-exit | loose-exit | barrier-proximity",
    )
    parser.add_argument(
        "--candidate",
        default="barrier-proximity",
        help="candidate variant id: always-enter | tight-exit | loose-exit | barrier-proximity",
    )
    args = parser.parse_args()

    VARIANTS = {
        "always-enter": StrategyVariant(
            name="always-enter", stop_loss_pct=0.15, take_profit_pct=0.25, max_holding_steps=10
        ),
        "tight-exit": StrategyVariant(
            name="tight-exit", stop_loss_pct=0.10, take_profit_pct=0.20, max_holding_steps=8
        ),
        "loose-exit": StrategyVariant(
            name="loose-exit", stop_loss_pct=0.15, take_profit_pct=0.25, max_holding_steps=10
        ),
        # crypto_price_threshold_v1 entry-style precheck (Iteration 022b):
        # only enter when price is within 10% of a synthetic barrier level.
        "barrier-proximity": StrategyVariant(
            name="barrier-proximity", stop_loss_pct=0.15, take_profit_pct=0.25,
            max_holding_steps=10, entry_mode="near_threshold",
            threshold_level=0.50, threshold_proximity_pct=0.10,
        ),
    }
    if args.baseline not in VARIANTS or args.candidate not in VARIANTS:
        print(f"unknown variant id; available: {sorted(VARIANTS)}")
        return 1

    config = StressConfig(steps=args.steps, markets=args.markets, seed=args.seed)
    result = run_ab_comparison(
        VARIANTS[args.baseline], VARIANTS[args.candidate], config
    )
    report = build_report(result, config)
    print(report)

    if not args.dry_run:
        AB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (AB_OUTPUT_DIR / "ab_comparison_report.md").write_text(report, encoding="utf-8")
        (AB_OUTPUT_DIR / "ab_comparison_summary.json").write_text(
            json.dumps(
                {
                    "config": asdict(config),
                    "baseline": asdict(VARIANTS[args.baseline]),
                    "candidate": asdict(VARIANTS[args.candidate]),
                    "baseline_total_pnl": result.baseline_total_pnl,
                    "candidate_total_pnl": result.candidate_total_pnl,
                    "rules": result.rules,
                    "verdict": result.verdict,
                    "reasons": result.reasons,
                    "per_regime": result.per_regime,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"written: {AB_OUTPUT_DIR}/ab_comparison_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
