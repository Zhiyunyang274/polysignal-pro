# ROADMAP.md — PolySignal Pro 开发路线图

## Trading MVP — Autonomous Profitable Trading Readiness

状态：🚧 Active Focus

当前原则：

- 所有开发围绕 executable shadow trades → corrected PnL → edge proof
- Dashboard / daily report / Telegram report / LLM provider expansion 暂停
- tiny live / wallet / signing / live order manager 暂停
- live_trading_enabled=false
- allow_auto_execution=false
- tiny_live_recommendation=NO

### Trading MVP Step 12 — Crypto Threshold Corrected Shadow PnL Validation

状态：⏳ Historical barrier integration complete; formal v7 cohort awaits qualifying >=240-minute forward observations and >=5 independent clusters

已完成：

- Parser v4 separates settlement/touch contracts and up/down/unknown barriers.
- Ambiguous, conflicting, already-crossed, and description-derived thresholds fail closed.
- Step 12 validator v7 is offline-only and writes to isolated run-scoped artifacts; it accepts discovery v5 only.
- Entry uses selected-side ask; exit can only use the same side bid.
- Verified resolution source/rules/status and a rules SHA-256 are mandatory.
- Entry is created only after spot and both orderbooks exist; both client-observed and
  server-side timestamps are checked with 60-second freshness and <=5-second clock skew.
- Entry and forward artifacts preserve all four YES/NO best-level prices and sizes.
- Entry quantity is `notional / entry_ask`; exit must conserve and support the same shares.
- Discovery downgrades any non-verified resolution candidate to `watch_only`.
- `resolution_source_adapter_v1` accepts a structured source or one HTTPS URL in an explicit
  source section, with exact-host, conflict, digest, locator and rule-semantics checks.
- Adapter version, rules hash and provenance digest are bound into stable trade identity.
- Exact trade/market/side/token matching and a minimum 240-minute horizon are mandatory.
- Forward quotes require trusted source, explicit stale/error metadata, and non-crossed bid/ask.
- Missing forward data produces null PnL rather than a synthetic zero.
- Prepared-input/final-output SHA-256 provenance and cohort concentration are recorded.
- Discovery schema v5 stores canonical expiry/timezone/Gamma provenance and explicit historical
  barrier evidence status; touch contracts without full candle coverage are watch-only.
- Stable entry identity binds expiry, resolution, spot, client/server timestamps, four prices,
  four sizes, tokens, notional/shares and gate fields; prepared inputs are immutable snapshots.
- Forward validation requires both non-crossed YES/NO books, all four positive sizes, trusted
  timestamps and selected-side capacity.
- Cohorts use asset/expiry/contract semantics; repeated scans cannot manufacture independence.
- Dependency declarations now support SOCKS proxy tests and dashboard collection.
- Historical full regression after v4 hardening: 1612 passed.
- v5 full regression: 1634 passed in 277.62s, exit code 0 (historical baseline).
- v6 full regression: 1664 passed in 264.97s, exit code 0 (historical baseline).
- v7 full regression: 1755 passed in 264.97s, exit code 0.
- Scoped Ruff/format/mypy/py_compile and `uv lock --check` passed; repository-wide Ruff still has
  historical findings and is not globally clean.

已作废的 read-only run：

- run: `step12_20260804_122700`
- v3 discovery: 1958 markets scanned, 44 candidates, 13 prepared positions
- v4 validation: 0 accepted positions
- 44/44 candidates lack resolution provenance and best-level quantity evidence
- 25 candidates have stale YES/NO server-side orderbook timestamps
- corrected PnL: null; closed positions: 0
- status: `entry_snapshot_refresh_required`
- tiny_live_recommendation: `NO`

Runs `step12_20260804_114000` and `step12_20260804_122700` are audit-only. The first used
run-start timestamps before spot/orderbook evidence existed; the second predates the v4
resolution, server timestamp, and quantity contract. Neither may be polled, migrated, or used
for forward validation.

The fresh v4 coverage run `step12_v4_20260804_064741` is also audit-only after the v5 schema
upgrade. It scanned 1,958 markets and parsed 44 candidates, but structured resolutionSource
coverage was 0/44, so it produced no positions. It must not be migrated or backfilled.

Audit-only v5 run `step12_v5_20260804_073542`:

- 1,958 Gamma markets scanned; 56 crypto markets detected; 44 thresholds parsed.
- Resolution provenance verified for 44/44, all from `resolution_rules_url` through
  `resolution_source_adapter_v1`.
- Discovery produced 16 shadow entries and 28 watch-only rows.
- The strict v5 gate accepted 14; revalidation retained 10 positions across 3 clusters.
- The first public CLOB poll wrote 10 observations with 0 errors and 0 stale rows;
  `updated_positions=false`.
- All observations were before 240 minutes, so closed positions=0, PnL=null and status is
  `insufficient_forward_data`.
- Safety remained live=false, auto=false, paper=true, default LLM=mock; tiny live remains `NO`.

This run is retained for audit only. Its expiry interpretation, historical touch evidence and
entry/forward identity contract are superseded by v6; it must not be polled, migrated or used for
PnL, expectancy or profitability claims.

Latest v6 run `step12_v6_20260804_083736`:

- 1,958 Gamma markets scanned; 56 crypto markets detected; 44 thresholds parsed.
- Resolution and expiry provenance verified for 44/44; canonical expiry is
  `2027-01-01T04:59:00Z` from `2026-12-31 23:59 ET`.
- All 44 candidates are `touch_before_expiry` without full historical candle coverage;
  discovery produced `0 shadow_entry / 44 watch_only`.
- Validator schema is `crypto_threshold_shadow_pnl_v6`; strict gate and positions are 0,
  PnL is null, validation status is `historical_barrier_evidence_required`.
- One Gamma terminal pagination 422 was recorded; scan coverage is not claimed exhaustive.
- Safety remains live=false, auto=false, paper=true, default LLM=mock; tiny live remains `NO`.

Formal v7 cohort `step12_v7_20260804_140305`:

- Discovery/validator schemas: `crypto_threshold_edge_discovery_v5` /
  `crypto_threshold_shadow_pnl_v7`.
- 1,958 Gamma markets scanned; 56 crypto markets detected; 44 threshold candidates parsed.
- Exact-minute entry was committed at `2026-08-04T14:04:00Z`; 3 asset preloads, 3 entry tails,
  3 shared candle snapshots and 43 threshold-specific manifests were produced.
- Historical barriers verified: 43/44. The one missing rules-defined start failed closed without a
  speculative historical request. Public CLOB reads loaded 85/88; 3 incomplete reads failed closed.
- Discovery emitted 12 `shadow_entry` and 32 `watch_only` rows. Validator created 11 fresh paper
  positions (BTC 3 / ETH 5 / SOL 3) across 3 correlated clusters.
- No qualifying forward observations or closed positions yet; coverage is 0.0, PnL and win rate are
  null, and status is `insufficient_forward_data`.
- `supports_tiny_live=false`; `tiny_live_recommendation=NO`. Gamma's recoverable terminal-page
  error means this scan is not claimed exhaustive.

Historical barrier integration is complete. The remaining blocker is >=240-minute forward maturity
plus at least 5 independent asset/expiry/contract-kind clusters. The current cohort has only 3
clusters, so it is pipeline evidence only and supports no edge, expectancy, or profitability claim.

Execution-model hardening completed in parallel:

- A pure L2 shadow cost model now supports visible-depth sweep, limit caps, VWAP, fees,
  full/partial/rejected status, and same-share round trips.
- PaperTrader now uses deterministic visible-depth fills and hard limit/slippage gates.
- `SignalSide.BOTH` deliberately fails closed until typed two-leg positions and leg-risk
  accounting exist; current interfaces represent only one order and one outcome position.

下一步：

- Once the formal v7 entry horizon is reached, collect only forward observations that pass the
  complete-book, timestamp, identity and selected-side capacity gates; invalid or missing data
  must remain null rather than becoming PnL.
- Preserve v6 and earlier runs as audit-only; do not poll, migrate or supplement them.
- Expand future fresh cohorts until at least 5 independent asset/expiry/contract-kind clusters exist.
- Validate out of sample across more assets/expiries/cohorts.
- Do not tune on this run and do not enter tiny live.

### Trading MVP Step 1 — Token Coverage + Side Bid/Ask Pricing

状态：✅ Completed

结果：

- tradable candidates: 34
- token coverage: 34/34
- side bid/ask pricing: 34/34
- missing_side_ask_count: 0

### Trading MVP Step 2 — Expected Edge v1

状态：✅ Completed

结果：

- expected_edge_available_count: 0
- executable_edge_positive_count: 0
- combined_ask_below_one_count: 0
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- main reasons: combined_ask_not_below_one=34, control_group_only_watch=34

结论：

- 当前 34 个候选不是 executable opportunities
- 不能放宽 filter
- 不能进入 tiny live

### Trading MVP Step 3 — Executable Edge Discovery Loop

状态：✅ Completed

目标：

- 扫描真实 active Polymarket markets
- 提取 YES/NO CLOB token ids
- 拉取 public read-only CLOB orderbooks
- 计算 combined_ask_gap 与 executable_edge
- 输出 executable_edge_candidates for shadow-only evaluation
- 不接入实盘，不下单，不调用 LLM，不运行 run_paper.py

验收：

- tests 全过: 1310 passed
- executable_edge_discovery_summary.json generated
- executable_edge_candidates.csv/json generated
- edge candidates 只进入 shadow candidate path
- tiny_live_recommendation=NO

结果：

- markets_scanned: 493
- markets_with_token_ids: 474
- orderbooks_fetched: 948
- combined_ask_below_one_count: 0
- executable_edge_positive_count: 0
- edge_candidates_count: 0
- avoid_candidate_count: 19

结论：

- 当前 scanned batch 没有 positive executable edge
- 不进入 tiny live
- 下一步应围绕 discovery cadence / wider market coverage / WebSocket near-real-time edge monitoring，而不是放宽 filter

### Trading MVP Step 4A — Multi-Edge Discovery Framework v1

状态：✅ Completed

目标：

- Introduce unified `EdgeCandidate`
- Keep `combined_ask_arbitrage`
- Add `price_dislocation_probability_v1`
- Use only orderbook microstructure fields for expected_edge
- Do not use LLM, alpha_score, or tradable_score as edge
- Emit `multi_edge_candidates.csv/json` for shadow-only evaluation
- tiny_live_recommendation=NO

Reserved only:

- stale_price_lag
- closing_market_convergence
- cross_market_consistency
- spread_capture_passive

Result:

- Added unified `EdgeCandidate` model
- Added `scripts/discover_multi_edge_candidates.py`
- Added `combined_ask_arbitrage` detector
- Added `price_dislocation_probability_v1` baseline estimator
- Updated `scripts/run_shadow_paper_loop.py` to prefer `multi_edge_candidates.csv`
- Added `tests/test_multi_edge_discovery.py`
- `python3 -m pytest tests/ -v`: 1328 passed, 8 warnings

