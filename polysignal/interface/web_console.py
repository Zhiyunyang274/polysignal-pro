"""Local, read-only control console for PolySignal research artifacts.

The console intentionally has no imports from execution or risk modules. It reads
run-scoped JSON and configuration snapshots, then exposes a small JSON API to the
static UI. It never writes to the project, calls a remote API, or loads ``.env``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import yaml
except ImportError:  # pragma: no cover - the project already depends on PyYAML
    yaml = None  # type: ignore[assignment]


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).with_name("web_console_static")
V7_ROOT = "crypto_threshold_shadow"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _basename(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return Path(value).name


def _compact_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "-"
    return value.replace("T", " ").replace("+00:00", "Z")[:23]


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return default


class ConsoleDataLoader:
    """Read and normalize the latest Step 12 v7 artifacts."""

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root.resolve()
        self.runs_dir = self.project_root / "runs"
        self.config_dir = self.project_root / "config"

    def latest_v7_run(self) -> Path | None:
        root = self.runs_dir / V7_ROOT
        if not root.is_dir():
            return None
        runs = [path for path in root.glob("step12_v7_*") if path.is_dir()]
        runs.sort(key=lambda path: path.name, reverse=True)
        return runs[0] if runs else None

    def _safety(self) -> dict[str, Any]:
        risk = _read_yaml(self.config_dir / "risk.yaml")
        llm = _read_yaml(self.config_dir / "llm.yaml")
        return {
            "live_trading_enabled": _bool(risk.get("live_trading_enabled")),
            "allow_auto_execution": _bool(risk.get("allow_auto_execution")),
            "paper_trading_enabled": _bool(risk.get("paper_trading_enabled"), True),
            "llm_provider": str(llm.get("provider") or "mock"),
            "authenticated_endpoints": False,
            "order_placement": False,
            "order_cancellation": False,
            "private_key_handling": False,
            "network_calls": False,
        }

    @staticmethod
    def _candidate(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "market_id": str(value.get("market_id") or ""),
            "asset": str(value.get("asset") or ""),
            "question": str(value.get("question") or "Untitled market"),
            "side": str(value.get("side") or "-"),
            "threshold_price": _number(value.get("threshold_price")),
            "barrier_direction": str(value.get("barrier_direction") or "unknown"),
            "contract_kind": str(value.get("contract_kind") or "-"),
            "expiry_time": _compact_time(value.get("expiry_time")),
            "entry_time": _compact_time(value.get("timestamp") or value.get("entry_time")),
            "entry_price": _number(value.get("entry_side_price") or value.get("entry_price")),
            "expected_edge": _number(value.get("expected_edge")),
            "confidence": _number(value.get("confidence")),
            "recommended_action": str(
                value.get("recommended_action") or value.get("entry_decision_hint") or "watch_only"
            ),
            "edge_status": str(value.get("edge_status") or "-"),
            "historical_status": str(value.get("historical_barrier_evidence_status") or "-"),
            "resolution_status": str(value.get("resolution_status") or "-"),
            "risk_flags": str(value.get("risk_flags") or ""),
            "spread": _number(value.get("spread")),
            "depth": _number(value.get("orderbook_depth") or value.get("depth")),
        }

    @staticmethod
    def _position(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "shadow_trade_id": str(value.get("shadow_trade_id") or ""),
            "market_id": str(value.get("market_id") or ""),
            "asset": str(value.get("asset") or ""),
            "question": str(value.get("question") or "Untitled market"),
            "side": str(value.get("side") or "-"),
            "status": str(value.get("status") or "unknown"),
            "contract_kind": str(value.get("contract_kind") or "-"),
            "barrier_direction": str(value.get("barrier_direction") or "unknown"),
            "entry_time": _compact_time(value.get("entry_time")),
            "entry_price": _number(value.get("entry_price")),
            "exit_price": _number(value.get("exit_price")),
            "expected_edge": _number(value.get("expected_edge")),
            "confidence": _number(value.get("confidence")),
            "holding_minutes": _number(value.get("holding_minutes")),
            "insufficient_reason": str(
                value.get("price_model_notes") or value.get("insufficient_reason") or ""
            ),
            "risk_decision": str(value.get("risk_decision") or ""),
        }

    def load_state(self) -> dict[str, Any]:
        run_dir = self.latest_v7_run()
        safety = self._safety()
        empty_cohort: dict[str, Any] = {
            "run_id": "unavailable",
            "discovery_schema": "-",
            "validator_schema": "-",
            "status": "no_snapshot",
            "entry_time": "-",
            "generated_at": "-",
            "markets_scanned": 0,
            "crypto_markets": 0,
            "candidates": 0,
            "shadow_entries": 0,
            "watch_only": 0,
            "positions": 0,
            "closed_positions": 0,
            "forward_observations": 0,
            "forward_coverage": 0.0,
            "pnl": None,
            "win_rate": None,
            "historical_verified": 0,
            "historical_total": 0,
            "cluster_count": 0,
            "cluster_target": 5,
            "gamma_exhaustive": False,
            "errors": [],
        }
        if run_dir is None:
            return self._state(empty_cohort, [], [], {}, {}, safety)

        discovery_dir = run_dir / "discovery"
        validation_dir = run_dir / "validation"
        discovery = _read_json(discovery_dir / "crypto_threshold_edge_discovery_summary.json")
        validation = _read_json(validation_dir / "crypto_threshold_shadow_pnl_summary.json")
        candidate_payload = _read_json(discovery_dir / "crypto_threshold_edge_candidates.json")
        position_payload = _read_json(validation_dir / "shadow_positions.json")
        candidates_raw = candidate_payload.get("crypto_threshold_edge_candidates", [])
        candidates = [self._candidate(row) for row in candidates_raw if isinstance(row, dict)]
        position_rows: list[dict[str, Any]] = []
        for key in ("closed_positions", "open_positions", "insufficient_forward_data_positions"):
            rows = position_payload.get(key, [])
            if isinstance(rows, list):
                position_rows.extend(self._position(row) for row in rows if isinstance(row, dict))

        performance = validation.get("performance", {})
        forward_data = validation.get("forward_data", {})
        validation_meta = validation.get("validation", {})
        discovery_error_rows = discovery.get("errors", [])
        errors = [
            str(row.get("error") or "unknown error")
            for row in discovery_error_rows
            if isinstance(row, dict)
        ]
        cohort = {
            "run_id": run_dir.name,
            "discovery_schema": str(discovery.get("schema_version") or "-"),
            "validator_schema": str(validation.get("schema_version") or "-"),
            "status": str(validation_meta.get("status") or "unknown"),
            "entry_time": _compact_time(discovery.get("batch_entry_time")),
            "generated_at": _compact_time(validation.get("generated_at")),
            "markets_scanned": _integer(discovery.get("markets_scanned")),
            "crypto_markets": _integer(discovery.get("crypto_markets_detected")),
            "candidates": _integer(discovery.get("candidates_generated")),
            "shadow_entries": _integer(discovery.get("shadow_entry_candidates")),
            "watch_only": _integer(discovery.get("watch_only_candidates")),
            "positions": _integer(performance.get("total_positions")),
            "closed_positions": _integer(performance.get("closed_positions")),
            "forward_observations": _integer(forward_data.get("observations_loaded")),
            "forward_coverage": _number(performance.get("forward_data_coverage"), 0.0) or 0.0,
            "pnl": _number(performance.get("total_pnl")),
            "win_rate": _number(performance.get("win_rate")),
            "historical_verified": _integer(
                discovery.get("verified_historical_barrier_evidence_candidates")
            ),
            "historical_total": _integer(
                discovery.get("historical_barrier_evidence_manifest_count")
            ),
            "cluster_count": _integer(performance.get("position_cluster_count")),
            "cluster_target": _integer(validation_meta.get("min_independent_clusters"), 5),
            "gamma_exhaustive": not bool(errors),
            "errors": errors,
        }
        provenance = validation.get("artifact_provenance", {})
        validation_inputs = validation.get("inputs", {})
        candidate_file = provenance.get("candidate_file") or validation_inputs.get("candidate_file")
        provenance_view = {
            "candidate_file_sha256": str(provenance.get("candidate_file_sha256") or ""),
            "shadow_trades_output_sha256": str(provenance.get("shadow_trades_output_sha256") or ""),
            "candidate_file": _basename(candidate_file),
            "shadow_trades_output": _basename(provenance.get("shadow_trades_output_path")),
        }
        round_trip = _read_json(run_dir / "paper_round_trip" / "round_trip_1.json")
        return self._state(cohort, candidates, position_rows, provenance_view, round_trip, safety)

    @staticmethod
    def _state(
        cohort: dict[str, Any],
        candidates: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        provenance: dict[str, Any],
        round_trip: dict[str, Any],
        safety: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": "polysignal_web_console_state_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "system": {
                "mode": "READ_ONLY_RESEARCH",
                "data_source": "run_scoped_artifacts",
                "safety": safety,
            },
            "cohort": cohort,
            "readiness": {
                "historical": {
                    "verified": cohort.get("historical_verified", 0),
                    "total": cohort.get("historical_total", 0),
                },
                "forward": {
                    "observations": cohort.get("forward_observations", 0),
                    "positions": cohort.get("positions", 0),
                    "coverage": cohort.get("forward_coverage", 0.0),
                },
                "clusters": {
                    "observed": cohort.get("cluster_count", 0),
                    "target": cohort.get("cluster_target", 5),
                },
            },
            "positions": positions,
            "candidates": candidates,
            "provenance": provenance,
            "round_trip": {
                "mode": round_trip.get("mode", "-") if isinstance(round_trip, dict) else "-",
                "pnl": _number((round_trip.get("result") or {}).get("gross_realized_pnl_usd"))
                if isinstance(round_trip, dict)
                else None,
                "orders_recorded": _integer((round_trip.get("result") or {}).get("orders_recorded"))
                if isinstance(round_trip, dict)
                else 0,
                "live_execution_allowed": _bool(
                    (round_trip.get("safety") or {}).get("live_execution_allowed")
                )
                if isinstance(round_trip, dict)
                else False,
            },
            "events": [
                {"kind": "discovery", "label": "Discovery snapshot", "status": "complete"},
                {
                    "kind": "validation",
                    "label": "Offline v7 validation",
                    "status": cohort.get("status", "unknown"),
                },
                {"kind": "safety", "label": "Execution guard", "status": "locked"},
            ],
        }


class ConsoleHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying a read-only data loader."""

    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], project_root: Path):
        self.data_loader = ConsoleDataLoader(project_root)
        super().__init__(address, ConsoleRequestHandler)


