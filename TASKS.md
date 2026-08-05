# TASKS.md — 当前任务清单

## 当前阶段

**Trading MVP Step 12 — Crypto Threshold Corrected Shadow PnL Validation**

---

## Trading MVP Step 12 — Crypto Threshold Corrected Shadow PnL Validation

状态：⏳ Historical barrier integration complete; formal v7 cohort awaits >=240-minute forward observations and >=5 independent clusters

目标：

- 修正 crypto threshold contract / barrier 语义并 fail closed
- 从同一次新鲜 read-only discovery 创建 isolated shadow entries
- 使用 selected-side ask 入场、同 side bid 退出
- 严格匹配 trade ID、market ID、side 和 YES/NO token pair
- 只使用至少 240 分钟后的 forward observation 计算 corrected PnL
- 缺数据时保持 PnL 为 null，`tiny_live_recommendation=NO`

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add contract_kind / barrier_direction / parser/model version | ✅ |
| Ambiguous, conflicting, or already-crossed barrier fails closed | ✅ |
| Separate avoid-list input from run-scoped output | ✅ |
| Add offline corrected shadow PnL validator | ✅ |
| Preserve threshold, spot, semantics, model and artifact provenance | ✅ |
| Separate prepared-input and final-output SHA-256 provenance | ✅ |
| Require verified resolution source/rules/status and rules SHA-256 | ✅ |
| Capture client/server entry timestamps with 60-second freshness and <=5-second clock skew | ✅ |
| Reject stale/future/pre-entry/cross-run/token-mismatched observations | ✅ |
| Require trusted source, explicit stale/error, and non-crossed exit quotes | ✅ |
| Require four entry prices/sizes and four forward best-level prices/sizes | ✅ |
| Conserve `notional / entry_ask` shares across entry and exit capacity checks | ✅ |
| Downgrade unverified resolution candidates to discovery `watch_only` | ✅ |
| Require >=240 minute forward horizon | ✅ |
| Prevent repeated scans from splitting asset/expiry/contract cohorts | ✅ |
| Repair SOCKS and dashboard test dependency declarations | ✅ |
| Migrate Pydantic v2 config warnings | ✅ |
| Run full test suite after v4 hardening | ✅ (1612 passed; historical v4 baseline) |
| Create a fresh v4 discovery coverage run | ✅ (44 watch_only; 0 verified resolution sources) |
| Implement and test `resolution_source_adapter_v1` | ✅ |
| Persist origin/locator/adapter/rules hash/provenance digest | ✅ |
| Bind adapter/rules provenance into stable trade ID | ✅ |
| Upgrade validator contract to `crypto_threshold_shadow_pnl_v7` | ✅ |
| Require discovery schema v5 / parser v4 | ✅ |
| Reconcile title/Gamma/rules expiry timezone provenance | ✅ |
| Require full historical candle coverage for touch contracts | ✅ (missing -> watch-only) |
| Bind complete entry evidence into stable identity | ✅ |
| Preserve prepared input as a content-addressed immutable snapshot | ✅ |
| Require complete non-crossed forward YES/NO books and all four sizes | ✅ |
| Create final v6 read-only validation run | ✅ (44 watch-only / 0 positions) |
| Run v6 full regression | ✅ (1664 passed in 264.97s; exit code 0) |
| Implement versioned historical 1m candle coverage adapter | ✅ |
| Share one preload, one entry tail, and one candle snapshot per asset | ✅ |
| Commit exact-minute batch entry before collecting fresh spot/CLOB quotes | ✅ |
| Create formal v7 cohort `step12_v7_20260804_140305` | ✅ (12 discovery entries / 11 fresh positions / 3 clusters) |
| Run v7 full regression and scoped quality gates | ✅ (1755 passed in 264.97s; Ruff/format/mypy/py_compile/lock passed) |
| Collect qualifying >=240-minute observations for the formal v7 cohort | ⏳ (0/11 in the recorded validation; poll only after the horizon and only with complete forward evidence) |
| Reach at least 5 independent clusters | ⏳ (current position clusters: 3) |

Superseded read-only run (`step12_20260804_122700`):

- Gamma markets scanned: 1958
- v3 candidates: 44; previously prepared positions: 13
- v4 accepted positions: 0
- missing resolution provenance: 44/44
- missing best-level quantity evidence: 44/44
- stale YES/NO server-side orderbook timestamps: 25 candidates
- closed positions: 0
- total_pnl: null
- validation status: `entry_snapshot_refresh_required`
- tiny_live_recommendation: `NO`

Self-iteration finding:

- The first fresh v2 run exposed description-derived false thresholds, including
  three non-price "best performance" markets incorrectly marked shadow-entry.
- Parser v3 now requires title-local asset, threshold, direction, and expiry
  evidence. The superseded v2 run was not sent to the validator.
- The later `step12_20260804_114000` run reused run-start time as entry time, before
  spot/orderbook evidence existed. Validator v3 rejects all 44 rows from that run;
  it is superseded audit evidence and must not be polled as a valid cohort.
- Validator v4 showed that client-observed causal timestamps alone were not enough:
  the `122700` run lacks verified resolution provenance, visible best-level sizes,
  and complete fresh server-side orderbook timestamps.
- The `122700` run is retained only for audit. It must not be polled, migrated, or
  supplemented with later fields because that would rewrite entry-time evidence.
- PaperTrader now walks visible asks deterministically and rejects stale/mismatched
  inputs, but `SignalSide.BOTH` remains fail-closed until a typed two-leg result,
  independent leg ledger, and explicit leg-risk model exist.
- Adapter v1 now verifies one explicit HTTPS resolution URL, exact trusted hosts and,
  for Binance, asset/pair/1m/High-Low semantics. Non-string, HTTP, multiple,
  untrusted or conflicting sources fail closed.
- QA downgraded v5 to audit-only: its title-derived 23:59 was treated as UTC, touch contracts
  lacked historical barrier coverage, forward books were incompletely checked, and persisted
  entry identity was not fully bound.
- v6 converts 23:59 ET to canonical UTC with Gamma corroboration and binds complete entry
  evidence. It correctly leaves every current touch candidate watch-only because no historical
  candle artifact proves the barrier was untouched before entry.
- Discovery v5 integrates rules-defined historical coverage without guessing from Gamma
  `startDate`. It shares asset-level candle retrieval while preserving independent
  threshold-specific evidence manifests.
- The formal v7 exact-minute cohort verifies 43/44 historical barriers. The one candidate with
  no rules-defined barrier start remains fail-closed without a historical request.

下一步：

- Do not poll the formal v7 cohort before its 240-minute horizon. Once the horizon is reached,
  collect only observations that pass the complete forward-book, timestamp, identity, and size
  gates; invalid or missing observations must remain null rather than becoming PnL.
- Expand future fresh cohorts until at least 5 independent asset/expiry/contract clusters exist;
  the current formal cohort contains only 3 position clusters.
- Preserve v6 and every earlier run for audit only; do not poll, migrate, supplement, reuse, or
  include them in corrected PnL.
- Do not claim expectancy or profitability from the current cohort: 11/11 positions still lack a
  qualifying forward observation, and the existing minimum-sample/independence gates are unmet.
- Keep live trading, authentication, signing, private keys, and real LLMs out of scope.

Previous fresh v4 read-only coverage run (`step12_v4_20260804_064741` UTC, audit-only):

- Gamma markets scanned: 1958
- crypto markets detected / parsed threshold markets: 56 / 44
- candidates: 44 (`0 shadow_entry`, `44 watch_only`)
- structured `resolutionSource` coverage: 0/44
- public CLOB orderbooks fetched: 88; handled Gamma terminal-page 422: 1
- validator schema: `crypto_threshold_shadow_pnl_v4`
- strict positions created: 0; forward observations: 0
- validation status: `entry_snapshot_refresh_required`
- total_pnl: null; tiny_live_recommendation: `NO`
- poller safety: positions loaded 0, API errors 0, updates disabled

This is a valid fresh-cohort coverage result, not a PnL sample. Do not infer edge from
the discovery heuristic's expected-edge fields. It predates the versioned adapter and must not
be polled, migrated, or supplemented.

Audit-only v5 cohort (`step12_v5_20260804_073542` UTC):

- Gamma markets scanned / crypto detected / parsed thresholds: 1958 / 56 / 44
- verified source provenance: 44/44; origin `resolution_rules_url`; adapter
  `resolution_source_adapter_v1`
- discovery: 16 `shadow_entry`, 28 `watch_only`
- validator schema: `crypto_threshold_shadow_pnl_v5`
- strict gate eligible: 14; persisted positions: 10 across 3 clusters
- public CLOB initial poll: 10 observations; API errors 0; stale 0;
  `updated_positions=false`
- offline revalidation: all observations before 240 minutes; closed positions 0;
  status `insufficient_forward_data`; total_pnl null
- safety flags: live=false, auto=false, paper=true, default LLM=mock
- `supports_tiny_live=false`; `tiny_live_recommendation=NO`

This run is not a valid forward cohort after the v6 audit and must not be continued.

Audit-only v6 read-only validation (`step12_v6_20260804_083736` UTC):

- discovery/validator schema: `crypto_threshold_edge_discovery_v4` /
  `crypto_threshold_shadow_pnl_v6`
- scanned / crypto detected / parsed: 1958 / 56 / 44; one recoverable terminal-page 422 means
  coverage is not claimed as exhaustive
