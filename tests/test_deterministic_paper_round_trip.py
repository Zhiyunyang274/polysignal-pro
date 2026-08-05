"""Tests for the deterministic mock-only paper round-trip harness."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.run_deterministic_paper_round_trip as round_trip


def test_round_trip_is_deterministic_and_never_allows_live_execution() -> None:
    first = round_trip.run_round_trip()
    second = round_trip.run_round_trip()

    assert first == second
    assert first["entry"]["risk_action"] == "paper_trade"
    assert first["entry"]["order_side"] == "buy_yes"
    assert first["entry"]["filled_price"] == 0.5
    assert first["entry"]["filled_shares"] == 2.0
    assert first["exit"]["risk_action"] == "paper_trade"
    assert first["exit"]["order_side"] == "sell_yes"
    assert first["exit"]["filled_price"] == 0.6
    assert first["result"] == {
        "gross_realized_pnl_usd": 0.2,
        "gross_return_on_notional": 0.2,
        "orders_recorded": 2,
        "position_size_after_exit": 0,
    }
    assert first["safety"]["live_execution_allowed"] is False
    assert first["safety"]["network_calls"] is False
    assert first["safety"]["private_key_handling"] is False


def test_dry_run_does_not_write_output(tmp_path: Path, capsys) -> None:
    output = tmp_path / "round_trip.json"

    assert round_trip.main(["--dry_run", "--output", str(output)]) == 0

    assert not output.exists()
    assert "DRY RUN" in capsys.readouterr().out


def test_output_is_normalized_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "round_trip.json"

    assert round_trip.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text()) == round_trip.run_round_trip()

    try:
        round_trip.main(["--output", str(output)])
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing deterministic artifact must not be overwritten")


def test_harness_source_has_no_live_trader_or_secret_access() -> None:
    source = Path(round_trip.__file__).read_text()

    assert "LiveTrader" not in source
    assert ".env" not in source
    assert "os.environ" not in source
    assert "httpx" not in source
    assert "requests" not in source
    assert "LIVE_EXECUTE" not in source
