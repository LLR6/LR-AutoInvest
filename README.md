<div align="center">

# LR-AutoInvest

中文 · [English](README_EN.md)
### 每天导入行情，连续记账，生成可解释的调仓草案。

**行情导入 → 数据质检 → 连续模拟账户 → 每日计划 → 审计工作台**

[![Verify](https://github.com/LLR6/LR-AutoInvest/actions/workflows/test.yml/badge.svg)](https://github.com/LLR6/LR-AutoInvest/actions)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Mode](https://img.shields.io/badge/Mode-Offline_Paper-16a34a)
![License](https://img.shields.io/badge/License-MIT-blue)

</div>

今天导入行情，明天继续记账：不用每次重新从初始现金开始，也不用靠终端输出猜为什么调仓。打开本地工作台，就能检查持仓、费用、输入行情和下一交易日的模拟计划。

[每日使用](docs/DAILY_WORKFLOW.md) · [预览工作台源码](examples/paper-demo/dashboard.html) · [操作回执](examples/paper-demo/evidence.json) · [English](README_EN.md)

| 你现在想验证什么 | 从这里开始 |
| --- | --- |
| 重复运行会不会重复交易 | 跑两次 paper demo，对照 evidence.json 的 repeat |
| 自己的日线是否过期或异常 | paper import 转换列名，再用 paper doctor 检查 |
| 为什么卖出这只、买入另一只 | paper plan 查看动量证据、目标权重和费用估算 |
| 手续费会不会改变结论 | 运行研究 demo / study 比较成本假设 |

这是可运行的研究原型。当前使用透明的规则策略，示例是固定种子生成的合成资产，不宣称预测市场或保证赚钱。项目不包含券商实盘接口。

## v0.2：从回测实验到每日工作台

无需券商账号，导入自己的已完成日线 CSV，就能保留连续模拟持仓、检查数据、查看下一交易日的调仓草案。回测实验模块仍可独立使用。

| 日常问题 | 已实现的处理 |
| --- | --- |
| 每次运行都从初始现金开始 | SQLite 保存连续账户与追加事件 |
| 重试或并发运行重复记账 | 事务写锁；相同行情重复导入不增加订单 |
| 旧行情修订悄悄改写历史收益 | 与已用历史逐条核对；修订时阻止更新 |
| 过期数据仍生成计划 | 检查查看日与最近行情日，过期则阻止 |
| 分数份额、小额频繁交易忽略费用 | 可设置手数、最低费用、最小交易金额 |
| 不知道为什么要调仓 | 输出动量分数、目标比例、信号日期和原因 |
| 结果只能看终端 | 离线 HTML 工作台、JSON 账户与计划导出 |

```bash
python -m lr_autoinvest paper demo
```

打开 `reports/paper-demo/dashboard.html`。同一命令可重复执行，模拟账户不会重复交易。示例使用合成行情，明确标注历史查看日。已有 **26 项测试通过**，包括并发幂等、修订阻止、过期阻止、未来数据隔离和资金记账。

[每日使用教程](docs/DAILY_WORKFLOW.md) · [工具能力与定位](docs/TOOL_POSITIONING.md) · [实际操作回执](examples/paper-demo/evidence.json)

## 三分钟跑起来

```bash
git clone https://github.com/LLR6/LR-AutoInvest.git
cd LR-AutoInvest
python -m lr_autoinvest demo
python -m lr_autoinvest.study
python -m unittest discover -s tests -v
```

运行核心无需第三方依赖、API Key 或账户。打开 `examples/demo-report/report.html` 看净值对照和滚动验证，`orders.csv` 看模拟订单，`report.json` 看全部现金、持仓、成本和输入哈希。安装命令行入口可用 `python -m pip install -e .`。

## 已实现

| 模块 | 当前行为 |
| --- | --- |
| 动量策略 | 在正动量资产中选择一个，目标最高 60% 初始再平衡权益，其余留现金 |
| 执行时序 | 只观察前一交易日及更早收盘数据，在当前开盘模拟成交 |
| 模拟账本 | 先卖后买、分数份额、扣除单边综合成本、不借钱、不做空 |
| 风险停止 | 前一天收盘回撤触发后，下一开盘清仓并锁定停止 |
| 滚动验证 | 180 日训练，60 日测试，只在训练段选择 20/40/80 日窗口 |
| 对照实验 | 现金、受同样回撤规则约束的等权再平衡、50bps 成本、一日信号滞后 |
| 审计输出 | 每笔订单的信号日期、执行价格、费用、原因以及完整净值轨迹 |
| 数据检查 | 非有限/非正价格、重复记录、缺失资产数据直接报错 |

## 一次实际运行：成本改变结论

相同策略参数，在 20 组固定种子的合成路径上运行，每条路径 600 个交易日。没有为了结果调参数，也没有把某条最佳路径当成总体表现。

| 单边综合成本 | 累计收益中位数 | 亏损路径 / 20 | 最大回撤中位数 |
| --- | --- | --- | --- |
| 0 bps | 5.41% | 6 | 10.84% |
| 10 bps | 3.86% | 6 | 11.24% |
| 50 bps | -3.64% | 13 | 13.66% |

从 10bps 提高到 50bps，逐路径配对的收益变化中位数为 **-6.78 个百分点**。这是本仓库合成机制下的实际计算结果，只用于展示成本敏感性；不能外推为市场收益预期。

[研究方法与依据](docs/RESEARCH.md) · [20 组原始结果](examples/study.json) · [单次完整报告](examples/demo-report/report.json)

## 导入自己的历史数据

```csv
date,symbol,open,close
2024-01-02,ASSET_A,100.0,101.2
2024-01-02,ASSET_B,80.0,79.9
2024-01-03,ASSET_A,101.3,102.0
2024-01-03,ASSET_B,80.0,80.4
```

```bash
python -m lr_autoinvest backtest your_prices.csv --output reports/my-run
```

至少 240 个交易日才能完成一折默认滚动验证。所有资产须对齐日期；日期排序，不静默填补价格。`open` 与 `close` 必须使用一致口径。不要混合复权收盘与未复权开盘；准备真实数据时保留数据授权和来源。

## 读结果前须知道的建模约定

- 合成资产 `SYN_A/B/C` 不对应任何股票或基金。演示模拟趋势切换、相关波动和一次冲击。
- 默认 10bps 是可修改的实验假设，统一包含手续费与滑点的比例损失，不代表任何券商费率。每次买卖都计费。
- 开盘无限流动性、允许分数份额、无借贷；不模拟税费、股息、拆股、汇率、停牌、涨跌停与未成交；每日账户可配置交易手数、最低费用和最小金额。
- 60% 是交易前权益的目标比例；费用和盘中价格变化后实际权重会漂移。15% 回撤是停止触发值，不是最大损失保证，开盘跳空可使损失更大。
- 每折样本外测试从现金重新开始，历史只用于特征；各折结果不是一条连续可执行的组合净值。
- Sharpe 使用 252 日年化和零无风险利率；现金对照没有利息。

## 后续研究

优先增加具有明确授权、包含退市资产的时间点历史数据；实现公司行动与真实交易约束；再比较稳健策略选择、连续持仓的滚动验证和长期模拟交易。LLM 若加入，先用于解释账本和数据检查，每个数值都须追溯到计算结果。

作者：**LLR6** · MIT