- source provenance verified: 44/44; expiry provenance verified: 44/44
- canonical expiry: `2027-01-01T04:59:00Z` from title-local `2026-12-31 23:59 ET`
- all 44 are touch contracts with `missing_historical_barrier_evidence`
- discovery: 0 shadow entry / 44 watch-only; strict gate: 0; positions: 0; PnL: null
- validation status: `historical_barrier_evidence_required`
- live=false, auto=false, paper=true, default LLM=mock; tiny live=`NO`

Formal v7 cohort (`step12_v7_20260804_140305` UTC):

- discovery/validator schema: `crypto_threshold_edge_discovery_v5` /
  `crypto_threshold_shadow_pnl_v7`
- scanned / crypto detected / parsed: 1958 / 56 / 44; one recoverable Gamma pagination error
  means the scan is not claimed as exhaustive
- exact-minute batch entry: `2026-08-04T14:04:00Z`
- historical sharing: 3 asset preloads / 3 entry tails / 3 shared candle snapshots /
  43 threshold-specific manifests
- historical barrier verification: 43/44; the candidate without a rules-defined start remains
  fail-closed
- public CLOB orderbooks loaded: 85/88; three incomplete reads remained fail-closed
- discovery: 12 shadow entries / 32 watch-only rows
- validator: 11 fresh positions (BTC 3 / ETH 5 / SOL 3) across 3 position clusters
- forward observations: 0 qualifying; closed positions: 0; forward coverage: 0.0
- total PnL: null; win rate: null; status: `insufficient_forward_data`
- `supports_tiny_live=false`; `tiny_live_recommendation=NO`

Historical barrier integration is complete. The remaining blockers are qualifying observations at
or beyond 240 minutes and at least 5 independent clusters; the current cohort has only 3 position
clusters. Until those gates are met, this run is pipeline evidence only and provides no expectancy
or profitability result. Do not poll it before the 240-minute horizon. All v6 and earlier runs are
audit-only and must not be polled or reused.

---

## Trading MVP Step 11 — Crypto Threshold Market Coverage Expansion

状态：✅ Completed

目标：

- Expand BTC / ETH / SOL threshold market discovery coverage
- Add Gamma pagination / offset scanning
- Add keyword search discovery
- Improve parser coverage for price-threshold wording
- Add avoid-aware diagnostics instead of silently dropping excluded markets
- Do not loosen edge gates or generate shadow trades
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add pagination / offset scanning | ✅ |
| Add `--page_size`, `--enable_keyword_search`, `--search_keywords` | ✅ |
| Add market_id deduplication | ✅ |
| Add keyword discovery for BTC/ETH/SOL aliases and price terms | ✅ |
| Expand parser for k/comma/M prices and more date expressions | ✅ |
| Prevent years / holdings counts from being parsed as price thresholds | ✅ |
| Add avoid-aware diagnostics summary fields | ✅ |
| Generate `crypto_threshold_market_diagnostics.csv` | ✅ |
| Expand `tests/test_crypto_threshold_edge_discovery.py` | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1451 passed, 8 warnings) |
| Run dry-run coverage check | ✅ |
| Run expanded read-only discovery | ✅ |

Result:

- dry_run:
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

- Crypto threshold coverage is now materially higher than Step 10.
- Diagnostics explain excluded markets.
- Avoid candidates remain excluded.
- No shadow trades were generated in Step 11.
- Step 12 should validate crypto threshold candidates with corrected shadow PnL, still shadow-only.

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 10 — Crypto Price Threshold Edge v1

状态：✅ Completed

目标：

- Discover BTC / ETH / SOL crypto threshold markets from public Gamma active markets
- Parse asset / threshold / direction / expiry without LLM
- Read external spot prices from public read-only ticker data
- Read public CLOB YES/NO bid/ask snapshots
- Estimate a conservative baseline probability from distance/time/volatility heuristics
- Emit `crypto_price_threshold_v1` candidates for shadow-only validation
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add `scripts/discover_crypto_threshold_edges.py` | ✅ |
| Add `crypto_price_threshold_v1` edge type | ✅ |
| Add parser for BTC/ETH/SOL threshold questions | ✅ |
| Add public Binance spot ticker provider | ✅ |
| Add baseline probability / expected edge / confidence calculation | ✅ |
| Add `tests/test_crypto_threshold_edge_discovery.py` | ✅ |
| Update `scripts/run_shadow_paper_loop.py` to read crypto threshold candidates | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1442 passed, 8 warnings) |
| Run crypto threshold dry-run | ✅ |
| Run read-only discovery | ✅ |
| Run shadow dry-run diagnostics | ✅ |

Result:

- dry_run max_markets=100:
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

- Crypto threshold discovery pipeline is implemented and read-only.
- The current scanned batch found one parsed BTC threshold market, but it was already marked `avoid_candidate`, so no candidate was emitted.
- No shadow trades were generated.
- No tested edge supports tiny live.
- Step 11 should improve crypto threshold market coverage / avoid-aware watch diagnostics before any PnL validation.

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 9F — Edge Pruning & New Edge Source Selection

状态：✅ Completed

目标：

- Audit all tested edge types into a single edge strategy registry
- Mark each edge as enabled / watch_only / quarantined / research_only / discontinued
- Confirm whether any tested edge supports tiny live
- Recommend the next edge source for Trading MVP Step 10
- Do not generate trades or modify strategy logic
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add `scripts/audit_edge_strategy_status.py` | ✅ |
| Read prior feedback / convergence / shadow performance summaries | ✅ |
| Generate `edge_strategy_registry.csv` | ✅ |
| Generate `edge_strategy_status_summary.json` | ✅ |
| Generate `edge_strategy_status_report.md` | ✅ |
| Add `tests/test_edge_strategy_status_audit.py` | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1428 passed, 8 warnings) |
| Run dry-run audit | ✅ |
| Run full audit | ✅ |

Result:

- edge_types_reviewed: 5
- enabled_edges:
  - combined_ask_arbitrage
- quarantined_edges:
  - price_dislocation_probability_v1
  - price_dislocation_probability_v2
- research_only_edges:
  - cross_market_consistency_v1
  - cross_market_convergence
- watch_only_edges: []
- discontinued_edges: []
- any_edge_supports_tiny_live: false
- tiny_live_recommendation: NO
- recommended_next_edge_source: Crypto Price Threshold Edge
- recommended_step_10: Trading MVP Step 10 — Crypto Price Threshold Edge v1

Conclusion:

- No tested edge currently supports tiny live.
- Probability v1/v2 remain quarantined.
- Cross-market consistency/convergence remains research-only.
- Combined ask arbitrage remains enabled/watchable but lacks positive PnL proof and is rare.
- Step 10 should pursue Crypto Price Threshold Edge v1 as an objective external edge source.

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 9E — Longer Cross-Market Convergence Dataset / Feature Calibration

状态：✅ Completed

目标：

- Extend cross-market convergence monitoring into append/resume dataset collection
- Analyze accumulated price_gap time series by group and market pair
- Identify shrinking / stable / widening / insufficient convergence patterns
- Produce future shadow recommendations without changing entry gates
- Do not generate shadow trades
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add append/resume/run_id support to `scripts/monitor_cross_market_convergence.py` | ✅ |
| Add `scripts/analyze_cross_market_convergence_dataset.py` | ✅ |
| Add dataset feature output CSV / summary / report | ✅ |
| Add `tests/test_cross_market_convergence_dataset.py` | ✅ |
| Update convergence monitor tests for append/resume | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1419 passed, 8 warnings) |
| Run monitor dry-run | ✅ |
| Run 30-minute read-only observation | ✅ |
| Run offline dataset analysis | ✅ |

Result:

- monitor dry-run:
  - candidates_monitored: 16
  - observations_collected: 0
  - groups_monitored: 6
  - convergence_pass_count: 0
  - convergence_fail_count: 0
  - insufficient_observation_count: 16
  - shadow_entry_eligible_count: 0
  - watch_only_count: 16
- longer read-only observation:
  - duration_minutes: 30
  - interval_seconds: 120
  - resume_enabled: true
  - existing_observations_loaded: 96
  - new_observations_collected: 256
  - total observations used in monitor summary: 352
  - candidates_monitored: 16
  - groups_monitored: 6
  - convergence_pass_count: 0
  - convergence_fail_count: 16
  - avg_initial_gap: 0.667125
  - avg_final_gap: 0.6654375
  - avg_gap_change: -0.0016874999999999217
  - shadow_entry_eligible_count: 0
  - watch_only_count: 16
  - rejected_count: 0
- dataset analysis:
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

- Longer read-only observation still found no usable cross-market convergence pattern.
- No shadow trades were generated.
- current convergence gate remains strict.
- tiny_live_recommendation=NO.

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 9D — Cross-Market Convergence Calibration / Repeated Observation Gate

状态：✅ Completed

目标：

- Require repeated read-only observations before cross-market candidates can become executable shadow entries
- Record price_gap time series for high-confidence duplicate candidates
- Only allow convergence-gated candidates into corrected shadow PnL
- Keep price_gap alone from becoming a trading signal
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add `polysignal/shadow/cross_market_convergence.py` | ✅ |
| Add `scripts/monitor_cross_market_convergence.py` | ✅ |
| Add convergence fields to shadow candidate/trade models | ✅ |
| Make shadow loop prefer `cross_market_edge_candidates_convergence_gated.csv` | ✅ |
| Add convergence diagnostics to entry filter/reporter | ✅ |
| Add `tests/test_cross_market_convergence.py` | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1405 passed, 8 warnings) |
| Run dry-run convergence monitor | ✅ |
| Run short read-only convergence monitor | ✅ |
| Run shadow dry-run diagnostics | ✅ |