Read-only multi-edge discovery:

- markets_scanned: 493
- orderbooks_fetched: 948
- edge_type_counts: combined_ask_arbitrage=474, price_dislocation_probability_v1=948
- shadow_entry_candidates: 125
- watch_only_candidates: 1145
- rejected_candidates: 152
- avg_expected_edge: -0.00886427566807314
- max_expected_edge: 0.049999999999999996
- avg_confidence: 0.9653955696202532
- api_error_count: 0

Shadow dry-run after discovery:

- candidates_loaded: 125
- eligible_shadow_entry: 125
- watch_only: 0
- rejected: 0

Conclusion:

- Multi-edge discovery can now produce shadow-only executable candidates from orderbook microstructure.
- These candidates are not live signals and do not enter PaperTrader, LiveTrader, or the Risk Governor live execution path.
- tiny_live_recommendation=NO

### Trading MVP Step 5 — Corrected Shadow Trades + Forward PnL Validation

状态：✅ Completed

Result:

- Corrected shadow trades generated: 25
- edge_type: price_dislocation_probability_v1
- positions_polled: 25
- observations_written: 24
- closed_positions: 24
- insufficient_forward_data_positions: 1
- total_pnl: -6.9267167607752755
- win_rate: 0.041666666666666664
- average_return: -0.2886131983656365
- max_drawdown: -6.9267167607752755

Conclusion:

- The corrected shadow PnL loop is technically closed.
- `price_dislocation_probability_v1` showed negative paper performance.
- Primary loss drivers were probability_model_bias, exit_bid_weakness, and confidence_overestimated.
- tiny_live_recommendation=NO

### Trading MVP Step 6 — Probability Edge Calibration v2

状态：✅ Completed

目标：

- Keep `price_dislocation_probability_v1` as a baseline.
- Add `price_dislocation_probability_v2` as a more conservative probability edge model.
- Penalize exit bid weakness, adverse selection, wide spread, shallow depth, and low liquidity.
- Lower inflated confidence from v1.
- Keep outputs shadow-only.

Expected outputs:

- `runs/multi_edge_candidates_v2.csv`
- `runs/multi_edge_candidates_v2.json`
- `runs/multi_edge_discovery_v2_summary.json`
- `runs/multi_edge_discovery_v2_report.md`

Result:

- `python3 -m pytest tests/ -v`: 1341 passed, 8 warnings
- markets_scanned: 493
- orderbooks_fetched: 942
- v2_shadow_entry_candidates: 20
- v2_watch_only_candidates: 620
- v2_rejected_candidates: 308
- avg_raw_expected_edge: -0.004280590717299581
- avg_calibrated_expected_edge: -0.03299360178429739
- avg_confidence: 0.8178872918424754
- top 10 v2 closed_positions: 10
- top 10 v2 total_pnl: -2.469158035079444
- top 10 v2 win_rate: 0.1
- top 10 v2 average_return: -0.2469158035079444
- primary loss driver: expected_edge_too_optimistic

Conclusion:

- v2 is materially more conservative than v1, but it still does not prove positive expectancy.
- Do not enter tiny live.
- Next Trading MVP work should further calibrate expected edge using actual forward PnL feedback, not loosen gates.

Safety:

- No live trading
- No private key handling
- No authenticated API
- No real LLM
- No `run_paper.py`
- tiny_live_recommendation=NO

### Trading MVP Step 7 — Expected Edge Feedback Calibration

状态：✅ Completed

目标：

- Read closed v1/v2 shadow PnL and multi-edge candidate prediction files.
- Build an edge feedback dataset.
- Measure expected_edge vs realized_return correlation.
- Measure confidence vs win/loss correlation.
- Identify systematic loss patterns.
- Recommend v3 filters / penalties without implementing v3.

Expected outputs:

- `runs/edge_feedback_dataset.csv`
- `runs/edge_feedback_calibration_summary.json`
- `runs/edge_feedback_calibration_report.md`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- tiny_live_recommendation=NO

Result:

- `python3 -m pytest tests/ -v`: 1351 passed, 8 warnings
- trades_analyzed: 10
- edge_types_analyzed: price_dislocation_probability_v2
- overall_win_rate: 0.1
- overall_average_return: -0.2469158035079444
- expected_edge_realized_return_correlation: -0.1784870086432687
- confidence_win_correlation: -0.009224758324091477
- false_positive_count: 9
- high_confidence_loss_count: 9
- top loss patterns: expected_edge_false_positive, high_confidence_loss, exit_bid_weakness, exit_bid_penalty_underestimated, microstructure_probability_loss

Conclusion:

- expected_edge is not positively correlated with realized_return in the current sample.
- confidence is not positively correlated with win/loss in the current sample.
- probability_edge should not continue as executable shadow entry in its current form.
- Step 8 should quarantine probability_edge to watch_only or require positive feedback-backed edge before executable shadow entry.
- tiny_live_recommendation=NO

### Trading MVP Step 8 — Probability Edge Quarantine / Feedback-Gated Shadow Entry

状态：✅ Completed

目标：

- Add `EdgeTypeGate` / `FeedbackGateConfig` for shadow-entry permission by edge type.
- Apply feedback results from `runs/edge_feedback_calibration_summary.json`.
- Force `price_dislocation_probability_v1/v2` to watch_only while feedback is negative or insufficient.
- Keep `combined_ask_arbitrage` available as a separate direct microstructure edge.
- Prevent quarantined probability edges from generating shadow trades even if a candidate file says `recommended_action=shadow_entry`.

Expected outputs:

- `runs/edge_feedback_gate_summary.json`
- `runs/edge_feedback_gate_report.md`
- `runs/multi_edge_candidates_gated.csv`
- `runs/multi_edge_candidates_gated.json`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- tiny_live_recommendation=NO

Result:

- `python3 -m pytest tests/ -v`: 1362 passed, 8 warnings
- `price_dislocation_probability_v1` gate status: watch_only
- `price_dislocation_probability_v2` gate status: quarantined
- `multi_edge_candidates_gated.csv/json` generated
- `edge_feedback_gate_summary.json/report.md` generated
- gated probability candidates forced to `recommended_action=watch_only`
- shadow dry-run for v2: eligible_shadow_entry=0, watch_only=25, rejected=0
- diagnostics include `edge_type_quarantined`, `feedback_gate_failed`, `expected_edge_negative_correlation`, and `confidence_not_predictive`
- combined_ask_arbitrage remains available through its original direct microstructure path

Next:

- Trading MVP Step 9 should focus on non-probability edge discovery or feedback-safe data collection.

### Trading MVP Step 9A — Cross-Market Consistency Edge v1

状态：✅ Completed

目标：

- Add `cross_market_consistency_v1` as a non-probability edge source.
- Detect same-event duplicate / near-duplicate markets with divergent YES prices.
- Detect simple mutually exclusive market groups, defaulting to watch-only.
- Emit read-only / shadow-only candidates.
- Keep probability edge v1/v2 quarantined.
- Keep tiny_live_recommendation=NO.

Expected outputs:

- `runs/cross_market_edge_candidates.csv`
- `runs/cross_market_edge_candidates.json`
- `runs/cross_market_edge_discovery_summary.json`
- `runs/cross_market_edge_discovery_report.md`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor changes
- tiny_live_recommendation=NO

Result:

- Added `cross_market_consistency_v1` edge type.
- Added `scripts/discover_cross_market_edges.py`.
- Updated `scripts/run_shadow_paper_loop.py` to read `cross_market_edge_candidates.csv`.
- Added `tests/test_cross_market_edge_discovery.py`.
- `python3 -m pytest tests/ -v`: 1375 passed, 8 warnings.
- dry_run `--max_markets 100`:
  - markets_scanned: 82
  - groups_detected: 0
  - candidates_generated: 0
- read-only discovery `--max_markets 1000 --min_volume 1000`:
  - markets_scanned: 989
  - groups_detected: 29
  - duplicate_groups_detected: 24
  - mutually_exclusive_groups_detected: 5
  - orderbooks_fetched: 282
  - candidates_generated: 95
  - watch_only_candidates: 95
  - shadow_entry_candidates: 0
  - avg_price_gap: 0.5061052631578947
  - max_price_gap: 0.885
  - api_error_count: 0
- Shadow dry-run after cross-market discovery:
  - candidates_loaded: 23
  - eligible_shadow_entry: 0
  - watch_only: 23
  - rejected: 0
  - edge_type_distribution: cross_market_consistency_v1=23

Conclusion:

- Cross-market consistency discovery is now available as a non-probability edge source.
- First run found related-market price gaps, but all candidates remained watch-only.
- Probability edge v1/v2 remains quarantined.
- No tiny live.

### Trading MVP Step 9B — Cross-Market Relationship Confidence Calibration

状态：✅ Completed

目标：

- Calibrate relationship confidence for Step 9A cross-market candidates.
- Distinguish high-confidence duplicates, medium related markets, mutually-exclusive watch groups, ambiguous relationships, and likely false matches.
- Ensure price gap alone cannot become a shadow entry.
- Keep probability edge v1/v2 quarantined.
- Keep tiny_live_recommendation=NO.

Expected outputs:

- `runs/cross_market_relationship_calibration_summary.json`
- `runs/cross_market_relationship_calibration_report.md`
- `runs/cross_market_edge_candidates_calibrated.csv`
- `runs/cross_market_edge_candidates_calibrated.json`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- tiny_live_recommendation=NO

Result:

- Added `scripts/calibrate_cross_market_relationships.py`.
- Updated `scripts/run_shadow_paper_loop.py` to prefer calibrated cross-market candidates.
- Added relationship diagnostics in `polysignal/shadow/entry_filter.py`.
- Added `tests/test_cross_market_relationship_calibration.py`.
- `python3 -m pytest tests/ -v`: 1390 passed, 8 warnings.
- offline calibration:
  - candidates_loaded: 95
  - groups_loaded: 14
  - high_confidence_duplicate_count: 16
  - medium_confidence_related_count: 0
  - ambiguous_relationship_count: 4
  - likely_false_match_count: 3
  - mutually_exclusive_watch_count: 72
  - shadow_entry_eligible_count: 16
  - watch_only_count: 76
  - rejected_count: 3
  - avg_relationship_confidence: 0.787885249230512
- Shadow dry-run after calibrated candidates:
  - candidates_loaded: 25
  - eligible_shadow_entry: 10
  - watch_only: 15
  - rejected: 0
  - top_watch_reasons: mutually_exclusive_watch=15
  - edge_type_distribution: cross_market_consistency_v1=25

Conclusion:

- Relationship calibration now separates false/ambiguous/mutually-exclusive cases from high-confidence duplicate candidates.
- Calibrated shadow entries are still shadow-only and need corrected forward PnL before any further promotion.
- Probability edge v1/v2 remains quarantined.
- No tiny live.

