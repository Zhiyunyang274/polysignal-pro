# CONTEXT.md — PolySignal Pro 当前项目压缩上下文

本文件是 PolySignal Pro 的当前项目状态摘要，用于降低 Claude Code / Agent Teams 的上下文负担。

每次新会话开始前，必须优先阅读：

1. CONTEXT.md
2. TASKS.md
3. CLAUDE.md
4. SPEC.md

---

## 1. 项目定位

PolySignal Pro 是一个 7×24h 运行的 Polymarket prediction market intelligence and paper trading research system。

它不是：

- 暴富脚本
- 稳赚机器人
- 无脑 copy trading bot
- LLM 自主交易系统

当前目标：

- read-only market monitoring
- signal generation
- Risk Governor evaluation
- paper trading
- SQLite logging
- CLI summary
- later optional Telegram alert

---

## 2. 当前里程碑状态

**Trading MVP Step 12 Active — Historical Barrier Integrated; Forward Cohort Maturing**

测试状态：

```text
uv run pytest -q
1873 passed in 267.62s (2026-09-12 full regression; exit code 0)
  = Step 12 v7 baseline 1755 + Iterations 001-020 (+118 tests)
    + Iteration 001 (22 AccountState) + 002 (36 SimBroker/metrics)
    + 003 (11 replay) + 004 (10 regime stress) + 005 (7 A/B) + 006 (15 risk guards)
Step 12 scoped tests: 238 passed
uv run ruff check .    -> All checks passed (1786 -> 0; accepted items declared)
uv run mypy polysignal -> Success: 0 errors in 93 files (no exemptions)
Requires-python: >=3.11 (ADR-026; bare python3 3.9 fails at import — always use uv run)
Iteration log: docs/iteration_log.md (Iterations 000-023 complete, in order)
  022b    A/B five-env precheck for crypto_price_threshold_v1 entry style:
           barrier-proximity KEEP_ELIGIBLE (all 5 rules pass; synthetic
           selectivity advantage, not a real-edge profitability claim)
  021      v7 cohort mature re-eval done (read-only poll 11/11, 0 errors);
           6 closed / 5 contract-rejected (stale forward book); 3 clusters < 5
           required -> expectancy still blocked; tiny_live=NO
  023-024  ADR-027 multi-source klines + ADR-028 asset universe expansion
           (+XRP/DOGE/BNB/LINK; parser $-anchored any-magnitude fix): v11 cohort
           8 positions / 5 clusters created; combined 6 independent clusters
           (>=5 expectancy precondition met for the first time); Phase B polls
           scheduled via automation (v10+v11 after 19:28 UTC maturity)
  022      v8 cohort expansion externally blocked: Binance HTTP 451 geo-block
           -> 0/46 historical barrier verified -> 0 positions created (contract
           held under external pressure); retry after access restoration
  026      crypto_price_threshold_v1 QUARANTINED (16 closed across 6 clusters,
           1 win / 6.2% / all-negative returns; gate: 5 hard-fail reasons)
  027      stale_price_lag reserved (0 near-barrier markets, untestable)
  029      ADR-030 market-making shift; MarketMaker + InventoryTracker built
           (15 tests); v12 pipeline running (discovery -> validate -> merge)
  030      MM five-regime stress: all invariants pass; high_vol = most fills
           (77) + highest spread capture ($4.06); liquidity_crisis = best
           balance (45/45) but adverse selection risk identified
  031      dynamic spread widening (vol_multiplier x volatility): mitigates
           adverse selection in crisis regimes; 19 tests / 1917 passed
  032      v12 discovery blocked by Binance 451 (1 candidate, 0 positions);
           merged expectancy final: 6 clusters / 17 closed / SAMPLE_INSUFFICIENT
           (need 3 more closed, but externally blocked by Binance geo-restriction)
  032      MM + AccountState 3-tier integration verified (market/strategy
           exposure + consecutive losses fire correctly in MM context)
  033      Real-time lag detection built (one-touch barrier probability model,
           edge in bps, significant observation filtering); 1932 passed
  023      ADR-027 multi-source klines (Binance primary + Coinbase fallback, user
           approved): v10 discovery 45/46 verified_full_coverage, cohort created
           (4 positions / 2 clusters, entry 13:14:00Z); Phase B poll scheduled
           17:25 UTC via automation
  024-025  ADR-028 asset expansion (+XRP/DOGE/BNB/LINK) + parser $-anchored fix:
           v11 cohort 8 positions / 5 clusters; Phase B done for v7+v10+v11 ->
           MERGED: 6 independent clusters (>=5 met) / 16 closed (15 losses, 1
           win, 6.2% win rate, merged PnL -2.25) -> verdict SAMPLE_INSUFFICIENT
           (<20 closed); all evidence negative -> v1 quarantine proposed
  (000-020 details below)
  001 AccountState ledger done (loss-limit breakers now live)
  002 SimBroker + performance metrics done (Phase 3 framework)
  003 real-data replay done; cross-validated with shadow PnL (-240.84 USDT / 10 trades)
  004 regime stress test done: 5 environments, all invariants PASS, breakers verified
  005 A/B framework done: 5-rule conservative verdict; demo REJECT via drawdown rule
  006 wired guards done: exposure caps are hard rejects (strategy-level cap new),
      liquidity guard is the single source for spread/depth gates
  007 run_paper.py split step 1 done: 3689 -> 2131 lines; watchlist/llm-sampling/
      control-group/alpha-repeat verbatim-moved to polysignal/runner/ (mixin +
      re-export, all existing imports unchanged)
  008 ruff batch 1 done: 510 zero-semantic fixes (F401/I001/UP017/UP015/F541/UP037);
      dashboard read-only open() modes kept explicit (security gate > lint)
  009 ruff batch 2 done: UP045 full PEP604 migration (547) + 74 linked imports;
      E501 accepted as declared style debt (pyproject) — actionable lint ~200 items
  010-012 done: RunConfig/RunStatistics -> runner/ (run_paper.py 3689->1724, -53%);
      F841 sweep found+fixed duplicate engine analysis in main.py; B904 explicit
      exception chaining 24->0
  013-014 done: UP042 behavior analysis — 5 enums migrated to StrEnum (custom
      __str__=value, behavior identical), 25 intentionally kept (declared in
      pyproject); F821 sweep caught 3 REAL bug classes: my own Iteration-012
      missing `as e` on timeout paths (NameError on first real timeout),
      dormant aiosqlite.Optional + missing LLMConfig import. All fixed.
  015-016  SIM115/B905/SIM102 judged; lint zero; database silent-failure removed
  017      full-repo mypy zero (event engine narrowing, shadow monkeypatch promoted,
           ws connection typed, provider router casts)
  018      models layer timezone-aware (D8 partial): utc_now/ensure_utc helpers,
           wallet chase chain + lifecycle ensure_utc normalization
  019      D12 resolved: CircuitBreaker consumes config & wired into main.py;
           llm Config single-source (provider re-exports llm_config);
           run_paper.py 1724->388 lines (PaperTradingRunner -> runner/)
  020      paper_runner typing debt cleared (mypy exemption removed); fixed
           orderbook.spread bug + report None-crash; db.require_connection()
Risk policy: docs/risk_policy.md §3.1 (Wired Guards); runner duty: feed real
  account state via AccountState.risk_context_fields
System review: docs/system_review_2026-09-11.md (R1-R8; D3/D4/D6-step1/D9/D10 resolved)
```

历史测试记录：

```text
Ruff lint/format, mypy, py_compile and uv lock checks passed
Trading MVP Step 10-12 tests: crypto threshold discovery and corrected shadow PnL
Trading MVP Step 6 targeted tests: tests/test_multi_edge_discovery.py, tests/test_shadow_trading.py, tests/test_shadow_performance_review.py updated
Phase 6 tests: tests/test_validate_strategy_signals.py (70 tests)
Phase 6.5A tests: tests/test_validation_loop.py (22 tests)
Phase 6.5B tests: tests/test_watchlist_monitoring.py and tests/test_validate_strategy_signals.py updated
Phase 7B tests: tests/test_run_validation_loop.py (13 tests)
Phase 7D tests: tests/test_generate_daily_report.py (14 tests)
Phase 8A/8B/8D/8E tests: tests/test_shadow_trading.py (45 tests)
Phase 8C/8D tests: tests/test_tradable_candidates.py (19 tests)
Phase 8F.1 tests: tests/test_shadow_forward_data.py (17 tests)
Phase 8F.2 tests: tests/test_shadow_forward_polling.py (16 tests)
Phase 8G.1/8G.2 tests: tests/test_shadow_token_backfill.py (24 tests)
Phase 8H tests: tests/test_shadow_performance_review.py (17 tests)
Phase 8I tests: tests/test_shadow_price_model_audit.py added; tests/test_shadow_trading.py updated
Phase 8J tests: tests/test_tradable_candidate_price_refresh.py added
```

最新验证状态：