Result:

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
- shadow dry-run:
  - candidates_loaded: 16
  - eligible_shadow_entry: 0
  - watch_only: 16
  - rejected: 0
  - top_watch_reasons: price_gap_not_converging=32
  - edge_type_distribution: cross_market_consistency_v1=16

Conclusion:

- Cross-market price gaps did not converge in the short monitor.
- Non-converging candidates are held as watch_only and cannot generate shadow trades.
- `cross_market_consistency_v1` still has no positive expectancy proof.
- tiny_live_recommendation=NO.

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 9C — Corrected Shadow PnL for High-Confidence Cross-Market Edge

状态：✅ Completed

目标：

- Generate corrected shadow trades only from `cross_market_consistency_v1` high-confidence duplicate candidates
- Use side-specific ask as entry price; never use `combined_ask` as entry
- Run one read-only forward polling pass
- Review corrected hypothetical PnL by edge type, relationship status, and price gap bucket
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Extend shadow trade/candidate models with cross-market relationship fields | ✅ |
| Ensure shadow generation can select top N accepted entries without watch-only rows consuming the cap | ✅ |
| Write relationship fields to shadow trades, diagnostics, and reports | ✅ |
| Add edge type / relationship / price gap performance summaries | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1392 passed, 8 warnings) |
| Run shadow generation dry-run | ✅ |
| Generate corrected shadow trades | ✅ |
| Run read-only forward polling once | ✅ |
| Run shadow performance review | ✅ |

Result:

- dry-run diagnostics:
  - candidates_loaded: 88
  - shadow_entries_would_generate: 10
  - eligible_shadow_entry: 16
  - watch_only: 72
  - rejected: 0
  - top_watch_reasons: mutually_exclusive_watch=72
- generated shadow_trades: 10
- edge_type distribution: cross_market_consistency_v1=10
- relationship_status distribution: high_confidence_duplicate=10
- forward polling:
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
  - primary_loss_drivers: expected_edge_too_optimistic=10
  - price_gap_not_converging=10
  - exit_bid_weakness=10
  - cross_market_consistency_v1 did not prove positive expectancy
  - tiny_live_recommendation=NO

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 9B — Cross-Market Relationship Confidence Calibration

状态：✅ Completed

目标：

- Calibrate relationship confidence for `cross_market_consistency_v1`
- Mark true duplicate / near-duplicate, mutually exclusive watch, ambiguous, and false matches
- Ensure price_gap alone cannot create a shadow entry
- Keep probability edge v1/v2 quarantined
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add `scripts/calibrate_cross_market_relationships.py` | ✅ |
| Add relationship confidence fields | ✅ |
| Prefer calibrated cross-market candidates in shadow loop | ✅ |
| Add relationship diagnostics to entry filter | ✅ |
| Add `tests/test_cross_market_relationship_calibration.py` | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1390 passed, 8 warnings) |
| Run offline calibration dry_run and full run | ✅ |
| Run shadow dry-run diagnostics | ✅ |

Result:

- calibration candidates_loaded: 95
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
- shadow dry-run after calibration:
  - candidates_loaded: 25
  - eligible_shadow_entry: 10
  - watch_only: 15
  - rejected: 0
  - top_watch_reasons: mutually_exclusive_watch=15
  - edge_type_distribution: cross_market_consistency_v1=25
- probability edge quarantine remains active
- tiny_live_recommendation=NO

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不进入 tiny live

---

## Trading MVP Step 9A — Cross-Market Consistency Edge v1

状态：✅ Completed

目标：

- Add non-probability `cross_market_consistency_v1`
- Detect same-event duplicate / near-duplicate market groups
- Detect simple mutually exclusive groups as watch-only
- Emit read-only / shadow-only cross-market edge candidates
- Keep probability edge v1/v2 quarantined
- Keep tiny_live_recommendation=NO

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add `scripts/discover_cross_market_edges.py` | ✅ |
| Add `cross_market_consistency_v1` edge type | ✅ |
| Make shadow loop read cross-market candidates | ✅ |
| Add `tests/test_cross_market_edge_discovery.py` | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1375 passed, 8 warnings) |
| Run read-only discovery | ✅ |

Result:

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
- shadow dry-run after discovery:
  - candidates_loaded: 23
  - eligible_shadow_entry: 0
  - watch_only: 23
  - rejected: 0
  - edge_type_distribution: cross_market_consistency_v1=23
- probability edge quarantine remains active
- tiny_live_recommendation=NO

禁止：

- 不接实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不进入 tiny live

---

## Trading MVP Step 8 — Probability Edge Quarantine / Feedback-Gated Shadow Entry

状态：✅ Completed

目标：

- Add feedback-gated execution permission for edge types
- Quarantine `price_dislocation_probability_v1/v2` to watch_only while feedback is negative
- Prevent probability-edge shadow trades when expected_edge/confidence are not predictive
- Preserve `combined_ask_arbitrage` as a separate direct microstructure edge
- Keep tiny_live_recommendation=NO

当前依据：

- v2 trades_analyzed: 10
- overall_win_rate: 0.1
- overall_average_return: -0.2469158035079444
- expected_edge_realized_return_correlation: -0.1784870086432687
- confidence_win_correlation: -0.009224758324091477
- false_positive_count: 9
- high_confidence_loss_count: 9

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add `polysignal/shadow/feedback_gate.py` | ✅ |
| Extend `EdgeCandidate` with gate fields | ✅ |
| Apply gate in `discover_multi_edge_candidates.py` | ✅ |
| Prefer gated candidates in `run_shadow_paper_loop.py` | ✅ |
| Add entry filter gate diagnostics | ✅ |
| Add `tests/test_edge_feedback_gate.py` | ✅ |
| Run `python3 -m pytest tests/ -v` | ✅ (1362 passed, 8 warnings) |

Result:

- `price_dislocation_probability_v1`: watch_only due insufficient feedback
- `price_dislocation_probability_v2`: quarantined due negative feedback
- `multi_edge_candidates_gated.csv` generated
- gated probability candidates are forced to `recommended_action=watch_only`
- shadow dry-run for v2: eligible_shadow_entry=0, watch_only=25, rejected=0
- diagnostics include `edge_type_quarantined`, `feedback_gate_failed`, `expected_edge_negative_correlation`, `confidence_not_predictive`
- combined_ask_arbitrage remains available through its separate gate path
- tiny_live_recommendation=NO

禁止：

- 不接入实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不实现 v3
- 不扩大 shadow trades

---

## Trading MVP Step 7 — Expected Edge Feedback Calibration

状态：✅ Completed

目标：

- Join multi-edge candidate prediction features with closed shadow PnL
- Compare expected_edge / calibrated_expected_edge against realized_return
- Compare confidence against win/loss
- Attribute systematic loss patterns
- Recommend v3 filters / penalties without implementing v3
- Keep tiny_live_recommendation=NO

禁止：

- 不接入实盘
- 不处理私钥
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config
- 不直接实现 v3

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add scripts/calibrate_edge_from_shadow_feedback.py | ✅ |
| Add tests/test_edge_feedback_calibration.py | ✅ |
| Run targeted tests | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1351 passed, 8 warnings) |
| Run dry_run calibration | ✅ |
| Run full offline calibration | ✅ |

关键前提：

- v1/v2 did not prove positive expectancy
- Step 7 only analyzes feedback; it does not loosen gates
- tiny_live_recommendation=NO

Calibration result:

- trades_analyzed: 10
- edge_types_analyzed: price_dislocation_probability_v2
- overall_win_rate: 0.1
- overall_average_return: -0.2469158035079444
- expected_edge_realized_return_correlation: -0.1784870086432687
- confidence_win_correlation: -0.009224758324091477
- false_positive_count: 9
- high_confidence_loss_count: 9
- top_loss_patterns:
  - expected_edge_false_positive=9
  - high_confidence_loss=9
  - exit_bid_weakness=9
  - exit_bid_penalty_underestimated=9
  - microstructure_probability_loss=9

Recommended next gate:

- Do not continue probability_edge executable in its current form
- Quarantine probability_edge to watch_only until positive edge correlation is observed
- Continue collecting shadow feedback, but do not tiny live

---

## Trading MVP Step 6 — Probability Edge Calibration v2

状态：✅ Completed

目标：

- Keep `price_dislocation_probability_v1` as baseline
- Add conservative `price_dislocation_probability_v2`
- Reduce v1 optimistic probability bias
- Add exit bid, adverse selection, liquidity, and confidence penalties
- Keep candidates shadow-only
- Keep tiny_live_recommendation=NO

禁止：

- 不接入实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config

当前实现范围：

| 任务 | 状态 |
|------|------|
| Extend EdgeCandidate with v2 calibration fields | ✅ |
| Add edge_type price_dislocation_probability_v2 | ✅ |
| Add conservative v2 probability estimator | ✅ |
| Add exit bid / adverse selection / liquidity penalties | ✅ |
| Add --edge_version and --output_suffix CLI options | ✅ |
| Make run_shadow_paper_loop.py prefer multi_edge_candidates_v2.csv | ✅ |
| Update tests/test_multi_edge_discovery.py | ✅ |
| Run targeted regression tests | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1341 passed, 8 warnings) |
| Run v2 read-only discovery | ✅ |
| Run top 10 v2 corrected shadow PnL | ✅ |

