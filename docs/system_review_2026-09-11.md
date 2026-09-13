# PolySignal Pro 系统全面审查报告 — 第一阶段技术地图

审查日期：2026-09-11
审查人：PolySignal Pro 长期维护 Agent（首席量化研究员 / 高级后端工程师 / 交易系统架构师 / 策略验证工程师）
审查范围：完整代码库（polysignal/ 80 个源文件、scripts/ 33 个脚本、tests/ 97 个测试文件、config/、docs/）
审查原则：只读分析，不做任何代码修改；所有结论均有代码或测试证据支撑。

---

## 0. 基线状态（本次审查实测）

```text
测试套件：    uv run pytest -q → 1762 passed in 268.67s（exit 0）
Ruff：        1786 findings（388 可自动修复）——与 CONTEXT.md 记载的"仓库级 Ruff 未清理"一致
mypy：        222 errors in 32 files（含核心路径 polysignal/main.py）
Python 环境： .venv Python 3.11.15；系统 python3 为 3.9.6，不可用于本项目
              （uv run 是唯一正确的运行方式；裸 python3 -m pytest 会因
               `RiskDecision | None` 注解在类体求值而收集失败）
安全状态：    live_trading_enabled=false, allow_auto_execution=false,
              paper_trading_enabled=true, default LLM=mock（config/risk.yaml 实测确认）
```

---

## 1. 当前系统能力总结

### 1.1 数据层（polysignal/ingestion/）

| 能力 | 实现 | 状态 |
|------|------|------|
| 市场发现 | Gamma REST（gamma_client.py），支持分页扫描（Step 11 实测 3000 市场） | ✅ 已验证 |
| 盘口数据 | CLOB REST 只读（clob_client.py） | ✅ 已验证 |
| 实时盘口 | CLOB WebSocket（websocket_client.py），协议细节已踩坑确认（`assets_ids` 复数、数组消息、无 type 字段） | ✅ 已验证 |
| YES/NO 合成 | OrderBookCache 按 token_id 维护并合成 YES/NO 书 | ✅ |
| 弹性 | api_errors 分类、reconnection_strategy 指数退避、subscription_manager 批量订阅、hybrid 模式真实 API 失败降级 mock | ✅ |
| 数据模式 | mock / real_readonly / hybrid 三模式 | ✅ |

### 1.2 四引擎 + LLM（polysignal/engines/, polysignal/llm/）

- Market Microstructure Engine：spread/depth/imbalance/YES-NO 合成错价检测（完整实现）。
- Wallet Intelligence Engine：wallet_score 加权公式 + copy/chase/timing 风险 + 共识检测（完整实现，但依赖 mock_wallet_provider，无真实钱包数据接入）。
- Event Intelligence Engine：event_score 公式 + LLM 降级规则（invalid JSON → neutral 50 + no trade）+ 禁止字段检测（完整实现）。
- Resolution & Lifecycle Engine：生命周期状态机 + ambiguity/resolution/close-time 风险（完整实现）。
- LLM：5 个 provider（mock / deepseek / glm / sensenova / xfyun_anthropic）+ provider_router + llm sampling 模式。默认 mock。真实 LLM 仅用于研究采样，永不进入交易路径。

### 1.3 风控层（polysignal/risk/）

- RiskGovernor：硬拒绝（13+ 条件）→ 评分（5 组件加权 − 9 类惩罚）→ 阈值决策（70/80/90/95）→ allowed_actions。任何执行必须经它。
- **但账户级风控状态无人维护（见风险 R1）**，`exposure_guard.py` / `liquidity_guard.py` 是从未被导入的孤岛模块（见技术债 D3）。

### 1.4 执行层（polysignal/execution/）

- PaperTrader：确定性可见深度撮合（walk asks、滑点压力因子、hard limit 封顶、跨书拒绝、BOTH fail-closed）。质量较高。
- LiveTraderStub：纯 stub，MVP 约束符合。
- 缺失：手续费模型（fee 参数存在但 PaperTrader 不收手续费）、延迟模拟、网络失败注入、订单超时的实际执行、账户现金/权益账本。

### 1.5 Shadow 研究层（polysignal/shadow/，项目最有价值的部分）