```text
Phase 6.5A Control Group Sampling Patch: completed
Phase 6.5A.1 Category Inference Patch: completed
Phase 6.5A.5 Control Group Data Collection + Validation: completed
Phase 6.5B Alpha Repeated Observation Run implementation: completed
pytest tests/ -v: 1132 passed, 8 warnings
Phase 7 Plan: approved
Phase 7A Cloud Deployment Checklist: completed
Phase 7B Validation Loop Script: completed
Phase 7C systemd/tmux Running Plan: completed
Phase 7D Daily Report Automation: completed
Phase 8A Shadow Paper Trading Engine Core: completed
Phase 8B Shadow Entry Filter Calibration: completed
Phase 8C Tradable Candidate Pool Construction: completed
Phase 8D Tradable Candidate Shadow Entry Calibration: completed
Phase 8E Shadow Paper Performance Evaluation: completed
Phase 8F.1 Offline Forward Observation Collector: completed
Phase 8F.2 Read-only Forward Price Polling for Shadow PnL: completed
Phase 8G.1 Offline Token ID Backfill: completed
Phase 8G.2 Read-only Gamma Token ID Lookup: completed
Phase 8H Shadow Performance Review Gate: completed
Phase 8I Price Model & Entry Filter Calibration: completed
Phase 8J Corrected Entry Price Collection / Candidate Rebuild: completed
Trading MVP Gap Audit: completed
Trading MVP Step 1 Token Coverage + Side Bid/Ask Pricing Coverage: completed
Trading MVP Step 2 Expected Edge v1: completed
Trading MVP Step 3 Executable Edge Discovery Loop: completed
Trading MVP Step 4A Multi-Edge Discovery Framework v1: completed
Trading MVP Step 5 Corrected Shadow Trades from Multi-Edge Candidates + Forward PnL Validation: completed
Trading MVP Step 6 Probability Edge Calibration v2: completed
Trading MVP Step 7 Expected Edge Feedback Calibration: completed
Trading MVP Step 8 Probability Edge Quarantine / Feedback-Gated Shadow Entry: completed
Trading MVP Step 9A Cross-Market Consistency Edge v1: completed
Trading MVP Step 9B Cross-Market Relationship Confidence Calibration: completed
Trading MVP Step 9C Corrected Shadow PnL for High-Confidence Cross-Market Edge: completed
Trading MVP Step 9D Cross-Market Convergence Calibration / Repeated Observation Gate: completed
Trading MVP Step 9E Longer Cross-Market Convergence Dataset / Feature Calibration: completed
Trading MVP Step 9F Edge Pruning & New Edge Source Selection: completed
Trading MVP Step 10 Crypto Price Threshold Edge v1: completed
Trading MVP Step 11 Crypto Threshold Market Coverage Expansion: completed
Trading MVP Step 12 Crypto Threshold Corrected Shadow PnL implementation: completed
Trading MVP Step 12 discovery v5 + validator v7: complete
Trading MVP Step 12 historical barrier integration: complete
Trading MVP Step 12 formal v7 cohort: 11 positions / 3 clusters / 0 closed; not an edge proof
Trading MVP Step 12 expectancy: blocked on >=240-minute forward observations and >=5 independent clusters

Superseded Step 12 run `step12_20260804_122700`:
- v4 dry-run accepts 0/44 because resolution provenance, best-level sizes, and complete
  server-side timestamps were not present in the old artifact
- retained for audit only; never poll or supplement it

Previous fresh v4 coverage run `step12_v4_20260804_064741` (UTC, audit-only):
- Gamma markets scanned: 1958; parsed threshold markets: 44
- discovery candidates: 0 shadow_entry, 44 watch_only
- structured resolutionSource coverage: 0/44
- validator positions: 0; forward observations: 0; total_pnl: null
- validation status: entry_snapshot_refresh_required
- initial poller: positions_loaded=0, api_error_count=0, updated_positions=false
- tiny_live_recommendation: NO

Previous v5 cohort `step12_v5_20260804_073542` (UTC, audit-only):
- Gamma markets scanned / crypto detected / threshold parsed: 1958 / 56 / 44
- verified resolution provenance: 44/44; origin `resolution_rules_url`; adapter
  `resolution_source_adapter_v1`
- discovery: 16 shadow_entry / 28 watch_only
- v5 strict gate: 14; persisted positions after revalidation: 10 across 3 clusters
- initial public CLOB poll: 10 observations, 0 API errors, 0 stale; updated_positions=false
- revalidation: all 10 observations before 240 minutes; closed=0; total_pnl=null
- validation status: insufficient_forward_data
- live/auto/paper/default LLM: false / false / true / mock
- tiny_live_recommendation: NO

Previous v6 read-only validation `step12_v6_20260804_083736` (UTC, audit-only):
- Gamma markets scanned / crypto detected / threshold parsed: 1958 / 56 / 44
- source provenance / expiry provenance verified: 44/44 / 44/44
- canonical expiry: `2027-01-01T04:59:00Z` from title-local `2026-12-31 23:59 ET`
- discovery: 0 `shadow_entry` / 44 `watch_only`; all 44 lack historical barrier coverage
- validator schema: `crypto_threshold_shadow_pnl_v6`; strict gate=0; positions=0; PnL=null
- validation status: `historical_barrier_evidence_required`; tiny_live_recommendation=`NO`
- one Gamma terminal-page 422 was recorded; scan coverage is not claimed exhaustive

Formal v7 cohort `step12_v7_20260804_140305` (UTC, current research cohort):
- discovery schema: `crypto_threshold_edge_discovery_v5`; validator schema:
  `crypto_threshold_shadow_pnl_v7`
- Gamma markets scanned / crypto detected / threshold candidates: 1958 / 56 / 44
- exact-minute batch entry: `2026-08-04T14:04:00Z`; all accepted spot/client/CLOB server
  timestamps precede entry and are no more than 60 seconds old
- historical evidence sharing: 3 preloads + 3 entry tails + 3 per-asset shared candle
  snapshots + 43 threshold-specific manifests
- historical barrier coverage: 43/44 verified; the candidate without a rules-defined start
  remains fail-closed and did not trigger a historical request
- public CLOB orderbooks: 85/88 loaded; 3 incomplete reads remained fail-closed
- discovery: 12 `shadow_entry` / 32 `watch_only`
- validator: 11 fresh paper positions (BTC 3 / ETH 5 / SOL 3) across 3 correlated clusters
- closed positions: 0; `insufficient_forward_data`: 11; forward coverage: 0.0
- total PnL: null; win rate: null; status: `insufficient_forward_data`
- `supports_tiny_live=false`; `tiny_live_recommendation=NO`
- Gamma pagination ended with one recorded recoverable terminal-page error, so the scan is not
  claimed exhaustive
- do not poll this cohort before it reaches the 240-minute forward horizon; after that point,
  collect only observations that pass every v7 forward-book, timestamp, identity, and size gate

All v6 and earlier Step 12 runs are audit-only: do not migrate, supplement, reuse, or continue
polling them. The formal v7 cohort has only 3 independent clusters; no edge, expectancy, or
profitability conclusion is supported.

Adapter v1 only accepts a structured source or one HTTPS URL in an explicit resolution-source
section, on an exact trusted host. Binance additionally requires matching asset, USDT pair,
one-minute candle and High/Low barrier semantics. Non-string fields, HTTP, multiple URLs,
untrusted hosts, source conflicts, or any locator/digest/rules-hash mismatch fail closed. The
adapter version, rules hash and provenance digest are bound into the stable trade ID.

Historical barrier integration is complete. Discovery now shares one preload, one entry tail and
one content-addressed candle snapshot per asset while retaining an independent evidence manifest
for each threshold. Gamma `startDate` remains lifecycle metadata and cannot replace the
rules-defined barrier start; a missing rules start fails closed without a historical request.

The current blocker is forward maturity and sample independence: accepted observations must be at
least 240 minutes after entry, and any expectancy assessment requires at least 5 independent
clusters. The formal v7 cohort currently has only 3 clusters, 0 closed positions and null PnL/win
rate, so it cannot support an edge or profitability claim. Historical barrier integration is
complete; do not reopen that gate or substitute Gamma `startDate` for a missing rules-defined start.

Superseded Step 12 run `step12_20260804_114000`:
- run-start time was incorrectly recorded before spot/orderbook evidence
- validator v3 rejects all 44 candidates
- retained for audit only; not a valid forward cohort

Execution safety iteration:
- L2 shadow cost estimator performs deterministic visible-depth sweep and same-share round trips.
- PaperTrader rejects stale/mismatched inputs and `SignalSide.BOTH` fail-closed.
- `live_trading_enabled=false`, `allow_auto_execution=false`, `paper_trading_enabled=true`.

run_id: run_20260510_105908_73831203
control_group_samples.csv generated
control_group_samples: 36 rows
unique_control_group_markets: 36
control_group_assessment events: 36
control group excludes avoid / alpha / watchlist
control_group_samples loaded by offline validation: 42
```

Trading MVP Step 8 target:

```text
price_dislocation_probability_v1/v2 are quarantined to watch_only unless feedback gates pass
feedback gate source: runs/edge_feedback_calibration_summary.json
current probability edge evidence:
  expected_edge_realized_return_correlation: -0.1784870086432687
  confidence_win_correlation: -0.009224758324091477
  false_positive_count: 9/10
  high_confidence_loss_count: 9/10
Step 8 result:
  price_dislocation_probability_v1 gate status: watch_only
  price_dislocation_probability_v2 gate status: quarantined
  multi_edge_candidates_gated.csv generated
  shadow dry_run v2: eligible_shadow_entry=0, watch_only=25, rejected=0
  diagnostics include edge_type_quarantined / feedback_gate_failed
combined_ask_arbitrage remains available as a separate direct microstructure edge
Step 9A result:
  added cross_market_consistency_v1 as a non-probability edge source
  added scripts/discover_cross_market_edges.py
  discovered same_event_duplicate / near_duplicate and simple mutually_exclusive groups
  output read-only / shadow-only cross_market_edge candidates
  probability edge remains quarantined
  pytest tests/ -v: 1375 passed, 8 warnings
  dry_run --max_markets 100:
    markets_scanned: 82
    groups_detected: 0
    candidates_generated: 0
  read-only discovery --max_markets 1000 --min_volume 1000:
    markets_scanned: 989
    groups_detected: 29
    duplicate_groups_detected: 24
    mutually_exclusive_groups_detected: 5
    orderbooks_fetched: 282
    candidates_generated: 95
    watch_only_candidates: 95
    shadow_entry_candidates: 0
    avg_price_gap: 0.5061052631578947
    max_price_gap: 0.885
    api_error_count: 0
  shadow dry_run after cross-market discovery:
    candidates_loaded: 23
    eligible_shadow_entry: 0
    watch_only: 23
    rejected: 0
    edge_type_distribution: cross_market_consistency_v1=23
Step 9B result:
  added scripts/calibrate_cross_market_relationships.py
  calibrated cross_market_consistency_v1 relationship confidence offline
  price_gap alone remains not a trading signal
  outputs:
    runs/cross_market_relationship_calibration_summary.json
    runs/cross_market_relationship_calibration_report.md
    runs/cross_market_edge_candidates_calibrated.csv
    runs/cross_market_edge_candidates_calibrated.json
  pytest tests/ -v: 1390 passed, 8 warnings
  dry_run / full calibration:
    candidates_loaded: 95
    groups_loaded: 14
    high_confidence_duplicate_count: 16
    medium_confidence_related_count: 0
    ambiguous_relationship_count: 4
    likely_false_match_count: 3
    mutually_exclusive_watch_count: 72
    shadow_entry_eligible_count: 16
    watch_only_count: 76
    rejected_count: 3
    avg_relationship_confidence: 0.787885249230512
  shadow dry_run after calibrated candidates:
    candidates_loaded: 25
    eligible_shadow_entry: 10
    watch_only: 15
    rejected: 0
    top_watch_reasons: mutually_exclusive_watch=15
    edge_type_distribution: cross_market_consistency_v1=25
Step 9C result:
  generated corrected shadow trades from high-confidence duplicate cross_market_consistency_v1 candidates
  max_shadow_entries: 10
  entry price model: side-specific ask only; combined_ask not used as entry
  read-only forward polling:
    positions_loaded: 10
    positions_polled: 10
    observations_written: 10
    missing_token_id_count: 0
    api_error_count: 0
    stale_observation_count: 0
  corrected shadow PnL:
    shadow_trades: 10
    closed_positions: 10
    open_positions: 0
    insufficient_forward_data_positions: 0
    total_pnl: -2.408470695970695
    win_rate: 0.0
    average_return: -0.24084706959706959
    median_return: -0.225
    max_drawdown: -2.408470695970695
  edge_type_performance:
    cross_market_consistency_v1:
      trades: 10
      average_return: -0.24084706959706959
      total_return: -2.408470695970695
      win_rate: 0.0
  relationship_status_performance:
    high_confidence_duplicate:
      trades: 10
      average_return: -0.24084706959706959
      total_return: -2.408470695970695
      win_rate: 0.0
  review conclusion:
    cross_market_consistency_v1 has not proven positive expectancy
    primary_loss_driver: expected_edge_too_optimistic=10
    price_gap_not_converging=10
Step 9D result:
  added CrossMarketConvergenceObservation model
  added scripts/monitor_cross_market_convergence.py
  cross-market price_gap alone no longer permits executable shadow entry
  convergence-gated candidates are preferred by run_shadow_paper_loop.py
  pytest tests/ -v: 1405 passed, 8 warnings
  dry_run:
    candidates_monitored: 16
    observations_collected: 0
    groups_monitored: 6
    convergence_pass_count: 0
    convergence_fail_count: 0
    insufficient_observation_count: 16
    shadow_entry_eligible_count: 0
    watch_only_count: 16
  short read-only convergence monitor:
    candidates_monitored: 16
    observations_collected: 96
    groups_monitored: 6
    convergence_pass_count: 0
    convergence_fail_count: 16
    insufficient_observation_count: 0
    avg_initial_gap: 0.667125
    avg_final_gap: 0.667125
    avg_gap_change: -6.938893903907228e-18
    shadow_entry_eligible_count: 0
    watch_only_count: 16
    rejected_count: 0
  shadow dry_run after convergence gate:
    candidates_loaded: 16
    eligible_shadow_entry: 0
    watch_only: 16
    rejected: 0
    top_watch_reasons: price_gap_not_converging=32
    edge_type_distribution: cross_market_consistency_v1=16
  artifacts:
    runs/cross_market_convergence_observations.jsonl
    runs/cross_market_convergence_summary.json
    runs/cross_market_convergence_report.md
    runs/cross_market_edge_candidates_convergence_gated.csv
    runs/cross_market_edge_candidates_convergence_gated.json
  conclusion:
    non-converging cross-market candidates do not enter shadow entry
    tiny_live_recommendation=NO
Step 9E result:
  monitor_cross_market_convergence.py now supports append/resume/run_id for longer read-only datasets
  added scripts/analyze_cross_market_convergence_dataset.py
  added tests/test_cross_market_convergence_dataset.py
  pytest tests/ -v: 1419 passed, 8 warnings
  monitor dry_run:
    candidates_monitored: 16
    observations_collected: 0
    groups_monitored: 6
    convergence_pass_count: 0
    insufficient_observation_count: 16
    shadow_entry_eligible_count: 0
    watch_only_count: 16
  longer read-only observation:
    duration_minutes: 30
    interval_seconds: 120
    resume_enabled: true
    existing_observations_loaded: 96
    new_observations_collected: 256
    total observations in monitor summary: 352
    candidates_monitored: 16
    convergence_pass_count: 0
    convergence_fail_count: 16
    avg_initial_gap: 0.667125
    avg_final_gap: 0.6654375
    avg_gap_change: -0.0016874999999999217
    shadow_entry_eligible_count: 0
    watch_only_count: 16
  convergence dataset analysis:
    total_observations: 352
    groups_analyzed: 6
    pairs_analyzed: 16
    converging_pairs_count: 0
    non_converging_pairs_count: 13
    widening_pairs_count: 3
    stable_pairs_count: 1
    avg_gap_change: -0.0016874999999999217
    avg_gap_volatility: 0.002452169763537771
    best_convergence_score: 0.020979020979020845
    candidates_recommended_for_future_shadow: 0
  artifacts:
    runs/cross_market_convergence_features.csv
    runs/cross_market_convergence_dataset_summary.json
    runs/cross_market_convergence_dataset_report.md
  conclusion:
    longer observation still found no usable convergence pattern
    no shadow trades generated
    tiny_live_recommendation=NO
Step 9F result:
  added scripts/audit_edge_strategy_status.py
  added tests/test_edge_strategy_status_audit.py
  generated edge strategy registry/status report
  pytest tests/ -v: 1428 passed, 8 warnings
  edge_types_reviewed: 5
  enabled_edges:
    - combined_ask_arbitrage
  quarantined_edges:
    - price_dislocation_probability_v1
    - price_dislocation_probability_v2
  research_only_edges:
    - cross_market_consistency_v1
    - cross_market_convergence
  watch_only_edges: []
  discontinued_edges: []
  any_edge_supports_tiny_live: false
  tiny_live_recommendation: NO
  recommended_next_edge_source: Crypto Price Threshold Edge
  recommended_step_10: Trading MVP Step 10 — Crypto Price Threshold Edge v1
  outputs:
    runs/edge_strategy_status_report.md
    runs/edge_strategy_status_summary.json
    runs/edge_strategy_registry.csv
  conclusion:
    no tested edge currently supports tiny live
    do not loosen failed microstructure/probability/cross-market gates
    Step 10 should focus on objective external crypto threshold markets
Step 10 result:
  added scripts/discover_crypto_threshold_edges.py
  added tests/test_crypto_threshold_edge_discovery.py
  updated scripts/run_shadow_paper_loop.py to read crypto_threshold_edge_candidates.csv
  pytest tests/ -v: 1442 passed, 8 warnings
  dry_run:
    markets_scanned: 100
    crypto_markets_detected: 1
    parsed_threshold_markets: 1
    candidates_generated: 0
  read-only discovery:
    markets_scanned: 100
    crypto_markets_detected: 1
    parsed_threshold_markets: 1
    spot_prices_loaded: 1
    orderbooks_fetched: 0
    candidates_generated: 0
    shadow_entry_candidates: 0
    avoid_candidate_count: 1
  artifacts:
    runs/crypto_threshold_edge_candidates.csv
    runs/crypto_threshold_edge_candidates.json
    runs/crypto_threshold_edge_discovery_summary.json
    runs/crypto_threshold_edge_discovery_report.md
  shadow dry_run crypto_price_threshold_v1:
    eligible_shadow_entry: 0
    watch_only: 0
    rejected: 0
  conclusion:
    crypto threshold discovery pipeline is implemented and read-only
    current scanned parsed BTC threshold market was an avoid candidate
    no shadow trades generated
    tiny_live_recommendation=NO
Step 11 result:
  expanded scripts/discover_crypto_threshold_edges.py with pagination, keyword search, parser expansion, market_id deduplication, and avoid-aware diagnostics
  updated tests/test_crypto_threshold_edge_discovery.py
  pytest tests/ -v: 1451 passed, 8 warnings
  dry_run:
    markets_scanned: 493
    crypto_markets_detected: 3
    parsed_threshold_markets: 3
  expanded read-only discovery:
    markets_scanned: 3000
    crypto_markets_detected: 49
    parsed_threshold_markets: 46
    spot_prices_loaded: 3
    orderbooks_fetched: 90
    excluded_avoid_candidates: 1
    excluded_parse_low_confidence: 3
    excluded_missing_token: 0
    excluded_missing_spot: 0
    excluded_missing_orderbook: 0
    eligible_after_avoid_filter: 45
    candidates_generated: 45
    shadow_entry_candidates: 29
    watch_only_candidates: 16
    rejected_candidates: 0
    asset_distribution:
      BTC: 17
      ETH: 14
      SOL: 14
  artifacts:
    runs/crypto_threshold_market_diagnostics.csv
    runs/crypto_threshold_edge_candidates.csv
    runs/crypto_threshold_edge_candidates.json
    runs/crypto_threshold_edge_discovery_summary.json
    runs/crypto_threshold_edge_discovery_report.md
  conclusion:
    coverage blocker is resolved enough to create candidate samples
    no shadow trades generated in Step 11
    next step should be crypto threshold shadow PnL validation, still shadow-only
    tiny_live_recommendation=NO
    exit_bid_weakness=10
    tiny_live_recommendation=NO
tiny_live_recommendation: NO
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
```

Trading MVP current blocker before Step 4A:

```text
token coverage: 34/34
side bid/ask pricing: 34/34
expected_edge_available_count: 0
executable_edge_positive_count: 0
eligible_shadow_entry: 0
watch_only: 34
rejected: 0
main reasons: combined_ask_not_below_one=34, control_group_only_watch=34
tiny_live_recommendation: NO
```

Trading MVP Step 4A result:

```text
Implemented unified EdgeCandidate model
Implemented scripts/discover_multi_edge_candidates.py
Implemented edge types v1:
  - combined_ask_arbitrage
  - price_dislocation_probability_v1
Reserved only:
  - stale_price_lag
  - closing_market_convergence
  - cross_market_consistency
  - spread_capture_passive
Output multi_edge_candidates for shadow-only evaluation
python3 -m pytest tests/ -v: 1328 passed, 8 warnings
discover_multi_edge_candidates.py --dry_run --max_markets 100:
  markets_scanned: 100
  active_markets_available: 100
  shadow_entry_candidates: 0
discover_multi_edge_candidates.py --max_markets 500 --min_volume 1000:
  markets_scanned: 493
  orderbooks_fetched: 948
  edge_type_counts:
    combined_ask_arbitrage: 474
    price_dislocation_probability_v1: 948
  combined_ask_arbitrage_count: 474
  probability_edge_count: 948
  shadow_entry_candidates: 125
  watch_only_candidates: 1145
  rejected_candidates: 152
  avg_expected_edge: -0.00886427566807314
  max_expected_edge: 0.049999999999999996
  avg_confidence: 0.9653955696202532
  api_error_count: 0
shadow dry_run after multi-edge discovery:
  candidates_loaded: 125
  eligible_shadow_entry: 125
  watch_only: 0
  rejected: 0
tiny_live_recommendation: NO
```

Trading MVP Step 5 result:

```text
Corrected shadow trades generated from multi_edge_candidates.csv: 25
edge_type: price_dislocation_probability_v1
forward polling:
  positions_loaded: 25
  positions_polled: 25
  observations_written: 24
  missing_token_id_count: 0
  api_error_count: 0
  stale_observation_count: 1
performance:
  closed_positions: 24
  insufficient_forward_data_positions: 1
  total_pnl: -6.9267167607752755
  win_rate: 0.041666666666666664
  average_return: -0.2886131983656365
  max_drawdown: -6.9267167607752755
review primary loss drivers:
  probability_model_bias: 23
  exit_bid_weakness: 23
  confidence_overestimated: 23
tiny_live_recommendation: NO
```

Trading MVP Step 6 result:

```text
Added price_dislocation_probability_v2 as a conservative baseline alongside v1.
V2 adds calibrated probability fields, exit bid penalty, adverse selection penalty,
liquidity penalty, and stricter confidence gating.
python3 -m pytest tests/ -v: 1341 passed, 8 warnings
discover_multi_edge_candidates.py --max_markets 500 --min_volume 1000 --edge_version v2 --output_suffix _v2:
  markets_scanned: 493
  orderbooks_fetched: 942
  v2_shadow_entry_candidates: 20
  v2_watch_only_candidates: 620
  v2_rejected_candidates: 308
  avg_raw_expected_edge: -0.004280590717299581
  avg_calibrated_expected_edge: -0.03299360178429739
  avg_confidence: 0.8178872918424754
  exit_bid_penalty_avg: 0.00943597046413502
  adverse_selection_penalty_avg: 0.01392162552742616
  liquidity_penalty_avg: 0.00012658227848101267
top 10 v2 corrected shadow PnL:
  closed_positions: 10
  total_pnl: -2.469158035079444
  win_rate: 0.1
  average_return: -0.2469158035079444
  max_drawdown: -2.469158035079444
  primary_loss_drivers: expected_edge_too_optimistic=9
v1 remains baseline; v2 does not use alpha_score, tradable_score, LLM, live execution,
PaperTrader, LiveTrader, or Risk Governor live execution path.
tiny_live_recommendation: NO
```

Trading MVP Step 7 result:

```text
Added scripts/calibrate_edge_from_shadow_feedback.py
Added tests/test_edge_feedback_calibration.py
python3 -m pytest tests/ -v: 1351 passed, 8 warnings
edge_feedback_calibration:
  trades_analyzed: 10
  edge_types_analyzed: price_dislocation_probability_v2
  overall_win_rate: 0.1
  overall_average_return: -0.2469158035079444
  expected_edge_realized_return_correlation: -0.1784870086432687
  confidence_win_correlation: -0.009224758324091477
  false_positive_count: 9
  high_confidence_loss_count: 9
  top_loss_patterns:
    expected_edge_false_positive: 9
    high_confidence_loss: 9
    exit_bid_weakness: 9
    exit_bid_penalty_underestimated: 9
    microstructure_probability_loss: 9
recommended_v3_filters include:
  quarantine_probability_edge_executable_to_watch_only_until_edge_correlation_is_positive
  redesign_confidence_model_do_not_use_current_confidence_as_execution_gate
  increase_exit_bid_penalty_and_require_stronger_exit_bid_support
  keep_microstructure_probability_edges_watch_only_until_positive_shadow_pnl
tiny_live_recommendation: NO
```

Trading MVP Step 3 target:

```text
Scan active Gamma markets
→ extract YES/NO CLOB token ids
→ fetch public read-only CLOB orderbooks
→ compute yes/no bid/ask, combined_ask, combined_ask_gap, executable_edge
→ apply spread / depth / liquidity gates
→ write executable_edge_candidates for shadow-only evaluation
```

Trading MVP Step 3 result:

```text
python3 -m pytest tests/ -v: 1310 passed, 8 warnings
discover_executable_edges.py --dry_run --max_markets 100:
  markets_scanned: 100
  active_markets_available: 100
  edge_candidates_count: 0
discover_executable_edges.py --max_markets 500 --min_volume 1000:
  markets_scanned: 493
  markets_with_token_ids: 474
  orderbooks_fetched: 948
  combined_ask_below_one_count: 0
  executable_edge_positive_count: 0
  edge_candidates_count: 0
  api_error_count: 0
  avoid_candidate_count: 19
shadow dry_run after discovery:
  candidates_loaded: 0
  eligible_shadow_entry: 0
  watch_only: 0
  rejected: 0
tiny_live_recommendation: NO
```

真实 API 验证状态：

| Phase | 描述 | 状态 |
|-------|------|------|
| Phase 4A | Gamma REST + CLOB REST | ✅ Verified |
| Phase 4A.5 | REST Smoke Test | ✅ Passed |
| Phase 4B | CLOB WebSocket | ✅ Verified |
| Phase 4B.5 | WebSocket Smoke Test | ✅ Passed |
| Phase 4C | Real LLM Providers Integration | ✅ Completed |
| Phase 4C.5 | LLM Smoke Test | ✅ Passed |
| Phase 4C Audit | LLM Provider Audit | ✅ Completed |
| Phase 5A | 30-Minute Dry Run | ✅ Completed |
| Phase 5B | WebSocket Subscription Integration | ✅ Completed |
| Phase 5B.6 | Runner Signal Path Hardening | ✅ Completed |
| Phase 5C | 10-Hour Real Readonly Run | ✅ Completed |
| Phase 5D.1 | LLM Sampling Mode | ✅ Completed |
| Phase 5D.2 | 4-Hour LLM Sampling Run | ✅ Completed |
| Phase 5D.3 | Audit & Metrics Fix | ✅ Completed |
| Phase 5E | Market Intelligence Report | ✅ Completed |
| Phase 5F | Multi-Run Intelligence Comparison | ✅ Completed |
| Phase 5F.5 | Watchlist-Driven Monitoring | ✅ Completed |

Real LLM Smoke Test 结果 (2026-05-08):

| Provider | Event Analysis | Rule Analysis | Recommendation |
|----------|---------------|---------------|----------------|
| XFyun Anthropic | ✅ Passed (26s) | ✅ Passed (17s) | **Recommended** |
| SenseNova | ✅ Passed (39s) | ❌ Timeout | Not for rule |

当前已跑通闭环：

```text
mock market / real API market
→ mock orderbook / real API orderbook / WebSocket orderbook
→ Market Microstructure Engine
→ Resolution & Lifecycle Engine (lifecycle_score)
→ Wallet Intelligence Engine (wallet_score)
→ Event Intelligence Engine (event_score) + Real LLM (XFyun Anthropic)
→ YES/NO mispricing signal
→ Risk Governor (含 lifecycle + wallet + event hard rejection)
→ Paper Trader (auto paper trade)
→ Telegram Signal Cockpit (monitoring/control)
→ SQLite log
→ CLI summary
→ Paper Trading Runner (Phase 5A)
→ tests
```

Phase 5A 新增：

```text
scripts/run_paper.py — Paper trading runner
RunConfig — Conservative defaults
RunStatistics — Run statistics tracking
Safety checks — Config assertions
Rate limiting — Hourly limits
Report generation — JSON + Markdown
```

Phase 5D.1 新增：

```text
LLM Sampling Mode — Research/intelligence logging only, no trading
--enable_llm_sampling — Enable LLM sampling
--llm_sampling_per_scan — Markets to sample per scan
--llm_sampling_min_volume — Minimum volume for candidates
--llm_sampling_strategy — Selection strategy (top_liquidity, top_liquidity_or_near_miss, random)
_select_llm_sampling_candidates() — Candidate selection
_perform_llm_sampling() — LLM call execution
_run_llm_sampling() — Sampling orchestration
events.jsonl — llm_sampling_assessment events
tests/test_llm_sampling_mode.py — 27 new tests
```

Phase 5E 新增：

```text
scripts/analyze_run_intelligence.py — Market Intelligence Analyzer
classify_near_miss_tier() — Near-miss tier classification (Tier 1-4)
infer_market_category() — Heuristic market category inference
IntelligenceAnalyzer — Offline run data analysis
generate_markdown_report() — intelligence_report.md generation
export_csv() — sampled_markets.csv export
tests/test_analyze_run_intelligence.py — 40 new tests
intelligence_report.md — Human-readable intelligence report
intelligence_summary.json — Machine-readable summary
sampled_markets.csv — CSV export for analysis
```

Phase 5F 新增：

```text
scripts/compare_run_intelligence.py — Multi-Run Intelligence Comparison Analyzer
RunDiscovery — Run discovery and filtering (--latest_n, --since, --run_ids)
RunDataLoader — Load intelligence_summary.json, summary.json, events.jsonl
MarketAggregator — Aggregate markets across runs with market_id/normalized_question fallback
PersistentWatchlistGenerator — Generate persistent watchlist with evidence_level
AlphaCandidateScorer — Alpha scoring with DISCLAIMER (heuristic research ranking, NOT trading signal)
AvoidCandidateScorer — Avoid scoring with category_risk (NOT hard_forbidden)
CategoryAnalyzer — Category-level statistics
ComparisonReportGenerator — Generate comparison reports and CSV exports
calculate_evidence_level() — Evidence level classification (weak/moderate/strong)
tests/test_compare_run_intelligence.py — 56 new tests
intelligence_comparison_report.md — Multi-run comparison report
intelligence_comparison_summary.json — Comparison summary JSON
persistent_watchlist.csv — Persistent watchlist CSV
alpha_candidates.csv — Alpha candidates CSV
avoid_candidates.csv — Avoid candidates CSV
market_trajectories.json — Market trajectory data
```

SQLite tables — paper_runs, paper_run_scans, paper_run_events
tests/test_paper_run.py — Comprehensive tests
docs/phase_5_dry_run.md — Documentation
```

数据模式支持：
- mock: 模拟数据
- real_readonly: 真实只读 API (REST + WebSocket)
- hybrid: 优先真实 API，失败降级到 mock

真实数据层能力：
- Gamma REST API: 市场发现
- CLOB REST API: Orderbook 数据
- CLOB WebSocket: 实时 orderbook 更新
- XFyun Anthropic LLM: Event + Rule analysis (推荐)
- SenseNova LLM: Event analysis only (高延迟)

WebSocket 协议发现：
- URL: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- 订阅字段: `assets_ids`（复数，不是 `asset_ids`）
- 返回格式: 数组，每个元素直接包含 orderbook 数据
- 消息没有 `type` 字段

下一步建议：Phase 8G — Token ID Backfill / Shadow Position Rebuild Gate

---

## 2.1 Phase 5F.5 新增功能

Phase 5F.5 — Watchlist-Driven Monitoring 新增：

```text
scripts/run_paper.py 新增参数:
  --watchlist_file          — persistent_watchlist.csv 路径
  --alpha_candidates_file   — alpha_candidates.csv 路径
  --avoid_candidates_file   — avoid_candidates.csv 路径
  --trajectories_file       — market_trajectories.json 路径
  --monitor_mode            — default/hybrid/watchlist
  --watchlist_priority_ratio — watchlist 市场占比
  --discovery_ratio         — 新市场探索占比
  --track_trajectory        — 轨迹跟踪开关

新增类 (scripts/run_paper.py):
  WatchlistLoader           — 加载 watchlist 文件
  MarketPrioritizer         — 市场优先级排序
  AvoidAnnotator            — Avoid 风险标注 (仅研究用途)
  TrajectoryTracker         — 轨迹跟踪
  WatchlistMonitoringStats  — 统计数据

输出文件 (当前 run 目录):
  watchlist_monitoring_summary.json  — 监控统计
  watchlist_monitoring_report.md     — 监控报告
  watchlist_trajectory_update.json   — 轨迹更新
  watchlist_events.jsonl             — 监控事件日志