class ConsoleRequestHandler(BaseHTTPRequestHandler):
    """Serve the static console and its read-only state endpoint."""

    server_version = "PolySignalConsole/1.0"

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._send_json(self.server.data_loader.load_state())  # type: ignore[attr-defined]
            return
        if parsed.path == "/api/health":
            self._send_json({"status": "ok", "read_only": True})
            return
        if parsed.path in {"/", "/index.html"}:
            self._send_file(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/assets/"):
            relative = parsed.path.removeprefix("/assets/")
            candidate = (STATIC_ROOT / relative).resolve()
            if STATIC_ROOT.resolve() not in candidate.parents or not candidate.is_file():
                self._send_json({"error": "asset_not_found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = "text/plain; charset=utf-8"
            if candidate.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif candidate.suffix == ".js":
                content_type = "text/javascript; charset=utf-8"
            self._send_file(candidate, content_type)
            return
        self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802 - explicit read-only boundary
        self._send_json({"error": "read_only_console"}, HTTPStatus.METHOD_NOT_ALLOWED)

    do_PUT = do_POST
    do_DELETE = do_POST

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json({"error": "asset_not_found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(body, content_type)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.debug("console request: " + format, *args)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8502,
    project_root: Path = PROJECT_ROOT,
) -> ConsoleHTTPServer:
    """Create a local console server without starting its blocking loop."""
    return ConsoleHTTPServer((host, port), project_root)


def serve(host: str = "127.0.0.1", port: int = 8502, project_root: Path = PROJECT_ROOT) -> None:
    """Run the console until interrupted."""
    server = create_server(host, port, project_root)
    LOGGER.info("PolySignal Web Console listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


__all__ = ["ConsoleDataLoader", "ConsoleHTTPServer", "create_server", "serve"]