### Trading MVP Step 9C — Corrected Shadow PnL for High-Confidence Cross-Market Edge

状态：✅ Completed

目标：

- Generate corrected shadow trades only from high-confidence duplicate `cross_market_consistency_v1` candidates.
- Use side-specific ask for entry and side-specific bid for exit.
- Run one read-only CLOB forward polling pass.
- Evaluate corrected hypothetical PnL by edge type, relationship status, and price gap bucket.
- Keep tiny_live_recommendation=NO.

Result:

- `python3 -m pytest tests/ -v`: 1392 passed, 8 warnings.
- Shadow dry-run:
  - candidates_loaded: 88
  - shadow_entries_would_generate: 10
  - eligible_shadow_entry: 16
  - watch_only: 72
  - rejected: 0
- Corrected shadow trades generated: 10
- edge_type: cross_market_consistency_v1
- relationship_status: high_confidence_duplicate
- read-only forward polling:
  - positions_loaded: 10
  - positions_polled: 10
  - observations_written: 10
  - missing_token_id_count: 0
  - api_error_count: 0
  - stale_observation_count: 0
- corrected PnL:
  - closed_positions: 10
  - open_positions: 0
  - insufficient_forward_data_positions: 0
  - total_pnl: -2.408470695970695
  - win_rate: 0.0
  - average_return: -0.24084706959706959
  - median_return: -0.225
  - max_drawdown: -2.408470695970695
- review:
  - primary_loss_driver: expected_edge_too_optimistic=10
  - price_gap_not_converging=10
  - exit_bid_weakness=10
  - cross_market_consistency_v1 has not proven positive expectancy.

Conclusion:

- The cross-market shadow PnL loop is technically closed.
- High-confidence duplicate price gaps did not converge positively in this one-shot sample.
- Do not enter tiny live.
- Next step should calibrate cross-market edge expected value / convergence rules and require repeated observations before executable shadow entries.

### Trading MVP Step 9D — Cross-Market Convergence Calibration / Repeated Observation Gate

状态：✅ Completed

目标：

- Require repeated read-only observations for high-confidence duplicate cross-market candidates.
- Record price_gap time series and calculate convergence score.
- Only allow cross-market candidates through shadow entry if convergence gate passes.
- Ensure price_gap alone cannot create executable shadow entries.
- Keep probability edge v1/v2 quarantined.
- Keep tiny_live_recommendation=NO.

Expected outputs:

- `runs/cross_market_convergence_observations.jsonl`
- `runs/cross_market_convergence_summary.json`
- `runs/cross_market_convergence_report.md`
- `runs/cross_market_edge_candidates_convergence_gated.csv`
- `runs/cross_market_edge_candidates_convergence_gated.json`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- tiny_live_recommendation=NO

Result:

- Added `polysignal/shadow/cross_market_convergence.py`.
- Added `scripts/monitor_cross_market_convergence.py`.
- Updated `scripts/run_shadow_paper_loop.py` to prefer convergence-gated cross-market candidates.
- Updated shadow candidate/trade models, entry diagnostics, and reporter fields with convergence metadata.
- Added `tests/test_cross_market_convergence.py`.
- `python3 -m pytest tests/ -v`: 1405 passed, 8 warnings.
- dry-run:
  - candidates_monitored: 16
  - observations_collected: 0
  - groups_monitored: 6
  - convergence_pass_count: 0
  - convergence_fail_count: 0
  - insufficient_observation_count: 16
  - shadow_entry_eligible_count: 0
  - watch_only_count: 16
- short read-only monitor:
  - candidates_monitored: 16
  - observations_collected: 96
  - groups_monitored: 6
  - convergence_pass_count: 0
  - convergence_fail_count: 16
  - insufficient_observation_count: 0
  - avg_initial_gap: 0.667125
  - avg_final_gap: 0.667125
  - avg_gap_change: -6.938893903907228e-18
  - shadow_entry_eligible_count: 0
  - watch_only_count: 16
  - rejected_count: 0
- Shadow dry-run after convergence gate:
  - candidates_loaded: 16
  - eligible_shadow_entry: 0
  - watch_only: 16
  - rejected: 0
  - top_watch_reasons: price_gap_not_converging=32
  - edge_type_distribution: cross_market_consistency_v1=16

Conclusion:

- The observed cross-market gaps did not converge during the short monitor.
- Non-converging candidates are held as watch_only and cannot generate shadow trades.
- `cross_market_consistency_v1` still has no positive expectancy proof.
- No tiny live.

### Trading MVP Step 9E — Longer Cross-Market Convergence Dataset / Feature Calibration

状态：✅ Completed

目标：

- Accumulate longer read-only convergence observations for high-confidence duplicate cross-market candidates.
- Support append/resume/run_id in the monitor so observations become a reusable dataset.
- Analyze gap time-series features by group and market pair.
- Recommend future shadow candidates only from observed convergence features.
- Do not generate shadow trades.
- Keep tiny_live_recommendation=NO.

Expected outputs:

- `runs/cross_market_convergence_observations.jsonl`
- `runs/cross_market_convergence_features.csv`
- `runs/cross_market_convergence_dataset_summary.json`
- `runs/cross_market_convergence_dataset_report.md`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- No shadow trades generated
- tiny_live_recommendation=NO

Result:

- Updated `scripts/monitor_cross_market_convergence.py` with append/resume/run_id support.
- Added `scripts/analyze_cross_market_convergence_dataset.py`.
- Added `tests/test_cross_market_convergence_dataset.py`.
- Updated `tests/test_cross_market_convergence.py` for append/resume coverage.
- `python3 -m pytest tests/ -v`: 1419 passed, 8 warnings.
- monitor dry-run:
  - candidates_monitored: 16
  - observations_collected: 0
  - groups_monitored: 6
  - convergence_pass_count: 0
  - insufficient_observation_count: 16
  - shadow_entry_eligible_count: 0
  - watch_only_count: 16
- 30-minute read-only observation:
  - interval_seconds: 120
  - resume_enabled: true
  - existing_observations_loaded: 96
  - new_observations_collected: 256
  - observations_collected used for monitor summary: 352
  - candidates_monitored: 16
  - groups_monitored: 6
  - convergence_pass_count: 0
  - convergence_fail_count: 16
  - avg_initial_gap: 0.667125
  - avg_final_gap: 0.6654375
  - avg_gap_change: -0.0016874999999999217
  - shadow_entry_eligible_count: 0
  - watch_only_count: 16
- Dataset analysis:
  - total_observations: 352
  - groups_analyzed: 6
  - pairs_analyzed: 16
  - converging_pairs_count: 0
  - non_converging_pairs_count: 13
  - widening_pairs_count: 3
  - stable_pairs_count: 1
  - avg_gap_change: -0.0016874999999999217
  - avg_gap_volatility: 0.002452169763537771
  - best_convergence_score: 0.020979020979020845
  - candidates_recommended_for_future_shadow: 0

Conclusion:

- Longer observation did not find a usable cross-market convergence pattern.
- Stable gaps and weak convergence remain watch_only.
- No candidates are recommended for future shadow entry from this dataset.
- No tiny live.

### Trading MVP Step 9F — Edge Pruning & New Edge Source Selection

状态：✅ Completed

目标：

- Audit tested edge types into a single strategy registry.
- Assign each edge type a current status.
- Confirm whether any edge supports tiny live.
- Recommend the next edge source.
- Do not generate trades or modify live/strategy logic.
- Keep tiny_live_recommendation=NO.

Expected outputs:

- `runs/edge_strategy_status_report.md`
- `runs/edge_strategy_status_summary.json`
- `runs/edge_strategy_registry.csv`

Safety:

- No live trading
- No private key handling
- No order placement
- No authenticated API
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- No shadow trades generated
- tiny_live_recommendation=NO

Result:

- Added `scripts/audit_edge_strategy_status.py`.
- Added `tests/test_edge_strategy_status_audit.py`.
- `python3 -m pytest tests/ -v`: 1428 passed, 8 warnings.
- edge_types_reviewed: 5
- enabled_edges:
  - `combined_ask_arbitrage`
- quarantined_edges:
  - `price_dislocation_probability_v1`
  - `price_dislocation_probability_v2`
- research_only_edges:
  - `cross_market_consistency_v1`
  - `cross_market_convergence`
- watch_only_edges: []
- discontinued_edges: []
- any_edge_supports_tiny_live: false
- tiny_live_recommendation: NO
- recommended_next_edge_source: Crypto Price Threshold Edge
- recommended_step_10: Trading MVP Step 10 — Crypto Price Threshold Edge v1

Conclusion:

- No tested edge currently supports tiny live.
- Probability v1/v2 remain quarantined due negative feedback.
- Cross-market consistency/convergence remains research-only because price gaps did not converge and shadow PnL was negative.
- Combined ask arbitrage remains logically valid but too rare and lacks positive PnL evidence.
- Step 10 should move to objective external crypto threshold markets rather than loosening failed gates.

### Trading MVP Step 10 — Crypto Price Threshold Edge v1

状态：✅ Completed

目标：

- Add `crypto_price_threshold_v1` as an external objective edge source.
- Scan public Gamma markets for BTC / ETH / SOL threshold questions.
- Parse asset, threshold, direction, and expiry without LLM.
- Read public spot prices and CLOB orderbooks in read-only mode.
- Estimate baseline probability from distance / time / volatility heuristics.
- Emit shadow-only candidates and keep tiny_live_recommendation=NO.

Expected outputs:

- `runs/crypto_threshold_edge_candidates.csv`
- `runs/crypto_threshold_edge_candidates.json`
- `runs/crypto_threshold_edge_discovery_summary.json`
- `runs/crypto_threshold_edge_discovery_report.md`

Safety:

- No live trading
- No private key handling
- No auth / signing
- No order placement or cancellation
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- tiny_live_recommendation=NO

Result:

- Added `scripts/discover_crypto_threshold_edges.py`.
- Added `tests/test_crypto_threshold_edge_discovery.py`.
- Updated `scripts/run_shadow_paper_loop.py` to read crypto threshold candidates.
- `python3 -m pytest tests/ -v`: 1442 passed, 8 warnings.
- dry-run:
  - markets_scanned: 100
  - crypto_markets_detected: 1
  - parsed_threshold_markets: 1
  - candidates_generated: 0
- read-only discovery:
  - markets_scanned: 100
  - crypto_markets_detected: 1
  - parsed_threshold_markets: 1
  - spot_prices_loaded: 1
  - orderbooks_fetched: 0
  - candidates_generated: 0
  - shadow_entry_candidates: 0
  - avoid_candidate_count: 1
- shadow dry-run:
  - eligible_shadow_entry: 0
  - watch_only: 0
  - rejected: 0

Conclusion:

- The crypto threshold edge discovery pipeline is implemented and read-only.
- The current scanned batch found one parsed BTC threshold market, but it was already an avoid candidate.
- No shadow trades were generated.
- No edge supports tiny live.
- Step 11 should improve crypto threshold market coverage and diagnostics before shadow PnL validation.