重要约束:
  - Watchlist 只影响扫描顺序，不影响交易决策
  - Avoid annotation 仅做研究标注，不是 hard forbidden
  - 不修改 Risk Governor
  - 不修改 Signal 模型
  - 不修改策略
```

---

## 2.2 Phase 5G.1 新增功能

Phase 5G.1 — Dashboard MVP 新增：

```text
polysignal/interface/dashboard.py — Streamlit Dashboard (READ-ONLY)
  DashboardDataLoader — 从 runs/ 加载数据
  RunSummary — 单个 run 的 summary.json 解析
  IntelligenceSummary — intelligence_summary.json 解析
  ComparisonSummary — intelligence_comparison_summary.json 解析
  SafetyStatus — 从 config/risk.yaml 读取安全状态
  render_overview_page() — Overview 页面
  render_run_details_page() — Run Details 页面
  render_llm_performance_page() — LLM Performance 页面
  render_intelligence_summary_page() — Intelligence Summary 页面
  render_watchlist_page() — Watchlist / Alpha / Avoid 页面

scripts/run_dashboard.py — Dashboard 启动脚本
  --check — 安全与环境检查
  --port — 自定义端口 (默认 8501)
  check_safety_config() — 风控配置检查
  check_runs_directory() — runs/ 目录检查
  check_data_files() — 数据文件检查
  check_no_trading_imports() — AST-based 交易模块导入检查
  launch_dashboard() — 启动 Streamlit

tests/test_dashboard.py — 61 tests
  覆盖：数据加载、安全约束、graceful handling、AST 导入检查

重要约束:
  - Dashboard 只读，不写入 runs/ 或 config/
  - 不导入 LiveTrader、PaperTrader、RiskGovernor
  - 不调用真实 API 或 LLM
  - 不提供交易按钮
  - localhost only (默认 8501)
```

---

## 2.3 Phase 6 新增功能

Phase 6 — Strategy Signal Validation 新增：

```text
scripts/validate_strategy_signals.py — Strategy Signal Validation Framework
  ValidationDataLoader — 加载 runs/ 数据 (alpha/avoid/watchlist/trajectories/events)
  AlphaValidator — Alpha candidate forward change 分析
  WatchlistValidator — Watchlist persistence 分析
  AvoidValidator — Avoid risk validation (含 control group comparison)
  CategoryValidator — Category-level signal quality
  EventScoreCorrelationValidator — Event score forward correlation
  ValidationReportGenerator — 报告生成 (MD + JSON + CSV)

数据类:
  AlphaForwardChange — first/last/min/max_combined_ask, delta, slope, num_observations, conclusion_status
  WatchlistPersistence — total_appearances, near_miss_hits, persistence_score, conclusion_status
  AvoidRiskValidation — avg_ambiguity_risk, category_risk, suggested_mode, conclusion_status
  AvoidGroupComparison — avoid vs non-avoid control group, conclusion_status
  CategoryPerformance — per-category stats, conclusion_status

conclusion_status 框架:
  observed — sufficient data for analysis
  insufficient_data — too few observations
  inconclusive — mixed results
  insufficient_control_group — control group too small (avoid validation)

输出文件:
  strategy_validation_report.md — 验证报告
  strategy_validation_summary.json — 机器可读摘要
  alpha_validation.csv — Alpha 验证 CSV
  avoid_validation.csv — Avoid 验证 CSV
  watchlist_validation.csv — Watchlist 验证 CSV

最新 Phase 6.5A.5 离线 validation 结果:
  Q1 Alpha forward change — inconclusive
  Q2 Avoid risk validation — observed
  Q2 non_avoid_group size — 21
  avoid avg ambiguity risk — 17.8
  non-avoid avg ambiguity risk — 8.8
  ambiguity delta — +9.0
  event_score correlation — r=-0.256, n=14

重要约束:
  - READ-ONLY: 不触发交易、不修改配置、不调用 API
  - 不导入 LiveTrader / PaperTrader / RiskGovernor
  - 结论是描述性观察，不是统计证明
  - live_trading_enabled 保持 false
```

---

## 2.4 Phase 6.5A 新增功能

Phase 6.5A — Control Group Sampling Patch 新增：

```text
scripts/run_paper.py 新增参数:
  --control_group_sampling_ratio  — control group 市场占比 (0.0-0.5)
  --exclude_avoid_from_control_group — 排除 avoid candidates

新增方法 (scripts/run_paper.py):
  _select_control_group_candidates() — 从非 avoid/alpha/watchlist 市场中选择 control group
  _run_control_group_sampling() — 执行 control group LLM sampling
  _generate_control_group_reports() — 生成 control group 输出文件

输出文件 (当前 run 目录):
  control_group_samples.csv        — control group 采样记录
  validation_loop_summary.json     — loop 级统计

scripts/validate_strategy_signals.py 更新:
  ValidationDataLoader.load_control_group_samples() — 加载 control_group_samples.csv
  AvoidValidator.validate_group_comparison() — 新增 control_group_samples 参数

重要约束:
  - Control group 只用于研究验证，不触发交易
  - 不修改 Risk Governor
  - 不修改 Signal 模型
  - 不修改策略
  - signals_generated: 0
  - paper_trades_created: 0
  - live_trading_enabled 保持 false
```

---

## 2.5 Phase 6.5B 新增功能

Phase 6.5B — Alpha Repeated Observation Run 新增：

```text
scripts/run_paper.py 新增参数:
  --alpha_priority_ratio  — alpha candidates 扫描优先级占比，默认 0.0
  --alpha_repeat_target   — 每个 alpha candidate 目标重复观测次数，默认 3

新增逻辑:
  alpha slots = min(int(max_markets * alpha_priority_ratio), remaining alpha candidates needing observations)
  达到 alpha_repeat_target 的 alpha market 降低优先级
  discovery_ratio 最低仍保持 0.1

输出文件 (当前 run 目录):
  alpha_repeat_observation_summary.json
  alpha_repeat_observation_report.md

scripts/validate_strategy_signals.py 更新:
  1 observation  -> insufficient_data
  2 observations -> weak_descriptive
  3-4 observations -> preliminary_observed
  >=5 observations -> stronger_observed

重要约束:
  - alpha_priority_ratio 只影响扫描优先级
  - alpha_score 不能生成 signal
  - alpha_score 不能触发 PaperTrader
  - alpha_score 不能改变 Risk Governor score
  - alpha_score 不能新增 hard reject / allow reason
  - 不修改 Risk Governor
  - 不修改策略逻辑
```

---

## 2.6 Phase 7A 新增文档

Phase 7A — Cloud Deployment Checklist:

```text
docs/cloud_deployment_checklist.md — 云服务器 read-only + paper-only data collection 部署清单

核心目标:
  - 云端只做 research/data collection
  - read-only monitoring
  - paper-only runner
  - 本地开发只跑 pytest 和短 smoke test
  - 长时间运行迁移到云服务器

安全约束:
  - 不接入实盘
  - 不处理私钥
  - 不存主钱包密钥
  - 不开放公网 dashboard
  - .env 不进 Git
  - live_trading_enabled=false
  - allow_auto_execution=false
  - paper_trading_enabled=true
  - default LLM provider=mock
```

---

## 2.7 Phase 7B 新增脚本

Phase 7B — Validation Loop Script:

```text
scripts/run_validation_loop.py — 云端 validation loop 编排脚本

职责:
  - 执行一次 read-only + paper-only data collection run
  - run 完成后自动执行 validate_strategy_signals.py
  - 自动执行 analyze_run_intelligence.py
  - 自动执行 compare_run_intelligence.py
  - 生成 runs/validation_loop_summary.json
  - 支持 --dry_run 和 --skip_run

安全检查:
  - live_trading_enabled=false
  - allow_auto_execution=false
  - paper_trading_enabled=true
  - default LLM provider=mock

重要约束:
  - 不导入 LiveTrader / PaperTrader / RiskGovernor
  - 不修改 config
  - 不修改策略
  - 不接入实盘
  - 不自动下单

验证:
  - python3 -m pytest tests/ -v
  - 1084 passed, 8 warnings
  - dry_run checked without executing run_paper.py
```

---

## 2.8 Phase 7C 新增运行方案

Phase 7C — systemd/tmux Running Plan:

```text
docs/cloud_running_plan.md — 云端长期运行方案
deploy/systemd/polysignal-validation.service.example — systemd service example
deploy/systemd/polysignal-validation.timer.example — systemd timer example

覆盖:
  - tmux manual running plan
  - systemd one-shot service + daily timer plan
  - /opt/polysignal app/runs/logs/.env paths
  - status / logs / stop / disable commands
  - pre-run safety checks
  - troubleshooting

重要约束:
  - 只新增文档和 example 模板
  - 不运行 systemctl
  - 不启动长任务
  - 不修改 config/risk.yaml
  - 不修改 scripts/run_paper.py
  - 不修改 Risk Governor / Strategy
```

---

## 2.9 Phase 7D 新增每日报告

Phase 7D — Daily Report Automation:

```text
scripts/generate_daily_report.py — 离线 daily research report generator
tests/test_generate_daily_report.py — daily report tests

职责:
  - 读取 runs/ 下最近 N 个 runs
  - 汇总 run summary
  - 汇总 strategy_validation_summary.json
  - 汇总 intelligence_comparison_summary.json
  - 汇总 persistent_watchlist.csv
  - 汇总 alpha_candidates.csv / avoid_candidates.csv
  - 汇总 validation_loop_summary.json
  - 生成 daily_report.md
  - 生成 daily_report_summary.json

安全约束:
  - 不运行 run_paper.py
  - 不调用真实 API
  - 不调用真实 LLM
  - 不导入 LiveTrader / PaperTrader / RiskGovernor
  - 不修改 config
  - 不修改 Risk Governor / Strategy
  - 不自动下单

验证:
  - python3 -m pytest tests/ -v
  - 1098 passed, 8 warnings
  - dry_run checked without writing report files
  - daily_report.md generated
  - daily_report_summary.json generated
```

---

## 2.10 Phase 8A Shadow Trading Core

Phase 8A — Shadow Paper Trading Engine Core:

```text
polysignal/shadow/models.py — shadow trade and candidate data models
polysignal/shadow/entry_filter.py — offline shadow entry filter
polysignal/shadow/exit_rules.py — fixed horizon / stop loss / take profit / stale / close exits
polysignal/shadow/pnl.py — hypothetical PnL and performance metrics
polysignal/shadow/reporter.py — CSV / JSON / Markdown outputs
scripts/run_shadow_paper_loop.py — offline shadow paper loop
tests/test_shadow_trading.py — Phase 8A tests

输出:
  - runs/shadow/shadow_trades.csv
  - runs/shadow/shadow_positions.json
  - runs/shadow/paper_performance_report.md
  - runs/shadow/paper_performance_summary.json