Step 5 baseline result:

- v1 corrected shadow trades: 25
- closed_positions: 24
- total_pnl: -6.9267167607752755
- win_rate: 0.041666666666666664
- average_return: -0.2886131983656365
- primary loss drivers: probability_model_bias, exit_bid_weakness, confidence_overestimated
- tiny_live_recommendation: NO

关键结论：

- v1 technical loop is closed but not profitable
- v2 is intentionally more conservative
- v2 reduced shadow_entry candidates to 20 and lowered avg confidence to 0.8178872918424754
- top 10 v2 corrected shadow PnL is still negative: total_pnl=-2.469158035079444, win_rate=0.1
- main v2 loss driver remains expected_edge_too_optimistic
- alpha_score / tradable_score / LLM are not used as expected_edge
- v2 candidates remain shadow-only and do not enter live execution
- tiny_live_recommendation=NO

v2 read-only discovery:

- markets_scanned: 493
- orderbooks_fetched: 942
- v2_shadow_entry_candidates: 20
- v2_watch_only_candidates: 620
- v2_rejected_candidates: 308
- avg_raw_expected_edge: -0.004280590717299581
- avg_calibrated_expected_edge: -0.03299360178429739
- avg_confidence: 0.8178872918424754
- exit_bid_penalty_avg: 0.00943597046413502
- adverse_selection_penalty_avg: 0.01392162552742616
- liquidity_penalty_avg: 0.00012658227848101267

top 10 v2 shadow PnL:

- closed_positions: 10
- total_pnl: -2.469158035079444
- win_rate: 0.1
- average_return: -0.2469158035079444
- max_drawdown: -2.469158035079444
- primary_loss_drivers: expected_edge_too_optimistic=9

---

## Trading MVP Step 4A — Multi-Edge Discovery Framework v1

状态：✅ Completed

目标：

- Add unified EdgeCandidate model
- Add scripts/discover_multi_edge_candidates.py
- Keep combined_ask_arbitrage
- Add price_dislocation_probability_v1 baseline estimator
- Reserve stale / closing / cross-market / spread-capture edge types without implementing them
- Output multi_edge_candidates for shadow-only evaluation
- Keep tiny_live_recommendation=NO

禁止：

- 不接入实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add polysignal/shadow/edge_candidates.py | ✅ |
| Add scripts/discover_multi_edge_candidates.py | ✅ |
| Implement combined_ask_arbitrage detector | ✅ |
| Implement price_dislocation_probability_v1 detector | ✅ |
| Make run_shadow_paper_loop.py prefer multi_edge_candidates.csv | ✅ |
| Add tests/test_multi_edge_discovery.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1328 passed, 8 warnings) |

read-only multi-edge discovery 结果：

- dry_run markets_scanned: 100
- markets_scanned: 493
- orderbooks_fetched: 948
- edge_type_counts: combined_ask_arbitrage=474, price_dislocation_probability_v1=948
- combined_ask_arbitrage_count: 474
- probability_edge_count: 948
- shadow_entry_candidates: 125
- watch_only_candidates: 1145
- rejected_candidates: 152
- avg_expected_edge: -0.00886427566807314
- max_expected_edge: 0.049999999999999996
- avg_confidence: 0.9653955696202532
- api_error_count: 0
- tiny_live_recommendation: NO

shadow dry_run diagnostics:

- candidates_loaded: 125
- eligible_shadow_entry: 125
- watch_only: 0
- rejected: 0

关键结论：

- Step 4A added a multi-edge framework instead of relying only on combined_ask arbitrage
- `price_dislocation_probability_v1` uses orderbook microstructure only
- alpha_score / tradable_score / LLM are not used as expected_edge
- edge candidates remain shadow-only and do not enter live execution

---

## Trading MVP Step 3 — Executable Edge Discovery Loop

状态：✅ Completed

目标：

- Scan real active Polymarket markets instead of reusing control_group-only candidates
- Extract YES/NO token ids from public Gamma metadata
- Fetch public read-only CLOB orderbooks
- Compute side-specific bid/ask, spread, combined_ask, combined_ask_gap, executable_edge
- Output executable edge candidates for shadow-only evaluation
- Keep tiny_live_recommendation=NO

禁止：

- 不接入实盘
- 不处理私钥
- 不认证 / 不签名
- 不下单 / 不撤单
- 不调用真实 LLM
- 不运行 run_paper.py
- 不修改 Risk Governor
- 不修改 live trading config

当前实现范围：

| 任务 | 状态 |
|------|------|
| Add scripts/discover_executable_edges.py | ✅ |
| Fetch active Gamma markets read-only | ✅ |
| Extract YES/NO token ids without guessing | ✅ |
| Fetch YES/NO CLOB orderbooks read-only | ✅ |
| Compute combined_ask / executable_edge | ✅ |
| Generate executable_edge_candidates.csv/json | ✅ |
| Generate executable_edge_discovery_summary.json/report.md | ✅ |
| Make run_shadow_paper_loop.py prefer executable_edge_candidates.csv | ✅ |
| Add tests/test_executable_edge_discovery.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1310 passed) |

read-only discovery 结果：

- markets_scanned: 493
- markets_with_token_ids: 474
- orderbooks_fetched: 948
- combined_ask_below_one_count: 0
- executable_edge_positive_count: 0
- edge_candidates_count: 0
- api_error_count: 0
- stale_orderbook_count: 0
- insufficient_depth_count: 0
- spread_too_wide_count: 0
- avoid_candidate_count: 19
- forbidden_category_count: 0
- ambiguous_market_count: 0
- tiny_live_recommendation: NO

shadow dry_run diagnostics:

- candidates_loaded: 0
- eligible_shadow_entry: 0
- watch_only: 0
- rejected: 0

关键结论：

- Step 3 proved the discovery loop can scan real active markets read-only
- No positive combined_ask gap was found in this batch
- No executable shadow candidates were generated
- edge_candidates remain shadow-only and never enter live execution

---

## Trading MVP Step 2 — Expected Edge v1

状态：✅ Completed

关键结果：

- tests: 1294 passed
- candidates_loaded: 34
- token coverage: 34/34
- side bid/ask pricing: 34/34
- expected_edge_available_count: 0
- executable_edge_positive_count: 0
- expected_edge_pass_count: 0
- combined_ask_below_one_count: 0
- control_group_only_count: 34
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- main reasons: combined_ask_not_below_one=34, control_group_only_watch=34
- tiny_live_recommendation: NO

---

## Phase 8J 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add scripts/refresh_tradable_candidate_prices.py | ✅ |
| Read tradable_candidates_with_tokens.csv before tradable_candidates.csv | ✅ |
| Resolve yes_token_id / no_token_id without using market_id as token_id | ✅ |
| Fetch public read-only CLOB orderbooks for priced candidates | ✅ |
| Write side-specific YES/NO bid/ask fields | ✅ |
| Keep combined_ask as market-level feature only | ✅ |
| Compute spread / liquidity proxy / expected_edge proxy | ✅ |
| Generate tradable_candidates_priced.csv | ✅ |
| Generate tradable_candidates_priced.json | ✅ |
| Generate tradable_candidate_price_refresh_summary.json | ✅ |
| Generate tradable_candidate_price_report.md | ✅ |
| Make run_shadow_paper_loop.py prefer tradable_candidates_priced.csv | ✅ |
| Add tests/test_tradable_candidate_price_refresh.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1266/1266 passed) |
| Run refresh_tradable_candidate_prices.py --dry_run | ✅ |
| Run refresh_tradable_candidate_prices.py --max_candidates 50 | ✅ |
| Run run_shadow_paper_loop.py --dry_run --diagnostics | ✅ |

read-only refresh 结果：

- candidates_loaded: 34
- candidates_priced: 5
- missing_token_id_count: 29
- empty_orderbook_count: 0
- api_error_count: 0
- yes_ask_available_count: 5
- no_ask_available_count: 5
- side_ask_available_count: 5
- expected_edge_available_count: 0
- tiny_live_recommendation: NO

shadow dry_run diagnostics:

- candidates_loaded: 34
- shadow_entries_would_generate: 0
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- top_rejection_reasons:
  - missing_side_ask: 29
  - invalid_entry_price_model: 29
- top_watch_reasons:
  - missing_alpha_score_but_not_required: 34
  - control_group_only_watch: 34
  - tradable_candidate_watch_only: 34
  - missing_expected_edge: 34
  - tradable_score_too_low: 29
  - tradable_candidate_quality_passed: 5

关键结论：

- Phase 8J solved the Phase 8I blocker for the 5 token-backed candidates by adding side-specific CLOB bid/ask snapshots
- missing_side_ask decreased from 34 to 29
- no eligible_shadow_entry was generated because priced candidates still lack expected edge and are control_group-only watch candidates
- `combined_ask` remains feature-only and is not used as side-specific entry price
- tiny live 仍然 NO

下一步建议：Phase 8K — Token Coverage / Expected Edge Calibration for executable shadow candidates

---

