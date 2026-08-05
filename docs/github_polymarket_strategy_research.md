# GitHub Polymarket Strategy Research

研究日期：2026-08-04

## 1. 研究边界

本轮只读检查 GitHub 源码、测试、文档和许可证。第三方代码没有安装、导入或执行；
README 中的收益、实盘验证和测试数量声明均不作为策略有效性的证据。

项目继续遵守以下边界：

- read-only 与 shadow/paper first
- `live_trading_enabled=false`
- `allow_auto_execution=false`
- 不使用私钥、签名、认证或真实下单路径
- 不允许 LLM 或单一钱包信号触发交易
- 所有策略必须先通过可成交性、结算语义和 Risk Governor 检查

## 2. 固定版本与研究矩阵

| 仓库 | 固定 commit | 可验证机制 | 对 PolySignal Pro 的价值 | 风险与结论 |
|---|---|---|---|---|
| [Polymarket/py-sdk](https://github.com/Polymarket/py-sdk/tree/d6b96adb2b4bdfbeb4739ee023b5606fd08dc05f) | `d6b96adb` | 当前官方 Python SDK；Pydantic `OrderBook`、Decimal 价格/数量、UTC 服务端 timestamp、显式 cursor pagination、bounded WebSocket queue、重连后重发订阅状态 | 作为后续只读数据层迁移与 schema 校准基准 | MIT、beta；当前 MVP 不贸然引入其签名/Web3 依赖，只独立借鉴公开数据与容错契约 |
| [Polymarket/py-clob-client](https://github.com/Polymarket/py-clob-client/tree/b076b04d61135657e25dccc1bbd6866a96bd8c6e) | `b076b04d` | 旧版官方 `OrderBookSummary` 包含服务端 timestamp、逐档 price/size、tick size、min order size、hash | 保留为历史 schema 对照 | MIT，但仓库已归档并声明不再可用；不得作为新集成目标，应迁移到 `py-sdk` |
| [Polymarket/real-time-data-client](https://github.com/Polymarket/real-time-data-client/tree/c937d9c11cdd2b771aa4818392a1b6dda65c25de) | `c937d9c1` | 公开 activity、CLOB market、crypto price 等 WebSocket topic 与毫秒 timestamp | 校准慢速事件/价格流的 topic 和 timestamp 契约 | MIT；不能替代 Binance 规则指定的历史 1m High/Low，也不进入 barrier 证明 |
| [warproxxx/poly-maker](https://github.com/warproxxx/poly-maker/tree/4f32103591c9582ccd012bdf10f77d86e5879444) | `4f321035` | BBO microprice、time-decayed EWMA、fill markout/toxicity、inventory skew、regime、kill switch | 适合后续 markout 与 maker shadow research | MIT；其 `--paper` 只伪造 order id，不模拟成交/PnL，不能作为收益证据 |
| [evan-kolberg/prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting/tree/c76e77af00ef53472a9da8f66dae7fdd2d3e5928) | `c76e77af` | L2 MBP replay、visible liquidity consumption、trade-tick fill evidence、queue-ahead、static latency、fee/rebate scenarios | 为回测真实性和敏感性分析提供主要参考 | mixed MIT/LGPL-3.0-or-later；只独立实现机制，不复制 extension/strategy 源码，不引入 Nautilus 重依赖 |
| [agent-next/polymarket-paper-trader](https://github.com/agent-next/polymarket-paper-trader/tree/ed601ed27b9a2dbaaaeaf2176d0cdcb5cde87e26) | `ed601ed2` | BUY 逐档走 asks、SELL 逐档走 bids、FOK/FAK、VWAP、逐档 fill ledger | 验证最小 L2 execution-cost 接口 | MIT；其 midpoint synthetic backtest 强制 fee=0 且吞掉 strategy exception，不可用来证明 edge |
| [warproxxx/poly_data](https://github.com/warproxxx/poly_data/tree/cab11bd5a2fc41a67c4c643835a4766907208b55) | `cab11bd5` | 链上事件与 CLOB metadata 分阶段合并、增量更新、恢复处理 | 后续历史 trade/market Parquet 管线参考 | GPL-3.0；不复制代码。外部 HyperSync 依赖也不进入当前 MVP |
| [Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis/tree/5330e823d197b3e1eeec8ea1992cfce9f648cf69) | `5330e823` | 可恢复 block cursor、批量 Parquet、市场与 trade 分层存储 | 后续 out-of-sample 数据集和断点续传参考 | MIT；数据量和索引成本大，不应阻塞当前 shadow 验证 |

关键源码证据：

- 当前官方 SDK 的 [Pydantic CLOB orderbook schema](https://github.com/Polymarket/py-sdk/blob/d6b96adb2b4bdfbeb4739ee023b5606fd08dc05f/src/polymarket/models/clob/order_book.py)、[严格 paginator](https://github.com/Polymarket/py-sdk/blob/d6b96adb2b4bdfbeb4739ee023b5606fd08dc05f/src/polymarket/pagination.py) 与 [CLOB reconnect/resubscribe](https://github.com/Polymarket/py-sdk/blob/d6b96adb2b4bdfbeb4739ee023b5606fd08dc05f/src/polymarket/_internal/streams/clob/market.py)
- 已归档旧客户端的 [CLOB orderbook schema](https://github.com/Polymarket/py-clob-client/blob/b076b04d61135657e25dccc1bbd6866a96bd8c6e/py_clob_client/clob_types.py#L151-L176)，仅作历史对照
- 官方 [real-time-data-client topics](https://github.com/Polymarket/real-time-data-client/blob/c937d9c11cdd2b771aa4818392a1b6dda65c25de/README.md)；其中 crypto price update 不是规则指定的 Binance 1m candle 证据
- `poly-maker` 的 [microprice](https://github.com/warproxxx/poly-maker/blob/4f32103591c9582ccd012bdf10f77d86e5879444/src/polymaker/marketdata/orderbook.py#L117-L134)、[markout/toxicity](https://github.com/warproxxx/poly-maker/blob/4f32103591c9582ccd012bdf10f77d86e5879444/src/polymaker/strategy/estimators.py#L137-L177)、[inventory quote construction](https://github.com/warproxxx/poly-maker/blob/4f32103591c9582ccd012bdf10f77d86e5879444/src/polymaker/strategy/quoting.py#L61-L127) 和 [regime priority](https://github.com/warproxxx/poly-maker/blob/4f32103591c9582ccd012bdf10f77d86e5879444/src/polymaker/strategy/regime.py#L44-L70)
- 回测框架的 [L2/queue/latency 边界](https://github.com/evan-kolberg/prediction-market-backtesting/blob/c76e77af00ef53472a9da8f66dae7fdd2d3e5928/docs/execution-modeling.md#L67-L170)、[microprice/imbalance strategy](https://github.com/evan-kolberg/prediction-market-backtesting/blob/c76e77af00ef53472a9da8f66dae7fdd2d3e5928/strategies/microprice_imbalance.py#L122-L267) 和 [non-atomic pair risk](https://github.com/evan-kolberg/prediction-market-backtesting/blob/c76e77af00ef53472a9da8f66dae7fdd2d3e5928/strategies/binary_pair_arbitrage.py#L121-L240)
- paper trader 的 [逐档 FOK/FAK fill model](https://github.com/agent-next/polymarket-paper-trader/blob/ed601ed27b9a2dbaaaeaf2176d0cdcb5cde87e26/pm_trader/orderbook.py)
- historical pipeline 的 [staged update](https://github.com/warproxxx/poly_data/blob/cab11bd5a2fc41a67c4c643835a4766907208b55/update_utils/pipeline.py) 与 [resumable block cursor](https://github.com/Jon-Becker/prediction-market-analysis/blob/5330e823d197b3e1eeec8ea1992cfce9f648cf69/src/indexers/polymarket/trades.py)

## 3. 关键技术结论

### 3.1 可成交价格必须替代 best-price 假设

一个 best ask 只能证明第一档存在，不能证明 `$1` 或更大 notional 可以成交。
正确的 shadow entry 应按 asks 从低到高逐档消耗；exit 应用 entry 得到的同一 shares，
按 bids 从高到低逐档消耗。深度不足时默认 FOK/fail closed，不能线性放大 PnL。

本轮已独立实现 [execution_cost.py](../polysignal/shadow/execution_cost.py)：

- 固定 dollar notional BUY sweep
- 固定 shares SELL sweep
- limit price 约束
- 完整/部分/拒绝三种显式状态
- VWAP、最差价、visible depth、adverse impact、fee 和逐档 ledger
- entry 后使用完全相同 shares 的 round-trip 估算

该模块是纯函数，无 I/O、网络、认证、密钥和执行路径。当前 fee 是明确标注的
flat-notional bps 研究假设；它不冒充 Polymarket 某市场的真实动态 fee schedule。

### 3.2 L2 回测仍不是实盘成交证明

L2 MBP 只显示某价格档位的聚合数量。maker 策略还必须建模 queue-ahead、trade tick、
insert/cancel latency 和 liquidity consumption。即便如此，隐藏流动性、ahead cancellation
和真实 L3/FIFO priority 仍不可观测。因此 maker fill 应报告情景区间，而不是单点收益。

### 3.3 Markout 比“胜率”更适合发现逆向选择

对每次 hypothetical fill，建议记录 `5s / 30s / 300s` markout：

- BUY：未来可执行 bid 或 fair value 减去 entry fill price
- SELL：entry fill price 减去未来可执行 ask 或 fair value
- 同时保留 executable-price 与 mid/microprice 两个口径
- 缺少、过早、stale 或乱序观察必须为 null

`poly-maker` 的单 horizon EWMA 概念可借鉴，但其同一 timestamp 批量到期 markout 可能因
`dt=0` 让后续样本没有权重；实现时不能照搬。

### 3.4 Microprice/imbalance 只能作为候选信号

适合本项目的下一候选是：

```text
BBO microprice edge
+ top-N depth imbalance
+ max spread gate
+ size-aware entry/exit VWAP
+ markout toxicity gate
+ lifecycle/resolution gate
```

这是一条可测试的 shadow hypothesis，不是已验证 alpha。尤其不能直接采用开源参数：
`poly-maker` 的 `flow_z` 实际是 signed EWMA / absolute EWMA，理论范围接近 `[-1, 1]`，
但默认 trending threshold 为 `1.5`，对应分支不可达。

### 3.5 YES/NO pair arbitrage 必须显式建模 leg risk

两边 `ask VWAP + fees < 1` 是必要条件，但两个 CLOB order 不是原子事务。研究输出必须分别
报告 YES/NO 可成交数量、两腿成本和单腿成交后的 hedge/flatten 风险。当前只允许 shadow，
不应把 combined best ask 当成可执行无风险套利。

### 3.6 官方 SDK 已换代，但当前不应仓促替换数据层

截至本次复核，`py-clob-client` 与 TypeScript `clob-client` 均已归档，并明确要求迁移到
`py-sdk` / `ts-sdk`。`py-sdk` 的几个契约值得直接吸收：

- 外部 orderbook 立即进入 typed Pydantic model，价格和数量使用 Decimal，timestamp 转为 UTC
- `has_more=true` 却没有 `next_cursor` 时直接报错，禁止把分页截断冒充完整扫描
- WebSocket 使用有界队列，统计 malformed/dropped event，并在重连后重发完整订阅状态
- 有副作用或花费资金的 integration test 需要额外的 `metered` 显式开关

本项目当前不新增 `polymarket-client` 依赖：它仍是 beta，并带入签名与 Web3 依赖；当前自研
只读客户端已有测试覆盖。Historical barrier integration 已完成；应先等待正式 v7 cohort
取得至少 240 分钟的合格 forward observations，并累计至少 5 个独立 cluster，再做隔离的
read-only adapter 对比。不允许借 SDK 迁移绕过既有 provenance。

## 4. 策略优先级

| 优先级 | 策略/能力 | 当前决定 | 进入下一阶段的条件 |
|---|---|---|---|
| P0 | 数据新鲜度、resolution provenance、逐档 size/VWAP、历史 barrier coverage | discovery v5 / validator v7 已完成历史证据集成；正式 cohort 有 12 个 discovery entries、11 个 fresh positions | entry 后 >=240 分钟的合格 out-of-sample observations + >=5 个独立 cluster；当前只有 3 个 cluster |
| P1 | L2 execution cost 与 round-trip ledger | 已完成独立基础模块 | 接入 run-scoped shadow artifact，并保留完整 provenance |
| P1 | 多 horizon markout/adverse selection | 下一安全迭代 | 有因果、有新鲜度、同 side 的 forward L2 observations |
| P2 | microprice + top-N imbalance | research-only | 经成本/markout gate 后做 out-of-sample shadow validation |
| P3 | maker-only inventory/regime | 暂不启用 | 先有 L2 replay、queue/latency sensitivity 和 inventory lifecycle |
| P3 | cross-market/YES-NO pair | 暂不启用 | resolution semantic match、双腿容量和 leg-risk 模型完整 |
| Reject | pure copy trading、LLM autonomous trading、宣传型“高胜率”策略 | 不采纳 | 不适用 |

## 5. 当前项目审查影响

安全审查已推动 validator 升级为 `crypto_threshold_shadow_pnl_v7`（仅接受 discovery v5）：resolution
source/rules/fingerprint/status、YES/NO 服务端 timestamp、entry/forward 四个 best-level
size、5 秒最大 clock skew、完整 entry identity、immutable prepared input 和 entry/exit
份额守恒都已 fail closed。Discovery 也会将 resolution、expiry 或历史 barrier evidence
不合格的候选直接降级为 `watch_only`。

用 v4 对 `step12_20260804_122700` 做只读 dry-run 后，原 44 个候选全部失效：44/44 缺
resolution provenance、44/44 缺 best-level size，且 25 个候选的 YES/NO 服务端盘口时间
stale；因此 position 为 0、PnL 为 null、状态为 `entry_snapshot_refresh_required`。该 run
与更早的 `step12_20260804_114000` 只能保留为审计材料，禁止继续 poll 或补写 entry-time
证据。当时的下一次验证必须从全新 v4 run 开始；当前任何新 position 仍需满足 entry 后至少
240 分钟 forward observation 与至少 5 个独立 cluster 的固定门槛，才能讨论期望值。

随后创建的全新 v4 run `step12_v4_20260804_064741` 做了真实 public read-only coverage
check：扫描 1958 个 Gamma markets，解析 44 个 threshold markets，取得 88 个公开 CLOB
orderbooks，但结构化 `resolutionSource` 覆盖为 0/44，因此 discovery 正确地产生
`0 shadow_entry / 44 watch_only`。离线 validator 的状态为
`entry_snapshot_refresh_required`，position、forward observation 和 PnL 均为空；poller
在 `positions_loaded=0` 下安全退出，没有 API 错误或持仓更新。Gamma 末页 422 被记录为
可恢复分页错误。规则正文中虽出现 Binance URL，本轮没有把未版本化的自然语言链接当作
可信 source，以免伪造 resolution provenance；当时确定的 adapter 要求是记录提取来源、
规则指纹并新增 fail-closed 测试。

该 gap 已通过独立版本的 `resolution_source_adapter_v1` 处理，而不是放松 v4 字段要求。
Adapter 优先使用结构化 Gamma source；fallback 只接受明确 resolution-source section 中的
唯一 HTTPS URL，并要求 exact trusted host。HTTP、多个 URL、non-string、untrusted host、
结构化与规则来源冲突均 fail closed。Binance 还必须同时匹配 candidate asset、
`BTC|ETH|SOL`/USDT 路径、规则 pair、1m candle 以及 up/High 或 down/Low 语义。Origin、
locator、adapter version、rules SHA-256 和 provenance digest 都被持久化；stable trade ID
绑定 adapter version、rules hash 和 provenance digest。旧 v4 artifacts 现在全部 audit-only。

v5 run `step12_v5_20260804_073542` 现为 audit-only：它曾产生 10 positions，但被 v6
审计发现 expiry timezone、touch history、完整 forward book 和 entry identity 均不足，禁止
继续 poll、迁移或用于 PnL。

最新 v6 run `step12_v6_20260804_083736` 扫描 1958 个 Gamma markets，检测 56 个 crypto
markets 并解析 44 个 threshold candidates。44/44 source 与 expiry provenance verified，
canonical expiry 为 `2027-01-01T04:59:00Z`（title-local `2026-12-31 23:59 ET`）；44/44
touch candidates 缺少完整历史 1m candle coverage，因此 discovery 为 `0 shadow_entry / 44
watch_only`，validator strict gate/positions=0，PnL=null，status=
`historical_barrier_evidence_required`。Gamma 末页 422 已记录，扫描不宣称 exhaustive。

v6 完整回归为 `1664 passed in 264.97s`，exit code 0；scoped Ruff/format/mypy/py_compile
与 `uv lock --check` 通过。Repository-wide Ruff 仍有 1786 个历史存量 finding，因此本轮
不宣称全仓 lint clean。

v6 结果是历史审计材料，不是 edge 证明；它暴露的 historical barrier gap 已由 discovery
v5 / validator v7 的 versioned 1m candle coverage adapter 完成。当前正式 v7 cohort 已有
43/44 verified barrier manifests，缺规则起点的候选 fail closed，不会猜测或下载历史数据。

正式 v7 cohort `step12_v7_20260804_140305` 的只读结果：扫描 1,958 个 Gamma markets，识别
56 个 crypto markets、解析 44 个 candidates；3 preloads + 3 entry tails 共享 3 个 candle
snapshots，并保留 43 个 threshold-specific manifests。Discovery 产生 12 shadow entries / 32
watch-only；validator 创建 11 个 fresh paper positions（BTC 3、ETH 5、SOL 3），仅 3 个
asset/expiry/contract-kind clusters。记录时 0 个 observation 合格、0 个 position closed，
forward coverage=0.0，PnL 和 win rate 均为 null，status=`insufficient_forward_data`。
Gamma 末页有可恢复错误，因此扫描不宣称 exhaustive。

历史 barrier integration 已完成；当前 blocker 是 entry 后至少 240 分钟的完整 forward
observations，以及至少 5 个独立 clusters。当前 cohort 不支持 edge、expectancy、profitability
或 tiny-live 结论，`supports_tiny_live=false`、`tiny_live_recommendation=NO`。达到 horizon
后也只能进行一次新的 public read-only poll，并将不完整/过期/身份或容量不匹配的 observation
保持为 null。v6 及更早 artifacts 继续 audit-only，禁止迁移、补写或参与 PnL。

PaperTrader 的执行层也已收紧：单腿 entry 按可见 asks 逐档确定性成交，执行价格受硬
limit 和压力 slippage 上限约束，并拒绝 stale/mismatched orderbook、signal/risk mismatch
以及 hard rejection。BUY NO PnL、close order size 和 outcome-token position isolation 已
修复。当前接口仍只能返回一个 order 和一个 position，所以 `SignalSide.BOTH` 明确
fail closed；typed two-leg result、独立两腿 ledger 和 leg-risk/flatten 语义完成前，不会
伪造 paired fill。另一个待明确问题是 risk-reducing close 的专用 RiskDecision 语义，
避免把新 entry 的硬拒绝规则机械套用到合理减仓。

## 6. 验收清单

- 多档 sweep、limit 边界、重复价格档聚合测试
- entry/exit 任一腿深度不足必须拒绝 round trip
- fees/slippage 后 edge 消失必须反映在 net PnL
- CLOB ISO、epoch-second、epoch-ms timestamp 全覆盖，missing/invalid/stale/future fail closed
- resolution source/origin/locator/adapter/rules/digest 缺失、歧义或冲突时只能 watch-only
- resolution URL 必须是显式上下文中的唯一 HTTPS exact-host source；Binance pair/1m/High-Low
  语义必须一致
- title expiry、Gamma lifecycle timestamp 与 rules timezone 不一致时 fail closed
- touch contract 缺少完整规则起点到 entry 的历史 1m candle coverage 时必须 watch-only
- 同一时间多个 fill 的 markout 全部计入
- replay 对乱序、数据缺口、stale 和重复事件保持确定性
- queue/latency 使用多情景敏感性，不使用单一乐观值
- Risk Governor、live flags、secret handling 不得被绕过
- 任何收益结论必须 out-of-sample，并报告样本数、cohort、成本与数据覆盖率