安全约束:
  - Shadow Trading 不是 PaperTrader
  - 不导入 LiveTrader / PaperTrader / RiskGovernor
  - 不调用真实 API / 真实 LLM
  - 不运行 run_paper.py
  - 不修改 Risk Governor / Strategy / config/risk.yaml
  - alpha_score 不能单独触发 shadow trade

验证:
  - python3 -m pytest tests/ -v
  - 1122 passed, 8 warnings
  - dry_run checked without writing runs/shadow outputs
```

---

## 2.11 Phase 8B Entry Filter Calibration

Phase 8B — Shadow Entry Filter Calibration:

```text
polysignal/shadow/entry_filter.py:
  - entry_decision: eligible_shadow_entry / watch_only / rejected
  - structured reject_reasons
  - structured watch_reasons
  - conservative watch_only calibration

scripts/run_shadow_paper_loop.py:
  - --diagnostics
  - --watch_only_output
  - --min_watch_alpha_score
  - --watch_tier3
  - dry_run diagnostics summary
  - formal run diagnostics CSV/JSON output

runs/shadow diagnostics outputs on formal run:
  - shadow_entry_diagnostics.json
  - shadow_entry_diagnostics.csv
```

Current dry_run diagnostics:

```text
candidates_loaded: 20
eligible_shadow_entry: 0
watch_only: 0
rejected: 20
top_rejection_reasons: avoid_candidate=20, high_ambiguity=2
top_watch_only_candidates: []
```

Interpretation:

```text
All current alpha candidates overlap with avoid candidates, so conservative
shadow entry correctly produces no trades.
```

验证:

```text
python3 -m pytest tests/ -v
1132 passed, 8 warnings
dry_run diagnostics checked without writing runs/shadow outputs
```

---

## 2.12 Phase 8C Tradable Candidate Pool

Phase 8C — Tradable Candidate Pool Construction:

```text
polysignal/shadow/tradable_candidates.py — offline tradable candidate model, builder, scorer
scripts/build_tradable_candidates.py — build tradable candidate pool from existing runs/
scripts/run_shadow_paper_loop.py — prefer runs/tradable_candidates.csv, fallback to legacy alpha/watchlist logic
tests/test_tradable_candidates.py — Phase 8C tests

输出:
  - runs/tradable_candidates.csv
  - runs/tradable_candidates.json
  - runs/tradable_candidate_report.md

当前构建结果:
  - candidates_considered: 64
  - tradable_candidates: 34
  - excluded_avoid_candidates: 28
  - exclusion_summary: avoid_candidate=28, high_ambiguity=7, missing_combined_ask=1

shadow dry_run after tradable pool:
  - candidates_loaded: 34
  - eligible_shadow_entry: 0
  - watch_only: 34
  - rejected: 0
  - top_rejection_reasons: missing_alpha_score=34
  - top_watch_reasons: tradable_candidate_watch_only=34
```

Safety note:

```text
tradable_score is a research/shadow priority score, not a trading signal.
Tradable candidates must still pass the Shadow Entry Filter.
Avoid candidates remain hard-excluded.
```

验证:

```text
python3 -m pytest tests/ -v
1150 passed, 8 warnings
```

---

## 2.13 Phase 8D Tradable Candidate Shadow Entry Calibration

Phase 8D — Tradable Candidate Shadow Entry Calibration:

```text
polysignal/shadow/models.py:
  - CandidateSnapshot supports tradable_score / tradable_source / tradable_reasons / evidence_level

polysignal/shadow/entry_filter.py:
  - tradable-evidence-centric eligible logic
  - missing alpha_score no longer rejects tradable candidates
  - tradable_score-only cannot trigger eligible_shadow_entry
  - alpha_score-only still cannot trigger eligible_shadow_entry

scripts/run_shadow_paper_loop.py:
  - reads tradable_score / source / reasons / evidence_level from tradable_candidates.csv
  - diagnostics include tradable evidence fields

shadow dry_run diagnostics:
  - candidates_loaded: 34
  - shadow_entries_would_generate: 5
  - eligible_shadow_entry: 5
  - watch_only: 29
  - rejected: 0
  - top_rejection_reasons: {}
  - top_watch_reasons include missing_alpha_score_but_not_required and tradable_score_too_low
```

Safety note:

```text
eligible_shadow_entry is only a hypothetical shadow trading entry.
tradable_score is not a live trading signal.
alpha_score is not a live trading signal.
Avoid candidates remain hard-excluded.
```

验证:

```text
python3 -m pytest tests/ -v
1158 passed, 8 warnings
```

---

## 2.14 Phase 8E Shadow Paper Performance Evaluation

Phase 8E — Shadow Paper Performance Evaluation:

```text
scripts/run_shadow_paper_loop.py:
  - non-dry-run writes shadow_trades.csv
  - writes shadow_positions.json
  - writes paper_performance_summary.json
  - writes paper_performance_report.md
  - does not synthesize forward prices when forward data is missing

polysignal/shadow/models.py:
  - ShadowTrade includes tradable_score / source / evidence_level
  - ShadowTradeStatus includes insufficient_forward_data

polysignal/shadow/pnl.py:
  - insufficient_forward_data positions do not contribute fake PnL

polysignal/shadow/reporter.py:
  - report includes Shadow Trading Summary / Entry Distribution / Exit Distribution / PnL Summary
  - report includes hypothetical performance disclaimer
```

当前离线 shadow evaluation:

```text
shadow_trades.csv generated: yes
shadow_trades: 5
closed_positions: 0
open_positions: 0
insufficient_forward_data_positions: 5
total_pnl: 0.0
win_rate: 0.0
max_drawdown: 0.0
forward data limitation: yes
```

验证:

```text
python3 -m pytest tests/ -v
1162 passed, 8 warnings
python3 scripts/run_shadow_paper_loop.py --diagnostics
```

---

## 2.15 Phase 8F.1 Offline Forward Observation Collector

Phase 8F.1 — Offline Forward Observation Collector:

```text
polysignal/shadow/forward_observations.py:
  - adds ForwardObservation model for offline price path observations
  - stores observed_price / yes_price / no_price / combined_ask / spread / liquidity / source / stale

scripts/collect_shadow_forward_data.py:
  - reads runs/shadow/shadow_positions.json
  - reads runs/shadow/shadow_trades.csv
  - reads runs/market_trajectories.json
  - reads existing runs/shadow/forward_observations.jsonl if present
  - updates positions only from real offline forward observations found in existing files
  - does not synthesize exit_price or PnL when forward data is missing
```

当前离线 forward collection:

```text
forward_observations.jsonl generated: yes (0 observations found)
updated_shadow_positions.json generated: yes
updated_shadow_trades.csv generated: yes
paper_performance_summary.json updated: yes
paper_performance_report.md updated: yes
closed_positions: 0
open_positions: 0
insufficient_forward_data_positions: 5
total_pnl: 0.0
win_rate: 0.0
max_drawdown: 0.0
forward data limitation: yes
```

验证:

```text
python3 -m pytest tests/ -v
1179 passed, 8 warnings
python3 scripts/collect_shadow_forward_data.py --dry_run
python3 scripts/collect_shadow_forward_data.py
```

Phase 8F.2 才考虑 read-only real API polling；Phase 8F.1 不调用真实 API / 真实 LLM / run_paper.py。

---

## 2.16 Phase 8F.2 Read-only Forward Price Polling

Phase 8F.2 — Read-only Forward Price Polling for Shadow PnL:

```text
polysignal/shadow/forward_observations.py:
  - ForwardObservation supports yes_token_id / no_token_id
  - supports YES/NO best bid/ask, source, stale, and error diagnostics
  - adds ShadowTokenIdResolver
  - explicitly refuses to treat market_id as token_id

scripts/poll_shadow_forward_prices.py:
  - loads open / insufficient_forward_data shadow positions
  - resolves token IDs from shadow, tradable, trajectory, and candidate files
  - polls public CLOB REST orderbooks only when token IDs are available
  - appends runs/shadow/forward_observations.jsonl
  - writes runs/shadow/forward_poll_summary.json
  - can invoke Phase 8F.1 collector to refresh performance outputs
  - does not authenticate, sign, place orders, cancel orders, call LLMs, or run run_paper.py
```

当前 read-only forward polling:

```text
dry_run positions_loaded: 5
dry_run positions_polled: 0
dry_run observations_written: 0
dry_run missing_token_id_count: 5

--once --max_positions 5:
positions_loaded: 5
positions_polled: 0
observations_written: 0
missing_token_id_count: 5
api_error_count: 0
updated_positions: true

forward_poll_summary.json generated: yes
forward_observations.jsonl remains empty: yes
closed_positions: 0
insufficient_forward_data_positions: 5
total_pnl: 0.0
win_rate: 0.0
max_drawdown: 0.0
```

当前 5 个 shadow positions 缺少 `yes_token_id` / `no_token_id`，因此 Phase 8F.2 未发出 CLOB REST polling 请求，也没有伪造 observation 或 PnL。

验证:

```text
python3 -m pytest tests/ -v
1195 passed, 8 warnings
python3 scripts/poll_shadow_forward_prices.py --dry_run
python3 scripts/poll_shadow_forward_prices.py --once --max_positions 5
```

---

## 2.17 Phase 8G.1 Offline Token ID Backfill

Phase 8G.1 — Offline Token ID Backfill:

```text
polysignal/shadow/models.py:
  - CandidateSnapshot supports yes_token_id / no_token_id
  - ShadowTrade supports yes_token_id / no_token_id
  - SHADOW_TRADE_FIELDS writes token columns

polysignal/shadow/tradable_candidates.py:
  - TradableCandidate supports yes_token_id / no_token_id

scripts/backfill_shadow_token_ids.py:
  - scans local runs/*/events.jsonl
  - scans local runs/*/summary.json
  - scans tradable / trajectory / watchlist / alpha / shadow artifacts
  - parses explicit yes_token_id / no_token_id
  - parses clobTokenIds / clob_token_ids + outcomes, including JSON-encoded strings
  - refuses to use market_id as token_id
  - does not call network or APIs when allow_api_lookup=false
