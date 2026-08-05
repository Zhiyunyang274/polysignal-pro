"""Tests for the local, read-only research web console."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from polysignal.interface.web_console import ConsoleDataLoader, create_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _http_request(base_url: str, path: str, method: str = "GET") -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=b"" if method != "GET" else None,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@pytest.fixture
def running_server():
    server = create_server("127.0.0.1", 0, PROJECT_ROOT)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_loader_reads_formal_v7_cohort_without_mutating_artifacts() -> None:
    run_root = PROJECT_ROOT / "runs" / "crypto_threshold_shadow"
    config_root = PROJECT_ROOT / "config"
    before = {
        path: (path.stat().st_mtime_ns, path.stat().st_size)
        for root in (run_root, config_root)
        for path in root.rglob("*")
        if path.is_file()
    }

    state = ConsoleDataLoader(PROJECT_ROOT).load_state()

    cohort = state["cohort"]
    assert cohort["run_id"] == "step12_v7_20260804_140305"
    assert cohort["markets_scanned"] == 1958
    assert cohort["crypto_markets"] == 56
    assert cohort["candidates"] == 44
    assert cohort["positions"] == 11
    assert cohort["closed_positions"] == 0
    assert cohort["pnl"] is None
    assert cohort["forward_coverage"] == 0.0
    assert cohort["cluster_count"] == 3
    assert len(state["positions"]) == 11
    assert state["provenance"]["candidate_file"] == "crypto_threshold_edge_candidates.csv"
    assert state["round_trip"]["orders_recorded"] == 2
    assert state["system"]["safety"] == {
        "live_trading_enabled": False,
        "allow_auto_execution": False,
        "paper_trading_enabled": True,
        "llm_provider": "mock",
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "private_key_handling": False,
        "network_calls": False,
    }

    after = {
        path: (path.stat().st_mtime_ns, path.stat().st_size)
        for root in (run_root, config_root)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_loader_fails_gracefully_when_snapshot_is_missing(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "risk.yaml").write_text(
        "live_trading_enabled: true\nallow_auto_execution: yes\npaper_trading_enabled: false\n",
        encoding="utf-8",
    )
    (config / "llm.yaml").write_text("provider: glm\n", encoding="utf-8")

    state = ConsoleDataLoader(tmp_path).load_state()

    assert state["cohort"]["status"] == "no_snapshot"
    assert state["cohort"]["run_id"] == "unavailable"
    assert state["positions"] == []
    assert state["candidates"] == []
    assert state["system"]["safety"] == {
        "live_trading_enabled": True,
        "allow_auto_execution": True,
        "paper_trading_enabled": False,
        "llm_provider": "glm",
        "authenticated_endpoints": False,
        "order_placement": False,
        "order_cancellation": False,
        "private_key_handling": False,
        "network_calls": False,
    }


def test_api_serves_state_and_health_as_read_only(running_server: str) -> None:
    status, body = _http_request(running_server, "/api/state")
    assert status == 200
    state = json.loads(body)
    assert state["schema_version"] == "polysignal_web_console_state_v1"
    assert state["system"]["mode"] == "READ_ONLY_RESEARCH"

    status, body = _http_request(running_server, "/api/health")
    assert status == 200
    assert json.loads(body) == {"status": "ok", "read_only": True}

    status, body = _http_request(running_server, "/")
    assert status == 200
    assert b"PolySignal Research Console" in body


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_api_rejects_mutating_methods(running_server: str, method: str) -> None:
    status, body = _http_request(running_server, "/api/state", method)
    assert status == 405
    assert json.loads(body) == {"error": "read_only_console"}


def test_api_rejects_path_traversal(running_server: str) -> None:
    status, body = _http_request(running_server, "/assets/../web_console.py")
    assert status == 404
    assert json.loads(body) == {"error": "asset_not_found"}
