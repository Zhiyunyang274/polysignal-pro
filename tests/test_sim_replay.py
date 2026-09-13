"""
Tests for the SimBroker shadow-trade replay script.

Uses synthetic RecordedTrade lists and a temp CSV; no real runs/ artifacts
are read or written. Equity identity and skip categorization are verified.
"""

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.replay_shadow_trades_sim import (
    ForwardObservation,
    RecordedTrade,
    ReplayAssumptions,
    load_recorded_trades,
    replay_trades,
)

UTC = UTC
T0 = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


def make_trade(
    trade_id: str,
    entry_price: float,
    exit_price: float | None,
    *,
    side: str = "YES",
    status: str = "",
    with_exit_time: bool = True,
) -> RecordedTrade:
    return RecordedTrade(
        shadow_trade_id=trade_id,
        market_id=trade_id,
        question="q",
        side=side,
        entry_time=T0,
        entry_side_price=entry_price,
        exit_time=T0 + timedelta(hours=4) if with_exit_time else None,
        exit_side_price=exit_price,
        price_model_status=status,
        edge_type="combined_ask_arbitrage",
    )


class TestReplayTrades:
    def test_profitable_and_losing_trades_with_identity(self):
        trades = [
            make_trade("t1", 0.40, 0.60),  # winner
            make_trade("t2", 0.60, 0.40),  # loser
        ]
        assumptions = ReplayAssumptions(
            starting_capital_usd=10000.0,
            notional_per_trade_usd=100.0,
            fee_bps=0.0,
            latency_seconds=0.0,
        )

        result = replay_trades(trades, assumptions)

        assert result.trades_loaded == 2
        assert result.trades_replayed == 2
        assert result.trades_skipped == 0
        assert result.final_equity_usd == pytest.approx(
            assumptions.starting_capital_usd + result.total_pnl_usd
        )
        # t1: 100 USDT at 0.40 -> 0.60; t2: 100 USDT at 0.60 -> 0.40
        pnl_t1 = result.per_trade[0]["realized_pnl_usd"]
        pnl_t2 = result.per_trade[1]["realized_pnl_usd"]
        assert pnl_t1 == pytest.approx(100.0 * (0.60 / 0.40 - 1.0))
        assert pnl_t2 == pytest.approx(100.0 * (0.40 / 0.60 - 1.0))
        assert result.metrics["max_consecutive_losses"] == 1

    def test_fees_reduce_pnl(self):
        trades = [make_trade("t1", 0.40, 0.60)]
        zero_fee = replay_trades(trades, ReplayAssumptions(fee_bps=0.0))
        with_fee = replay_trades(trades, ReplayAssumptions(fee_bps=100.0))
        assert with_fee.total_pnl_usd < zero_fee.total_pnl_usd

    def test_missing_exit_price_skipped_not_fabricated(self):
        trades = [
            make_trade("t_open", 0.40, None),
            make_trade("t_ok", 0.40, 0.55),
        ]
        result = replay_trades(trades, ReplayAssumptions())
        assert result.trades_replayed == 1
        assert result.trades_skipped == 1
        assert result.skip_reasons == {"missing_exit_evidence": 1}
        assert result.total_pnl_usd > 0  # only the closed winner contributes

    def test_invalid_price_model_skipped(self):
        trades = [make_trade("t_legacy", 0.40, 0.60, status="legacy_invalid_price_model")]
        result = replay_trades(trades, ReplayAssumptions())
        assert result.trades_replayed == 0
        assert result.skip_reasons == {"invalid_price_model": 1}
        assert result.total_pnl_usd == 0.0

    def test_unknown_side_skipped(self):
        trades = [make_trade("t_x", 0.40, 0.60, side="BOTH")]
        result = replay_trades(trades, ReplayAssumptions())
        assert result.skip_reasons == {"unknown_side": 1}

    def test_missing_exit_time_skipped(self):
        trades = [make_trade("t_x", 0.40, 0.60, with_exit_time=False)]
        result = replay_trades(trades, ReplayAssumptions())
        assert result.skip_reasons == {"missing_exit_evidence": 1}

    def test_empty_trade_list(self):
        result = replay_trades([], ReplayAssumptions())
        assert result.trades_replayed == 0
        assert result.total_pnl_usd == 0.0
        assert result.final_equity_usd == pytest.approx(
            result.assumptions.starting_capital_usd
        )


