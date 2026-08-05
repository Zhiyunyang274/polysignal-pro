# Coding Standard — PolySignal Pro 代码工程规范

本文件定义 PolySignal Pro 的代码质量标准、模块组织方式、命名规范、异常处理、测试规范和禁止行为。

目标：避免屎山，避免 AI 生成不可维护代码，保证项目可长期迭代。

---

## 1. 基本原则

代码必须满足：

- 清晰
- 可测试
- 可解释
- 可替换
- 可观测
- 可维护
- 可风控

优先级：

```text
Correctness > Safety > Testability > Maintainability > Performance > Feature speed
```

不要为了快速实现牺牲架构边界。

---

## 2. Python 版本与工具

使用：

* Python 3.11+
* black
* ruff
* pytest
* pydantic
* mypy optional

建议 `pyproject.toml` 包含：

```toml
[tool.black]
line-length = 100
target-version = ["py311"]

[tool.ruff]
line-length = 100
select = ["E", "F", "I", "B", "UP", "SIM"]
ignore = []

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

---

## 3. 模块设计规范

每个模块只做一件事。

正确示例：

```text
risk_governor.py       # 只做最终风控决策
paper_trader.py        # 只做模拟交易
clob_orderbook_ws.py   # 只做 WebSocket 盘口接入
```

错误示例：

```text
bot.py                 # 包含 API、策略、下单、风控、Telegram
utils.py               # 包含所有杂乱函数
main.py                # 包含业务核心逻辑
```

---

## 4. 文件大小建议

一般规则：

* 单个 Python 文件尽量 < 400 行
* 单个函数尽量 < 60 行
* 单个 class 尽量 < 250 行
* 超过限制时应拆分模块

例外必须有明确理由。

---

## 5. 类型规范

必须使用 type hints。

推荐：

```python
async def compute_signal(snapshot: OrderBookSnapshot) -> Signal | None:
    ...
```

禁止：

```python
def compute_signal(data):
    ...
```

外部输入必须用 Pydantic 校验。

---

## 6. 数据模型规范

跨模块数据使用 Pydantic model。

推荐位置：

```text
polysignal/storage/models.py
```

或按领域拆分：

```text
polysignal/models/market.py
polysignal/models/signal.py
polysignal/models/risk.py
```

禁止多个模块重复定义同一实体。

---

## 7. 配置规范

禁止硬编码配置。

错误：

```python
MAX_SPREAD = 0.05
```

正确：

```python
settings.risk.max_spread_pct
```

配置来源：

```text
config/*.yaml
.env
环境变量
```

敏感信息只能来自环境变量。

---

## 8. 异常处理规范

禁止裸 except：

```python
try:
    ...
except:
    pass
```

必须捕获具体异常，并记录日志：

```python
try:
    ...
except WebSocketError as exc:
    logger.warning("WebSocket reconnect required", exc_info=exc)
```

异常处理原则：

* 可恢复错误：记录、重试、降级
* 不可恢复错误：记录、触发 circuit breaker
* 安全相关错误：直接拒绝交易

---

## 9. 日志规范

禁止用 print 调试。

使用 logger。

日志必须包含上下文：

```python
logger.info(
    "signal_generated",
    extra={
        "market_id": market_id,
        "strategy": strategy_name,
        "score": score,
    },
)
```

日志中禁止出现：

* private key
* API secret
* Telegram token
* full auth header
* wallet mnemonic

---

## 10. 异步规范

WebSocket、API polling、定时任务可以使用 asyncio。

禁止在 async path 中执行长时间阻塞操作。

如果必须执行阻塞 I/O，应隔离到后台线程或独立任务。

Ultra-fast path 中禁止：

* LLM call
* 网络搜索
* 大文件读写
* 长 SQL 查询
* 钱包画像重算

---

## 11. 策略模块规范

策略模块只输出 Signal，不执行交易。

推荐接口：

```python
class Strategy(Protocol):
    name: str

    async def compute(self, context: StrategyContext) -> Signal | None:
        ...
```

Signal 必须进入 Risk Governor。

禁止：

```python
if signal:
    live_trader.buy(...)
```

---

## 12. Risk Governor 调用规范

所有执行动作前必须调用：

```python
risk_decision = risk_governor.evaluate(signal, context)
```

只有 Risk Governor 返回允许的 action，后续模块才能执行。

执行模块不得重新解释风控结果。

---

## 13. Paper Trader 规范

Paper Trader 必须 deterministic。

同样输入应产生同样输出。

必须记录：

* signal_id
* simulated order price
* fill status
* slippage assumption
* position change
* realized / unrealized PnL
* reason

---

## 14. Live Trader 规范

MVP 阶段 live_trader 只能是 stub。

如果后续实现，必须：

* feature flag 关闭默认实盘
* 只支持 limit order
* 只支持小额测试钱包
* 下单前二次检查 Risk Governor
* 完整记录 audit log

---

## 15. 测试规范

核心模块必须有单元测试。

测试命名：

```text
test_<module>.py
```

测试应覆盖：

* 正常路径
* 边界条件
* 硬性拒绝
* 异常输入
* invalid LLM JSON
* stale price
* insufficient depth

测试不得：

* 依赖真实私钥
* 真实下单
* 依赖真实 API 稳定返回
* 写入用户真实文件

---

## 16. Mock 规范

MVP 允许 mock，但必须明确标记。

禁止把 mock 伪装成真实数据。

Mock 文件建议放在：

```text
tests/fixtures/
```

---

## 17. 命名规范

变量名应表达业务含义。

推荐：

```python
combined_ask_price
liquidity_score
resolution_risk
paper_position
```

禁止：

```python
data
x
res
thing
final_result
```

---

## 18. 禁止行为清单

严禁：

* God class
* 超大 bot.py
* 策略直接下单
* LLM 直接下单
* 风控写在多个地方
* 重复定义模型
* 到处传裸 dict
* 硬编码 secret
* 默认开启实盘
* 无测试核心逻辑
* 静默吞异常
* 生成营销式暴利文案

---

## 19. Code Review Checklist

提交前检查：

* [ ] 类型标注完整
* [ ] 配置未硬编码
* [ ] 无 secret 泄露
* [ ] 无 live trading 默认开启
* [ ] 所有执行经过 Risk Governor
* [ ] 测试覆盖核心逻辑
* [ ] 日志有上下文
* [ ] 文档已更新
* [ ] 未引入不必要依赖
* [ ] 未破坏 fast path 性能