- 完整研究闭环：EdgeCandidate 发现 → entry_filter（三层决策 + 结构化原因）→ exit_rules → pnl → forward_observations（只读轮询 + 防伪造）→ performance review gate。
- execution_cost.py：纯函数 L2 成本模型（可见深度扫描、VWAP、fee_bps、full/partial/rejected、同份额 round-trip）——这是接入第三阶段验证框架的正确地基。
- 严格防数据伪造契约：缺 forward 数据时 PnL=null 而非 0；resolution/expiry provenance SHA-256；schema 版本绑定。Step 12 v7 契约尤其严谨。

### 1.6 接口与部署

- CLI summary、Telegram Cockpit（只监控不交易，禁 buy/sell/execute 操作）、Streamlit Dashboard（只读 + AST 导入安全检查）、web_console。
- docker-compose.yml、.env.example、systemd/tmux 云端运行方案文档、daily report 自动化。

### 1.7 策略/edge 现状（诚实结论）

```text
combined_ask_arbitrage          enabled（但现实中极罕见：Step 3 扫描 493 市场 0 命中）
price_dislocation_probability_v1/v2   quarantined（shadow PnL 显著为负，correlation 为负）
cross_market_consistency_v1     research_only（10 笔全亏，价差不收敛）
crypto_price_threshold_v1       流水线完整；v7 cohort 11 仓位 / 3 clusters / 0 closed，待 240min 前向数据
tiny_live_recommendation        NO
```

**系统当前没有任何被证明正期望的 edge。这是事实而非缺陷——工程上的诚实隔离正是本系统最值钱的设计。**

---

## 2. 核心模块关系图

```text
                        ┌────────────────────────────────────────────┐
                        │                 数据接入层                  │
                        │  Gamma REST ── CLOB REST ── CLOB WebSocket │
                        │        └──── DataProviderManager ────┘     │
                        │        (mock / real_readonly / hybrid)     │
                        │   OrderBookCache ← SubscriptionManager     │
                        └───────────────┬────────────────────────────┘
                                        │ Market / OrderBookSnapshot (Pydantic)
              ┌─────────────────────────┼──────────────────────────────┐
              ▼                         ▼                              ▼
   ┌────────────────────┐   ┌──────────────────────┐    ┌──────────────────────┐
   │ Microstructure Eng │   │ Lifecycle Engine      │    │ Wallet / Event Eng    │
   │ (fast, 同步计算)    │   │ (状态机+歧义风险)      │    │ (slow path, LLM 可选) │
   └─────────┬──────────┘   └──────────┬───────────┘    └──────────┬───────────┘
             │      ComponentScores    │                           │
             └────────────┬────────────┴─────────────┬─────────────┘
                          ▼                          ▼
              ┌────────────────────┐      ┌──────────────────────┐
              │ YesNoMispricing    │      │ LLM Providers (5)     │
              │ Strategy (唯一主策略)│      │ mock 默认/sampling 专用 │
              └─────────┬──────────┘      └──────────────────────┘
                        │ Signal
                        ▼
              ┌────────────────────────────────────────────┐
              │              Risk Governor                  │
              │  硬拒绝 → trade_score → 阈值 → allowed       │
              │  ⚠ 账户状态(daily_pnl等)依赖调用方传入，当前无维护者│
              └───────┬───────────────────────────┬─────────┘
                      ▼                           ▼
          ┌───────────────────┐        ┌────────────────────┐
          │ PaperTrader        │        │ Telegram Cockpit    │
          │ (确定性深度撮合)     │        │ Dashboard / CLI     │
          │ LiveTraderStub     │        │ (只读，禁交易操作)    │
          └───────┬───────────┘        └────────────────────┘
                  ▼
          ┌───────────────────┐
          │ SQLite Database    │   runs/ artifacts (JSON/CSV/MD)
          └───────────────────┘

  ═══════════════ 研究旁路（不进入实时执行）═══════════════
  scripts/discover_* → EdgeCandidate → shadow/entry_filter
      → shadow exit_rules → shadow/pnl ← forward_observations(只读轮询)
      → shadow/reporter → runs/shadow/* → review gate → edge 注册表状态
  （crypto threshold: discovery v5 + validator v7 + provenance 契约）
```

数据流要点：

1. **实时路径**（main.py / run_paper.py）：轮询或 WS → 引擎 → 策略 → Risk Governor → PaperTrader → SQLite/Telegram。LLM 永不在此路径。
2. **研究路径**（scripts/run_shadow_paper_loop.py 及 discover/validate 系列）：离线 candidate 文件 → shadow 撮合 → 前向观测 → PnL/复盘 → 反馈校准（feedback gate 隔离失败 edge）。
3. **快慢分层**：microstructure 为 ultra-fast（纯内存计算），wallet/event 为 slow path（缓存分数）。WebSocket→策略的直接 ultra-fast 链路在 run_paper.py 中集成，main.py 仍是 10s 轮询的 MVP 遗留轨道。

