"""Shadow paper trading research engine.

Shadow trading is offline-only hypothetical execution analysis. It is not the
existing PaperTrader and must never enter the live execution path.
"""

from polysignal.shadow.edge_candidates import EdgeAction, EdgeCandidate, EdgeType
from polysignal.shadow.execution_cost import (
    ExecutionCost,
    ExecutionSide,
    FillStatus,
    L2Level,
    RoundTripCost,
    simulate_buy_notional,
    simulate_round_trip,
    simulate_sell_shares,
)
from polysignal.shadow.models import (
    CandidateSnapshot,
    ExitReason,
    ShadowSide,
    ShadowTrade,
    ShadowTradeStatus,
)
from polysignal.shadow.resolution_provenance import (
    RESOLUTION_SOURCE_ADAPTER_VERSION,
    ResolutionProvenance,
    resolution_integrity_reasons,
    resolve_resolution_provenance,
)

__all__ = [
    "CandidateSnapshot",
    "EdgeAction",
    "EdgeCandidate",
    "EdgeType",
    "ExecutionCost",
    "ExecutionSide",
    "ExitReason",
    "FillStatus",
    "L2Level",
    "RoundTripCost",
    "RESOLUTION_SOURCE_ADAPTER_VERSION",
    "ResolutionProvenance",
    "ShadowSide",
    "ShadowTrade",
    "ShadowTradeStatus",
    "simulate_buy_notional",
    "resolve_resolution_provenance",
    "resolution_integrity_reasons",
    "simulate_round_trip",
    "simulate_sell_shares",
]
