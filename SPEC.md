# SPEC.md — PolySignal Pro 产品、架构与风控规格说明

本文件是 PolySignal Pro 的项目规格说明，是产品目标、系统架构、模块职责、策略边界、风控规则和验收标准的单一事实来源。

所有实现必须以本文件为准。

---

## 1. 项目概述

PolySignal Pro 是一个 7×24h 运行的 Polymarket 预测市场情报分析与交易研究系统。

系统默认运行模式为：

```text
Read-only market monitoring
+ Signal generation
+ Paper trading
+ Telegram alert
+ Dashboard / report
+ Strict risk governance
```

系统不是：

* 暴富脚本
* 稳赚机器人
* 无脑 copy trading bot
* LLM 自主交易系统
* 高频抢跑系统

系统目标是：

* 研究 Polymarket 市场结构
* 发现潜在错价和信息滞后
* 构建可解释信号
* 长期记录 paper trading 结果
* 用严格风控验证策略
* 逐步评估是否允许小额实盘

---

## 2. 核心架构

PolySignal Pro 由四个智能引擎和一个中央风控中枢组成：

```text
Market Microstructure Engine
Wallet Intelligence Engine
Event Intelligence Engine
Resolution & Lifecycle Engine
        ↓
Risk Governor
        ↓
Log / Alert / Paper Trade / Manual Review / Limited Live Execution
```

### 2.1 Market Microstructure Engine

职责：

* 分析 CLOB 盘口
* 监控 best bid / best ask
* 计算 spread、depth、mid price
* 检测 YES/NO 合成错价
* 检测 orderbook imbalance
* 检测 liquidity shock

输出：

* microstructure_score
* liquidity_score
* spread_score
* imbalance_score
* yes_no_mispricing_signal

### 2.2 Wallet Intelligence Engine

职责：

* 追踪 watchlist wallets
* 建立 wallet profile
* 计算 wallet_score
* 识别 wallet specialization
* 过滤高风险 copy 信号

输出：

* wallet_score
* wallet_consensus_score
* copy_risk_score
* wallet_recent_state

### 2.3 Event Intelligence Engine

职责：

* 解析 market title / description / resolution rules
* 处理外部事件数据
* 使用 LLM 判断事件相关性和歧义风险
* 生成结构化 event assessment

输出：

* event_score
* evidence_strength
* market_relevance
* ambiguity_risk
* suggested_mode

### 2.4 Resolution & Lifecycle Engine

职责：

* 跟踪市场生命周期
* 判断市场是否临近结束
* 判断 resolution source 是否清晰
* 判断是否存在争议风险
* 输出 tradable 状态

输出：

* lifecycle_score
* tradable
* ambiguity_risk
* resolution_risk
* close_time_risk

### 2.5 Risk Governor

职责：

* 接收所有 engine 输出
* 执行硬性拒绝条件
* 计算 trade_score
* 决定最终动作
* 控制 paper trading 与 live trading 权限

---

## 3. 快慢分层执行架构

系统必须区分快速路径和慢速路径。

### 3.1 Ultra-fast path

触发来源：WebSocket orderbook update。

用途：

* YES/NO combined ask detection
* spread / depth / imbalance
* price impact

禁止：

* 调用 LLM
* 访问慢速 API
* 查询网页
* 重新计算钱包画像

目标延迟：0.1–2 秒。

### 3.2 Fast path

用途：

* 临近结算机会
* 市场状态变化
* 已缓存事件数据判断

目标延迟：5–30 秒。

### 3.3 Slow path

用途：

* 钱包画像
* LLM 分析
* 新闻摘要
* 市场规则解析

目标延迟：1–15 分钟。

### 3.4 Research path

用途：

* 日报
* 复盘
* 策略统计
* 钱包排名

目标延迟：小时级或天级。

---

## 4. MVP 范围

### Milestone 1 必须完成

* 项目基础结构
* 配置加载
* SQLite 存储
* mock market data
* mock orderbook updates
* Market Microstructure Engine
* YES/NO mispricing strategy
* Risk Governor
* Paper Trader
* Telegram alert optional
* CLI 或 dashboard summary
* 核心测试

### Milestone 1 不包含

* 真实实盘下单
* 私钥处理
* 全量钱包画像
* 完整 LLM 新闻分析
* 复杂 dashboard
* 自动实盘