### Trading MVP Step 11 — Crypto Threshold Market Coverage Expansion

状态：✅ Completed

目标：

- Expand Gamma coverage with pagination / offset scanning.
- Add keyword discovery for BTC / ETH / SOL threshold markets.
- Improve parser support for common crypto threshold wording.
- Add avoid-aware diagnostics and `crypto_threshold_market_diagnostics.csv`.
- Keep all outputs read-only / shadow-only.
- Do not loosen edge gates or enter tiny live.

Expected outputs:

- `runs/crypto_threshold_edge_candidates.csv`
- `runs/crypto_threshold_edge_candidates.json`
- `runs/crypto_threshold_edge_discovery_summary.json`
- `runs/crypto_threshold_edge_discovery_report.md`
- `runs/crypto_threshold_market_diagnostics.csv`

Safety:

- No live trading
- No private key handling
- No auth / signing
- No order placement or cancellation
- No real LLM
- No `run_paper.py`
- No Risk Governor or live config changes
- No shadow trades generated
- tiny_live_recommendation=NO

Result:

- Expanded `scripts/discover_crypto_threshold_edges.py`.
- Expanded `tests/test_crypto_threshold_edge_discovery.py`.
- `python3 -m pytest tests/ -v`: 1451 passed, 8 warnings.
- dry-run:
  - markets_scanned: 493
  - crypto_markets_detected: 3
  - parsed_threshold_markets: 3
- expanded read-only discovery:
  - markets_scanned: 3000
  - crypto_markets_detected: 49
  - parsed_threshold_markets: 46
  - spot_prices_loaded: 3
  - orderbooks_fetched: 90
  - excluded_avoid_candidates: 1
  - excluded_parse_low_confidence: 3
  - excluded_missing_token: 0
  - excluded_missing_spot: 0
  - excluded_missing_orderbook: 0
  - eligible_after_avoid_filter: 45
  - candidates_generated: 45
  - shadow_entry_candidates: 29
  - watch_only_candidates: 16
  - rejected_candidates: 0
  - asset_distribution: BTC=17, ETH=14, SOL=14

Conclusion:

- Crypto threshold market coverage improved materially.
- Candidate samples now exist for shadow-only validation.
- Avoid-aware diagnostics are available.
- Step 12 should run corrected shadow PnL validation for crypto threshold candidates, still with tiny_live_recommendation=NO.

## Milestone 1 — Read-only + Paper Trading MVP

状态：✅ Completed

结果：

- 57/57 tests passed
- mock data pipeline 完成
- Market Microstructure Engine 完成
- YES/NO mispricing strategy 完成
- Risk Governor 完成 (含硬性拒绝、评分、决策阈值)
- Paper Trader 完成 (仅 LIMIT orders)
- SQLite logging 完成
- CLI summary 完成

关键验收：

- 所有测试通过
- 安全门禁通过 (live_trading_enabled=false)
- 最小闭环可运行

---

## Milestone 1.5 — Engineering Audit & Deliverable Cleanup

状态：✅ Completed

结果：

- 57/57 tests passed
- Application runs correctly
- All security gates passed
- Documentation updated
- Audit report created

完成标准：

- pytest 全通过 ✅
- `python -m polysignal.main` 可运行 ✅
- docs/milestone_1_5_audit.md 存在 ✅
- README 反映真实功能 ✅
- 安全检查通过 ✅

---

## Milestone 2A — Resolution & Lifecycle Engine

状态：✅ Completed

结果：

- 109/109 tests passed
- Resolution & Lifecycle Engine 完成
- lifecycle_score 集成到 Risk Governor
- 市场状态检查 (OPEN/CLOSED/RESOLVED)
- Ambiguity risk 检测
- Resolution risk 检测
- Forbidden category 双重兜底
- Close-time guard 实现

完成标准：

- lifecycle tests added ✅
- Risk Governor integrates lifecycle_score ✅
- ambiguous markets hard rejected ✅
- forbidden categories hard rejected ✅
- closed/resolved markets hard rejected ✅

---

## Milestone 2B — Wallet Intelligence Engine

状态：✅ Completed

结果：

- 138/138 tests passed
- Wallet Intelligence Engine 完成
- wallet_score 集成到 Risk Governor
- wallet_signal_only 双重保障实现
- copy_risk / chase_risk / timing_risk 检测
- wallet_consensus 策略实现

完成标准：

- wallet signal cannot trigger trade alone ✅
- wallet scores cached for fast path ✅
- tests added ✅

---

## Milestone 2C — Event Intelligence + Mock LLM

状态：✅ Completed

结果：

- 202/202 tests passed
- LLM provider abstraction 完成
- mock provider 完善
- event JSON schema 定义
- event_score 集成到 Risk Governor
- event_signal_only 双重保障实现
- invalid JSON handling 完成

完成标准：

- LLM never enters ultra-fast path ✅
- invalid JSON → no trade ✅
- tests added ✅

---

## Milestone 3 — Telegram Signal Cockpit

状态：✅ Completed

结果：

- 261/261 tests passed
- Telegram Client with lazy loading
- Telegram Action Handler
- 非交易控制操作 (details, ignore_future, blacklist_market, track_wallet, pause/resume)
- 暂停模式 (alerts_paused, signals_paused)
- 系统自动执行 paper trades
- 优雅降级到 CLI/log 模式
- 所有操作记录到 SQLite

完成标准：

- Telegram token 可选 (降级为 CLI) ✅
- 按钮操作记录到数据库 ✅
- tests added ✅
- forbidden actions rejected ✅

---

## Milestone 4 — Real Read-only Polymarket API

状态：✅ Completed (Phase 4A + 4B + 4C + Audit)

结果：

**Phase 4A — REST API:**
- Gamma API client 完成
- CLOB REST client 完成（只读）
- DataConverter 完成（防御性解析）
- DataProviderManager 完成（mock / real_readonly / hybrid）

**Phase 4A.5 — REST Smoke Test:**
- 真实 REST API 验证通过
- 100 markets fetched
- Token IDs 正确解析
- Orderbooks 正确获取

**Phase 4B — WebSocket:**
- CLOB WebSocket client 完成（只读）
- OrderBook Cache 完成（按 token_id 维护）
- Subscription Manager 完成
- Reconnection Strategy 完成
- 消息解析器完成（支持数组格式）

**Phase 4B.5 — WebSocket Smoke Test:**
- 真实 WebSocket 验证通过
- URL: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- 订阅格式: `{"type": "subscribe", "channel": "market", "assets_ids": [...]}`
- 返回消息是数组，没有 `type` 字段

**Phase 4 Audit:**
- 真实数据层审计完成
- 协议细节已记录
- 文档已更新

**Phase 4C — Real LLM Providers:**
- SenseNova Provider 完成（OpenAI-compatible）
- XFyun Anthropic Provider 完成（Anthropic-compatible）
- Provider Router 更新
- 配置更新

**Phase 4C.5 — LLM Smoke Test:**
- XFyun Anthropic: Event ✅ (26s), Rule ✅ (17s) — **Recommended**
- SenseNova: Event ✅ (39s), Rule ❌ (timeout)
- 588/588 tests passed

**Phase 4C Audit:**
- API key 安全检查通过
- Forbidden fields 检查正确
- Fallback 策略正确
- LLM 不触发交易
- 审计报告完成

完成标准：

- 公开数据不需要认证 ✅
- API 失败时降级到 mock ✅
- 测试不依赖真实 API ✅
- live_trading_enabled 保持 false ✅
- WebSocket 协议验证通过 ✅
- LLM smoke test 通过 ✅
- LLM audit 通过 ✅
- 588/588 tests passed ✅

下一步：Phase 5 — 24h Paper Trading Run

---

## Phase 5A — 30-Minute Dry Run

状态：✅ Completed

结果：

- scripts/run_paper.py 完成
- RunConfig / RunStatistics 完成
- Safety checks 完成
- Rate limiting 完成
- Report generation 完成
- SQLite tables (paper_runs, paper_run_scans, paper_run_events) 完成
- tests/test_paper_run.py 完成
- docs/phase_5_dry_run.md 完成

完成标准：

- live_trading_enabled = false ✅
- allow_auto_execution = false ✅
- paper_trading_enabled = true ✅
- No real orders ✅
- No private keys ✅
- Conservative defaults ✅
- Real LLM requires explicit limit ✅
- Telegram disabled by default ✅
- Graceful shutdown ✅
- Report files generated ✅

下一步：Phase 5B — 3-Hour Paper Trading Run

---

## Phase 5B — 3-Hour Paper Trading Run

状态：✅ Completed

---

## Phase 5C — 10-Hour Real Readonly Overnight Stability Run

状态：✅ Completed

run_id: `run_20260508_155427_612f24ff`

结果：

- duration: 10h 01m
- real_markets_fetched: 27,800
- markets_checked: 5,560
- orderbooks_fetched: 5,560
- websocket_messages: 171
- api_errors: 1 (transient, handled gracefully)
- critical_errors: 0
- signals_generated: 0
- paper_trades_created: 0
- reports generated: summary.json, report.md, events.jsonl

完成标准：

- live_trading_enabled = false ✅
- allow_auto_execution = false ✅
- paper_trading_enabled = true ✅
- No real orders ✅
- No private keys ✅
- No crashes ✅
- Graceful shutdown ✅
- Reports generated ✅

下一步：Phase 5D — Limited Real LLM Run

---

## Phase 5D — Limited Real LLM Run

状态：🔮 Next

条件：

- Phase 5C completed ✅
- 10-hour run successful ✅
- All tests passed ✅
- combined_ask distribution added to summary ✅

目标：

- 运行 2-4 小时
- 使用真实 LLM (xfyun_anthropic)
- Max LLM calls/hour: 5-10
- 验证 LLM 集成稳定性
- 收集真实 event analysis 数据

---

## Phase 5D.1 — LLM Sampling Mode

状态：✅ Completed

结果：

- 739/739 tests passed
- LLM Sampling Mode 实现
- `--enable_llm_sampling` 参数添加
- `--llm_sampling_per_scan` 参数添加
- 候选市场选择逻辑实现
- Rate limiting 强制执行
- events.jsonl 日志记录 (event_type: llm_sampling_assessment)
- summary.json 和 report.md 包含 LLM sampling 统计

关键验收：

- LLM sampling 独立于交易信号路径 ✅
- LLM sampling 不触发 PaperTrader ✅
- Rate limiting 正确执行 ✅
- 安全检查拒绝 mock provider ✅
- 安全检查拒绝无 rate limit 配置 ✅
- 测试覆盖完整 (27 new tests) ✅
- 真实 LLM 调用验证成功 ✅
- 平均延迟 ~0.10s ✅

下一步：Phase 5D.2 — Extended LLM Sampling Run (2-4 hours)