## Phase 8I 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add side-specific price fields to shadow models | ✅ |
| Keep combined_ask as feature-only | ✅ |
| YES entry uses yes_best_ask | ✅ |
| NO entry uses no_best_ask | ✅ |
| YES exit uses yes_best_bid | ✅ |
| NO exit uses no_best_bid | ✅ |
| Missing side ask prevents eligible_shadow_entry | ✅ |
| Missing side bid prevents close / PnL fabrication | ✅ |
| control_group-only defaults to watch_only | ✅ |
| expected_edge > spread + buffer gate added | ✅ |
| Add scripts/audit_shadow_price_model.py | ✅ |
| Update scripts/review_shadow_performance.py for legacy_invalid_price_model | ✅ |
| Update tests/test_shadow_trading.py | ✅ |
| Add tests/test_shadow_price_model_audit.py | ✅ |
| Run audit_shadow_price_model.py --dry_run | ✅ |
| Run audit_shadow_price_model.py | ✅ |
| Run run_shadow_paper_loop.py --dry_run --diagnostics | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1254/1254 passed) |

price model audit 结果：

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
- shadow_entries_would_generate: 0
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- top_rejection_reasons:
  - missing_side_ask: 34
  - invalid_entry_price_model: 34
- top_watch_reasons:
  - missing_alpha_score_but_not_required: 34
  - control_group_only_watch: 34
  - tradable_candidate_watch_only: 34
  - missing_expected_edge: 34
  - tradable_score_too_low: 29

关键结论：

- combined_ask 不再作为 YES/NO 单边 entry price
- 当前旧 PnL invalid / not reliable
- 旧 5 笔 closed trades 均缺 entry_side_price，无法 corrected PnL
- 当前 corrected shadow loop 不再生成错误 entry
- tiny live 仍然 NO

下一步已完成：Phase 8J — Corrected Entry Price Collection / Candidate Rebuild

---

## Phase 8H 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add scripts/review_shadow_performance.py | ✅ |
| Read updated_shadow_trades.csv | ✅ |
| Read updated_shadow_positions.json | ✅ |
| Read forward_observations.jsonl | ✅ |
| Read tradable_candidates_with_tokens.csv / tradable_candidates.csv | ✅ |
| Generate per-trade diagnosis | ✅ |
| Generate aggregate loss attribution | ✅ |
| Generate shadow_performance_review.md | ✅ |
| Generate shadow_performance_review_summary.json | ✅ |
| Generate shadow_trade_diagnostics.csv | ✅ |
| Add tests/test_shadow_performance_review.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1236/1236 passed) |
| Run python3 scripts/review_shadow_performance.py --dry_run | ✅ |
| Run python3 scripts/review_shadow_performance.py | ✅ |

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

- 主要亏损原因不是 exit spread 过宽，而是 entry/exit price semantics 不一致
- 当前 shadow entry 使用 `combined_ask` 作为 YES-side entry price，接近 1.0
- forward polling exit 使用 side bid，导致所有 YES positions 显示巨大亏损
- 5/5 trades 均为 control_group source，near-miss evidence weak
- 5/5 trades 缺少 explicit expected edge
- low-risk control group 不等于 executable opportunity
- 当前不进入 tiny live ✅

建议下一步：

- Phase 8I follow-up completed; Phase 8J corrected entry price collection completed
- require side-specific executable entry price
- require expected_edge > spread + buffer
- reduce or exclude control_group-only candidates from eligible_shadow_entry
- require Tier1/Tier2 near-miss evidence for executable shadow entries
- separate research watchlist candidates from executable shadow entries

安全验收：

- 不接入实盘 ✅
- 不处理私钥 ✅
- 不认证 / 不签名 ✅
- 不下单 / 不撤单 ✅
- 不调用真实 LLM ✅
- 不运行 run_paper.py ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅
- 不修改 entry filter ✅
- live_trading_enabled=false ✅
- allow_auto_execution=false ✅
- paper_trading_enabled=true ✅

---

## Phase 8G.2 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add GammaTokenLookupClient to scripts/backfill_shadow_token_ids.py | ✅ |
| Keep allow_api_lookup default false | ✅ |
| Support --max_api_calls / --api_timeout_seconds / --api_cache_file | ✅ |
| Direct public Gamma market lookup | ✅ |
| Strict question/title validation | ✅ |
| Optional exact question search fallback | ✅ |
| Parse clobTokenIds / clob_token_ids + outcomes | ✅ |
| Parse JSON-encoded token/outcome strings | ✅ |
| Map YES / NO even when outcome order is reversed | ✅ |
| Reject ambiguous outcome mappings | ✅ |
| Reject unsupported market structures | ✅ |
| Refuse market_id-as-token_id | ✅ |
| Write shadow_trades_with_tokens.csv | ✅ |
| Write tradable_candidates_with_tokens.csv | ✅ |
| Write updated_shadow_positions.json with token ids | ✅ |
| Update ShadowTokenIdResolver priority for backfilled files | ✅ |
| Update tests/test_shadow_token_backfill.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1219/1219 passed) |
| Run python3 scripts/backfill_shadow_token_ids.py --dry_run | ✅ |
| Run python3 scripts/backfill_shadow_token_ids.py --allow_api_lookup --max_api_calls 5 | ✅ |
| Run python3 scripts/poll_shadow_forward_prices.py --once --max_positions 5 | ✅ |

dry_run 结果：

- markets_scanned: 101
- token_pairs_found: 0
- shadow_trades_loaded: 5
- shadow_trades_backfilled: 0
- shadow_trades_missing_token_id: 5
- tradable_candidates_loaded: 34
- tradable_candidates_backfilled: 0
- api_lookup_enabled: false
- api_calls_used: 0

allow_api_lookup 结果：

- api_lookup_enabled: true
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
- tradable_candidates_backfilled: 5

forward polling 结果：

- positions_loaded: 5
- positions_polled: 5
- observations_written: 5
- missing_token_id_count: 0
- api_error_count: 0
- stale_observation_count: 0
- updated_positions: true
- closed_positions: 5
- insufficient_forward_data_positions: 0
- total_pnl: -4.62937062937063
- win_rate: 0.0
- max_drawdown: -4.62937062937063

关键结论：

- Phase 8G.2 已打通 token id backfill -> CLOB read-only polling -> shadow PnL update 闭环
- 本次 PnL 为 shadow-only hypothetical result，不是实盘交易结果
- 没有真实交易 ✅
- 没有认证 / 签名 / 下单 / 撤单 ✅
- 没有处理私钥 ✅
- 没有调用真实 LLM ✅
- 没有运行 run_paper.py ✅
- 没有修改 Risk Governor / 策略 / config/risk.yaml ✅
- live_trading_enabled=false ✅
- allow_auto_execution=false ✅
- paper_trading_enabled=true ✅

下一步完成：Phase 8H — Shadow Performance Review Gate

---

## Phase 8G.1 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add yes_token_id / no_token_id to CandidateSnapshot | ✅ |
| Add yes_token_id / no_token_id to ShadowTrade | ✅ |
| Add yes_token_id / no_token_id to TradableCandidate | ✅ |
| Keep old CSV/JSON compatibility | ✅ |
| Add scripts/backfill_shadow_token_ids.py | ✅ |
| Scan local events / summary / tradable / trajectory / watchlist / shadow artifacts | ✅ |
| Parse explicit yes_token_id / no_token_id | ✅ |
| Parse clobTokenIds / clob_token_ids + outcomes | ✅ |
| Parse JSON-encoded clobTokenIds strings | ✅ |
| Refuse market_id-as-token_id | ✅ |
| Add tests/test_shadow_token_backfill.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1209/1209 passed) |
| Run python3 scripts/backfill_shadow_token_ids.py --dry_run | ✅ |

当前 dry_run:

- markets_scanned: 101
- token_pairs_found: 0
- shadow_trades_loaded: 5
- shadow_trades_backfilled: 0
- shadow_trades_missing_token_id: 5
- tradable_candidates_loaded: 34
- tradable_candidates_backfilled: 0
- api_lookup_enabled: false

关键结论：

- 本地 artifacts 无可恢复 YES/NO CLOB token IDs
- 未伪造 token id ✅
- 未把 market_id 当 token_id ✅
- 未调用网络 / Gamma API / CLOB API ✅
- 未写 *_with_tokens 输出，因为 dry_run 显示 0 个可恢复 token pairs ✅
- 未运行 poll_shadow_forward_prices.py --once，因为 missing_token_id_count 不会改善 ✅

下一步完成：Phase 8G.2 — Read-only Gamma Token ID Lookup

---

## Phase 8F.2 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Extend ForwardObservation with token/orderbook fields | ✅ |
| Add ShadowTokenIdResolver | ✅ |
| Prevent market_id from being used as token_id | ✅ |
| Add scripts/poll_shadow_forward_prices.py | ✅ |
| Read open / insufficient_forward_data shadow positions | ✅ |
| Poll public CLOB REST only when token IDs exist | ✅ |
| Write forward_poll_summary.json | ✅ |
| Append forward_observations.jsonl when observations exist | ✅ |
| Optionally update positions via Phase 8F.1 collector | ✅ |
| Add tests/test_shadow_forward_polling.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1195/1195 passed) |
| Run python3 scripts/poll_shadow_forward_prices.py --dry_run | ✅ |
| Run python3 scripts/poll_shadow_forward_prices.py --once --max_positions 5 | ✅ |

当前 polling 结果:

- positions_loaded: 5
- positions_polled: 0
- observations_written: 0
- missing_token_id_count: 5
- api_error_count: 0
- forward_poll_summary.json: generated
- forward_observations.jsonl: remains empty
- updated_positions: true
- closed_positions: 0
- insufficient_forward_data_positions: 5
- total_pnl: 0.0
- win_rate: 0.0
- max_drawdown: 0.0

关键验收：