class TestForwardObservationFallback:
    @staticmethod
    def obs(
        trade_id: str,
        timestamp: datetime,
        bid: float,
        *,
        side: str = "YES",
        stale: bool = False,
    ) -> ForwardObservation:
        return ForwardObservation(
            shadow_trade_id=trade_id,
            side=side,
            timestamp=timestamp,
            side_best_bid=bid,
            stale=stale,
        )

    def test_open_trade_exits_via_latest_observation(self):
        trades = [make_trade("t_open", 0.40, None)]
        observations = {
            "t_open": [
                self.obs("t_open", T0 + timedelta(hours=4), 0.50),
                self.obs("t_open", T0 + timedelta(hours=6), 0.55),
            ]
        }
        result = replay_trades(trades, ReplayAssumptions(), observations)
        assert result.trades_replayed == 1
        # Latest observation bid wins: 100 USDT at 0.40 exits at 0.55
        pnl = result.per_trade[0]["realized_pnl_usd"]
        assert pnl == pytest.approx(100.0 * (0.55 / 0.40 - 1.0))
        assert result.per_trade[0]["exit_source"] == "forward_observation"

    def test_stale_or_wrong_side_observations_ignored(self):
        trades = [make_trade("t_open", 0.40, None)]
        observations = {
            "t_open": [
                self.obs("t_open", T0 + timedelta(hours=4), 0.70, stale=True),
                self.obs("t_open", T0 + timedelta(hours=5), 0.70, side="NO"),
                self.obs("t_open", T0 - timedelta(hours=1), 0.70),  # before entry
            ]
        }
        result = replay_trades(trades, ReplayAssumptions(), observations)
        assert result.skip_reasons == {"missing_exit_evidence": 1}

    def test_recorded_exit_preferred_over_observation(self):
        trades = [make_trade("t1", 0.40, 0.50)]
        observations = {"t1": [self.obs("t1", T0 + timedelta(hours=4), 0.90)]}
        result = replay_trades(trades, ReplayAssumptions(), observations)
        assert result.per_trade[0]["exit_source"] == "recorded_exit"
        assert result.per_trade[0]["exit_side_price"] == pytest.approx(0.50)


class TestLoadRecordedTrades:
    def test_loads_and_filters_csv_rows(self, tmp_path: Path):
        csv_path = tmp_path / "shadow_trades.csv"
        rows = [
            {
                "shadow_trade_id": "t1",
                "market_id": "m1",
                "question": "q1",
                "side": "YES",
                "entry_time": "2026-09-11T12:00:00",
                "entry_side_price": "0.40",
                "exit_side_price": "0.55",
                "exit_time": "2026-09-11T16:00:00",
                "price_model_status": "",
                "edge_type": "combined_ask_arbitrage",
            },
            {
                "shadow_trade_id": "t2",
                "market_id": "m2",
                "question": "q2",
                "side": "NO",
                "entry_time": "",
                "entry_side_price": "",  # missing entry -> dropped at load
                "exit_side_price": "0.55",
                "exit_time": "",
                "price_model_status": "",
                "edge_type": "",
            },
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        trades = load_recorded_trades(csv_path)
        assert len(trades) == 1
        assert trades[0].shadow_trade_id == "t1"
        assert trades[0].entry_time == datetime(2026, 9, 11, 12, 0, 0)
        assert trades[0].exit_side_price == pytest.approx(0.55)