---

## Phase 5D.2 — 4-Hour LLM Sampling Run

状态：✅ Completed

run_id: `run_20260509_112002_8977ca4e`

结果：

- duration: 4 hours
- llm_sampling_calls_attempted: 20
- llm_sampling_calls_succeeded: 18
- llm_sampling_calls_failed: 2
- llm_sampling_avg_latency: 26.19s
- sampled_markets_count: 20

关键验收：

- LLM sampling 稳定运行 4 小时 ✅
- Rate limiting 正确执行 ✅
- 错误处理正确 ✅
- 报告生成正确 ✅

下一步：Phase 5D.3 — Audit & Metrics Fix

---

## Phase 5D.3 — Audit & Metrics Fix

状态：✅ Completed

结果：

- 780/780 tests passed
- P95 latency calculation bug fixed
- LLM error type distribution added
- API error source distribution added
- WebSocket reconnect summary added
- Audit document created

关键验收：

- P95 latency 正确计算 ✅
- 错误分类正确 ✅
- WebSocket 重连统计正确 ✅
- 测试覆盖完整 ✅

下一步：Phase 5E — Market Intelligence Report

---

## Phase 5E — Market Intelligence Report / Alpha Discovery

状态：✅ Completed

结果：

- 814/814 tests passed
- scripts/analyze_run_intelligence.py 完成
- tests/test_analyze_run_intelligence.py 完成 (40 new tests)
- Near-miss tier classification (Tier 1-4)
- Heuristic market category inference
- Correlation calculation with sample size protection
- Top candidates sections
- CSV export
- Safety verification

关键验收：

- Offline analysis only (no real-time API calls) ✅
- No trading execution ✅
- live_trading_enabled remains false ✅
- Near-miss tier classification ✅
- Category inference (heuristic) ✅
- Correlation with sample size protection ✅
- Top candidates sections ✅
- CSV export ✅
- 40 new tests ✅

下一步：Phase 5F — Multi-Run Intelligence Comparison

---

## Phase 5F — Multi-Run Intelligence Comparison

状态：✅ Completed

结果：

- 870/870 tests passed
- scripts/compare_run_intelligence.py 完成
- tests/test_compare_run_intelligence.py 完成 (56 new tests)
- RunDiscovery (--latest_n, --since, --run_ids)
- RunDataLoader (intelligence_summary.json, summary.json, events.jsonl)
- MarketAggregator with market_id/normalized_question fallback
- PersistentWatchlistGenerator with evidence_level
- AlphaCandidateScorer with DISCLAIMER
- AvoidCandidateScorer with category_risk (NOT hard_forbidden)
- CategoryAnalyzer
- ComparisonReportGenerator

关键验收：

- Offline analysis only ✅
- No trading execution ✅
- live_trading_enabled remains false ✅
- Alpha DISCLAIMER: "heuristic research ranking, NOT a trading signal" ✅
- Avoid uses category_risk, NOT hard_forbidden ✅
- Evidence level (weak/moderate/strong) ✅
- Market identity fallback ✅
- Top N limit ✅
- 56 new tests ✅

下一步：Phase 5G — Dashboard Integration (Optional)

---

## Phase 5F.5 — Watchlist-Driven Monitoring

状态：✅ Completed

结果：

- ~900+ tests passed
- WatchlistLoader 完成 (加载 persistent_watchlist.csv, alpha_candidates.csv, avoid_candidates.csv, market_trajectories.json)
- MarketPrioritizer 完成 (市场优先级排序)
- AvoidAnnotator 完成 (Avoid 风险标注，仅研究用途)
- TrajectoryTracker 完成 (轨迹跟踪)
- WatchlistMonitoringStats 完成 (统计数据)
- scripts/run_paper.py 新增 watchlist 参数
- tests/test_watchlist_monitoring.py 完成 (30+ new tests)

关键验收：

- Watchlist 只影响扫描顺序，不影响交易决策 ✅
- Avoid annotation 仅做研究标注，不是 hard forbidden ✅
- 不修改 Risk Governor ✅
- 不修改 Signal 模型 ✅
- 不修改策略 ✅
- 向后兼容（无 watchlist 时行为不变） ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅

输出文件：

- watchlist_monitoring_summary.json
- watchlist_monitoring_report.md
- watchlist_trajectory_update.json
- watchlist_events.jsonl

下一步：Phase 5G.1 — Dashboard MVP

---

## Phase 5G.1 — Dashboard MVP

状态：✅ Completed

结果：

- 955/955 tests passed
- polysignal/interface/dashboard.py 完成 (READ-ONLY Streamlit Dashboard)
- scripts/run_dashboard.py 完成 (启动脚本 + --check)
- tests/test_dashboard.py 完成 (61 new tests)
- DashboardDataLoader 完成 (runs/ 数据加载)
- RunSummary / IntelligenceSummary / ComparisonSummary 完成
- SafetyStatus 完成 (config/risk.yaml 读取)
- 5 个页面: Overview, Run Details, LLM Performance, Intelligence Summary, Watchlist/Alpha/Avoid
- AST-based import safety check

关键验收：

- Dashboard 只读 ✅
- 不写入 runs/ 或 config/ ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不调用真实 API 或 LLM ✅
- 不提供交易按钮 ✅
- localhost only (默认 8501) ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅
- Missing files graceful handling ✅
- 61 new tests ✅

下一步：Phase 6 — Strategy Signal Validation

---

## Phase 6 — Strategy Signal Validation

状态：✅ Completed

结果：

- 1025/1025 tests passed
- scripts/validate_strategy_signals.py 完成 (offline validation framework)
- tests/test_validate_strategy_signals.py 完成 (70 new tests)
- ValidationDataLoader 完成 (alpha/avoid/watchlist/trajectories/events)
- AlphaValidator 完成 (forward change: first/last/min/max, delta, slope, conclusion_status)
- WatchlistValidator 完成 (persistence score, near-miss hits)
- AvoidValidator 完成 (single + group comparison with control group)
- CategoryValidator 完成 (per-category signal quality)
- EventScoreCorrelationValidator 完成 (Pearson correlation with sample size protection)
- conclusion_status 框架实现 (observed/insufficient_data/inconclusive/insufficient_control_group)
- ValidationReportGenerator 完成 (MD + JSON + CSV exports)
- AST safety audit 通过

验证结果：

| 研究问题 | conclusion_status |
|----------|-------------------|
| Q1: Alpha forward change | inconclusive (2/20 observed) |
| Q2: Avoid risk validation | observed after Phase 6.5A.5 control group validation |
| Q3: Watchlist persistence | observed (4/4) |
| Q4: Event score correlation | observed (r=-0.256, n=14) |
| Q5: Category performance | observed (3 categories) |

关键验收：

- READ-ONLY: 不触发交易、不修改配置、不调用 API ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- conclusion_status 框架实现 ✅
- Alpha forward change 完整指标输出 ✅
- Avoid control group 定义正确 ✅
- AST 安全审计通过 ✅
- live_trading_enabled 保持 false ✅
- 70 new tests ✅

下一步：Phase 6.5A — Control Group Sampling Patch

---

## Phase 6.5A — Control Group Sampling Patch

状态：✅ Completed

结果：

- 1049/1049 tests passed
- RunConfig 新增 control_group_sampling_ratio, exclude_avoid_from_control_group
- _select_control_group_candidates() 完成 (category diversity, exclude avoid/alpha/watchlist)
- _run_control_group_sampling() 完成 (reuses _perform_llm_sampling, rate limited)
- _generate_control_group_reports() 完成 (control_group_samples.csv, validation_loop_summary.json)
- validate_strategy_signals.py 更新 (load_control_group_samples, validate_group_comparison 接受 control_group_samples)
- tests/test_validation_loop.py 完成 (22 new tests)
- tests/test_validate_strategy_signals.py 更新 (2 new tests)
- Phase 6.5A.1 Category Inference Patch 完成
- Phase 6.5A.5 Control Group Data Collection + Validation 完成
- run_id: `run_20260510_105908_73831203`
- control_group_samples.csv generated
- control_group_samples: 36 rows
- unique_control_group_markets: 36
- control_group_assessment events: 36
- control_group_samples loaded by offline validation: 42

关键验收：

- control_group_sampling_ratio 默认 0，不影响旧行为 ✅
- control group 排除 avoid / alpha / watchlist ✅
- control group category 多样性 ✅
- control_group_assessment 不触发交易 ✅
- control_group_samples.csv 正确生成 ✅
- validate_strategy_signals.py 能读取 control_group_samples.csv ✅
- avoid validation 使用 control group 作为 non-avoid group ✅
- Q1 alpha forward change 仍为 inconclusive ✅
- Q2 avoid risk validation 更新为 observed ✅
- Q2 non_avoid_group size = 21 ✅
- ambiguity delta = +9.0 ✅
- signals_generated = 0 ✅
- paper_trades_created = 0 ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅
- paper_trading_enabled 保持 true ✅
- default LLM provider 保持 mock ✅
- 22 new tests ✅

下一步：Phase 6.5B — Alpha Repeated Observation Run

---

## Phase 6.5B — Alpha Repeated Observation Run

状态：✅ Implementation Completed

目标：

- 继续 read-only research validation
- 对 alpha candidates 做 repeated observation
- 提高 Q1 alpha forward change 的样本覆盖
- 保持 live_trading_enabled=false
- 保持 allow_auto_execution=false
- 不修改 Risk Governor

实现：

- scripts/run_paper.py 新增 `--alpha_priority_ratio`，默认 0.0
- scripts/run_paper.py 新增 `--alpha_repeat_target`，默认 3
- alpha slots = min(int(max_markets * alpha_priority_ratio), remaining alpha candidates needing observations)
- 达到 repeat target 的 alpha market 降低优先级
- discovery_ratio 最低保持 0.1
- 输出 alpha_repeat_observation_summary.json
- 输出 alpha_repeat_observation_report.md
- scripts/validate_strategy_signals.py 更新 alpha conclusion tiers:
  - 1 observation: insufficient_data
  - 2 observations: weak_descriptive
  - 3-4 observations: preliminary_observed
  - >=5 observations: stronger_observed
- pytest tests/ -v: 1071/1071 passed

安全约束：

- alpha_priority_ratio 只影响扫描优先级
- alpha_score 不生成 signal
- alpha_score 不触发 PaperTrader
- alpha_score 不改变 Risk Governor score
- alpha_score 不新增 hard reject / allow reason
- live_trading_enabled=false
- allow_auto_execution=false
- paper_trading_enabled=true
- default LLM provider=mock

下一步：Phase 7A — Cloud Deployment Checklist

---

## Phase 7A — Cloud Deployment Checklist

状态：✅ Documentation Completed

目标：

- 将长时间 data collection 从本地手动等待迁移到云服务器
- 文档化 read-only + paper-only 云端部署流程
- 保持本地开发只跑 pytest 和短 smoke test
- 不新增自动化脚本
- 不修改业务代码