- token_id 缺失时明确输出 missing_token_id ✅
- 不把 market_id 当 token_id ✅
- token_id 缺失时不拉价格、不伪造 observation、不关闭 position ✅
- 不认证 / 不签名 / 不下单 / 不撤单 ✅
- 不调用真实 LLM ✅
- 不运行 run_paper.py ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅

下一步完成：Phase 8G.2 — Read-only Gamma Token ID Lookup

---

## Phase 8F.1 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add ForwardObservation model | ✅ |
| Add scripts/collect_shadow_forward_data.py | ✅ |
| Read shadow_positions.json | ✅ |
| Read shadow_trades.csv | ✅ |
| Read market_trajectories.json | ✅ |
| Read existing forward_observations.jsonl if present | ✅ |
| Generate forward_observations.jsonl | ✅ |
| Generate updated_shadow_positions.json | ✅ |
| Generate updated_shadow_trades.csv | ✅ |
| Regenerate paper_performance_summary.json | ✅ |
| Regenerate paper_performance_report.md | ✅ |
| Keep insufficient_forward_data when no forward observations exist | ✅ |
| Do not forge exit price or PnL | ✅ |
| Add tests/test_shadow_forward_data.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1179/1179 passed) |
| Run python3 scripts/collect_shadow_forward_data.py --dry_run | ✅ |
| Run python3 scripts/collect_shadow_forward_data.py | ✅ |

当前 offline forward collection:

- forward_observations.jsonl: generated, 0 observations found
- updated_shadow_positions.json: generated
- updated_shadow_trades.csv: generated
- paper_performance_summary.json: updated
- paper_performance_report.md: updated
- closed_positions: 0
- open_positions: 0
- insufficient_forward_data_positions: 5
- total_pnl: 0.0
- win_rate: 0.0
- max_drawdown: 0.0
- forward data limitation: yes

关键验收：

- 没有 forward observed_price 时不计算 PnL ✅
- 不使用 entry_price 伪造 exit_price ✅
- 不生成 synthetic exit ✅
- Phase 8F.1 不调用真实 API / 真实 LLM ✅
- 不运行 run_paper.py ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅
- 不自动下单 ✅

下一步建议：Phase 8G — Token ID Backfill / Shadow Position Rebuild Gate

---

## Phase 8E 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Non-dry-run generates shadow_trades.csv | ✅ |
| Non-dry-run generates shadow_positions.json | ✅ |
| Non-dry-run generates paper_performance_summary.json | ✅ |
| Non-dry-run generates paper_performance_report.md | ✅ |
| ShadowTrade records tradable_score / source / evidence_level | ✅ |
| Missing forward data does not forge PnL | ✅ |
| Add insufficient_forward_data status | ✅ |
| Summary includes insufficient_forward_data_positions | ✅ |
| Report includes hypothetical disclaimer | ✅ |
| Update tests/test_shadow_trading.py | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1162/1162 passed) |
| Run python3 scripts/run_shadow_paper_loop.py --diagnostics | ✅ |

当前 shadow evaluation:

- shadow_trades.csv: generated
- shadow_trades: 5
- shadow_positions.json: generated
- paper_performance_summary.json: generated
- paper_performance_report.md: generated
- closed_positions: 0
- open_positions: 0
- insufficient_forward_data_positions: 5
- total_pnl: 0.0
- win_rate: 0.0
- max_drawdown: 0.0
- forward data limitation: yes

关键验收：

- 不伪造 forward price / PnL ✅
- insufficient forward data 明确记录 ✅
- Shadow performance is hypothetical and not a live trading result ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不调用真实 API / 真实 LLM ✅
- 不运行 run_paper.py ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅
- 不自动下单 ✅

---

## Phase 8D 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Extend CandidateSnapshot with tradable evidence fields | ✅ |
| Read tradable_score / source / reasons / evidence_level from tradable_candidates.csv | ✅ |
| Make missing alpha non-fatal for tradable candidates | ✅ |
| Add tradable-evidence-centric eligible logic | ✅ |
| Keep alpha_score-only from eligible_shadow_entry | ✅ |
| Keep tradable_score-only from eligible_shadow_entry | ✅ |
| Keep avoid candidates hard-rejected | ✅ |
| Add/update tests/test_shadow_trading.py | ✅ |
| Add/update tests/test_tradable_candidates.py | ✅ |
| Run shadow dry_run diagnostics | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1158/1158 passed) |

当前 shadow dry_run diagnostics:

- candidates_loaded: 34
- shadow_entries_would_generate: 5
- eligible_shadow_entry: 5
- watch_only: 29
- rejected: 0
- top_rejection_reasons: {}
- top_watch_reasons:
  - tradable_candidate_quality_passed=34
  - missing_alpha_score_but_not_required=29
  - tradable_candidate_watch_only=29
  - tradable_score_too_low=28

关键验收：

- missing_alpha_score 不再作为 tradable candidates 的误导性主要 reject reason ✅
- eligible_shadow_entry 仍然只是 shadow trading 入口，不是实盘许可 ✅
- tradable_score 不是交易信号 ✅
- alpha_score 不是交易信号 ✅
- alpha_score-only 不能 eligible ✅
- tradable_score-only 不能 eligible ✅
- avoid candidates 仍然硬排除 ✅
- watch_only 不生成 shadow trade ✅
- rejected 不生成 shadow trade ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不调用真实 API / 真实 LLM ✅
- 不运行 run_paper.py ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅
- 不自动下单 ✅

---

## Phase 8C 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create polysignal/shadow/tradable_candidates.py | ✅ |
| Add TradableCandidate model | ✅ |
| Add TradableCandidateBuilder | ✅ |
| Add TradableCandidateScorer | ✅ |
| Create scripts/build_tradable_candidates.py | ✅ |
| Read watchlist / alpha / avoid / trajectories / validation artifacts | ✅ |
| Read control group samples from existing run directories | ✅ |
| Exclude avoid / high ambiguity / low liquidity / missing combined_ask candidates | ✅ |
| Generate tradable_candidates.csv | ✅ |
| Generate tradable_candidates.json | ✅ |
| Generate tradable_candidate_report.md | ✅ |
| Update run_shadow_paper_loop.py to prefer tradable_candidates.csv | ✅ |
| Preserve fallback alpha/watchlist loading when tradable candidates are absent | ✅ |
| Add tests/test_tradable_candidates.py | ✅ |
| Run build_tradable_candidates dry_run | ✅ |
| Run shadow dry_run diagnostics | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1150/1150 passed) |

当前 build_tradable_candidates dry_run:

- candidates_considered: 64
- tradable_candidates_would_generate: 34
- excluded_avoid_candidates: 28
- exclusion_summary: avoid_candidate=28, high_ambiguity=7, missing_combined_ask=1

当前 shadow dry_run diagnostics:

- candidates_loaded: 34
- eligible_shadow_entry: 0
- watch_only: 34
- rejected: 0
- top_rejection_reasons: missing_alpha_score=34
- top_watch_reasons: tradable_candidate_watch_only=34

关键验收：

- tradable_candidates 不包含 avoid candidates ✅
- avoid candidates 仍然硬排除 ✅
- tradable_score 只是 research/shadow priority score，不是交易信号 ✅
- tradable candidates 仍必须经过 Shadow Entry Filter ✅
- alpha_score-only 不成为 tradable reason ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不调用真实 API / 真实 LLM ✅
- 不运行 run_paper.py ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅
- 不自动下单 ✅

---

## Phase 8B 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add structured entry reject diagnostics | ✅ |
| Add eligible / watch_only / rejected decisions | ✅ |
| Add conservative watch_only calibration | ✅ |
| Add diagnostics summary in dry_run | ✅ |
| Add diagnostics CSV/JSON writers for formal runs | ✅ |
| Enhance performance report with diagnostics | ✅ |
| Add CLI --diagnostics | ✅ |
| Add CLI --watch_only_output | ✅ |
| Add CLI --min_watch_alpha_score | ✅ |
| Add CLI --watch_tier3 | ✅ |
| Update tests/test_shadow_trading.py | ✅ |
| Run dry_run diagnostics | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1132/1132 passed) |

当前 dry_run diagnostics:

- candidates_loaded: 20
- eligible_shadow_entry: 0
- watch_only: 0
- rejected: 20
- top_rejection_reasons: avoid_candidate=20, high_ambiguity=2

关键验收：

- alpha_score-only 仍不能触发 eligible_shadow_entry ✅
- watch_only 不生成 shadow trade ✅
- rejected 不生成 shadow trade ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- 不调用真实 API / 真实 LLM ✅
- 不运行 run_paper.py ✅
- 不修改 Risk Governor / 策略 / config/risk.yaml ✅
- 不自动下单 ✅

---

## Phase 8A 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create polysignal/shadow package | ✅ |
| Add shadow trade data models | ✅ |
| Add entry filter | ✅ |
| Add exit rules | ✅ |
| Add PnL calculations | ✅ |
| Add shadow reporter | ✅ |
| Create scripts/run_shadow_paper_loop.py | ✅ |
| Load alpha/watchlist/avoid/trajectories offline | ✅ |
| Add tests/test_shadow_trading.py | ✅ |
| Run dry_run | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1122/1122 passed) |

关键验收：

- Shadow Trading 不是现有 PaperTrader ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不导入 LiveTrader ✅
- 不导入 PaperTrader ✅
- 不调用真实 API ✅
- 不调用真实 LLM ✅
- 不运行 run_paper.py ✅
- 不修改 Risk Governor ✅
- 不修改策略逻辑 ✅
- 不修改 config/risk.yaml ✅
- 不让 alpha_score 变成真实交易信号 ✅
- 不自动下单 ✅