```

当前 offline token backfill dry_run:

```text
markets_scanned: 101
token_pairs_found: 0
shadow_trades_loaded: 5
shadow_trades_backfilled: 0
shadow_trades_missing_token_id: 5
tradable_candidates_loaded: 34
tradable_candidates_backfilled: 0
api_lookup_enabled: false
```

结论:

```text
Existing local artifacts do not contain recoverable YES/NO CLOB token IDs for the current shadow positions.
No token IDs were fabricated.
No *_with_tokens files were written because dry_run found zero recoverable token pairs.
poll_shadow_forward_prices.py --once was not rerun after backfill because missing_token_id_count would not improve.
```

验证:

```text
python3 -m pytest tests/ -v
1209 passed, 8 warnings
python3 scripts/backfill_shadow_token_ids.py --dry_run
```

---

## 3. 当前默认安全状态

```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
default_llm_provider: mock
```

当前 live_trader 只能是 stub。

禁止：

- 真实下单
- 真实私钥
- 默认开启 live trading
- LLM 直接下单
- 策略绕过 Risk Governor
- ultra-fast path 调用 LLM
- wallet_signal_only 触发交易（必须 hard reject）
- event_signal_only 触发交易（必须 hard reject）
- LLM 输出包含交易执行字段

---

## 4. 当前已实现模块

已实现：

- config loading (config/*.yaml + .env)
- Pydantic models (models/market, orderbook, signal, risk, paper_trade, lifecycle, wallet, event, telegram)
- Data Provider Manager (mock / real_readonly / hybrid 模式)
- Gamma API client (市场发现)
- CLOB REST client (orderbook 数据，只读)
- Data Converter (API 数据转换，防御性解析)
- WebSocket Client (CLOB Market Channel，只读)
- OrderBook Cache (按 token_id 维护，YES + NO 合成)
- Subscription Manager (订阅管理，批量订阅)
- Reconnection Strategy (指数退避重连)
- mock market data (ingestion/mock_data_provider.py)
- mock orderbook data (ingestion/mock_data_provider.py)
- mock wallet data (ingestion/mock_wallet_provider.py)
- Market Microstructure Engine (engines/market_microstructure.py)
- Resolution & Lifecycle Engine (engines/resolution_lifecycle.py)
- Wallet Intelligence Engine (engines/wallet_intelligence.py)
- Event Intelligence Engine (engines/event_intelligence.py)
- LLM Provider abstraction (llm/base.py)
- Mock LLM Provider (llm/mock_provider.py)
- YES/NO mispricing strategy (strategies/yes_no_mispricing.py)
- Risk Governor (risk/risk_governor.py) - 含硬性拒绝、评分、决策阈值、lifecycle + wallet + event 检查
- Paper Trader (execution/paper_trader.py) - 仅 LIMIT orders
- Telegram Signal Cockpit (interface/telegram_client.py, interface/telegram_handler.py)
- SQLite storage (storage/database.py)
- CLI summary (interface/cli.py)
- tests (tests/test_*.py)

尚未实现或仍受限：

- Step 12 expiry timezone reconciliation is implemented in `gamma_expiry_adapter_v1`
- Step 12 historical barrier integration and per-asset shared evidence are complete
- Step 12 historical barrier integration is complete; the recorded formal v7 validation still has
  0 qualifying forward observations and only 3 independent clusters, while expectancy assessment
  requires at least 5
- Dashboard 已实现，但仍是只读研究界面
- Real LLM providers 已实现为可选能力；默认 provider 仍为 mock
- live trading 仍仅为 stub，且不在当前范围

---

## 5. 当前架构原则

系统采用：

```text
Market Microstructure Engine (完整实现)
Resolution & Lifecycle Engine (完整实现)
Wallet Intelligence Engine (完整实现)
Event Intelligence Engine (完整实现)
        ↓
Risk Governor (完整实现，含 lifecycle + wallet + event hard rejection)
        ↓
Log / Alert / Paper Trade / Manual Review / Limited Live Execution
```

当前已完整实现：
- Market Microstructure Engine
- Resolution & Lifecycle Engine
- Wallet Intelligence Engine
- Event Intelligence Engine
- Risk Governor
- Paper Trader

Risk Governor 是唯一执行裁决者，不可绕过。

---

## 6. 快慢路径原则

Ultra-fast path：

- 用于 WebSocket / orderbook / YES-NO mispricing
- 不调用 LLM
- 不访问慢速网页
- 不重新计算钱包画像
- 只读缓存

Slow path：

- 钱包画像
- 事件分析
- LLM rule parsing
- 新闻摘要
- 日报

---

## 7. Wallet Intelligence Engine 关键逻辑

wallet_score 公式：

```text
wallet_score =
  0.30 * reliability_score
  + 0.35 * performance_score
  + 0.20 * specialization_score
  + 0.15 * discipline_score
  - copy_risk_penalty (copy_risk_score * 0.30, max 30)
```

specialization_factor：

```text
category match: 1.0
generalist: 0.9
category mismatch: 0.7
```

consensus 检测：

```text
min_wallets: 2
min_same_direction_ratio: 66%
```

wallet_signal_only 检测（hard reject）：

```text
wallet_score >= 80
AND microstructure_score < 60
AND event_score < 60
AND liquidity_score < 60
```

Risk Governor 双重保障：

1. 检查 signal.risk_flags 中的 "wallet_signal_only"
2. 直接检查 component_scores（主要保障）

---

## 8. Event Intelligence Engine 关键逻辑

event_score 公式：

```text
event_score =
  0.40 * evidence_strength
  + 0.30 * market_relevance
  + 0.20 * (100 - ambiguity_risk)
  + 0.10 * confidence * 100
