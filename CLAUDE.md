# CLAUDE.md — PolySignal Pro Claude Code 工程行为规范

本文件是 PolySignal Pro 项目的最高级 Claude Code 工程行为规范。Claude Code、Agent Teams、Subagents、自动化脚本和任何 AI coding assistant 在本仓库内工作时，必须优先遵守本文件。

PolySignal Pro 是一个 7×24h 运行的 Polymarket 预测市场情报分析、模拟交易、信号推送与严格风控研究系统。它不是暴富脚本，不是稳赚机器人，也不是无脑自动交易 bot。

本项目第一目标是：稳定、可测试、可解释、可风控、可长期运行。

---

## 1. 最高优先级原则

所有代码、文档、配置、测试和重构都必须遵守以下原则：

1. 默认只读监控与模拟交易。
2. 默认关闭实盘交易。
3. LLM 永远不能直接下单。
4. 任何策略都不能绕过 Risk Governor。
5. 任何 live trading 代码都必须由显式 feature flag 关闭。
6. 不允许硬编码私钥、API key、Telegram token、钱包密钥或任何 secret。
7. 不允许为了跑通 demo 牺牲风控、测试、日志和可维护性。
8. 不允许把复杂逻辑堆进单个大文件或 God class。
9. 不允许在未理解现有架构前重复造轮子。
10. 安全性、可解释性、可测试性优先于功能数量。

如果用户要求与上述原则冲突，必须优先遵守本文件。

---

## 2. 项目定位

PolySignal Pro 是 research-first 的 prediction market intelligence system。

系统围绕四个智能引擎与一个风控中枢构建：

```text
PolySignal Pro
├── Market Microstructure Engine
├── Wallet Intelligence Engine
├── Event Intelligence Engine
├── Resolution & Lifecycle Engine
└── Risk Governor
```

系统需要 7×24h 运行，但 7×24h 运行不等于 7×24h 自动下注。

大多数时间系统应该执行：

* 观察市场
* 更新盘口
* 记录数据
* 生成信号
* 模拟交易
* 推送 Telegram alert
* 等待人工确认
* 生成复盘报告
* 更新策略统计

实盘交易不是 MVP 第一优先级。

---

## 3. 快慢分层架构原则

禁止让四个 engine 串行阻塞。系统必须采用 fast / slow path 架构。

### 3.1 Ultra-fast path

用途：

* WebSocket orderbook updates
* YES/NO combined ask 检测
* spread / depth / imbalance
* price impact
* trade velocity

约束：

* 不调用 LLM
* 不访问慢速网页
* 不重新计算钱包画像
* 不进行复杂 I/O
* 只读取内存或缓存中的最新分数
* 目标延迟：0.1–2 秒
* 默认动作：log、paper trade、Telegram alert

### 3.2 Fast path

用途：

* 临近结算机会
* 高置信市场状态变化
* 已缓存外部事件数据判断

约束：

* 目标延迟：5–30 秒
* 可以读取缓存好的事件和生命周期分数
* 默认动作：Telegram review + paper trade

### 3.3 Slow path

用途：

* 钱包画像
* 事件分析
* LLM rule parsing
* 新闻摘要
* 市场分类
* 日报生成

约束：

* 目标延迟：1–15 分钟
* 不允许阻塞 ultra-fast path
* 只生成缓存分数、解释和研究结果

### 3.4 Research path

用途：

* 日报
* 策略表现统计
* 钱包排名
* 回测式分析
* 长周期优化

约束：

* 目标延迟：小时级或天级
* 不参与即时交易决策

---

## 4. 推荐目录结构

尽量遵守以下结构，不要随意新增混乱目录：