---

## Phase 7D 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create scripts/generate_daily_report.py | ✅ |
| Read recent runs from runs/ | ✅ |
| Aggregate run summary metrics | ✅ |
| Load strategy_validation_summary.json | ✅ |
| Load intelligence_comparison_summary.json | ✅ |
| Load persistent_watchlist.csv | ✅ |
| Load alpha_candidates.csv | ✅ |
| Load avoid_candidates.csv | ✅ |
| Load validation_loop_summary.json | ✅ |
| Generate daily_report.md | ✅ |
| Generate daily_report_summary.json | ✅ |
| Add tests/test_generate_daily_report.py | ✅ |
| Update docs | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1098/1098 passed) |

关键验收：

- 不运行 run_paper.py ✅
- 不调用真实 API ✅
- 不调用真实 LLM ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不修改 config ✅
- 不修改 Risk Governor ✅
- 不修改策略 ✅
- 不让 alpha_score 变成交易信号 ✅
- 不自动下单 ✅
- 不打印 API key ✅
- 只读取 runs/ 和 config/ ✅

---

## Phase 7C 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create docs/cloud_running_plan.md | ✅ |
| Document tmux manual running plan | ✅ |
| Document systemd service / timer plan | ✅ |
| Add service example template | ✅ |
| Add timer example template | ✅ |
| Document logs / status / stop / restart commands | ✅ |
| Document safety checks | ✅ |
| Update CONTEXT / TASKS / ROADMAP | ✅ |
| Update cloud deployment checklist link | ✅ |
| Run targeted Phase 7B pytest | ✅ |

关键验收：

- 不运行 systemctl ✅
- 不启动长任务 ✅
- 不运行 overnight ✅
- 不接入实盘 ✅
- 不处理私钥 ✅
- 不修改 config/risk.yaml ✅
- 不修改 scripts/run_paper.py ✅
- 不修改 Risk Governor ✅
- 不修改策略 ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅
- paper_trading_enabled 保持 true ✅
- default LLM provider 保持 mock ✅

---

## Phase 7B 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create scripts/run_validation_loop.py | ✅ |
| Add dry_run mode | ✅ |
| Add skip_run mode | ✅ |
| Add safety checks | ✅ |
| Run run_paper.py orchestration | ✅ |
| Run validation/analyze/compare orchestration | ✅ |
| Generate validation_loop_summary.json | ✅ |
| Add tests/test_run_validation_loop.py | ✅ |
| Update docs | ✅ |
| Run python3 -m pytest tests/ -v | ✅ (1084/1084 passed) |

关键验收：

- 不接入实盘 ✅
- 不处理私钥 ✅
- 不修改 config ✅
- 不修改 Risk Governor ✅
- 不修改策略 ✅
- 不降低阈值 ✅
- 不让 alpha_score 变成交易信号 ✅
- 不自动下单 ✅
- 不开放 dashboard ✅
- 不新增 systemd service ✅

---

## Phase 7A 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create docs/cloud_deployment_checklist.md | ✅ |
| Document cloud-only research/data collection goals | ✅ |
| Document recommended server configuration | ✅ |
| Document /opt/polysignal directory layout | ✅ |
| Document Linux user and permissions | ✅ |
| Document deployment steps | ✅ |
| Document environment variable safety | ✅ |
| Document safety check commands | ✅ |
| Document first cloud verification flow | ✅ |
| Document 5-minute smoke commands | ✅ |
| Document tmux manual run option | ✅ |
| Document systemd Phase 7C preview | ✅ |
| Document logs/backups/dashboard/troubleshooting | ✅ |
| Update CONTEXT / TASKS / ROADMAP | ✅ |

关键验收：

- 只新增/更新部署文档 ✅
- 不修改业务代码 ✅
- 不修改 scripts/run_paper.py ✅
- 不修改 Risk Governor / Strategy / execution live trading code ✅
- 不修改 config/risk.yaml ✅
- 不运行 4h / 10h / overnight run ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅
- paper_trading_enabled 保持 true ✅
- default LLM provider 保持 mock ✅

---

## Phase 6.5B 完成情况

状态：✅ Implementation completed; cloud data collection deferred to Phase 7

| 任务 | 状态 |
|------|------|
| Add alpha_priority_ratio to RunConfig / CLI | ✅ |
| Add alpha_repeat_target to RunConfig / CLI | ✅ |
| Prioritize alpha candidates needing observations | ✅ |
| Deprioritize alpha markets at repeat target | ✅ |
| Preserve discovery_ratio floor >= 0.1 | ✅ |
| Generate alpha_repeat_observation_summary.json | ✅ |
| Generate alpha_repeat_observation_report.md | ✅ |
| Update alpha observation conclusion tiers | ✅ |
| Add/update tests | ✅ |
| Run pytest tests/ -v | ✅ (1071/1071 passed) |

关键验收：

- alpha_priority_ratio 默认 0，不影响旧行为 ✅
- alpha_repeat_target 默认 3 ✅
- alpha_priority_ratio 只影响扫描优先级 ✅
- alpha_score 不生成 signal ✅
- alpha_score 不触发 PaperTrader ✅
- alpha_score 不改变 Risk Governor score ✅
- alpha_score 不新增 hard reject / allow reason ✅
- discovery_ratio 最低保持 0.1 ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅
- paper_trading_enabled 保持 true ✅
- default LLM provider 保持 mock ✅

Alpha observation conclusion 分级：

| 观测次数 | conclusion_status |
|----------|-------------------|
| 1 | insufficient_data |
| 2 | weak_descriptive |
| 3-4 | preliminary_observed |
| >=5 | stronger_observed |

---

## Phase 6.5A 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Add control_group params to RunConfig | ✅ |
| Implement _select_control_group_candidates | ✅ |
| Implement _run_control_group_sampling | ✅ |
| Output control_group_samples.csv + validation_loop_summary.json | ✅ |
| Update validate_strategy_signals.py for control group | ✅ |
| Create tests/test_validation_loop.py | ✅ |
| Update tests/test_validate_strategy_signals.py | ✅ |
| Run pytest tests/ -v | ✅ (1049/1049 passed) |
| Run 4-hour control group data collection | ✅ |
| Run offline validation with control group | ✅ |
| Update documentation | ✅ |

关键验收：

- control_group_sampling_ratio 默认 0，不影响旧行为 ✅
- control group 排除 avoid / alpha / watchlist ✅
- control group category 多样性 ✅
- control_group_assessment 不触发交易 ✅
- control_group_samples.csv 正确生成 ✅
- validate_strategy_signals.py 能读取 control_group_samples.csv ✅
- avoid validation 使用 control group 作为 non-avoid group ✅
- live_trading_enabled 仍为 false ✅
- 无 LiveTrader / PaperTrader / RiskGovernor 导入新增 ✅
- 22 new tests ✅

### Phase 6.5A.5 Control Group Data Collection + Validation

run_id: `run_20260510_105908_73831203`

运行结果：

- control_group_samples.csv generated ✅
- control_group_samples: 36 rows ✅
- unique_control_group_markets: 36 ✅
- control_group_assessment events: 36 ✅
- control group excludes avoid / alpha / watchlist ✅
- signals_generated: 0 ✅
- paper_trades_created: 0 ✅
- live_trading_enabled=false ✅
- allow_auto_execution=false ✅
- paper_trading_enabled=true ✅
- default LLM provider=mock ✅

离线 validation 结果：

| 研究问题 / 指标 | 结果 |
|-----------------|------|
| control group samples loaded | 42 |
| Q1: Alpha forward change | inconclusive |
| Q2: Avoid risk validation | observed |
| Q2 non_avoid_group size | 21 |
| avoid avg ambiguity risk | 17.8 |
| non-avoid avg ambiguity risk | 8.8 |
| ambiguity delta | +9.0 |
| event_score correlation | r=-0.256, n=14 |

LLM rate limit 核查：

- max_llm_calls_per_hour=15 ✅
- duration=4h ✅
- actual total LLM calls=60 ✅
- regular LLM + control group LLM 共用同一个 rate limiter ✅
- 不是 60 + 36 = 96 ✅

---

## Phase 6 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create scripts/validate_strategy_signals.py | ✅ |
| Create tests/test_validate_strategy_signals.py | ✅ |
| ValidationDataLoader (alpha/avoid/watchlist/trajectories/events) | ✅ |
| AlphaValidator (forward change: first/last/min/max, delta, slope) | ✅ |
| WatchlistValidator (persistence score, near-miss hits) | ✅ |
| AvoidValidator (single + group comparison with control group) | ✅ |
| CategoryValidator (per-category signal quality) | ✅ |
| EventScoreCorrelationValidator (Pearson correlation with protection) | ✅ |
| conclusion_status framework (observed/insufficient_data/inconclusive) | ✅ |
| ValidationReportGenerator (MD + JSON + CSV exports) | ✅ |
| AST safety audit (no trading module imports) | ✅ |
| Run pytest tests/ -v | ✅ (1025/1025 passed) |
| Run validation script on real data | ✅ |
| Update documentation | ✅ |

关键验收：

- READ-ONLY: 不触发交易、不修改配置、不调用 API ✅
- 不导入 LiveTrader / PaperTrader / RiskGovernor ✅
- conclusion_status 框架实现 ✅
- Alpha forward change 输出完整指标 ✅
- Avoid control group 定义正确 ✅
- AST 安全审计通过 ✅
- live_trading_enabled 保持 false ✅
- 70 new tests ✅