实现：

- 新增 docs/cloud_deployment_checklist.md
- 记录推荐服务器配置：2 vCPU, 4GB RAM minimum / 8GB preferred, 40-80GB SSD, Ubuntu 22.04/24.04 LTS
- 记录 /opt/polysignal 云端目录结构
- 记录 Linux 用户、权限、.env chmod 600、SSH key login 建议
- 记录部署步骤、环境变量说明、安全检查命令
- 记录云端首次验证流程和 5-minute smoke commands
- 记录 tmux 手动运行方案
- 预告 Phase 7C systemd service / timer
- 记录日志、备份、dashboard 安全访问和故障排查

安全约束：

- live_trading_enabled=false
- allow_auto_execution=false
- paper_trading_enabled=true
- default LLM provider=mock
- 不接入实盘
- 不处理私钥
- 不修改 Risk Governor
- 不开放公网 Dashboard
- .env 不进 Git

下一步：Phase 7B — Validation Loop Script

---

## Phase 7B — Validation Loop Script

状态：✅ Completed

目标：

- 新增云端可运行的 validation loop 编排脚本
- 执行一次 read-only + paper-only data collection run
- run 完成后自动执行 validation / intelligence / comparison 报告生成
- 输出 runs/validation_loop_summary.json
- 支持 --dry_run 和 --skip_run

实现：

- 新增 scripts/run_validation_loop.py
- 新增 tests/test_run_validation_loop.py
- 更新 docs/cloud_deployment_checklist.md 脚本用法
- python3 -m pytest tests/ -v: 1084/1084 passed
- dry_run checked without executing run_paper.py

安全约束：

- live_trading_enabled=false
- allow_auto_execution=false
- paper_trading_enabled=true
- default LLM provider=mock
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不修改 Risk Governor
- 不修改策略
- 不新增 systemd service
- 不接入实盘

下一步：Phase 7C — systemd/tmux Running Plan

---

## Phase 7C — systemd/tmux Running Plan

状态：✅ Completed

目标：

- 为云服务器上的长期 data collection 提供标准运行方案
- 文档化 tmux 手动长跑流程
- 文档化 systemd service / timer 模板
- 记录日志路径、状态查看、停止和禁用命令
- 保持 read-only + paper-only，不接入实盘

实现：

- 新增 docs/cloud_running_plan.md
- 新增 deploy/systemd/polysignal-validation.service.example
- 新增 deploy/systemd/polysignal-validation.timer.example
- 更新 docs/cloud_deployment_checklist.md Phase 7C 链接
- 更新 CONTEXT / TASKS / ROADMAP
- targeted pytest: tests/test_run_validation_loop.py passed

安全约束：

- 不运行 systemctl
- 不启动长任务
- 不运行 overnight
- 不接入实盘
- 不处理私钥
- 不修改 config/risk.yaml
- 不修改 scripts/run_paper.py
- 不修改 Risk Governor
- 不修改策略
- live_trading_enabled=false
- allow_auto_execution=false
- paper_trading_enabled=true
- default LLM provider=mock

下一步：Phase 7D — Daily Report Automation

---

## Phase 7D — Daily Report Automation

状态：✅ Completed

目标：

- 新增离线 daily report 脚本
- 汇总最近 runs、validation、intelligence comparison、watchlist、alpha/avoid candidates
- 生成 daily_report.md 和 daily_report_summary.json
- 保持本阶段完全 offline/read-only

实现：

- 新增 scripts/generate_daily_report.py
- 新增 tests/test_generate_daily_report.py
- 更新 docs/cloud_running_plan.md daily report 说明
- 更新 docs/cloud_deployment_checklist.md Phase 7D 链接
- 更新 CONTEXT / TASKS / ROADMAP
- python3 -m pytest tests/ -v: 1098/1098 passed
- dry_run checked without writing report files
- daily_report.md generated
- daily_report_summary.json generated

安全约束：

- 不运行 run_paper.py
- 不调用真实 API
- 不调用真实 LLM
- 不接入实盘
- 不处理私钥
- 不修改 config
- 不修改 Risk Governor
- 不修改策略
- 不让 alpha_score 变成交易信号
- 不自动下单

下一步：Phase 8A — Shadow Paper Trading Engine Core

---

## Phase 8A — Shadow Paper Trading Engine Core

状态：✅ Completed

目标：

- 建立独立 Shadow Trading 核心引擎
- 离线验证“如果系统自主交易，会不会赚钱”
- 生成 hypothetical entry / exit / PnL
- 输出 shadow trade ledger 和 paper performance summary
- 保持与 PaperTrader / live execution 完全隔离

实现：

- 新增 polysignal/shadow/models.py
- 新增 polysignal/shadow/entry_filter.py
- 新增 polysignal/shadow/exit_rules.py
- 新增 polysignal/shadow/pnl.py
- 新增 polysignal/shadow/reporter.py
- 新增 scripts/run_shadow_paper_loop.py
- 新增 tests/test_shadow_trading.py
- dry_run checked without writing shadow outputs
- python3 -m pytest tests/ -v: 1122/1122 passed

安全约束：

- Shadow Trading 不是 PaperTrader
- 不导入 LiveTrader
- 不导入 PaperTrader
- 不调用真实 API
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改策略逻辑
- 不修改 config/risk.yaml
- 不让 alpha_score 变成真实交易信号
- 不自动下单

下一步：Phase 8B — Shadow Entry Filter Calibration

---

## Phase 8B — Shadow Entry Filter Calibration

状态：✅ Completed

目标：

- 诊断为什么当前 20 个 alpha candidates 都没有进入 shadow entry
- 增加 eligible_shadow_entry / watch_only / rejected 三层决策
- 输出结构化 reject_reasons 和 watch_reasons
- 保持 alpha_score 不能单独触发 eligible_shadow_entry
- 为后续真实 paper performance loop 准备可解释 entry filter

实现：

- 增强 polysignal/shadow/entry_filter.py
- 增强 scripts/run_shadow_paper_loop.py diagnostics
- 增强 polysignal/shadow/reporter.py diagnostics output
- 更新 tests/test_shadow_trading.py
- dry_run diagnostics:
  - candidates_loaded: 20
  - eligible_shadow_entry: 0
  - watch_only: 0
  - rejected: 20
  - top_rejection_reasons: avoid_candidate=20, high_ambiguity=2
- python3 -m pytest tests/ -v: 1132/1132 passed

安全约束：

- 不接入实盘
- 不处理私钥
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 API / 真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改策略逻辑
- 不修改 config/risk.yaml
- 不让 alpha_score 变成真实交易信号
- 不自动下单

下一步：Phase 8C — Tradable Candidate Pool Construction

---

## Phase 8C — Tradable Candidate Pool Construction

状态：✅ Completed

目标：

- 建立独立 tradable candidate pool
- 从现有 runs/ 数据中筛选 non-avoid、low-ambiguity、liquid、near-miss 或 watchlist-improving candidates
- 将 alpha_candidates 与 tradable_candidates 解耦
- 保持 tradable_score 只用于 research/shadow priority，不作为交易信号
- 让 shadow loop 优先读取 tradable_candidates.csv，并保留旧逻辑 fallback

实现：

- 新增 polysignal/shadow/tradable_candidates.py
- 新增 scripts/build_tradable_candidates.py
- 更新 scripts/run_shadow_paper_loop.py 以优先读取 runs/tradable_candidates.csv
- 新增 tests/test_tradable_candidates.py
- 生成 runs/tradable_candidates.csv
- 生成 runs/tradable_candidates.json
- 生成 runs/tradable_candidate_report.md

当前结果：

- candidates_considered: 64
- tradable_candidates: 34
- excluded_avoid_candidates: 28
- exclusion_summary: avoid_candidate=28, high_ambiguity=7, missing_combined_ask=1
- shadow dry_run: eligible_shadow_entry=0, watch_only=34, rejected=0

安全约束：

- tradable_score is a research/shadow priority score, not a trading signal
- tradable candidates 仍必须经过 Shadow Entry Filter
- avoid candidates 仍硬排除
- 不接入实盘
- 不处理私钥
- 不自动下单
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 API / 真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor / 策略 / config/risk.yaml

验证：

- python3 -m pytest tests/ -v: 1150/1150 passed

下一步：Phase 8D — Tradable Candidate Shadow Entry Calibration

---

## Phase 8D — Tradable Candidate Shadow Entry Calibration

状态：✅ Completed

目标：

- 让 Shadow Entry Filter 正确理解 tradable_candidates.csv
- 从 alpha_score-centric 升级为 tradable-evidence-centric
- missing alpha_score 不再自动阻断 tradable candidates
- 在严格质量门槛下允许高质量 tradable candidates 进入 eligible_shadow_entry
- 保持 eligible_shadow_entry 仅用于 hypothetical shadow trading

实现：

- 扩展 polysignal/shadow/models.py CandidateSnapshot
- 更新 polysignal/shadow/entry_filter.py tradable evidence logic
- 更新 scripts/run_shadow_paper_loop.py tradable candidate parsing
- 更新 tests/test_shadow_trading.py
- 更新 tests/test_tradable_candidates.py

当前结果：

- shadow dry_run candidates_loaded: 34
- eligible_shadow_entry: 5
- watch_only: 29
- rejected: 0
- top_rejection_reasons: {}
- missing_alpha_score 不再作为主要误导性原因

安全约束：

- tradable_score 不是实盘交易信号
- alpha_score 不是实盘交易信号
- eligible_shadow_entry 不是实盘许可
- avoid candidates 仍然硬排除
- 不接入实盘
- 不处理私钥
- 不自动下单
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 API / 真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor / 策略 / config/risk.yaml

验证：

- python3 -m pytest tests/ -v: 1158/1158 passed

下一步：Phase 8E — Shadow Paper Performance Evaluation

---

## Phase 8E — Shadow Paper Performance Evaluation

状态：✅ Completed

目标：

- 基于 eligible_shadow_entry 生成离线 shadow trades
- 输出 shadow trade ledger / positions / performance summary / report
- 在 forward data 不足时明确标记 insufficient_forward_data
- 不伪造 PnL

实现：

- 更新 polysignal/shadow/models.py
- 更新 polysignal/shadow/pnl.py
- 更新 polysignal/shadow/reporter.py
- 更新 scripts/run_shadow_paper_loop.py
- 更新 tests/test_shadow_trading.py

当前结果：

- shadow_trades: 5
- closed_positions: 0
- open_positions: 0
- insufficient_forward_data_positions: 5
- total_pnl: 0.0
- win_rate: 0.0
- max_drawdown: 0.0
- forward data limitation: yes

安全约束：

- Shadow performance is hypothetical and not a live trading result
- 不接入实盘
- 不处理私钥
- 不自动下单
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 API / 真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor / 策略 / config/risk.yaml

验证：

- python3 -m pytest tests/ -v: 1162/1162 passed
- python3 scripts/run_shadow_paper_loop.py --diagnostics