---

## 5. 策略规格

### 5.1 YES/NO 合成错价策略

逻辑：

```text
combined_ask = yes_best_ask + no_best_ask
```

初始信号阈值：

```text
combined_ask <= 0.985
```

必须满足：

* total volume >= 100000 USD
* 24h volume >= 50000 USD，若该数据可用
* YES side depth >= 20 USD
* NO side depth >= 20 USD
* spread <= 3%
* price not stale
* lifecycle tradable = true
* ambiguity risk below threshold

默认动作：paper trade + alert。

禁止默认 live execution。

---

### 5.2 Orderbook Imbalance 策略

逻辑：

* 检测 bid / ask depth 的明显失衡
* 检测短时间 trade velocity 异常
* 检测 spread 收窄或扩大

用途：

* 辅助评分
* 研究记录
* alert

禁止：

* 单独触发实盘

---

### 5.3 Settlement Edge 策略

逻辑：

* 市场接近结束
* 外部结果接近明确
* 市场价格尚未完全收敛

默认动作：manual review + paper trade。

禁止自动实盘类别：

* politics
* war
* legal judgment
* subjective market
* unclear source

---

### 5.4 Wallet Consensus 策略

逻辑：

* 多个高质量钱包同向行动
* 钱包在该市场类别有稳定表现
* 钱包行为没有明显追高或异常

用途：

* 作为 component score
* 作为 alert 解释

禁止：

* 纯 copy trading 自动实盘
* 钱包信号单独触发交易

---

### 5.5 Event Lag 策略

逻辑：

* 外部事件变化早于市场价格反应
* 事件证据强
* 市场规则清晰
* 信息源可验证

MVP 允许研究类别：

* Crypto
* Sports
* Weather
* Macro data

禁止自动执行类别：

* Politics
* War / geopolitics
* Legal judgments
* Celebrity / pop culture
* Subjective markets

---

## 6. Risk Governor 规格