验证结果摘要：

| 研究问题 | conclusion_status |
|----------|-------------------|
| Q1: Alpha forward change | inconclusive (2/20 observed) |
| Q2: Avoid risk validation | observed after Phase 6.5A.5 control group validation |
| Q3: Watchlist persistence | observed (4/4) |
| Q4: Event score correlation | observed (r=-0.256, n=14) |
| Q5: Category performance | observed (3 categories) |

---

## Phase 5G.1 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create polysignal/interface/dashboard.py | ✅ |
| Create scripts/run_dashboard.py | ✅ |
| Create tests/test_dashboard.py | ✅ |
| Dashboard 5 个页面实现 | ✅ |
| Data loader (runs/, config/) | ✅ |
| Safety check (--check) | ✅ |
| AST-based import safety check | ✅ |
| Run pytest tests/ -v | ✅ (955/955 passed) |
| Update documentation | ✅ |

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

---

## Phase 5F.5 完成情况

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create WatchlistLoader class | ✅ |
| Create MarketPrioritizer class | ✅ |
| Create AvoidAnnotator class | ✅ |
| Create TrajectoryTracker class | ✅ |
| Add watchlist parameters to RunConfig | ✅ |
| Integrate watchlist into scan loop | ✅ |
| Generate watchlist reports | ✅ |
| Create tests/test_watchlist_monitoring.py | ✅ |
| Update documentation | ✅ |
| Run pytest tests/ -v | ✅ |

关键验收：

- Watchlist 只影响扫描顺序，不影响交易决策 ✅
- Avoid annotation 仅做研究标注，不是 hard forbidden ✅
- 不修改 Risk Governor ✅
- 不修改 Signal 模型 ✅
- 不修改策略 ✅
- 向后兼容（无 watchlist 时行为不变） ✅
- live_trading_enabled 保持 false ✅
- allow_auto_execution 保持 false ✅

---

## Phase 5F.5 设计要点

### Watchlist-Driven Monitoring 架构

```
persistent_watchlist.csv ──┐
alpha_candidates.csv ──────┼──► WatchlistLoader ──► MarketPrioritizer ──► Scanner
avoid_candidates.csv ───────┤         │
market_trajectories.json ───┘         │
                                      ▼
                              AvoidAnnotator (仅研究标注)
                                      │
                                      ▼
                              TrajectoryTracker
                                      │
                                      ▼
                              Watchlist Reports
```

### 重要约束

| 约束 | 说明 |
|------|------|
| Watchlist 不触发交易 | 只影响扫描顺序 |
| Avoid 不是 hard forbidden | 仅做研究标注 |
| 不修改 Risk Governor | 保持原有评分逻辑 |
| 不修改 Signal 模型 | avoid_annotation 不进入 Signal |
| 不修改策略 | 策略逻辑不变 |

### 输出文件

| 文件 | 内容 |
|------|------|
| watchlist_monitoring_summary.json | 监控统计 |
| watchlist_monitoring_report.md | 监控报告 |
| watchlist_trajectory_update.json | 轨迹更新 |
| watchlist_events.jsonl | 监控事件日志 |

---

## 上阶段完成情况

### Phase 5F — Multi-Run Intelligence Comparison

| 任务 | 状态 |
|------|------|
| Create scripts/compare_run_intelligence.py | ✅ |
| Create tests/test_compare_run_intelligence.py | ✅ |
| Implement RunDiscovery (--latest_n, --since, --run_ids) | ✅ |
| Implement RunDataLoader (intelligence_summary.json, summary.json, events.jsonl) | ✅ |
| Implement MarketAggregator with market_id/normalized_question fallback | ✅ |
| Implement PersistentWatchlistGenerator with evidence_level | ✅ |
| Implement AlphaCandidateScorer with DISCLAIMER | ✅ |
| Implement AvoidCandidateScorer with category_risk (NOT hard_forbidden) | ✅ |
| Implement CategoryAnalyzer | ✅ |
| Implement ComparisonReportGenerator | ✅ |
| Add --top_n and --min_appearances parameters | ✅ |
| Run pytest tests/ -v | ✅ (870/870 passed) |
| Run comparison analyzer on existing runs | ✅ |
| Update documentation | ✅ |

关键验收：

- Offline analysis only (no real-time API calls) ✅
- No trading execution ✅
- live_trading_enabled remains false ✅
- Alpha score DISCLAIMER present ✅
- Avoid uses category_risk, NOT hard_forbidden ✅
- Evidence level (weak/moderate/strong) included ✅
- Market identity fallback (market_id → normalized_question) ✅
- Top N limit implemented ✅
- 56 new tests ✅

---

## Comparison Analyzer 输出示例

Runs analyzed: 5 runs from 2026-05-09

| 指标 | 值 |
|------|-----|
| Total Runs | 5 |
| Unique Markets | 20 |
| Total LLM Samples | 34 |
| LLM Success Rate | 91.2% |
| Persistent Watchlist | 4 markets |
| Alpha Candidates | 20 markets |
| Avoid Candidates | 20 markets |
| live_trading_enabled | False (all runs) |

---

## 上阶段完成情况

### Phase 5E — Market Intelligence Report / Alpha Discovery

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Create scripts/analyze_run_intelligence.py | ✅ |
| Create tests/test_analyze_run_intelligence.py | ✅ |
| Implement classify_near_miss_tier() | ✅ |
| Implement infer_market_category() | ✅ |
| Implement IntelligenceAnalyzer class | ✅ |
| Add correlation calculation with sample size protection | ✅ |
| Add top candidates sections | ✅ |
| Add safety verification | ✅ |

### Phase 5D.3 — Audit & Metrics Fix

状态：✅ Completed

| 任务 | 状态 |
|------|------|
| Fix p95 latency calculation bug | ✅ |
| Add LLM error type distribution | ✅ |
| Add API error source distribution | ✅ |
| Add WebSocket reconnect summary | ✅ |
| Create audit document | ✅ |

---

## 历史计划：Phase 8K — 已被 Trading MVP Steps 1-12 取代

### 本地开发节奏调整

- 本地代码开发只跑 pytest 和必要的 5-10 minute smoke
- 不再把 4-hour / 10-hour / 24-hour run 作为功能阻塞验收
- 长时间 data collection 迁移到云服务器
- Phase 7B validation loop script 已完成
- Phase 7C systemd/tmux running plan 已完成
- Phase 7D daily report automation 已完成
- Phase 8F.1 offline forward observation collector 已完成
- Phase 8F.2 read-only forward price polling 已完成
- Phase 8G.1 offline token id backfill 已完成
- Phase 8G.2 public Gamma read-only token lookup 已完成
- 5/5 shadow trades 已恢复 yes_token_id / no_token_id
- 5/5 positions 已通过 read-only CLOB polling 写入 forward observations
- 5/5 positions 已关闭并生成 hypothetical PnL
- 当前关键事实：本轮 5 个 shadow trades 的 total_pnl 为 -4.62937062937063，win_rate 为 0.0，max_drawdown 为 -4.62937062937063
- Phase 8H shadow performance review gate 已完成
- 5/5 closed shadow trades 的 primary loss driver 是 price_interpretation_risk
- 当前不进入 tiny live
- Phase 8I 已修正 shadow price model 与 entry filter
- Phase 8J 已为 token-backed tradable candidates 收集 side-specific CLOB bid/ask snapshots
- Phase 8J shadow dry_run 仍为 0 eligible；主要原因是 remaining missing token ids and missing expected edge on control_group-only candidates
- Phase 8K 的 token coverage 工作已由后续 Trading MVP Steps 完成；当前以 Step 12
  的 corrected shadow PnL 数据收集为准，继续保持 tiny live = NO
- 仍不修改 Risk Governor，不进入实盘

### Milestone 5 条件（未来可选，不是当前建议下一步）

- paper trading >= 14 days
- paper trades >= 100
- max drawdown acceptable
- all safety docs complete
- test wallet only
- live trading explicitly enabled
- Risk Governor 二次确认

### 推荐命令

```bash
# Phase 6 validation (已完成)
python3 scripts/validate_strategy_signals.py --runs_dir runs --output_dir runs --min_appearances 2

# Watchlist-driven monitoring
python3 scripts/run_paper.py \
  --duration_minutes 30 \
  --max_markets 20 \
  --data_mode real_readonly \
  --watchlist_file runs/persistent_watchlist.csv \
  --alpha_candidates_file runs/alpha_candidates.csv \
  --avoid_candidates_file runs/avoid_candidates.csv \
  --monitor_mode hybrid \
  --watchlist_priority_ratio 0.6 \
  --discovery_ratio 0.2
```

---

## 注意事项

- Phase 6 已完成 (Strategy Signal Validation)
- Dashboard 是只读研究工具，不触发交易
- Watchlist-driven monitoring 是研究工具，不影响交易决策
- Avoid candidates 仅做风险标注，不是 hard forbidden
- Strategy validation 是验证框架，不是统计证明
- conclusion_status 是描述性观察，不是因果推断
- live_trading_enabled 保持 false
- allow_auto_execution 保持 false
- paper_trading_enabled 保持 true
- default LLM provider 保持 mock
- 当前下一步是 Step 12 versioned historical 1m candle coverage；只有全覆盖证据通过 v6
  后才创建新 cohort 并收集 >=240-minute forward observations，不进入 tiny live