```

suggested_mode 枚举（不含 "trade"）：

```text
ignore | research | alert_only | manual_review | avoid
```

LLM 失败降级规则：

```text
invalid JSON / schema error / low confidence / timeout / error:
- event_score = 50 (neutral)
- confidence = 0
- suggested_mode = "research" 或 "avoid"
- 添加对应 risk_flag
- 不触发 paper_trade、manual_review 或任何执行动作
```

event_signal_only 检测（hard reject）：

```text
event_score >= 80
AND microstructure_score < 60
AND wallet_score < 60
AND liquidity_score < 60
```

Risk Governor 双重保障：

1. 检查 signal.risk_flags 中的 "event_signal_only"
2. 直接检查 component_scores（主要保障）

LLM 输出禁止字段：

```text
side, size, order, position, buy, sell, action
```

如果检测到禁止字段，标记 `llm_forbidden_trading_instruction`。

---

## 9. Telegram Signal Cockpit 关键逻辑

Telegram 是监控/控制面板，不是交易系统。

系统自动执行：
- IGNORE → 最小日志，无 Telegram
- LOG_ONLY → SQLite 日志，无 Telegram
- ALERT → 发送 Telegram alert
- PAPER_TRADE → 自动执行 paper trade + 发送 Telegram 通知
- MANUAL_REVIEW → 发送 Telegram review request
- HARD_REJECT → 仅高分(>=80)或系统错误时发送 Telegram

允许的操作（非交易）：
- details - 查看信号详情
- ignore_future - 忽略未来同类信号
- blacklist_market - 黑名单市场
- track_wallet - 追踪钱包到 watchlist
- pause_alerts / resume_alerts - 暂停/恢复 Telegram alerts
- pause_signals / resume_signals - 暂停/恢复信号生成
- mark_reviewed - 标记信号已审核
- view_journal - 查看日志

禁止的操作：
- buy, sell, execute, live_trade, approve_live, auto_trade, paper_trade

懒加载：
- python-telegram-bot 懒加载
- 无 token 时优雅降级到 CLI/log 模式

---

## 10. 当前下一步

当前下一步是：

```text
Trading MVP Step 12 — collect qualified >=240-minute forward evidence and expand to >=5 independent clusters
```

Historical barrier integration is complete. Formal cohort `step12_v7_20260804_140305` has 11
fresh positions across only 3 correlated clusters; all 11 remain `insufficient_forward_data`,
closed=0, PnL/win rate=null. Do not poll this cohort before the 240-minute horizon. After the
horizon, only trusted public read-only CLOB observations that satisfy the v7 contract may be used;
missing or invalid data stays null.
At least 5 independent clusters are required before expectancy assessment. v6 and all earlier
runs remain audit-only and must not be polled or supplemented. This cohort does not establish an
edge or profitability, and `tiny_live_recommendation=NO`.

历史 Phase 8G.2 结果：public Gamma read-only token lookup 曾为旧的 5 个 shadow trades 恢复
YES/NO CLOB token IDs，并由旧 poller 写入 5 条 forward observations、按 exit rules 关闭 5 个
positions。该结果属于 superseded shadow-only hypothetical PnL，不是正式 v7 cohort，也不能
用于当前 PnL、expectancy 或实盘判断。

Phase 8G.2 结果：

- tests: 1219/1219 passed
- dry_run: token_pairs_found=0, shadow_trades_missing_token_id=5, api_lookup_enabled=false
- allow_api_lookup: api_calls_used=5, api_lookup_successes=5, api_lookup_failures=0
- token_pairs_found: 5
- shadow_trades_backfilled: 5
- shadow_trades_missing_token_id: 0
- ambiguous_market_matches: 0
- ambiguous_outcome_mappings: 0
- unsupported_market_structures: 0
- market_lookup_not_found: 0
- shadow_trades_with_tokens.csv: generated
- updated_shadow_positions.json: contains yes_token_id / no_token_id for 5 positions
- forward polling: positions_loaded=5, positions_polled=5, observations_written=5, missing_token_id_count=0, api_error_count=0
- paper performance after polling: closed_positions=5, insufficient_forward_data_positions=0, total_pnl=-4.62937062937063, win_rate=0.0, max_drawdown=-4.62937062937063
- no live trading, no authentication, no signing, no order placement/cancellation, no private key handling

Phase 8H review 结果：

- tests: 1236/1236 passed
- trades_reviewed: 5
- losing_trades: 5
- winning_trades: 0
- primary_loss_drivers: price_interpretation_risk=5
- spread_drag_count: 0
- weak_evidence_count: 5
- control_group_source_count: 5
- expected_edge_missing_count: 5
- exit_timing_risk_count: 0
- price_interpretation_risk_count: 5
- key diagnosis: entry_price used combined_ask near 1.0 while exit used side bid, so entry/exit price semantics are mismatched
- current tiny_live_recommendation: NO
- Phase 8I follow-up: completed; Phase 8J corrected entry price collection completed

Phase 8I 结果：

- tests: 1254/1254 passed
- combined_ask is now feature-only and no longer used as side-specific entry price
- YES entry price uses yes_best_ask
- NO entry price uses no_best_ask
- YES exit price uses yes_best_bid
- NO exit price uses no_best_bid
- missing side ask prevents eligible_shadow_entry
- missing side bid prevents closing / PnL fabrication
- control_group-only candidates default to watch_only unless strong executable evidence exists
- expected_edge > spread + buffer gate added
- old 5 closed trades are marked legacy_invalid_price_model / invalid_entry_price_model
- price model audit dry_run: trades_reviewed=5, combined_ask_entry_detected_count=5, invalid_entry_price_model_count=5, missing_entry_side_price_count=5, corrected_pnl_available_count=0, corrected_pnl_unavailable_count=5
- run_shadow_paper_loop dry_run: candidates_loaded=34, eligible_shadow_entry=0, watch_only=34, rejected=0
- tiny_live_recommendation: NO

Phase 8J 结果：

- `scripts/refresh_tradable_candidate_prices.py` added for read-only CLOB side-specific price snapshots
- `tests/test_tradable_candidate_price_refresh.py` added
- `python3 -m pytest tests/ -v`: 1266 passed, 8 warnings
- dry_run loaded 34 candidates from `runs/tradable_candidates_with_tokens.csv`
- read-only refresh priced 5 candidates and left 29 as `missing_token_id`
- `runs/tradable_candidates_priced.csv` generated
- `runs/tradable_candidates_priced.json` generated
- `runs/tradable_candidate_price_refresh_summary.json` generated
- `runs/tradable_candidate_price_report.md` generated
- side-specific fields written: `yes_best_bid`, `yes_best_ask`, `no_best_bid`, `no_best_ask`, `yes_spread`, `no_spread`, `max_spread`, `expected_edge`, `entry_yes_best_ask`, `entry_no_best_ask`, `entry_yes_best_bid`, `entry_no_best_bid`
- `combined_ask` remains a market-level feature only and is not a side-specific entry price
- shadow dry_run now reads `tradable_candidates_priced.csv` first
- shadow dry_run diagnostics: candidates_loaded=34, eligible_shadow_entry=0, watch_only=34, rejected=0
- `missing_side_ask` decreased from 34 to 29
- current primary blocker: 29 candidates still lack token ids; priced control-group candidates lack expected edge and remain watch_only
- tiny_live_recommendation: NO
- no live trading, no authenticated API, no LLM call, no `run_paper.py`

---

## 11. 后续路线

推荐路线：

```text
Milestone 1.5: 工程审计与文档整理 (已完成)
Milestone 2A: Resolution & Lifecycle Engine (已完成)
Milestone 2B: Wallet Intelligence Engine (已完成)
Milestone 2C: Event Intelligence + Mock LLM (已完成)
Milestone 3: Telegram Signal Cockpit (已完成)
Phase 4A: Real Read-only Polymarket REST API (已完成)
Phase 4A.5: REST Smoke Test (已完成)
Phase 4B: CLOB WebSocket read-only (已完成)
Phase 4B.5: WebSocket Smoke Test (已完成)
Phase 4 Audit: Real Read-only Data Layer Audit (已完成)
Phase 4C: Real LLM Providers Integration (已完成)
Phase 4C.5: LLM Smoke Test (已完成)
Phase 4C Audit: Real LLM Provider Audit (已完成)
Phase 5A: 30-Minute Dry Run (已完成)
Phase 5B: 3-Hour Paper Trading Run (已完成)
Phase 5C: 24-Hour Paper Trading Run (已完成)
Phase 5D.1: LLM Sampling Mode (已完成)
Phase 5D.2: 4-Hour LLM Sampling Run (已完成)
Phase 5D.3: Audit & Metrics Fix (已完成)
Phase 5E: Market Intelligence Report (已完成)
Phase 5F: Multi-Run Intelligence Comparison (已完成)
Phase 5F.5: Watchlist-Driven Monitoring (已完成)
Phase 5G.1: Dashboard MVP (已完成)
Phase 6: Strategy Signal Validation (已完成)
Phase 6.5A: Control Group Sampling Patch (已完成)
Phase 6.5A.1: Category Inference Patch (已完成)
Phase 6.5A.5: Control Group Data Collection + Validation (已完成)
Phase 6.5B: Alpha Repeated Observation Run (实现完成)
Phase 7A: Cloud Deployment Checklist (已完成)
Phase 7B: Validation Loop Script (已完成)
Phase 7C: systemd/tmux Running Plan (已完成)
Phase 7D: Daily Report Automation (已完成)
Phase 8A: Shadow Paper Trading Engine Core (已完成)
Phase 8B: Shadow Entry Filter Calibration (已完成)
Phase 8C: Tradable Candidate Pool Construction (已完成)
Phase 8D: Tradable Candidate Shadow Entry Calibration (已完成)
Phase 8E: Shadow Paper Performance Evaluation (已完成)
Phase 8F.1: Offline Forward Observation Collector (已完成)
Phase 8F.2: Read-only Forward Price Polling for Shadow PnL (已完成)
Phase 8G.1: Offline Token ID Backfill (已完成，local artifacts token metadata 不足)
Phase 8G.2: Read-only Gamma Token ID Lookup (已完成)
Phase 8H: Shadow Performance Review Gate (已完成)
Phase 8I: Price Model & Entry Filter Calibration (已完成)
Phase 8J: Corrected Entry Price Collection / Candidate Rebuild (已完成)
Phase 8K: Token Coverage / Expected Edge Calibration (已被后续 Trading MVP Steps 取代)
Trading MVP Steps 1-11: completed
Trading MVP Step 12: discovery v5 / validator v7 and historical-barrier integration complete;
>=240-minute forward evidence and >=5 independent clusters pending
Milestone 5: Optional tiny test-wallet live limit order (可选，非当前建议下一步)
```

优先级：

1. ✅ 生命周期 / 结算风险
2. ✅ 钱包画像
3. ✅ 事件情报
4. ✅ Telegram Signal Cockpit
5. ✅ 真实只读 API (REST)
6. ✅ WebSocket 实时数据
7. ✅ 真实数据层审计
8. ✅ 真实 LLM 接入
9. ✅ LLM 接入审计
10. ✅ 30-Minute Dry Run
11. ✅ 3-Hour Paper Trading Run
12. ✅ 24-Hour Paper Trading Run
13. ✅ LLM Sampling Mode
14. ✅ Market Intelligence Report
15. ✅ Multi-Run Intelligence Comparison
16. ✅ Watchlist-Driven Monitoring
17. ✅ Dashboard MVP
18. ✅ Strategy Signal Validation
19. ✅ Control Group Sampling Patch
20. ✅ Alpha Repeated Observation Run implementation
21. ✅ Cloud Deployment Checklist
22. ✅ Shadow Paper Trading Engine Core
23. ✅ Shadow Entry Filter Calibration
24. ✅ Tradable Candidate Pool Construction
25. ✅ Tradable Candidate Shadow Entry Calibration
26. ✅ Shadow Paper Performance Evaluation
27. ✅ Forward Data Collection for Shadow PnL
28. 小额实盘 (可选，当前不进入)

---

## 12. 关键文件路径

核心模块：

```text
polysignal/models/          # Pydantic 数据模型
polysignal/ingestion/       # 数据接入 (mock, REST, WebSocket)
polysignal/engines/         # 智能引擎
polysignal/strategies/      # 交易策略
polysignal/risk/            # 风控模块
polysignal/execution/       # 执行层
polysignal/shadow/          # Shadow paper trading research engine
polysignal/storage/         # SQLite 存储
polysignal/interface/       # CLI / Telegram / Dashboard
polysignal/llm/             # LLM Provider
tests/                      # 测试
config/*.yaml               # 配置文件
scripts/smoke_*.py          # Smoke tests
scripts/run_paper.py        # Paper trading runner (Phase 5A)
scripts/run_dashboard.py    # Dashboard launcher (Phase 5G.1)
scripts/run_shadow_paper_loop.py # Shadow paper loop (Phase 8A)
scripts/build_tradable_candidates.py # Tradable candidate builder (Phase 8C)
scripts/analyze_run_intelligence.py  # Market Intelligence Analyzer (Phase 5E)
scripts/compare_run_intelligence.py # Multi-Run Comparison Analyzer (Phase 5F)
scripts/validate_strategy_signals.py # Strategy Signal Validation (Phase 6)
runs/                       # Run output directory
  run_*/                    # Individual run directory
    summary.json            # Run summary (JSON)
    report.md               # Run report (Markdown)
    events.jsonl            # Event log (JSONL)
    intelligence_report.md  # Intelligence report (Phase 5E)
    intelligence_summary.json # Intelligence summary (Phase 5E)
    sampled_markets.csv     # Sampled markets CSV (Phase 5E)
  intelligence_comparison_report.md # Multi-run comparison report (Phase 5F)
  intelligence_comparison_summary.json # Comparison summary (Phase 5F)
  persistent_watchlist.csv  # Persistent watchlist (Phase 5F)
  alpha_candidates.csv      # Alpha candidates (Phase 5F)
  avoid_candidates.csv      # Avoid candidates (Phase 5F)
  market_trajectories.json  # Market trajectories (Phase 5F)
  strategy_validation_report.md # Validation report (Phase 6)
  strategy_validation_summary.json # Validation summary (Phase 6)
  alpha_validation.csv      # Alpha validation CSV (Phase 6)
  avoid_validation.csv      # Avoid validation CSV (Phase 6)
  watchlist_validation.csv  # Watchlist validation CSV (Phase 6)
  tradable_candidates.csv   # Tradable candidate pool (Phase 8C)
  tradable_candidates.json  # Tradable candidate pool JSON (Phase 8C)
  tradable_candidate_report.md # Tradable candidate report (Phase 8C)
  control_group_samples.csv # Control group samples (Phase 6.5A, per run)
  validation_loop_summary.json # Validation loop summary (Phase 6.5A, per run)
```

配置：

```text
config/app.yaml      # 应用配置
config/risk.yaml     # 风控配置 (live_trading_enabled: false)
config/markets.yaml  # 市场配置
config/wallets.yaml  # 钱包配置
config/llm.yaml      # LLM 配置 (provider: mock)
config/websocket.yaml # WebSocket 配置
.env                 # 环境变量 (含 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
```

---

## 13. Risk Governor 关键逻辑

评分公式：

```text
trade_score =
  0.30 * microstructure_score
  + 0.20 * liquidity_score
  + 0.20 * event_score
  + 0.15 * wallet_score
  + 0.15 * lifecycle_score
  - ambiguity_penalty
  - slippage_penalty
  - concentration_penalty
  - copy_risk_penalty
  - chase_risk_penalty
  - timing_risk_penalty
  - event_ambiguity_penalty
  - event_weak_evidence_penalty
  - llm_failure_penalty
```

决策阈值：

```text
score < 70        → IGNORE
70 <= score < 80  → LOG_ONLY
80 <= score < 90  → ALERT + paper_trade
90 <= score < 95  → PAPER_TRADE / MANUAL_REVIEW
score >= 95       → PAPER_TRADE (live only if explicitly enabled)
```

硬性拒绝条件：

- live_trading_disabled
- market_not_open (status != OPEN)
- market_ambiguous
- forbidden_category
- spread_too_wide
- depth_too_thin (按信号方向检查对应侧深度)
- price_stale
- api_unhealthy
- websocket_unhealthy
- daily/weekly/consecutive_loss_limit_breached
- wallet_signal_only_reason (双重保障)
- event_signal_only_reason (双重保障)

---

## 14. 新会话启动协议

每次新会话开始前，Claude Code 必须：

1. 阅读 CONTEXT.md
2. 阅读 TASKS.md
3. 阅读 CLAUDE.md
4. 阅读 SPEC.md

然后输出：

1. 当前项目状态
2. 当前任务
3. 不会做什么
4. 本轮计划修改哪些文件

在用户确认前不要写代码。