```text
PolySignal-Pro/
├── README.md
├── CLAUDE.md
├── AGENTS.md
├── SPEC.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml
├── config/
│   ├── app.yaml
│   ├── risk.yaml
│   ├── markets.yaml
│   ├── wallets.yaml
│   └── llm.yaml
├── polysignal/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── logging_config.py
│   ├── ingestion/
│   ├── engines/
│   ├── strategies/
│   ├── risk/
│   ├── execution/
│   ├── storage/
│   ├── interface/
│   ├── llm/
│   └── utils/
├── tests/
└── docs/
```

禁止：

* 将业务代码放在根目录
* 将测试代码混入业务模块
* 将配置散落在代码中
* 在多个地方重复定义同一数据结构
* 把实验脚本和正式模块混在一起

---

## 5. 技术栈约束

默认技术栈：

* Python 3.11+
* asyncio
* Pydantic
* SQLite
* pytest
* ruff
* black
* Telegram Bot API
* Streamlit 或 FastAPI dashboard
* Docker / docker-compose

MVP 阶段不要强依赖：

* Redis
* PostgreSQL
* Kubernetes
* Celery
* 复杂微服务
* 多语言混合工程
* 真实下单 SDK

除非 SPEC.md 明确要求，否则不要引入大型依赖。

---

## 6. 配置管理规范

配置必须集中在：

```text
config/
├── app.yaml
├── risk.yaml
├── markets.yaml
├── wallets.yaml
└── llm.yaml
```

敏感信息必须来自环境变量，不允许写入配置文件。

必须提供 `.env.example`，但禁止提交 `.env`。

默认配置必须包含：

```yaml
live_trading_enabled: false
allow_auto_execution: false
paper_trading_enabled: true
```

任何 live trading 相关逻辑必须同时检查：

1. `LIVE_TRADING_ENABLED=true`
2. `ALLOW_AUTO_EXECUTION=true` 或收到人工确认
3. Risk Governor 通过
4. 钱包凭据存在且来自环境变量
5. 当前市场不是 forbidden category

缺一不可。

---

## 7. 数据模型规范

跨模块传递的数据必须使用 Pydantic model 或明确 typed dataclass。

禁止在模块边界传递未经校验的裸 dict。

核心模型至少包括：

* Market
* OrderBookSnapshot
* Signal
* EngineScore
* RiskDecision
* PaperOrder
* PaperPosition
* WalletProfile
* EventAssessment
* LifecycleState
* SystemHealth

每个 Signal 必须包含：

```text
signal_id
timestamp
market_id
market_title
strategy_name
side
price
component_scores
risk_flags
decision
reason
```

每个 RiskDecision 必须包含：

```text
decision
trade_score
hard_reject_reasons
component_scores
allowed_actions
explanation
```

---

## 8. Risk Governor 规范

Risk Governor 是系统最高权限。

任何 engine、strategy、LLM、wallet signal、execution module 都不能绕过 Risk Governor。

默认决策阈值：

```text
score < 70        → ignore
70 <= score < 80  → log only
80 <= score < 90  → Telegram alert + paper trade
90 <= score < 95  → Telegram alert + paper trade + manual review
score >= 95       → paper trade by default; live execution only if explicitly enabled
```

硬性拒绝条件：

* live trading disabled
* market ambiguous
* forbidden category
* spread too wide
* depth too thin
* stale price
* API unhealthy
* WebSocket unhealthy
* LLM output invalid
* resolution risk too high
* daily loss limit breached
* weekly loss limit breached
* consecutive loss limit breached
* wallet signal is the only reason to trade

任何硬拒绝成立时，即使 score 很高也必须拒绝。

---

## 9. LLM 使用规范

LLM 只能用于：

* 事件摘要
* 市场规则解释
* 歧义风险判断
* 新闻初筛
* Telegram alert 文案生成
* 日报总结

LLM 不能用于：

* 直接下单
* 绕过风控
* ultra-fast path
* 处理私钥
* 直接决定仓位
* 单独触发 live execution

LLM 输出必须是结构化 JSON，并通过 Pydantic 校验。

无效 JSON、字段缺失、置信度不足时，必须返回 no trade / alert only。

---

## 10. 策略开发规范

