"""Tests for Phase 8A shadow paper trading core."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml

import scripts.run_shadow_paper_loop as shadow_script
from polysignal.shadow.entry_filter import EntryDecision, EntryFilterConfig, ShadowEntryFilter
from polysignal.shadow.exit_rules import ExitReason, ExitRuleConfig, decide_exit
from polysignal.shadow.models import CandidateSnapshot, ShadowSide, ShadowTrade, ShadowTradeStatus
from polysignal.shadow.pnl import calculate_pnl, max_drawdown, summarize_performance
from polysignal.shadow.reporter import write_all_reports


def candidate(**overrides) -> CandidateSnapshot:
    base = {
        "market_id": "m1",
        "question": "Test market?",
        "side": ShadowSide.YES,
        "alpha_score": 40.0,
        "expected_edge": 0.03,
        "entry_yes_best_ask": 0.51,
        "entry_no_best_ask": 0.50,
        "entry_yes_best_bid": 0.50,
        "entry_no_best_bid": 0.49,
        "combined_ask": 1.01,
        "liquidity_score": 5.0,
        "ambiguity_risk": 10.0,
        "near_miss_tier": "tier2_strong_near_miss",
        "orderbook_spread": 0.01,
        "orderbook_depth": 5.0,
        "risk_decision": "allow_shadow",
        "source": "watchlist",
        "entry_time": "2026-05-11T00:00:00",
    }
    base.update(overrides)
    return CandidateSnapshot(**base)


def tradable_candidate(**overrides) -> CandidateSnapshot:
    base = {
        "market_id": "m_trade",
        "question": "Tradable market?",
        "side": ShadowSide.YES,
        "alpha_score": 0.0,
        "expected_edge": 0.03,
        "entry_yes_best_ask": 0.51,
        "entry_no_best_ask": 0.50,
        "entry_yes_best_bid": 0.50,
        "entry_no_best_bid": 0.49,
        "combined_ask": 1.01,
        "liquidity_score": 3.0,
        "ambiguity_risk": 10.0,
        "near_miss_tier": "",
        "orderbook_spread": 0.01,
        "orderbook_depth": 3.0,
        "risk_decision": "allow_shadow",
        "source": "tradable_candidate",
        "entry_time": "2026-05-11T00:00:00",
        "entry_decision_hint": "watch_only",
        "tradable_score": 20.0,
        "tradable_source": "control_group",
        "tradable_reasons": ["low_risk_control_group"],
        "evidence_level": "control_group",
    }
    base.update(overrides)
    return CandidateSnapshot(**base)


def closed_trade(return_pct: float, category: str = "Sports") -> ShadowTrade:
    trade = ShadowTrade.from_candidate(candidate(category=category), "near_miss_tier2")
    trade.exit_time = "2026-05-11T01:00:00"
    trade.exit_price = trade.entry_price * (1 + return_pct)
    trade.return_pct = return_pct
    trade.pnl = return_pct
    trade.exit_reason = ExitReason.FIXED_HORIZON
    trade.status = ShadowTradeStatus.CLOSED
    trade.category = category
    return trade


def test_shadow_trade_model_serialization():
    trade = ShadowTrade.from_candidate(
        candidate(
            yes_token_id="yes1",
            no_token_id="no1",
            edge_type="cross_market_consistency_v1",
            confidence=0.95,
            evidence="microstructure_probability_edge",
            relationship_status="high_confidence_duplicate",
            relationship_confidence=0.86,
            price_gap=0.22,
            reference_market_id="ref1",
            reference_question="Reference?",
            reference_price=0.55,
        ),
        "near_miss_tier2",
    )
    payload = trade.to_dict()
    restored = ShadowTrade.from_dict(payload)

    assert payload["shadow_trade_id"].startswith("shadow_")
    assert payload["market_id"] == "m1"
    assert payload["yes_token_id"] == "yes1"
    assert payload["no_token_id"] == "no1"
    assert payload["edge_type"] == "cross_market_consistency_v1"
    assert payload["confidence"] == 0.95
    assert payload["evidence"] == "microstructure_probability_edge"
    assert payload["relationship_status"] == "high_confidence_duplicate"
    assert payload["relationship_confidence"] == 0.86
    assert payload["price_gap"] == 0.22
    assert payload["reference_market_id"] == "ref1"
    assert restored.side == ShadowSide.YES
    assert restored.status == ShadowTradeStatus.OPEN
    assert restored.yes_token_id == "yes1"
    assert restored.relationship_status == "high_confidence_duplicate"


def test_yes_entry_uses_yes_best_ask():
    trade = ShadowTrade.from_candidate(candidate(entry_yes_best_ask=0.42), "near_miss_tier2")

    assert trade.entry_price == 0.42
    assert trade.entry_side_price == 0.42
    assert trade.entry_price_source == "yes_best_ask"


def test_no_entry_uses_no_best_ask():
    trade = ShadowTrade.from_candidate(
        candidate(side=ShadowSide.NO, entry_no_best_ask=0.47),
        "near_miss_tier2",
    )

    assert trade.entry_price == 0.47
    assert trade.entry_side_price == 0.47
    assert trade.entry_price_source == "no_best_ask"


def test_combined_ask_not_used_as_side_entry_price():
    trade = ShadowTrade.from_candidate(
        candidate(combined_ask=1.01, entry_yes_best_ask=0.44),
        "near_miss_tier2",
    )

    assert trade.entry_price == 0.44
    assert trade.combined_ask == 1.01


def test_select_shadow_candidates_limits_top_expected_edge():
    candidates = [
        candidate(market_id="m_low", expected_edge=0.01, confidence=0.9),
        candidate(market_id="m_high", expected_edge=0.05, confidence=0.8),
        candidate(market_id="m_mid", expected_edge=0.03, confidence=0.95),
    ]

    selected = shadow_script.select_shadow_candidates(
        candidates,
        max_shadow_entries=2,
        min_expected_edge=0.001,
        min_confidence=0.6,
    )

    assert [item.market_id for item in selected] == ["m_high", "m_mid"]


def test_select_shadow_candidates_filters_edge_type_and_confidence():
    selected = shadow_script.select_shadow_candidates(
        [
            candidate(market_id="m_keep", edge_type="price_dislocation_probability_v1", confidence=0.7),
            candidate(market_id="m_other", edge_type="combined_ask_arbitrage", confidence=0.9),
            candidate(market_id="m_low_conf", edge_type="price_dislocation_probability_v1", confidence=0.2),
        ],
        max_shadow_entries=25,
        min_expected_edge=0.001,
        min_confidence=0.6,
        edge_type="price_dislocation_probability_v1",
    )

    assert [item.market_id for item in selected] == ["m_keep"]


def test_tier1_near_miss_can_enter():
    result = ShadowEntryFilter().evaluate(candidate(near_miss_tier="tier1_mispricing"))

    assert result.allowed is True


def test_tier2_near_miss_can_enter():
    result = ShadowEntryFilter().evaluate(candidate(near_miss_tier="tier2_strong_near_miss"))

    assert result.allowed is True


def test_missing_side_ask_not_eligible():
    result = ShadowEntryFilter().evaluate(candidate(entry_yes_best_ask=0.0))

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "missing_side_ask" in result.reject_reasons
    assert "invalid_entry_price_model" in result.reject_reasons


def test_avoid_candidate_excluded():
    result = ShadowEntryFilter().evaluate(candidate(is_avoid_candidate=True))

    assert result.allowed is False
    assert result.reason == "avoid_candidate"


def test_high_ambiguity_excluded():
    result = ShadowEntryFilter(EntryFilterConfig(max_ambiguity_risk=20)).evaluate(
        candidate(ambiguity_risk=50)
    )

    assert result.allowed is False
    assert result.reason == "high_ambiguity"


def test_low_liquidity_excluded():
    result = ShadowEntryFilter(EntryFilterConfig(min_liquidity_score=3)).evaluate(
        candidate(liquidity_score=1)
    )

    assert result.allowed is False
    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "low_liquidity" in result.reject_reasons
    assert "high_alpha_but_insufficient_liquidity" in result.watch_reasons


def test_llm_only_signal_excluded():
    result = ShadowEntryFilter().evaluate(candidate(is_llm_only=True))

    assert result.allowed is False
    assert "llm_only_signal" in result.reject_reasons


def test_alpha_score_only_signal_excluded():
    result = ShadowEntryFilter().evaluate(
        candidate(near_miss_tier="", source="alpha_score_only", alpha_score=99)
    )

    assert result.allowed is False
    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "alpha_score_only_not_allowed" in result.reject_reasons


def test_fixed_horizon_exit():
    trade = ShadowTrade.from_candidate(candidate(), "near_miss")
    decision = decide_exit(
        trade,
        [{"yes_best_bid": 0.511}, {"yes_best_bid": 0.512}, {"yes_best_bid": 0.513}],
        ExitRuleConfig(fixed_horizon_minutes=120, take_profit_pct=1, stop_loss_pct=-1),
    )

    assert decision.reason == ExitReason.FIXED_HORIZON


def test_stop_loss_exit():
    trade = ShadowTrade.from_candidate(candidate(entry_yes_best_ask=1.0, combined_ask=1.0), "near_miss")
    decision = decide_exit(
        trade,
        [{"yes_best_bid": 0.94}],
        ExitRuleConfig(stop_loss_pct=-0.05),
    )

    assert decision.reason == ExitReason.STOP_LOSS


def test_take_profit_exit():
    trade = ShadowTrade.from_candidate(candidate(entry_yes_best_ask=1.0, combined_ask=1.0), "near_miss")
    decision = decide_exit(
        trade,
        [{"yes_best_bid": 1.06}],
        ExitRuleConfig(take_profit_pct=0.05),
    )

    assert decision.reason == ExitReason.TAKE_PROFIT


def test_stale_data_exit():
    trade = ShadowTrade.from_candidate(candidate(), "near_miss")
    decision = decide_exit(trade, [{"yes_best_bid": 0.51, "stale": True}])

    assert decision.reason == ExitReason.STALE_DATA


def test_missing_side_bid_does_not_close_position():
    trade = ShadowTrade.from_candidate(candidate(), "near_miss")
    decision = decide_exit(trade, [{"combined_ask": 1.07}], ExitRuleConfig(take_profit_pct=0.05))

    assert decision.should_exit is False
    assert decision.exit_price is None


def test_yes_side_pnl():
    pnl, ret = calculate_pnl(1.0, 1.05, ShadowSide.YES)

    assert round(ret, 4) == 0.05
    assert round(pnl, 4) == 0.05


def test_no_side_pnl():
    pnl, ret = calculate_pnl(1.0, 0.95, ShadowSide.NO)

    assert round(ret, 4) == -0.05
    assert round(pnl, 4) == -0.05


def test_yes_exit_uses_yes_best_bid():
    trade = ShadowTrade.from_candidate(candidate(entry_yes_best_ask=0.50), "near_miss")
    decision = decide_exit(trade, [{"yes_best_bid": 0.55, "price": 0.99}], ExitRuleConfig(take_profit_pct=0.05))

    assert decision.reason == ExitReason.TAKE_PROFIT
    assert decision.exit_price == 0.55


def test_no_exit_uses_no_best_bid():
    trade = ShadowTrade.from_candidate(
        candidate(side=ShadowSide.NO, entry_no_best_ask=0.50),
        "near_miss",
    )
    decision = decide_exit(trade, [{"no_best_bid": 0.55, "price": 0.01}], ExitRuleConfig(take_profit_pct=0.05))

    assert decision.reason == ExitReason.TAKE_PROFIT
    assert decision.exit_price == 0.55


def test_max_drawdown():
    assert max_drawdown([0.1, -0.2, 0.05, -0.1]) == -0.25


def test_win_rate():
    summary = summarize_performance([closed_trade(0.1), closed_trade(-0.05)])

    assert summary["win_rate"] == 0.5


def test_average_return():
    summary = summarize_performance([closed_trade(0.1), closed_trade(-0.05)])

    assert summary["average_return"] == 0.025


def test_shadow_trades_csv_format(tmp_path: Path):
    output_dir = tmp_path / "shadow"
    write_all_reports(output_dir, [closed_trade(0.1)], {"safe_to_shadow_trade": True})
    text = (output_dir / "shadow_trades.csv").read_text()

    assert "shadow_trade_id,market_id,question,side" in text
    assert "return_pct" in text


def test_shadow_positions_json_format(tmp_path: Path):
    output_dir = tmp_path / "shadow"
    write_all_reports(output_dir, [closed_trade(0.1)], {"safe_to_shadow_trade": True})
    payload = json.loads((output_dir / "shadow_positions.json").read_text())

    assert "open_positions" in payload
    assert "closed_positions" in payload


def test_paper_performance_summary_json_format(tmp_path: Path):
    output_dir = tmp_path / "shadow"
    write_all_reports(output_dir, [closed_trade(0.1)], {"safe_to_shadow_trade": True})
    payload = json.loads((output_dir / "paper_performance_summary.json").read_text())

    assert payload["total_shadow_trades"] == 1
    assert "win_rate" in payload
    assert "safety_verification" in payload


def test_no_forbidden_trading_imports():
    files = [
        Path("polysignal/shadow/models.py"),
        Path("polysignal/shadow/entry_filter.py"),
        Path("polysignal/shadow/exit_rules.py"),
        Path("polysignal/shadow/pnl.py"),
        Path("polysignal/shadow/reporter.py"),
        Path("scripts/run_shadow_paper_loop.py"),
    ]
    forbidden = {"LiveTrader", "PaperTrader", "RiskGovernor"}

    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[-1] not in forbidden
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not any(name in node.module for name in forbidden)
                for alias in node.names:
                    assert alias.name not in forbidden


def test_no_api_key_required(monkeypatch):
    for key in ["POLYMARKET_API_KEY", "CLOB_API_KEY", "PRIVATE_KEY"]:
        monkeypatch.delenv(key, raising=False)

    assert shadow_script.verify_safety()["offline_only"] is True


def test_live_trading_enabled_still_false():
    risk = yaml.safe_load(Path("config/risk.yaml").read_text())

    assert risk["live_trading_enabled"] is False


def test_dry_run_does_not_write_files(tmp_path: Path, capsys):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "alpha_candidates.csv").write_text(
        "market_id,question,category,appearances,avg_combined_ask,avg_ambiguity_risk,alpha_score,run_ids\n"
        "m1,Question?,Sports,3,1.01,10,40,run_a\n"
    )

    rc = shadow_script.main([
        "--runs_dir",
        str(runs_dir),
        "--output_dir",
        str(tmp_path / "shadow"),
        "--dry_run",
    ])
    output = capsys.readouterr().out

    assert rc == 0
    assert "DRY RUN: shadow paper loop" in output
    assert not (tmp_path / "shadow" / "shadow_trades.csv").exists()


def test_each_reject_reason_can_be_recorded():
    cases = {
        "avoid_candidate": candidate(is_avoid_candidate=True),
        "high_ambiguity": candidate(ambiguity_risk=99),
        "low_liquidity": candidate(liquidity_score=0),
        "spread_too_wide": candidate(orderbook_spread=0.2),
        "stale_data": candidate(is_stale=True),
        "missing_combined_ask": candidate(combined_ask=0),
        "missing_alpha_score": candidate(alpha_score=0, near_miss_tier=""),
        "near_miss_tier_not_eligible": candidate(near_miss_tier="tier4_normal_monitor"),
        "alpha_score_only_not_allowed": candidate(near_miss_tier="", source="alpha_score_only"),
        "risk_hard_reject": candidate(risk_decision="hard_reject_ambiguous"),
        "insufficient_orderbook_depth": candidate(orderbook_depth=0),
    }
    entry_filter = ShadowEntryFilter()

    for reason, item in cases.items():
        result = entry_filter.evaluate(item)
        assert reason in result.reject_reasons


def test_unknown_reject_reason():
    result = ShadowEntryFilter().evaluate(
        candidate(alpha_score=1, near_miss_tier="", source="weak_candidate", expected_edge=0.0)
    )

    assert result.entry_decision == EntryDecision.REJECTED
    assert result.reject_reasons == ["unknown"]


def test_high_alpha_but_insufficient_liquidity_watch_only():
    result = ShadowEntryFilter().evaluate(
        candidate(near_miss_tier="", alpha_score=50, liquidity_score=0, orderbook_depth=0)
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "high_alpha_but_insufficient_liquidity" in result.watch_reasons


def test_tier3_near_miss_watch_only():
    result = ShadowEntryFilter().evaluate(candidate(near_miss_tier="tier3_weak_near_miss"))

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "tier3_near_miss_watch" in result.watch_reasons


def test_avoid_candidate_rejected_decision():
    result = ShadowEntryFilter().evaluate(candidate(is_avoid_candidate=True))

    assert result.entry_decision == EntryDecision.REJECTED


def test_eligible_candidate_decision():
    result = ShadowEntryFilter().evaluate(candidate(near_miss_tier="tier1_mispricing"))

    assert result.entry_decision == EntryDecision.ELIGIBLE_SHADOW_ENTRY


def test_no_shadow_trade_created_for_watch_only():
    trades = shadow_script.build_shadow_trades(
        [candidate(near_miss_tier="tier3_weak_near_miss")],
        EntryFilterConfig(),
        ExitRuleConfig(),
    )

    assert trades == []


def test_no_shadow_trade_created_for_rejected():
    trades = shadow_script.build_shadow_trades(
        [candidate(is_avoid_candidate=True)],
        EntryFilterConfig(),
        ExitRuleConfig(),
    )

    assert trades == []


def test_tradable_candidate_missing_alpha_not_rejected():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(tradable_score=4.0, orderbook_depth=1.0, liquidity_score=1.0, expected_edge=0.0)
    )

    assert "missing_alpha_score" not in result.reject_reasons
    assert "missing_alpha_score_but_not_required" in result.watch_reasons
    assert result.entry_decision == EntryDecision.WATCH_ONLY


def test_control_group_only_default_watch_only():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(expected_edge=0.0, near_miss_tier="", tradable_source="control_group")
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "control_group_only_watch" in result.watch_reasons


def test_expected_edge_too_low_not_eligible():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(expected_edge=0.015, orderbook_spread=0.01)
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "edge_too_low" in result.reject_reasons or "edge_too_low" in result.watch_reasons


def test_expected_edge_above_spread_buffer_can_enter():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(
            expected_edge=0.03,
            orderbook_spread=0.01,
            tradable_source="watchlist",
            tradable_reasons=["non_avoid_watchlist"],
            evidence_level="strong",
        )
    )

    assert result.entry_decision == EntryDecision.ELIGIBLE_SHADOW_ENTRY


def test_tier1_near_miss_with_edge_is_strong_evidence():
    result = ShadowEntryFilter().evaluate(
        candidate(near_miss_tier="tier1_mispricing", expected_edge=0.03)
    )

    assert result.entry_decision == EntryDecision.ELIGIBLE_SHADOW_ENTRY


def test_tier1_near_miss_without_edge_stays_watch_only():
    result = ShadowEntryFilter().evaluate(
        candidate(near_miss_tier="tier1_mispricing", expected_edge=0.0)
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY


def test_high_quality_tradable_candidate_can_enter():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(
            tradable_source="watchlist",
            tradable_reasons=["non_avoid_watchlist"],
            evidence_level="strong",
        )
    )

    assert result.entry_decision == EntryDecision.ELIGIBLE_SHADOW_ENTRY
    assert result.reason == "tradable_candidate_evidence_passed"
    assert "tradable_candidate_quality_passed" in result.watch_reasons


def test_tradable_score_only_cannot_enter():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(tradable_reasons=[], evidence_level="", tradable_score=99.0)
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "tradable_score_only_not_allowed" in result.watch_reasons
    assert "insufficient_tradable_evidence" in result.watch_reasons


def test_control_group_with_edge_stays_watch_only_without_strong_evidence():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(expected_edge=0.05, tradable_source="control_group", near_miss_tier="")
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "control_group_only_watch" in result.watch_reasons


def test_tradable_candidate_avoid_still_rejected():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(is_avoid_candidate=True, tradable_score=99.0)
    )

    assert result.entry_decision == EntryDecision.REJECTED
    assert result.reason == "avoid_candidate"


def test_low_quality_tradable_candidate_rejections():
    cases = {
        "high_ambiguity": tradable_candidate(ambiguity_risk=99),
        "low_liquidity": tradable_candidate(liquidity_score=0),
        "spread_too_wide": tradable_candidate(orderbook_spread=0.2),
        "missing_combined_ask": tradable_candidate(combined_ask=0),
    }

    for reason, item in cases.items():
        result = ShadowEntryFilter().evaluate(item)
        assert reason in result.reject_reasons
        assert result.entry_decision in {EntryDecision.REJECTED, EntryDecision.WATCH_ONLY}


def test_tier3_tradable_candidate_insufficient_evidence_watch_only():
    result = ShadowEntryFilter().evaluate(
        tradable_candidate(
            near_miss_tier="tier3_weak_near_miss",
            tradable_score=4.0,
            tradable_reasons=["tier3_improving_watch_only"],
            evidence_level="trajectory",
            liquidity_score=1,
            orderbook_depth=1,
            expected_edge=0.0,
        )
    )

    assert result.entry_decision == EntryDecision.WATCH_ONLY
    assert "near_miss_not_strong_enough" in result.watch_reasons
    assert "tier3_near_miss_watch" in result.watch_reasons


def test_no_shadow_trade_created_for_tradable_watch_only():
    trades = shadow_script.build_shadow_trades(
        [tradable_candidate(tradable_score=4.0, liquidity_score=1, orderbook_depth=1, expected_edge=0.0)],
        EntryFilterConfig(),
        ExitRuleConfig(),
    )

    assert trades == []


def write_tradable_csv(path: Path, score: str = "20", reasons: str = "non_avoid_watchlist") -> None:
    path.write_text(
        "market_id,question,category,source,combined_ask,ambiguity_risk,liquidity_score,spread,"
        "orderbook_depth,near_miss_tier,appearances,evidence_level,is_avoid_candidate,"
        "near_miss_score,liquidity_score_component,ambiguity_penalty,spread_penalty,"
        "repeat_observation_score,watchlist_persistence_score,tradable_score,entry_decision_hint,"
        "reasons,alpha_score,run_ids,expected_edge,entry_yes_best_ask,entry_no_best_ask,"
        "entry_yes_best_bid,entry_no_best_bid\n"
        f"m_trade,Tradable?,Sports,watchlist,1.01,10,3,0.01,3,tier2_strong_near_miss,3,strong,False,"
        f"0,15,5,1,6,5,{score},watch_only,{reasons},0,,0.03,0.51,0.50,0.50,0.49\n"
    )


def test_non_dry_run_generates_shadow_outputs(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "shadow"
    runs_dir.mkdir()
    write_tradable_csv(runs_dir / "tradable_candidates.csv")

    rc = shadow_script.main([
        "--runs_dir",
        str(runs_dir),
        "--output_dir",
        str(output_dir),
        "--diagnostics",
    ])

    assert rc == 0
    assert (output_dir / "shadow_trades.csv").exists()
    assert (output_dir / "shadow_positions.json").exists()
    assert (output_dir / "paper_performance_summary.json").exists()
    assert (output_dir / "paper_performance_report.md").exists()


def test_insufficient_forward_data_does_not_forge_pnl(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    output_dir = tmp_path / "shadow"
    runs_dir.mkdir()
    write_tradable_csv(runs_dir / "tradable_candidates.csv")

    shadow_script.main(["--runs_dir", str(runs_dir), "--output_dir", str(output_dir)])
    summary = json.loads((output_dir / "paper_performance_summary.json").read_text())
    positions = json.loads((output_dir / "shadow_positions.json").read_text())

    assert summary["total_shadow_trades"] == 1
    assert summary["closed_positions"] == 0
    assert summary["insufficient_forward_data_positions"] == 1
    assert summary["total_pnl"] == 0
    assert positions["insufficient_forward_data_positions"][0]["status"] == "insufficient_forward_data"
    assert positions["insufficient_forward_data_positions"][0]["exit_price"] is None


def test_closed_position_calculates_pnl_with_forward_data():
    trades = shadow_script.build_shadow_trades(
        [candidate(observations=[{"yes_best_bid": 0.57}])],
        EntryFilterConfig(),
        ExitRuleConfig(take_profit_pct=0.05),
    )

    assert len(trades) == 1
    assert trades[0].status == ShadowTradeStatus.CLOSED
    assert trades[0].return_pct > 0
    assert trades[0].pnl > 0
    assert trades[0].max_favorable_excursion > 0


def test_performance_report_contains_hypothetical_disclaimer(tmp_path: Path):
    output_dir = tmp_path / "shadow"
    write_all_reports(output_dir, [closed_trade(0.1)], {"safe_to_shadow_trade": True})
    text = (output_dir / "paper_performance_report.md").read_text()

    assert "Shadow performance is hypothetical and not a live trading result." in text
    assert "Shadow Trading Summary" in text
    assert "PnL Summary" in text


def test_diagnostics_csv_json_format(tmp_path: Path):
    output_dir = tmp_path / "shadow"
    diagnostics = [
        {
            "market_id": "m1",
            "question": "Question?",
            "alpha_score": 50,
            "ambiguity_risk": 10,
            "liquidity_score": 1,
            "combined_ask": 1.01,
            "near_miss_tier": "tier3_weak_near_miss",
            "is_avoid_candidate": False,
            "entry_decision": "watch_only",
            "reject_reasons": ["near_miss_tier_not_eligible"],
            "watch_reasons": ["tier3_near_miss_watch"],
        }
    ]
    summary = shadow_script.summarize_diagnostics(diagnostics)
    from polysignal.shadow.reporter import write_all_reports_with_diagnostics

    write_all_reports_with_diagnostics(
        output_dir,
        [],
        {"safe_to_shadow_trade": True},
        diagnostics,
        summary,
    )

    csv_text = (output_dir / "shadow_entry_diagnostics.csv").read_text()
    json_payload = json.loads((output_dir / "shadow_entry_diagnostics.json").read_text())
    report_text = (output_dir / "paper_performance_report.md").read_text()

    assert "market_id,question,alpha_score" in csv_text
    assert json_payload[0]["entry_decision"] == "watch_only"
    assert "Candidates loaded" in report_text


def test_dry_run_outputs_diagnostics_summary(tmp_path: Path, capsys):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "alpha_candidates.csv").write_text(
        "market_id,question,category,appearances,avg_combined_ask,avg_ambiguity_risk,alpha_score,run_ids\n"
        "m1,Question?,Sports,0,1.01,10,40,run_a\n"
    )

    rc = shadow_script.main([
        "--runs_dir",
        str(runs_dir),
        "--output_dir",
        str(tmp_path / "shadow"),
        "--dry_run",
        "--diagnostics",
    ])
    output = capsys.readouterr().out

    assert rc == 0
    assert "eligible_shadow_entry:" in output
    assert "watch_only:" in output
    assert "top_rejection_reasons:" in output
