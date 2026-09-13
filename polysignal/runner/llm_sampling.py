"""
LLM sampling domain (Phase 5D.1).

Verbatim extraction from scripts/run_paper.py (Iteration 007). The mixin holds
the runner methods unchanged; PaperTradingRunner inherits them, so behaviour is
identical. RunConfig/stats/provider/logger state is accessed via `self`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from polysignal.models.market import Market
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.models.signal import ComponentScores, Signal
from polysignal.strategies.base import StrategyContext


class LLMSamplingMixin:
    """Runner methods for rate-limited LLM sampling (research logging only)."""

    if TYPE_CHECKING:
        from polysignal.runner.run_state import RunConfig, RunStatistics
        # Runner surface required by this mixin. Transitional: runner-owned
        # state beyond these will move into polysignal/runner with
        # RunConfig/RunStatistics in a later split step.
        _log_event: Any
        _ws_connected: Any
        data_provider: DataProviderManager
        event_engine: Any
        lifecycle_engine: Any
        microstructure_engine: Any
        run_config: RunConfig
        stats: RunStatistics
        strategy: YesNoMispricingStrategy
        wallet_engine: Any
        ws_cache_manager: OrderBookCacheManager
        ws_client: Any

        from polysignal.ingestion.data_provider_manager import DataProviderManager
        from polysignal.ingestion.orderbook_cache import OrderBookCacheManager
        from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy

    async def _run_llm_sampling(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> None:
        """
        Run LLM sampling for selected markets.

        This is research/intelligence logging only - NO TRADING.
        """
        # Select candidates
        candidates = self._select_llm_sampling_candidates(markets, orderbooks)

        if not candidates:
            self._log_event("llm_sampling_no_candidates", "llm_sampling", "No eligible candidates for LLM sampling")
            return

        self._log_event("llm_sampling_start", "llm_sampling", f"Starting LLM sampling for {len(candidates)} markets")

        for market, orderbook in candidates:
            # Check if this is a repeated sample
            is_repeated = market.market_id in self.stats.sampled_market_history

            # Perform LLM sampling
            result = await self._perform_llm_sampling(market, orderbook)

            # Update sampling history
            now = datetime.utcnow()
            if market.market_id not in self.stats.sampled_market_history:
                self.stats.sampled_market_history[market.market_id] = []
                self.stats.unique_sampled_markets += 1
            else:
                self.stats.repeated_sampled_markets += 1
            self.stats.sampled_market_history[market.market_id].append(now)

            # Track sampled markets
            self.stats.sampled_markets_count += 1
            if len(self.stats.sampled_markets_examples) < 5:
                self.stats.sampled_markets_examples.append({
                    "market_id": result["market_id"],
                    "question": result["question"][:100] if result["question"] else None,
                    "success": result["success"],
                    "event_score": result["event_score"],
                    "latency_seconds": result["latency_seconds"],
                    "repeated_market": is_repeated,
                    "market_sample_count": len(self.stats.sampled_market_history[market.market_id]),
                })

            # Log event with diversity fields
            self._log_event(
                "llm_sampling_assessment",
                "llm_sampling",
                f"LLM sampling for {market.market_id}: {'success' if result['success'] else 'failed'}",
                {
                    "market_id": result["market_id"],
                    "question": result["question"],
                    "combined_ask": result["combined_ask"],
                    "volume_24h": result["volume_24h"],
                    "success": result["success"],
                    "latency_seconds": result["latency_seconds"],
                    "event_score": result["event_score"],
                    "confidence": result["confidence"],
                    "suggested_mode": result["suggested_mode"],
                    "evidence_strength": result["evidence_strength"],
                    "market_relevance": result["market_relevance"],
                    "ambiguity_risk": result["ambiguity_risk"],
                    "risk_flags": result["risk_flags"],
                    "error": result["error"],
                    # Diversity fields
                    "sampling_strategy": self.run_config.llm_sampling_strategy,
                    "repeated_market": is_repeated,
                    "market_sample_count": len(self.stats.sampled_market_history[market.market_id]),
                    "cooldown_applied": False,  # Already filtered by cooldown in selection
                }
            )

    async def _get_orderbook(self, market: Market) -> OrderBookSnapshot | None:
        """Get orderbook for a market, with WebSocket cache and fallback logic"""

        # Try WebSocket cache first (if enabled and connected)
        if self.ws_client and self._ws_connected and self.ws_cache_manager:
            if market.yes_token_address and market.no_token_address:
                cached_orderbook = self.ws_cache_manager.get_market_orderbook(
                    market_id=market.market_id,
                    yes_token_id=market.yes_token_address,
                    no_token_id=market.no_token_address,
                )

                if cached_orderbook and not cached_orderbook.is_stale:
                    # Cache hit - use WebSocket data
                    self.stats.websocket_cache_hits += 1
                    self._log_event("websocket_cache_hit", "websocket", f"Cache hit for {market.market_id}")
                    return cached_orderbook
                elif cached_orderbook and cached_orderbook.is_stale:
                    # Cache stale - fallback to REST
                    self.stats.websocket_stale_fallbacks += 1
                    self._log_event("websocket_cache_stale", "websocket", f"Cache stale for {market.market_id}")
                else:
                    # Cache miss - fallback to REST
                    self.stats.websocket_cache_misses += 1

        # Fallback to REST API
        try:
            orderbook = await self.data_provider.get_orderbook(market.market_id)
            if orderbook:
                self.stats.rest_fallbacks += 1
            return orderbook
        except Exception as e:
            self._log_event("orderbook_error", "error", f"Orderbook fetch error for {market.market_id}: {e}")
            self.stats.api_errors += 1

            if self.run_config.data_mode == "hybrid":
                self.stats.api_fallbacks += 1

            return None

    async def _process_market(self, market: Market, orderbook: OrderBookSnapshot) -> Signal | None:
        """Process a market through the intelligence pipeline using YesNoMispricingStrategy"""
        # Ensure orderbook metrics are calculated
        orderbook.calculate_metrics()

        # Record combined_ask for distribution tracking
        if orderbook.combined_ask is not None:
            self.stats.combined_ask_observations.append(orderbook.combined_ask)

        # Run through Market Microstructure Engine for component scores
        micro_result = self.microstructure_engine.analyze_snapshot(orderbook)

        # Run through Resolution & Lifecycle Engine
        lifecycle_result = self.lifecycle_engine.assess(market)

        # Run through Wallet Intelligence Engine (mock for now)
        wallet_result = self.wallet_engine.assess(market, [])

        # Run through Event Intelligence Engine (mock LLM)
        event_result = await self.event_engine.assess_async(market)

        # Build component scores
        component_scores = ComponentScores(
            microstructure_score=micro_result.microstructure_score,
            liquidity_score=micro_result.liquidity_score,
            lifecycle_score=lifecycle_result.lifecycle_score,
            wallet_score=wallet_result.wallet_score,
            event_score=event_result.event_score,
        )

        # Create strategy context
        context = StrategyContext(
            market=market,
            orderbook=orderbook,
            component_scores=component_scores,
        )

        # Use YesNoMispricingStrategy to compute signal
        signal = self.strategy.compute_signal(context)

        return signal

    def _select_llm_sampling_candidates(
        self,
        markets: list[Market],
        orderbooks: dict[str, OrderBookSnapshot],
    ) -> list[tuple[Market, OrderBookSnapshot]]:
        """
        Select candidate markets for LLM sampling.

        Selection criteria:
        - Market status is OPEN
        - Not in forbidden category
        - Not ambiguous
        - Sufficient liquidity (volume >= llm_sampling_min_volume)
        - Orderbook available

        Strategy:
        - top_liquidity: Select markets with highest volume
        - top_liquidity_or_near_miss: Prefer markets close to mispricing threshold
        - random: Random selection from eligible markets
        - diversified: Prioritize unsampled markets, spread across categories

        Diversity features:
        - Cooldown: Markets sampled within cooldown period are skipped
        - Max repeats: Markets exceeding max_repeats_per_market are skipped
        - Fallback: If no candidates, allow random selection from all eligible

        Returns:
            List of (market, orderbook) tuples for LLM sampling
        """
        candidates = []
        now = datetime.utcnow()
        cooldown_delta = timedelta(minutes=self.run_config.llm_sampling_cooldown_minutes)

        for market in markets:
            # Check market eligibility
            # Note: For LLM sampling, we don't require is_auto_allowed() since we're not trading
            # We only check: OPEN status, not ambiguous, has orderbook
            # Use lowercase comparison since MarketStatus.OPEN.value == "open"
            status_ok = market.status == "open" or (hasattr(market.status, 'value') and market.status.value == "open")
            if not status_ok:
                continue
            if market.is_ambiguous:
                continue

            # Check volume (use total_volume_usd since volume_24h_usd is often not populated)
            volume = market.total_volume_usd or market.volume_24h_usd or 0
            if volume < self.run_config.llm_sampling_min_volume:
                continue

            # Get orderbook
            orderbook = orderbooks.get(market.market_id)
            if not orderbook:
                continue

            # Check cooldown and max repeats
            sample_history = self.stats.sampled_market_history.get(market.market_id, [])
            sample_count = len(sample_history)

            # Check if market exceeds max repeats
            if sample_count >= self.run_config.llm_sampling_max_repeats_per_market:
                continue

            # Check if market is in cooldown
            if sample_history:
                last_sample = sample_history[-1]
                if now - last_sample < cooldown_delta:
                    continue

            candidates.append((market, orderbook, volume))

        if not candidates:
            return []

        # Apply selection strategy
        if self.run_config.llm_sampling_strategy == "top_liquidity":
            # Sort by volume descending
            candidates.sort(key=lambda x: x[2], reverse=True)
            selected = candidates[:self.run_config.llm_sampling_per_scan]

        elif self.run_config.llm_sampling_strategy == "top_liquidity_or_near_miss":
            # Prefer markets close to mispricing threshold (combined_ask near 0.985)
            def near_miss_score(item):
                market, orderbook, volume = item
                if orderbook.combined_ask is None:
                    return (0, 0)  # No score, low priority
                # Score based on distance from 0.985 (mispricing threshold)
                # Closer to threshold = higher priority
                distance = abs(orderbook.combined_ask - 0.985)
                # Also consider volume for tie-breaking
                return (1.0 - distance, volume)

            candidates.sort(key=near_miss_score, reverse=True)
            selected = candidates[:self.run_config.llm_sampling_per_scan]

        elif self.run_config.llm_sampling_strategy == "diversified":
            # Prioritize unsampled markets, then by category spread
            def diversified_score(item):
                market, orderbook, volume = item
                # Check if never sampled
                sample_count = len(self.stats.sampled_market_history.get(market.market_id, []))
                never_sampled = sample_count == 0

                # Get category for spreading (use market.category if available)
                getattr(market, 'category', 'unknown') or 'unknown'

                # Score: never sampled first, then by volume
                return (never_sampled, volume)

            candidates.sort(key=diversified_score, reverse=True)
            selected = candidates[:self.run_config.llm_sampling_per_scan]

        else:  # random
            import random
            selected = random.sample(
                candidates,
                min(self.run_config.llm_sampling_per_scan, len(candidates))
            )

        return [(m, o) for m, o, _ in selected]

    async def _perform_llm_sampling(
        self,
        market: Market,
        orderbook: OrderBookSnapshot,
    ) -> dict[str, Any]:
        """
        Perform LLM sampling for a single market.

        This is research/intelligence logging only - NO TRADING.

        Returns:
            Sampling result dict with event analysis data
        """
        import time

        result: dict[str, Any] = {
            "market_id": market.market_id,
            "question": market.title,
            "combined_ask": orderbook.combined_ask,
            "volume_24h": market.volume_24h_usd,
            "success": False,
            "latency_seconds": None,
            "event_score": None,
            "confidence": None,
            "suggested_mode": None,
            "evidence_strength": None,
            "market_relevance": None,
            "ambiguity_risk": None,
            "risk_flags": [],
            "error": None,
        }

        # Check rate limit
        if self.stats.llm_calls_this_hour >= self.run_config.max_llm_calls_per_hour:
            result["error"] = "rate_limit_exceeded"
            result["risk_flags"] = ["llm_rate_limit_exceeded"]
            self.stats.llm_sampling_fallback_count += 1
            return result

        # Check LLM provider
        if self.run_config.llm_provider == "mock":
            result["error"] = "mock_provider_no_real_call"
            result["risk_flags"] = ["llm_mock_provider"]
            return result

        try:
            self.stats.llm_sampling_calls_attempted += 1
            self.stats.llm_calls_this_hour += 1

            start_time = time.time()

            # Call EventIntelligenceEngine for LLM assessment
            event_result = await self.event_engine.assess_async(market)

            latency = time.time() - start_time
            result["latency_seconds"] = latency
            self.stats.llm_latencies.append(latency)

            # Extract results
            result["event_score"] = event_result.event_score
            result["confidence"] = event_result.confidence
            result["suggested_mode"] = event_result.suggested_mode
            result["evidence_strength"] = event_result.evidence_strength
            result["market_relevance"] = event_result.market_relevance
            result["ambiguity_risk"] = event_result.ambiguity_risk
            result["risk_flags"] = list(event_result.risk_flags)

            # Check for forbidden trading fields in LLM output
            forbidden_fields = {"side", "size", "order", "position", "buy", "sell", "action"}
            if hasattr(event_result, "raw_response") and event_result.raw_response:
                raw = event_result.raw_response.lower() if isinstance(event_result.raw_response, str) else ""
                for field in forbidden_fields:
                    if field in raw:
                        result["risk_flags"].append("llm_forbidden_trading_instruction")

            # Track success/failure
            if event_result.confidence > 0:
                result["success"] = True
                self.stats.llm_sampling_calls_succeeded += 1
                self.stats.llm_successes += 1
            else:
                result["error"] = "low_confidence"
                self.stats.llm_sampling_calls_failed += 1
                self.stats.llm_failures += 1

        except TimeoutError:
            result["error"] = "timeout"
            result["risk_flags"] = ["llm_timeout"]
            self.stats.llm_sampling_timeout_count += 1
            self.stats.llm_sampling_calls_failed += 1
            self.stats.llm_failures += 1

        except json.JSONDecodeError as e:
            result["error"] = f"invalid_json: {str(e)[:50]}"
            result["risk_flags"] = ["llm_invalid_json"]
            self.stats.llm_sampling_invalid_json_count += 1
            self.stats.llm_sampling_calls_failed += 1
            self.stats.llm_failures += 1

        except Exception as e:
            error_str = str(e).lower()
            result["error"] = f"error: {str(e)[:100]}"
            result["risk_flags"] = ["llm_error"]
            self.stats.llm_sampling_calls_failed += 1
            self.stats.llm_failures += 1

            # Classify error type
            if "server error: 500" in error_str or "500" in error_str:
                self.stats.llm_sampling_server_error_count += 1
            elif "connection" in error_str or "connect" in error_str:
                self.stats.llm_sampling_connection_error_count += 1
            elif "rate limit" in error_str or "429" in error_str:
                self.stats.llm_sampling_rate_limit_count += 1

        return result