---

## 3. 当前最大风险列表（按严重度排序）

### R1（高）账户级风控状态无人维护 → 亏损熔断永远不会触发

- 证据：`RiskContext.daily_pnl_usd / weekly_pnl_usd / consecutive_losses / current_market_exposure_usd` 默认全 0（models/risk.py:36-46）；`grep daily_pnl|consecutive_losses|weekly_pnl scripts/run_paper.py` 零命中；main.py 构造 RiskContext 时不传这些字段。
- 后果：Risk Governor 中 `daily_loss_limit_breached` / `weekly_loss_limit_breached` / `consecutive_loss_limit_breached` / `concentration_penalty` 四道防线在所有现行 runner 中是**死代码**。一旦未来接通任何真实执行，账户会被单策略连续亏损拖穿而没有熔断。
- 当前不构成资金损失（无实盘），但它是“具备接入真实资金交易的工程基础”这一最终目标的**首要缺口**。

### R2（高）策略层零正期望证据，且唯一的 enabled edge（combined_ask）现实命中率≈0

- 证据：Step 3/4A 实测 493 市场 `combined_ask_below_one_count: 0`；概率 edge 与 cross-market edge 的 shadow PnL 全线为负并被 gate 隔离；v7 cohort 0 closed。
- 后果：系统当前“能跑但不会交易”。这不是要降低门槛去硬找机会，而是要按 SPEC 路线扩充前向数据与独立 cluster，同时把验证框架做实（第三阶段），避免“框架空转”。

### R3（中高）PaperTrader 成本模型乐观偏差

- 证据：`PaperTrader.__init__` 无 fee 参数，成交不收手续费；`close_position(market_id, close_price)` 由调用方给定价格成交、不校验 bid 深度；无延迟/部分成交失败注入（partial 只由深度决定——这部分是确定性优点，但成本侧不完整）。
- 对比：`shadow/execution_cost.py` 已有带 fee_bps 的 L2 模型却未被 PaperTrader 复用。
- 后果：paper PnL 系统性偏乐观，用它的结论去评估 edge 会高估。用户要求的“模拟资金账户（10000 USDT + 手续费 + 滑点 + 延迟 + 网络失败 + API 异常 + 订单失败）”正是要补这块。

### R4（中）main.py 与 run_paper.py 双轨 runner 漂移

- 证据：main.py（517 行）是 MVP 轨道：10s 轮询、RiskContext 不传 price_stale/账户状态；run_paper.py（3689 行）才是功能完整的云 runner。两者行为已不一致（mypy 在 main.py:225 报 RiskContext 缺参即为症状）。
- 后果：同一系统两套行为语义，未来任何风控/策略改动必须双处验证，遗漏一处即产生隐性安全差异。

### R5（中）scripts/run_paper.py God-script（3689 行）

- 证据：wc -l 实测 3689 行，包含 RunConfig、watchlist、control group、LLM sampling、trajectory 等 10+ 个 Phase 的增量堆叠。tests 直接 `from scripts.run_paper import ...`（test_combined_ask_distribution.py:23），模块边界已被测试固化为“scripts 即库”。
- 后果：修改风险高、审查成本高，与 CLAUDE.md“禁止 God class”原则冲突。

### R6（中低）时区与时间戳规范不统一

- 证据：全库使用 `datetime.utcnow()`（naive，Python 3.12 起 deprecated）；本项目的最严重历史事故恰恰是 Step 12 v5 的 ET/UTC expiry 偏差（CONTEXT.md 明确记载“v5 cohort 暴露的标题 23:59/ET 偏差已在 v6 adapter 中 fail closed”）。
- 后果：naive 时间戳在任何跨时区比较处都是隐患；shadow 层已加固，但 models 层与 main 路径仍是 naive。

### R7（低）文档-实现漂移

- 证据：AGENTS.md 列出的 `polysignal/ingestion/clob_orderbook_ws.py`、`clob_rest_client.py`、`gamma_market_loader.py`、`strategies/orderbook_imbalance.py`、`risk/circuit_breaker.py`、`risk/ambiguity_guard.py`、`risk/slippage_guard.py` 均不存在（实际为 websocket_client.py、clob_client.py、gamma_client.py 等）。config/risk.yaml 的 `circuit_breaker` 配置节无对应代码消费。
- 后果：新 agent/贡献者按 AGENTS.md 找文件会扑空；配置节给人“有熔断”的错觉（实际熔断只在文档里）。

