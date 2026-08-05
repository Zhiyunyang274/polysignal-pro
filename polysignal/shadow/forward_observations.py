"""Forward observation models for shadow PnL evaluation.

Forward observations may come from offline trajectory files or from
read-only CLOB orderbook polling. They are research inputs for shadow PnL,
not trading instructions.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass
class ForwardObservation:
    shadow_trade_id: str
    market_id: str
    timestamp: str
    observed_price: float
    yes_token_id: str = ""
    no_token_id: str = ""
    yes_best_bid: float | None = None
    yes_best_ask: float | None = None
    no_best_bid: float | None = None
    no_best_ask: float | None = None
    yes_best_bid_size: float | None = None
    yes_best_ask_size: float | None = None
    no_best_bid_size: float | None = None
    no_best_ask_size: float | None = None
    yes_orderbook_timestamp: str = ""
    no_orderbook_timestamp: str = ""
    yes_price: float = 0.0
    no_price: float = 0.0
    combined_ask: float = 0.0
    spread: float = 0.0
    liquidity: float = 0.0
    source: str = ""
    stale: bool = False
    run_id: str = ""
    question: str = ""
    side: str = ""
    notes: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForwardObservation:
        payload = dict(data)
        payload["observed_price"] = _float(payload.get("observed_price"))
        payload["yes_best_bid"] = _optional_float(payload.get("yes_best_bid"))
        payload["yes_best_ask"] = _optional_float(payload.get("yes_best_ask"))
        payload["no_best_bid"] = _optional_float(payload.get("no_best_bid"))
        payload["no_best_ask"] = _optional_float(payload.get("no_best_ask"))
        payload["yes_best_bid_size"] = _optional_float(payload.get("yes_best_bid_size"))
        payload["yes_best_ask_size"] = _optional_float(payload.get("yes_best_ask_size"))
        payload["no_best_bid_size"] = _optional_float(payload.get("no_best_bid_size"))
        payload["no_best_ask_size"] = _optional_float(payload.get("no_best_ask_size"))
        payload["yes_price"] = _float(payload.get("yes_price"))
        payload["no_price"] = _float(payload.get("no_price"))
        payload["combined_ask"] = _float(payload.get("combined_ask"), payload["observed_price"])
        payload["spread"] = _float(payload.get("spread"))
        payload["liquidity"] = _float(payload.get("liquidity"))
        payload["stale"] = _bool(payload.get("stale"))
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in allowed})

    def to_exit_observation(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "combined_ask": self.combined_ask,
            "price": self.observed_price,
            "yes_best_bid": self.yes_best_bid,
            "yes_best_ask": self.yes_best_ask,
            "no_best_bid": self.no_best_bid,
            "no_best_ask": self.no_best_ask,
            "yes_best_bid_size": self.yes_best_bid_size,
            "yes_best_ask_size": self.yes_best_ask_size,
            "no_best_bid_size": self.no_best_bid_size,
            "no_best_ask_size": self.no_best_ask_size,
            "yes_orderbook_timestamp": self.yes_orderbook_timestamp,
            "no_orderbook_timestamp": self.no_orderbook_timestamp,
            "stale": self.stale,
            "market_closed": self.notes == "market_closed",
        }


@dataclass
class TokenIdResolution:
    market_id: str
    yes_token_id: str = ""
    no_token_id: str = ""
    source: str = ""
    error: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.yes_token_id and self.no_token_id)


class ShadowTokenIdResolver:
    """Resolve YES/NO token IDs without treating market_id as token_id."""

    FIELD_PAIRS = [
        ("yes_token_id", "no_token_id"),
        ("yes_token_address", "no_token_address"),
        ("yes_clob_token_id", "no_clob_token_id"),
        ("yes_asset_id", "no_asset_id"),
        ("yes_token", "no_token"),
    ]

    def __init__(self, runs_dir: Path, shadow_dir: Path):
        self.runs_dir = runs_dir
        self.shadow_dir = shadow_dir
        self._index: dict[str, TokenIdResolution] = {}
        self._loaded = False

    def resolve(self, market_id: str) -> TokenIdResolution:
        if not self._loaded:
            self._load_all()
        resolution = self._index.get(str(market_id))
        if resolution and resolution.complete:
            return resolution
        return TokenIdResolution(
            market_id=str(market_id),
            error="missing_token_id",
        )

    def _load_all(self) -> None:
        self._loaded = True
        sources = [
            self.shadow_dir / "shadow_trades.csv",
            self.shadow_dir / "shadow_positions.json",
            self.shadow_dir / "updated_shadow_trades.csv",
            self.shadow_dir / "updated_shadow_positions.json",
            self.shadow_dir / "shadow_trades_with_tokens.csv",
            self.runs_dir / "tradable_candidates_with_tokens.csv",
            self.runs_dir / "tradable_candidates.csv",
            self.runs_dir / "market_trajectories.json",
            self.runs_dir / "persistent_watchlist.csv",
            self.runs_dir / "alpha_candidates.csv",
            self.runs_dir / "avoid_candidates.csv",
        ]
        for path in sources:
            if path.suffix == ".csv":
                self._load_csv(path)
            elif path.suffix == ".json":
                self._load_json(path)

    def _store(self, market_id: Any, yes_token_id: Any, no_token_id: Any, source: str) -> None:
        market = str(market_id or "")
        yes = str(yes_token_id or "")
        no = str(no_token_id or "")
        if not market:
            return
        if not _valid_token_id(yes, market) or not _valid_token_id(no, market):
            return
        if market not in self._index:
            self._index[market] = TokenIdResolution(
                market_id=market,
                yes_token_id=yes,
                no_token_id=no,
                source=source,
            )

    def _load_csv(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    self._store_from_record(row, str(path))
        except OSError:
            return

    def _load_json(self, path: Path) -> None:
        if not path.exists() or path.stat().st_size == 0:
            return
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for record in _iter_dicts(data):
            self._store_from_record(record, str(path))

    def _store_from_record(self, record: dict[str, Any], source: str) -> None:
        market_id = record.get("market_id") or record.get("id") or record.get("condition_id")
        for yes_field, no_field in self.FIELD_PAIRS:
            if record.get(yes_field) or record.get(no_field):
                self._store(market_id, record.get(yes_field), record.get(no_field), source)
                return

        clob_token_ids = _coerce_list(record.get("clobTokenIds") or record.get("clob_token_ids"))
        outcomes = _coerce_list(record.get("outcomes"))
        if len(clob_token_ids) >= 2:
            yes_token_id, no_token_id = _token_pair_from_outcomes(clob_token_ids, outcomes)
            self._store(market_id, yes_token_id, no_token_id, source)


def _float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _valid_token_id(token_id: str, market_id: str) -> bool:
    token = str(token_id or "").strip()
    market = str(market_id or "").strip()
    return bool(token and token != market)


def _iter_dicts(data: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(data, dict):
        records.append(data)
        for value in data.values():
            records.extend(_iter_dicts(value))
    elif isinstance(data, list):
        for item in data:
            records.extend(_iter_dicts(item))
    return records


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _token_pair_from_outcomes(token_ids: list[Any], outcomes: list[Any]) -> tuple[str, str]:
    if outcomes and len(outcomes) == len(token_ids):
        yes_token_id = ""
        no_token_id = ""
        for token_id, outcome in zip(token_ids, outcomes):
            label = str(outcome).strip().lower()
            if label == "yes":
                yes_token_id = str(token_id)
            elif label == "no":
                no_token_id = str(token_id)
        if yes_token_id and no_token_id:
            return yes_token_id, no_token_id
    return str(token_ids[0]), str(token_ids[1])
