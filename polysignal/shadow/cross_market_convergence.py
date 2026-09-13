"""Cross-market convergence observations for shadow-only edge gating."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass
class CrossMarketConvergenceObservation:
    """Read-only observation for deciding whether a cross-market price gap is converging."""

    timestamp: str
    group_id: str
    market_id: str
    reference_market_id: str
    question: str
    reference_question: str
    side: str
    entry_price: float
    reference_price: float
    price_gap: float
    spread: float
    depth: float
    liquidity: float
    relationship_confidence: float
    relationship_status: str
    observation_index: int
    stale: bool = False
    error: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrossMarketConvergenceObservation:
        payload = dict(data)
        for key in [
            "entry_price",
            "reference_price",
            "price_gap",
            "spread",
            "depth",
            "liquidity",
            "relationship_confidence",
        ]:
            payload[key] = _float(payload.get(key))
        payload["observation_index"] = int(_float(payload.get("observation_index")))
        payload["stale"] = _bool(payload.get("stale"))
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in allowed})


def _float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}