### R8（低）运行方式陷阱

- 证据：系统 python3 3.9.6 跑 pytest 直接收集失败（`TypeError: unsupported operand for |`）；pyproject 声明 requires-python >=3.9 但代码实际需要 3.10+（PEP 604 类体注解）。
- 后果：任何环境没走 `uv run` 都会得到误导性错误。pyproject 的 requires-python 声明偏低。

---

## 4. 技术债列表（含量化证据）

| # | 债项 | 证据 | 影响 | 偿还建议 |
|---|------|------|------|----------|
| D1 | Ruff 1786 findings | `uv run ruff check .` 实测；388 可 safe-fix | 噪音掩盖真问题 | 分批 `ruff check --fix`（仅 safe），每批跑全量测试 |
| D2 | mypy 222 errors / 32 文件 | `uv run mypy polysignal` 实测 | 类型安全承诺失效 | 优先清 risk/ execution/ models/ main.py 核心路径，scripts 除外 |
| D3 | 孤岛模块 exposure_guard.py / liquidity_guard.py | 全库 grep 无导入方 | 名义防线实际不存在 | 接入 Risk Governor 或明确标注 research-only；二选一，不留幻觉 |
| D4 | RiskContext 账户状态无维护者 | 见 R1 | 亏损熔断死代码 | 引入 AccountState 账本，由 runner 持有并传入 RiskContext |
| D5 | PaperTrader 无手续费/延迟/失败注入 | 见 R3 | paper PnL 乐观偏差 | 复用 shadow/execution_cost.py 的 fee 模型；建账户级模拟器 |
| D6 | run_paper.py 3689 行 God script | wc -l 实测 | 可维护性/审查成本 | 按领域拆到 polysignal/runner/（不改变行为，分步走） |
| D7 | main.py 双轨漂移 | 见 R4 | 行为不一致 | 与 D6 合并决策：要么 main.py 委托 runner 核心库，要么明确降级为 demo |
| D8 | naive datetime.utcnow() | grep 全库大量命中 | 3.12 deprecated + 时区隐患 | 渐进迁移 timezone-aware UTC（models 层先行） |
| D9 | AGENTS.md 文件清单过时 | 见 R7 | 协作误导 | 更新 AGENTS.md/CLAUDE.md 文件清单至真实状态 |
| D10 | requires-python>=3.9 声明不实 | pyproject.toml:6 vs 实际需 3.10+ | 环境误导 | 声明改为 >=3.11 并同步文档 |
| D11 | tests 反向依赖 scripts/ | test_combined_ask_distribution.py 导入 scripts.run_paper | 边界模糊 | 随 D6 拆分时把可复用逻辑移入 polysignal/ |
| D12 | circuit_breaker 配置无消费者 | config/risk.yaml:75-79 vs 无对应模块 | 配置幻觉 | 实现消费或在配置注释中声明保留 |

### 技术债偿还进度（迭代日志为准）

* ✅ D3（2026-09-11，Iteration 006）：exposure_guard / liquidity_guard 已接入 Risk Governor
  硬拒绝链——exposure 提供市场级/策略级敞口硬限制（策略级敞口此前全系统无处检查），
  liquidity 承接原内嵌 spread/depth 检查（单一事实来源，行为逐字保留）。
* ✅ D4（Iteration 001）：AccountState 账本落地，亏损熔断状态由 runner 真实维护。
* ✅ D10（Iteration 001，ADR-026）：requires-python 已改为 >=3.11。
* ✅ D9（Iteration 001）：AGENTS.md 文件清单已校准。
* 🔶 D6（Iteration 007+010，两步完成）：run_paper.py 3689 → 1724 行（累计 -53%）；
  watchlist / llm-sampling / control-group / alpha-repeat / RunConfig+RunStatistics
  均已逐字等价迁至 polysignal/runner/（mixin + re-export，既有测试原样通过），
  mixin 类型注解升级为真实类型。剩余：PaperTradingRunner 本体与报告生成域。
* ✅ D8（Iteration 018，models 层完成）：新增 utils/time.py 规范时钟，models 全部
  15 处 naive utcnow 迁移为 aware，wallet 链与 lifecycle 引擎对称归一化
  （ensure_utc）；scripts/runner 内部 naive（自洽不混算）留后续批次。