下一步：Phase 8F.1 — Offline Forward Observation Collector

---

## Phase 8F.1 — Offline Forward Observation Collector

状态：✅ Completed

目标：

- 为 Phase 8E 的 shadow positions 收集离线 forward observations
- 只读取已有 runs / trajectories / shadow files
- 有真实 forward observations 时更新 exit / PnL
- 没有 forward observations 时继续标记 insufficient_forward_data
- 不伪造 exit_price / PnL

实现：

- 新增 polysignal/shadow/forward_observations.py
- 新增 scripts/collect_shadow_forward_data.py
- 新增 tests/test_shadow_forward_data.py
- 更新 CONTEXT.md / TASKS.md / ROADMAP.md

当前结果：

- forward_observations.jsonl generated: yes
- forward observations found: 0
- updated_shadow_positions.json generated: yes
- updated_shadow_trades.csv generated: yes
- paper_performance_summary.json updated: yes
- paper_performance_report.md updated: yes
- closed_positions: 0
- open_positions: 0
- insufficient_forward_data_positions: 5
- total_pnl: 0.0
- win_rate: 0.0
- max_drawdown: 0.0
- forward data limitation: yes

安全约束：

- 不接入实盘
- 不处理私钥
- 不自动下单
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 API / 真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor / 策略 / config/risk.yaml
- 不伪造 PnL

验证：

- python3 -m pytest tests/ -v: 1179/1179 passed
- python3 scripts/collect_shadow_forward_data.py --dry_run
- python3 scripts/collect_shadow_forward_data.py

下一步：Phase 8F.2 — Read-only Forward Price Polling for Shadow PnL

---

## Phase 8F.2 — Read-only Forward Price Polling for Shadow PnL

状态：✅ Completed

目标：

- 为 open / insufficient_forward_data shadow positions 拉取只读 CLOB forward prices
- 只使用公开 CLOB REST orderbook endpoints
- token_id 缺失时明确诊断 missing_token_id
- 不把 market_id 当 token_id
- 不伪造 observation / exit / PnL

实现：

- 扩展 polysignal/shadow/forward_observations.py
- 新增 ShadowTokenIdResolver
- 新增 scripts/poll_shadow_forward_prices.py
- 新增 tests/test_shadow_forward_polling.py
- 更新 CONTEXT.md / TASKS.md / ROADMAP.md

当前结果：

- positions_loaded: 5
- positions_polled: 0
- observations_written: 0
- missing_token_id_count: 5
- api_error_count: 0
- forward_poll_summary.json generated: yes
- forward_observations.jsonl remains empty: yes
- updated_positions: true
- closed_positions: 0
- insufficient_forward_data_positions: 5
- total_pnl: 0.0
- win_rate: 0.0
- max_drawdown: 0.0

说明：

- 当前 5 个 shadow positions 缺少 yes_token_id / no_token_id
- 因此 --once 没有发起 CLOB orderbook request
- 没有伪造 forward observation 或 PnL

安全约束：

- 不接入实盘
- 不处理私钥
- 不认证 / 不签名
- 不提交订单 / 不撤单
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor / 策略 / config/risk.yaml

验证：

- python3 -m pytest tests/ -v: 1195/1195 passed
- python3 scripts/poll_shadow_forward_prices.py --dry_run
- python3 scripts/poll_shadow_forward_prices.py --once --max_positions 5

下一步：Phase 8G.1 — Offline Token ID Backfill

---

## Phase 8G.1 — Offline Token ID Backfill

状态：✅ Completed

目标：

- 从已有 runs/ artifacts 离线恢复 YES/NO CLOB token IDs
- 让 tradable candidates / shadow trades / shadow positions 支持 token 字段
- 无法恢复时明确 missing_token_id
- 不调用网络，不调用 Gamma/CLOB/LLM，不运行 run_paper.py

实现：

- 更新 polysignal/shadow/models.py
- 更新 polysignal/shadow/tradable_candidates.py
- 更新 scripts/build_tradable_candidates.py
- 更新 scripts/collect_shadow_forward_data.py
- 更新 scripts/poll_shadow_forward_prices.py
- 新增 scripts/backfill_shadow_token_ids.py
- 新增 tests/test_shadow_token_backfill.py
- 更新 tests/test_shadow_trading.py

当前 dry_run 结果：

- markets_scanned: 101
- token_pairs_found: 0
- shadow_trades_loaded: 5
- shadow_trades_backfilled: 0
- shadow_trades_missing_token_id: 5
- tradable_candidates_loaded: 34
- tradable_candidates_backfilled: 0
- api_lookup_enabled: false

结论：

- 本地 artifacts 中没有当前 shadow positions 可用的 token metadata
- 没有伪造 token id
- 没有把 market_id 当 token_id
- 没有写 *_with_tokens 输出
- 没有 rerun forward polling，因为 missing_token_id_count 不会改善

安全约束：

- 不接入实盘
- 不处理私钥
- 不认证 / 不签名
- 不提交订单 / 不撤单
- 不导入 LiveTrader / PaperTrader / RiskGovernor
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor / 策略 / config/risk.yaml

验证：

- python3 -m pytest tests/ -v: 1209/1209 passed
- python3 scripts/backfill_shadow_token_ids.py --dry_run

下一步完成：Phase 8G.2 — Read-only Gamma Token ID Lookup

---

## Phase 8G.2 — Read-only Gamma Token ID Lookup

状态：✅ Completed

目标：

- 在显式 `--allow_api_lookup` 时使用 public Gamma read-only API 恢复 YES/NO CLOB token IDs
- 不认证、不签名、不处理私钥、不下单、不撤单
- 为 shadow forward polling 提供真实 token ids
- 打通 shadow token backfill -> CLOB read-only polling -> hypothetical PnL update

结果：

- scripts/backfill_shadow_token_ids.py 新增 GammaTokenLookupClient
- 支持 direct market id lookup
- 支持 exact normalized question search fallback
- 支持 --max_api_calls / --api_timeout_seconds / --api_cache_file
- 支持 clobTokenIds / clob_token_ids / outcomes 的 list 与 JSON string 格式
- outcomes 顺序反转时仍能正确映射 YES / NO
- ambiguous market match / ambiguous outcome mapping / unsupported market structure 均明确记录
- 不把 market_id 当 token_id
- ShadowTokenIdResolver 优先读取 backfilled files
- tests/test_shadow_token_backfill.py 扩展到 Gamma lookup 场景

验证：

- python3 -m pytest tests/ -v: 1219/1219 passed
- python3 scripts/backfill_shadow_token_ids.py --dry_run
- python3 scripts/backfill_shadow_token_ids.py --allow_api_lookup --max_api_calls 5
- python3 scripts/poll_shadow_forward_prices.py --once --max_positions 5

dry_run 结果：

- token_pairs_found: 0
- shadow_trades_loaded: 5
- shadow_trades_missing_token_id: 5
- api_lookup_enabled: false
- api_calls_used: 0

allow_api_lookup 结果：

- api_calls_used: 5
- api_lookup_successes: 5
- api_lookup_failures: 0
- ambiguous_market_matches: 0
- ambiguous_outcome_mappings: 0
- unsupported_market_structures: 0
- market_lookup_not_found: 0
- token_pairs_found: 5
- shadow_trades_backfilled: 5
- shadow_trades_missing_token_id: 0

forward polling 结果：

- positions_loaded: 5
- positions_polled: 5
- observations_written: 5
- missing_token_id_count: 0
- api_error_count: 0
- closed_positions: 5
- insufficient_forward_data_positions: 0
- total_pnl: -4.62937062937063
- win_rate: 0.0
- max_drawdown: -4.62937062937063

关键验收：

- no live trading ✅
- no private key handling ✅
- no authentication / signing ✅
- no order placement / cancellation ✅
- no real LLM ✅
- no run_paper.py ✅
- no Risk Governor / strategy / config/risk.yaml changes ✅
- live_trading_enabled=false ✅
- allow_auto_execution=false ✅
- paper_trading_enabled=true ✅

下一步完成：Phase 8H — Shadow Performance Review Gate

---

## Phase 8H — Shadow Performance Review Gate

状态：✅ Completed

目标：

- 对首批 5 个 closed shadow trades 做离线亏损归因
- 解释 win_rate=0、total_pnl=-4.62937062937063 的原因
- 给出下一阶段 filter calibration 建议
- 不修改交易逻辑，不接入实盘，不运行 run_paper.py

结果：

- 新增 scripts/review_shadow_performance.py
- 新增 tests/test_shadow_performance_review.py
- 输出 runs/shadow/shadow_performance_review.md
- 输出 runs/shadow/shadow_performance_review_summary.json
- 输出 runs/shadow/shadow_trade_diagnostics.csv

验证：

- python3 -m pytest tests/ -v: 1236/1236 passed
- python3 scripts/review_shadow_performance.py --dry_run
- python3 scripts/review_shadow_performance.py

review 结果：

- trades_reviewed: 5
- losing_trades: 5
- winning_trades: 0
- total_pnl: -4.62937062937063
- win_rate: 0.0
- max_drawdown: -4.62937062937063
- primary_loss_drivers: price_interpretation_risk=5
- spread_drag_count: 0
- weak_evidence_count: 5
- control_group_source_count: 5
- expected_edge_missing_count: 5
- exit_timing_risk_count: 0
- price_interpretation_risk_count: 5
- tiny_live_recommendation: NO

关键结论：

- 主要亏损原因不是 exit spread 过宽
- 核心问题是 entry 使用 combined_ask near 1.0，而 exit 使用 side bid，entry/exit price semantics 不一致
- control_group-only candidates 不应被视为 executable shadow entries
- 当前缺少 explicit expected edge filter
- 当前不进入 tiny live

建议下一步：

- Phase 8I follow-up completed; Phase 8J corrected entry price collection completed
- 使用 side-specific executable entry price
- 要求 expected_edge > spread + buffer
- 降低或排除 control_group-only candidates 的 eligible_shadow_entry 权重
- 要求 Tier1/Tier2 near-miss evidence
- 区分 research watchlist 与 executable shadow entry

下一步完成：Phase 8I — Price Model & Entry Filter Calibration

---

## Phase 8I — Price Model & Entry Filter Calibration

状态：✅ Completed

目标：

- 修正 shadow trading 的 side-specific entry/exit price model
- 禁止 combined_ask 作为 YES/NO 单边 entry price
- 基于 Phase 8H 亏损归因收紧 entry filter
- 不接入实盘，不调用 API/LLM，不运行 run_paper.py

结果：