### 6.1 评分公式

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
```

### 6.2 决策阈值

```text
score < 70        → ignore
70 <= score < 80  → log only
80 <= score < 90  → Telegram alert + paper trade
90 <= score < 95  → Telegram alert + paper trade + manual review
score >= 95       → paper trade by default; live only if explicitly enabled
```

### 6.3 硬性拒绝

任何以下条件成立时，必须拒绝 live execution：

* live_trading_enabled = false
* allow_auto_execution = false 且没有人工确认
* market ambiguous
* forbidden category
* spread too wide
* depth too thin
* stale price
* API unhealthy
* WebSocket unhealthy
* invalid LLM output
* high resolution risk
* daily loss limit breached
* weekly loss limit breached
* consecutive loss limit breached
* wallet signal is the only reason

---

## 7. 默认风控参数

```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
max_account_capital_usd: 100
max_position_pct: 0.01
max_market_exposure_pct: 0.03
max_strategy_exposure_pct: 0.08
daily_max_loss_pct: 0.03
weekly_max_loss_pct: 0.08
max_consecutive_losses: 3
order_timeout_seconds: 20
max_price_drift_pct: 0.02
min_total_volume_usd: 100000
min_24h_volume_usd: 50000
max_spread_pct: 0.05
min_depth_usd: 20
```

---

## 8. 数据存储规格

MVP 使用 SQLite。

至少包含表：

* markets
* orderbook_snapshots
* signals
* paper_orders
* paper_positions
* wallet_profiles
* event_assessments
* risk_decisions
* system_health
* blacklist

每个 signal 必须可复盘。

---

## 9. Telegram 规格

Telegram alert 必须包含：

* market title
* strategy
* side
* current price
* trade_score
* component_scores
* risk_flags
* decision
* reason

按钮：

* Paper
* Manual Review
* Ignore
* Blacklist Market
* Track Wallet

MVP 中按钮可以只记录操作，不执行实盘。

---

## 10. Dashboard 规格

Dashboard 至少展示：

* system health
* recent signals
* paper PnL
* strategy performance
* risk decisions
* open paper positions
* wallet scores
* blacklisted markets

---

## 11. 测试验收标准

Milestone 1 完成前必须通过：

* config validation tests
* Risk Governor tests
* YES/NO mispricing tests
* Paper Trader tests
* Lifecycle tests
* invalid LLM JSON tests
* mock integration test

任何测试不得下真实订单。

---

## 12. 安全验收标准

项目必须满足：

* `.env` 不提交
* `.env.example` 存在
* live trading 默认关闭
* secret 不进入日志
* live trader MVP 为 stub
* Risk Governor 不可绕过
* README 有风险提示
* docs/risk_policy.md 完整

---

## 13. 非目标

本项目当前阶段不追求：

* 稳赚
* 高频交易
* 大资金实盘
* 完全自主 AI 交易
* 无风控自动跟单
* 面向用户售卖信号
* 营销式暴利展示

任何实现不得偏离这些边界。

---

## 14. Crypto Threshold Research Strategy

`crypto_price_threshold_v1` 仅用于 read-only discovery 和 shadow validation。
它不是 ultra-fast strategy，也不得直接进入任何 execution path。

### 14.1 合约语义

候选必须显式保存：

* `contract_kind`: `settlement_threshold` 或 `touch_before_expiry`
* `barrier_direction`: `up` 或 `down`
* `threshold_price`
* `expiry_time`
* `parser_version` 和 `model_version`

资产、阈值、方向和到期信息必须来自市场标题中的明确证据。描述文本中的示例价格、
其他市场价格或结算说明不得被当作标题阈值。以下情况只能 `watch_only` 或排除：

* barrier direction unknown or conflicting
* barrier already crossed for a touch contract
* non-price performance / ranking market
* missing title-local threshold or expiry
* stale spot or CLOB snapshot
* unclear resolution semantics

### 14.2 Corrected Shadow PnL 契约

每个 validation run 必须使用独立目录，并记录候选、avoid list、forward observation、
prepared entry input 和最终 shadow trade output 的可区分 SHA-256。Discovery 必须先承诺
未来的 exact-minute batch entry，再采集 spot 与 YES/NO orderbook；候选只能在所有证据取得
且该分钟到达后写出。Spot、client quote 与两侧 server timestamp 必须不晚于 entry 且不旧于
60 秒。Discovery 必须输出 `crypto_threshold_edge_discovery_v5` /
`crypto_threshold_parser_v4`；Validator schema 必须为 `crypto_threshold_shadow_pnl_v7`，并
保存可验证的 resolution source、完整 rules、rules
SHA-256、source origin、source locator、adapter version、provenance SHA-256 和
`resolution_status=verified`；任一字段缺失、冲突或歧义时，discovery 必须降级为
`watch_only`，validator 必须拒绝 entry。旧 v5 及更早 artifacts 只能审计，不得迁移、
补写 provenance、继续 poll 或参与 PnL。

Title expiry 必须同时保存 local time、rules timezone、canonical UTC、Gamma `endDate`、
Gamma metadata、adapter version 和 provenance digest。`gamma_expiry_adapter_v1` 只接受
明确的 ET/UTC 规则 timezone，并在 120 秒内与带时区的 Gamma `endDate` corroborate；冲突、
缺失或 naive Gamma 时间一律 fail closed。Touch contract 还必须保存历史 barrier candle
coverage 的 source、起止时间和 SHA-256；状态不是 `verified_full_coverage` 时必须
`watch_only`，validator 不得创建 entry。

同一资产和规则起点的 ladder 候选必须共享一次 preload、一次 entry tail 和一个
content-addressed candle snapshot；每个 threshold 仍必须有独立 manifest。Gamma
`startDate` 只作为市场 lifecycle metadata 保存，不得替代或重定义规则正文中的 barrier
start。缺少 rules-defined start 时不得下载历史来猜测。

`resolution_source_adapter_v1` 的规则如下：

* 优先读取结构化 Gamma source 字段；否则只接受明确 resolution-source 上下文中的唯一 URL
* URL 必须是 HTTPS，且 hostname 必须精确匹配 allowlist；禁止 suffix/subdomain 猜测
* 当前精确 host allowlist 为 Binance、Coinbase、Kraken、CoinGecko、CoinMarketCap、OKX、
  Bybit 的明确 public hosts（含代码中逐项列出的 `www`/exchange 变体）
* Binance URL 必须匹配 `/en/trade/{BTC|ETH|SOL}_USDT`，并与候选 asset、规则中的
  `ASSET/USDT`、`1m`/one-minute 以及 up=`High`/`equal to or greater`、
  down=`Low`/`equal to or lower` 语义一致
* non-string source/rules、HTTP、多个 URL、未知 host、结构化 source 与规则 URL 冲突、
  locator/digest/rules hash 不一致时一律 fail closed；非 Binance source 还必须在 URL 和
  去除 URL 后的规则正文中各自唯一匹配 provider 与 asset，不能让 URL 自身伪造语义

稳定 shadow trade ID 必须绑定 discovery schema/parser、expiry/resolution provenance、spot、
所有 client/server 时间戳、四个 entry 价格与 size、token pair、notional/shares 和 gate
字段；prepared input 在覆盖前必须保存为内容寻址的不可变快照，避免规则、盘口或 sizing
变化后复用旧 entry。

Entry 必须同时保存 client-observed quote timestamp、YES/NO 原始服务端 orderbook
timestamp，以及四个 best bid/ask price 和对应 size。Entry evidence 默认不得超过 60 秒，
未来时钟偏差硬上限为 5 秒；已持久化的 client timestamp 不得替代或绕过服务端时间检查。
Entry 使用 selected-side best ask；exit 只能使用同一 side 的 best bid。不得回退到 generic
price、mid price 或 combined ask。

数量必须守恒：`entry_shares = notional_usd / selected_entry_ask`。Selected entry ask 的
可见 size 必须覆盖全部 `entry_shares`，forward selected-side bid 的可见 size 也必须覆盖
同一份额；否则不创建或关闭 shadow position，不允许按比例放大 best-level PnL。

Forward observation 必须同时满足：

* exact shadow trade ID, market ID, side and YES/NO token pair
* strictly later than entry and not later than evaluation time
* at least 240 minutes after entry
* not later than market expiry
* trusted public read-only CLOB source with explicit `stale=false` and empty error
* valid, non-crossed YES/NO bid/ask prices, all four best-level sizes, and server timestamps
* selected-side exit bid size sufficient for the exact entry shares

Title-derived expiry、Gamma lifecycle timestamp 和规则正文中的时区必须一致并保留 timezone
provenance。Naive timestamp 不得默认当作 UTC 参与 expiry cutoff。v5 cohort 暴露的标题
`23:59`/ET 偏差已在 v6 adapter 中 fail closed；v5 只能审计，不能证明 expectancy 或推进
tiny live。

缺少合格 observation 时，exit price、return 和 PnL 必须为 null/blank，不能写零收益。
报告必须展示 asset、expiry、side、contract kind、barrier direction 和 cohort 集中度。
旧 schema 或缺少 entry-time evidence 的 run 只能保留用于审计，不得通过后续补字段继续
poll 或参与 PnL；必须从新的 run-scoped discovery 重新开始。

### 14.3 推进门槛

单一 threshold ladder 中的多行和重复分钟扫描都不等于独立样本。Cohort 固定按
asset、expiry 和 contract kind 聚合；任何正期望结论都必须有足够的独立 cohort 和
out-of-sample forward observations。当前阶段固定：

```text
supports_tiny_live = false
tiny_live_recommendation = NO
```

`step12_v5_20260804_073542` 是 audit-only：10 个 position 分布在 3 个 cluster，且其
expiry、touch history 和完整 identity 合约已被 v6/v7 取代。最新
`step12_v7_20260804_140305` 扫描 1,958 markets、解析 44 candidates，以 3 preload + 3 tail
生成 3 个共享 candle snapshots 和 43 个 threshold manifests；43/44 historical barrier
verified，缺规则起点的 1 个候选继续 fail closed。Discovery 产生 12 entries，validator v7
创建 11 个 fresh paper positions，分布在 3 个 cluster；closed=0、PnL=null、status=
`insufficient_forward_data`。Discovery heuristic 的 expected-edge 字段不是 edge 或收益
证明；Gamma 末页错误也意味着该扫描不宣称 exhaustive。

当前单腿 PaperTrader 不支持 `SignalSide.BOTH`。任何 YES/NO 双腿策略在 typed two-leg
result、独立两腿 ledger/position 和 leg-risk 处理接通前必须 fail closed；不得把 BOTH
静默解释为 BUY YES，也不得假定两腿原子成交。