策略模块只负责产生信号，不负责下单。

每个策略必须实现：

```text
name
description
inputs
compute_signal()
explain_signal()
risk_notes
```

策略输出必须进入 Risk Governor。

禁止策略直接调用 live_trader。

默认启用策略：

* yes_no_mispricing
* orderbook_imbalance
* settlement_edge
* wallet_consensus
* event_lag

默认禁止自动实盘策略：

* politics
* war / geopolitics
* legal judgment
* celebrity / pop culture
* subjective markets
* pure copy trading
* LLM autonomous trading

---

## 11. Paper Trading 规范

Paper Trader 是 MVP 核心模块，不能敷衍。

必须支持：

* limit order simulation
* order timeout
* partial fill simulation
* slippage assumption
* mark-to-market
* realized PnL
* unrealized PnL
* position tracking
* trade journal
* strategy-level statistics

Paper Trader 必须 deterministic，方便测试。

任何信号都应优先进入 paper trading，而不是 live trading。

---

## 12. Live Trading 规范

MVP 阶段 live trader 只能是 stub。

如果实现 live trading，必须：

* 默认关闭
* 只支持测试钱包
* 只支持小额
* 只支持 limit order
* 禁止 market-order-style sweep
* 订单超时自动撤销
* 失败不允许激进重试
* 每次下单记录完整日志
* 每次下单经过 Risk Governor

严禁为了 demo 方便而打开 live trading。

---

## 13. 日志规范

系统必须有可读日志。

日志至少包括：

* startup config summary
* market loading status
* WebSocket connection status
* signal generated
* risk decision
* paper order created
* position update
* Telegram alert sent
* errors and retries
* circuit breaker events

禁止静默失败。

所有异常必须被捕获、记录，并尽可能恢复。

---

## 14. 测试规范

核心模块必须有测试。

至少包含：

* config validation tests
* Risk Governor hard rejection tests
* YES/NO mispricing tests
* paper trader tests
* lifecycle state transition tests
* invalid LLM JSON tests
* mock integration test

测试不得要求真实私钥。
测试不得下真实订单。
测试不得依赖真实 API 稳定返回。

优先使用 mock data fixture。

---

## 15. 开发流程规范

每次开始任务前，先执行：

1. 阅读 CLAUDE.md、SPEC.md、AGENTS.md。
2. 检查当前目录结构。
3. 明确本次任务修改哪些文件。
4. 不做无关重构。
5. 不改动与任务无关模块。
6. 修改后运行相关测试。
7. 更新必要文档。

新增模块必须说明：

* 为什么需要新增
* 放在哪个目录
* 输入输出是什么
* 是否影响 Risk Governor
* 是否需要测试

---

## 16. 代码风格规范

必须：

* 使用 type hints
* 使用 Pydantic 校验外部输入
* 函数保持短小
* 模块职责单一
* 日志清晰
* 异常处理明确
* 命名直观
* 避免魔法数字

禁止：

* 巨型 God class
* 到处传裸 dict
* 重复定义模型
* 硬编码配置
* 裸 except
* print 调试
* 静默失败
* 在策略里直接下单
* 在 LLM 里决定交易

---

## 17. 文档规范

核心模块完成后，应更新相关文档：

```text
docs/architecture_decisions.md
docs/risk_policy.md
docs/coding_standard.md
SPEC.md
```

README 应面向用户。
CLAUDE.md 面向 Claude Code。
SPEC.md 面向产品、架构和验收。
AGENTS.md 面向 Agent Teams 协作。

---

## 18. 完成定义

一个任务只有满足以下条件，才算完成：

* 代码可运行
* 类型清晰
* 测试通过
* 日志合理
* 文档同步
* 不破坏现有接口
* 不绕过 Risk Governor
* 不引入 secret 风险
* 不默认开启实盘

如果无法完成完整任务，应优先交付安全、可测试的部分，而不是交付不可控的完整幻觉工程。