- Shadow models 增加 side-specific price 字段
- YES entry 使用 yes_best_ask
- NO entry 使用 no_best_ask
- YES exit 使用 yes_best_bid
- NO exit 使用 no_best_bid
- combined_ask 只保留为 market-level feature
- missing side ask 不再 eligible
- missing side bid 不再 close position
- control_group-only 默认 watch_only
- expected_edge > spread + buffer gate 生效
- 新增 scripts/audit_shadow_price_model.py
- 新增 tests/test_shadow_price_model_audit.py
- 更新 tests/test_shadow_trading.py
- 更新 scripts/review_shadow_performance.py
- python3 -m pytest tests/ -v: 1254/1254 passed

price model audit:

- trades_reviewed: 5
- combined_ask_entry_detected_count: 5
- invalid_entry_price_model_count: 5
- missing_entry_side_price_count: 5
- corrected_pnl_available_count: 0
- corrected_pnl_unavailable_count: 5
- price_interpretation_risk_count: 5
- tiny_live_recommendation: NO

shadow loop dry_run diagnostics:

- candidates_loaded: 34
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- missing_side_ask: 34
- invalid_entry_price_model: 34

关键结论：

- 旧 PnL invalid / not reliable
- corrected price model 不再生成 combined_ask-based entries
- 当前需要新的 side-specific entry ask / expected_edge 数据后才能重新评估 shadow PnL
- tiny live 仍然 NO

下一步完成：Phase 8J — Corrected Entry Price Collection / Candidate Rebuild

---

## Phase 8J — Corrected Entry Price Collection / Candidate Rebuild

状态：✅ Completed

目标：

- 为 tradable candidates 获取 public read-only CLOB side-specific price snapshot
- 补齐 `yes_best_bid`, `yes_best_ask`, `no_best_bid`, `no_best_ask`
- 计算 spread / combined_ask / liquidity proxy / expected_edge proxy
- 让 shadow dry_run 使用 corrected priced candidates
- 保持 `combined_ask` 为 market-level feature only，不作为 side-specific entry price

结果：

- `scripts/refresh_tradable_candidate_prices.py` added
- `tests/test_tradable_candidate_price_refresh.py` added
- `scripts/run_shadow_paper_loop.py` now prefers `runs/tradable_candidates_priced.csv`
- `python3 -m pytest tests/ -v`: 1266 passed, 8 warnings
- `runs/tradable_candidates_priced.csv` generated
- `runs/tradable_candidates_priced.json` generated
- `runs/tradable_candidate_price_refresh_summary.json` generated
- `runs/tradable_candidate_price_report.md` generated

read-only refresh:

- candidates_loaded: 34
- candidates_priced: 5
- missing_token_id_count: 29
- empty_orderbook_count: 0
- api_error_count: 0
- yes_ask_available_count: 5
- no_ask_available_count: 5
- side_ask_available_count: 5
- expected_edge_available_count: 0

shadow dry_run diagnostics:

- candidates_loaded: 34
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- missing_side_ask decreased from 34 to 29
- current blocker: missing token ids for 29 candidates; priced control-group candidates lack executable expected edge

安全状态：

- live_trading_enabled=false ✅
- allow_auto_execution=false ✅
- paper_trading_enabled=true ✅
- default LLM provider=mock ✅
- no authenticated API ✅
- no live orders ✅
- no real LLM ✅
- no run_paper.py ✅
- tiny_live_recommendation=NO ✅

下一步：Phase 8K — Token Coverage / Expected Edge Calibration

---

## Milestone 5 — Optional Tiny Live Limit Order

状态：🔮 Future / Optional

条件：

- paper trading >= 14 days
- paper trades >= 100
- max drawdown acceptable
- all safety docs complete
- test wallet only
- live trading explicitly enabled
- Risk Governor 二次确认

目标：

- live_trader_stub 升级为真实接口
- 仅支持测试钱包
- 仅支持小额
- 仅支持 LIMIT orders
- 完整 audit log

完成标准：

- 每次下单经过 Risk Governor
- 完整审计日志
- 安全文档更新

---

## 优先级排序

```text
1. Milestone 1.5 — 工程审计 (已完成)
2. Milestone 2A — 生命周期/结算风险 (已完成)
3. Milestone 2B — 钱包画像 (已完成)
4. Milestone 2C — 事件情报 + Mock LLM (已完成)
5. Milestone 3 — Telegram Signal Cockpit (已完成)
6. Phase 4A — 真实只读 REST API (已完成)
7. Phase 4A.5 — REST Smoke Test (已完成)
8. Phase 4B — WebSocket 实时数据 (已完成)
9. Phase 4B.5 — WebSocket Smoke Test (已完成)
10. Phase 4 Audit — 真实数据层审计 (已完成)
11. Phase 4C — 真实 LLM 接入 (已完成)
12. Phase 4C.5 — LLM Smoke Test (已完成)
13. Phase 4C Audit — LLM 接入审计 (已完成)
14. Phase 5A — 30-Minute Dry Run (已完成)
15. Phase 5B — 3-Hour Paper Trading Run (已完成)
16. Phase 5C — 24-Hour Paper Trading Run (已完成)
17. Phase 5D.1 — LLM Sampling Mode (已完成)
18. Phase 5D.2 — 4-Hour LLM Sampling Run (已完成)
19. Phase 5D.3 — Audit & Metrics Fix (已完成)
20. Phase 5E — Market Intelligence Report (已完成)
21. Phase 5F — Multi-Run Intelligence Comparison (已完成)
22. Phase 5F.5 — Watchlist-Driven Monitoring (已完成)
23. Phase 5G.1 — Dashboard MVP (已完成)
24. Phase 6 — Strategy Signal Validation (已完成)
25. Phase 6.5A — Control Group Sampling Patch (已完成)
26. Phase 6.5A.1 — Category Inference Patch (已完成)
27. Phase 6.5A.5 — Control Group Data Collection + Validation (已完成)
28. Phase 6.5B — Alpha Repeated Observation Run implementation (已完成)
29. Phase 7A — Cloud Deployment Checklist (已完成)
30. Phase 7B — Validation Loop Script (已完成)
31. Phase 7C — systemd/tmux Running Plan (已完成)
32. Phase 7D — Daily Report Automation (已完成)
33. Phase 8A — Shadow Paper Trading Engine Core (已完成)
34. Phase 8B — Shadow Entry Filter Calibration (已完成)
35. Phase 8C — Tradable Candidate Pool Construction (已完成)
36. Phase 8D — Tradable Candidate Shadow Entry Calibration (已完成)
37. Phase 8E — Shadow Paper Performance Evaluation (已完成)
38. Phase 8F.1 — Offline Forward Observation Collector (已完成)
39. Phase 8F.2 — Read-only Forward Price Polling for Shadow PnL (已完成)
40. Phase 8G.1 — Offline Token ID Backfill (已完成)
41. Phase 8G.2 — Read-only Gamma Token ID Lookup (已完成)
42. Phase 8H — Shadow Performance Review Gate (已完成)
43. Phase 8I — Price Model & Entry Filter Calibration (已完成)
44. Phase 8J — Corrected Entry Price Collection / Candidate Rebuild (已完成)
45. Phase 8K — Token Coverage / Expected Edge Calibration (已被后续 Steps 取代)
46. Trading MVP Steps 1-11 (已完成)
47. Trading MVP Step 12 — v5 Forward Cohort (superseded; audit-only)
48. Milestone 5 — 小额实盘 (可选，当前不进入)
```

---

## 依赖关系

```text
Milestone 1.5 (无依赖)
    ↓
Milestone 2A (无依赖)
    ↓
Milestone 2B (无依赖)
    ↓
Milestone 2C (依赖 2A/2B 的评分集成)
    ↓
Milestone 3 (依赖完整评分体系)
    ↓
Phase 4A — REST API (依赖稳定系统 + Telegram)
    ↓
Phase 4A.5 — REST Smoke Test (依赖 Phase 4A)
    ↓
Phase 4B — WebSocket (依赖 Phase 4A)
    ↓
Phase 4B.5 — WebSocket Smoke Test (依赖 Phase 4B)
    ↓
Phase 4 Audit (依赖 Phase 4A + 4B)
    ↓
Phase 4C — Real LLM (依赖真实数据层稳定)
    ↓
Phase 4C.5 — LLM Smoke Test (依赖 Phase 4C)
    ↓
Phase 4C Audit (依赖 Phase 4C + 4C.5)
    ↓
Phase 5A — 30-Minute Dry Run (依赖 Phase 4C Audit)
    ↓
Phase 5B — 3-Hour Paper Trading Run (依赖 Phase 5A)
    ↓
Phase 5C — 24-Hour Paper Trading Run (依赖 Phase 5B)
    ↓
Phase 5D.1 — LLM Sampling Mode (依赖 Phase 5C)
    ↓
Phase 5D.2 — 4-Hour LLM Sampling Run (依赖 Phase 5D.1)
    ↓
Phase 5D.3 — Audit & Metrics Fix (依赖 Phase 5D.2)
    ↓
Phase 5E — Market Intelligence Report (依赖 Phase 5D.3)
    ↓
Phase 5F — Multi-Run Intelligence Comparison (依赖 Phase 5E)
    ↓
Phase 5F.5 — Watchlist-Driven Monitoring (依赖 Phase 5F)
    ↓
Phase 5G.1 — Dashboard MVP (依赖 Phase 5F.5)
    ↓
Phase 6 — Strategy Signal Validation (依赖 Phase 5G.1)
    ↓
Phase 6.5A — Control Group Sampling Patch (依赖 Phase 6)
    ↓
Phase 6.5A.5 — Control Group Data Collection + Validation (依赖 Phase 6.5A)
    ↓
Phase 6.5B — Alpha Repeated Observation Run implementation (已完成)
    ↓
Phase 7A — Cloud Deployment Checklist (已完成)
    ↓
Phase 7B — Validation Loop Script (已完成)
    ↓
Phase 7C — systemd/tmux Running Plan (已完成)
    ↓
Phase 7D — Daily Report Automation (已完成)
    ↓
Phase 8A — Shadow Paper Trading Engine Core (已完成)
    ↓
Phase 8B — Shadow Entry Filter Calibration (已完成)
    ↓
Phase 8C — Tradable Candidate Pool Construction (已完成)
    ↓
Phase 8D — Tradable Candidate Shadow Entry Calibration (已完成)
    ↓
Phase 8E — Shadow Paper Performance Evaluation (已完成)
    ↓
Phase 8F.1 — Offline Forward Observation Collector (已完成)
    ↓
Phase 8F.2 — Read-only Forward Price Polling for Shadow PnL (已完成)
    ↓
Phase 8G.1 — Offline Token ID Backfill (已完成)
    ↓
Phase 8G.2 — Read-only Gamma Token ID Lookup (已完成)
    ↓
Phase 8H — Shadow Performance Review Gate (已完成)
    ↓
Phase 8I — Price Model & Entry Filter Calibration (已完成)
    ↓
Phase 8J — Corrected Entry Price Collection / Candidate Rebuild (已完成)

Trading MVP Step 12 — historical 1m barrier coverage, then >=240-minute forward validation
    ↓
Milestone 5 (依赖所有前置条件)
```