* 🔶 D1（Iteration 008+009+011，完成主体）：ruff 1786 → ~180 项。第一批 510 项零语义
  规则清零；第二批 UP045 全量迁移 547 项 + 连带 74 项；E501（816 项）接受为 pyproject
  显式声明的风格债；F841 语义排查发现并修复 main.py 重复引擎分析。剩余 ~180 项
  （UP042/B904/SIM/E712）每项需独立行为分析，按批次推进。

---

## 5. 优化路线规划（对应用户六阶段目标）

> 原则重申：删掉复杂性而不是能力；每次修改可回滚；永保系统可运行；禁止以最大历史收益为唯一目标；任何策略升级必须回答经济含义/过拟合/样本外六问。

### Iteration 1（阶段2，本周期内）：风控真实性与核心类型安全
1. **账户状态账本（补 R1/D4）**：新增 `polysignal/execution/account_state.py`（AccountState：balance、daily/weekly PnL、consecutive losses、exposure），runner 每笔 paper trade 后更新并传入 RiskContext。带测试。这是通往“可接入真实资金的工程基础”的第一块硬地基。
2. **孤岛守卫接线或标弃（D3）**：exposure/liquidity guard 接入 Risk Governor 评估链（若逻辑正确）或显式标注弃用。
3. **mypy 核心路径清零（D2 部分）**：risk/、execution/、models/、main.py 的类型错误修复；main.py RiskContext 补 price_stale。
4. **Ruff safe-fix 批处理（D1）**：分批自动修复 + 全量测试验证。
5. **AGENTS.md/CLAUDE.md 文件清单校准（D9）**、requires-python 改 >=3.11（D10）。
6. 回滚保障：全部改动落在独立 commit；测试 1762 基线不得回退。

### Iteration 2（阶段3）：真实感模拟交易验证框架
1. `polysignal/execution/sim_broker.py`：账户级模拟券商——初始 10000 USDT、手续费（fee_bps，Polymarket 现实费率口径）、滑点（复用 shadow/execution_cost.py L2 扫描）、下单延迟、网络失败/API 异常/订单失败注入（确定性 seed）、订单超时撤销。
2. 绩效指标模块 `polysignal/research/performance_metrics.py`：年化收益、最大回撤、Sharpe、Sortino、胜率、盈亏比、换手率、风险暴露、最长连亏/连亏次数。
3. 用 mock 数据 + crypto threshold 历史候选做端到端模拟回放，产出第一份正式模拟绩效报告。
4. PaperTrader 增加可选 fee 接线（保持向后兼容，默认不变以不破坏既有测试语义）。

### Iteration 3+（阶段4/5/6，持续循环）
- **策略 A/B**：每轮以“旧 vs 新”在同一数据窗口跑双版本（框架天然支持：同一 sim broker、同一 seed），新策略必须同时在收益、风险、稳定性、泛化四维不劣才可保留；同时强制回答经济含义六问。
- **环境压力**（阶段6）：扩展 MockDataProvider 支持 regime 参数（趋势/震荡/高波动/流动性收缩/价差放大），验证风控与退出规则在恶劣环境下的行为（重点：R1 修复后的熔断、exit_rules 的 stale/close 出场）。
- **持续循环**：分析 → 假设 → 修改 → 测试 → 模拟 → 复盘 → docs/iteration_log.md 记录（iteration 编号/日期/修改/目的/结果/收益变化/风险变化/是否保留）。

### 明确不做（本阶段红线）
- 不放宽任何已被 shadow PnL 证伪的 edge gate（feedback gate 结论优先）。
- 不打开 live trading / allow_auto_execution；不触碰私钥；LLM 不进交易路径。
- 不为“报表好看”而伪造 PnL（shadow 层 null-PnL 契约继续严格）。
- 不大规模重写（尤其 run_paper.py 拆分必须分步、行为等价）。

---

## 6. 结论

PolySignal Pro 的工程质量显著高于典型个人量化项目：安全门禁层层设防、研究契约（provenance/null-PnL/gate）严谨、测试覆盖厚实（1762 项）。**它当前最大的问题不是代码质量，而是三件事：① 账户级风控在代码里是死的（R1）；② 成本模型乐观导致 paper 结论偏乐观（R3）；③ 没有一个被证明的 edge（R2，客观现实而非缺陷）。** 第一阶段的优化火力应集中在把“风控与成本”从名义状态变成真实状态，同时建设第三阶段的真实感验证框架——这两件事不改变任何策略逻辑，却直接决定“未来能否安全接通真实资金”。
