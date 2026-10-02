# 每日模拟投资工作流（v0.2）

作者：LLR6

## 先直接体验

```bash
python -m lr_autoinvest paper demo
```

打开 `reports/paper-demo/dashboard.html`，看连续账户、持仓、成本、下一交易日调仓草案和最近订单。演示内置固定种子合成行情：明确使用历史查看日，而非把旧数据冒充当前价格。

再次运行同一命令，账户不会重复交易：返回 `repeat: unchanged`。演示还尝试过期行情导入并记录阻止原因。可以在 [公开演示回执](../examples/paper-demo/evidence.json) 核对实际结果。

## 使用自己的行情

### 1. 从已有行情软件导出已完成的日线

支持统一长表 `date,symbol,open,close`。单资产中文导出表也可转换：

```bash
python -m lr_autoinvest paper import exported.csv --symbol YOUR_SYMBOL --output local/prices.csv
```

支持 `日期/交易日期/date`、`开盘/开盘价/open`、`收盘/收盘价/close`、`代码/证券代码/symbol`；日期为 ISO 或 `YYYY/MM/DD`。CSV 使用 UTF-8，可带 BOM；不自动猜 GBK、不解析千位分隔金额，不支持任意供应商格式。代码保留前导零。多资产须同日期齐全。多个单资产文件转换后可合并成统一长表再验证。

数据由使用者提供，工具不自动下载实时行情。须确认授权、来源、开收盘复权一致性，且当天收盘已经完成。日期只有日精度，程序不能判断盘中数据是否被错误标记为已完成日线。

### 2. 检查数据

```bash
python -m lr_autoinvest paper doctor local/prices.csv
```

默认以电脑本地日期为查看日，允许最新行情落后最多 4 个日历日。周末/长假请按市场日历选择查看日或在建账时设置合理 `--max-age`；没有交易所日历自动识别。

超过 35% 的单日开盘或收盘相对前收盘跳变会阻止使用，请先核实拆股、复权口径、异常行情。阈值是数据质检规则，不是市场波动保证；真正的大幅行情也会被挡住，需人工核实后创建具有不同明确阈值的比较账户。

### 3. 创建长期保留的模拟账户（只做一次）

```bash
python -m lr_autoinvest paper init --db local/my-paper.db --start 2024-01-02 --cash 100000 --lookback 40 --rebalance 10 --weight 0.6 --lot-size 100 --min-fee 5 --min-notional 1000 --cost-bps 10
```

把 `--start` 换成 CSV 中真实存在、且有足够前置历史的交易日期。`--lot-size 100`、`--min-fee 5` 只是参数用法示例，不代表任何证券或券商的规则。`--lot-size 0` 表示分数份额。金额、价格和账户现金须采用同一种币种，不能直接混合不同货币。

账户策略、费用与阈值建账后固定；参数实验用新数据库，避免改变旧账。现有数据库拒绝覆盖。数据库和本地行情默认被 `.gitignore` 排除。

### 4. 每天更新行情，然后重复这三条命令

```bash
python -m lr_autoinvest paper sync local/prices.csv --db local/my-paper.db
python -m lr_autoinvest paper plan --db local/my-paper.db
python -m lr_autoinvest paper dashboard --db local/my-paper.db --output reports/my-daily
```

打开 `reports/my-daily/dashboard.html`。这是静态文件，可离线查看；`account.json` 与 `plan.json` 可供自己的脚本读取。输入应持续包含从最早一次导入开始的完整历史，不能只给最新一天。

`sync` 在收盘数据可用后重放新的模拟交易日，填补停机期间的已完成日线，保留连续持仓；它不是在市场上立即下单的实时交易程序。每次只追加新的记账事件，重复导入返回 `unchanged`。

`plan` 给下一输入交易日的目标权重、动量证据、估算数量、费用和交易原因；不改变账户。估算使用最近收盘价，下一个模拟开盘会按开盘权益重新计算、检查现金并取整，所以计划数量可能与最终模拟成交不同。未到调仓周期就显示保持持仓。

### 5. 核对审计记录

```bash
python -m lr_autoinvest paper status --db local/my-paper.db
python -m lr_autoinvest paper audit --db local/my-paper.db
```

SQLite 事务与写锁使同一账户的并发更新串行化。事件带前序哈希；行情历史与最后同步事件摘要绑定。读工作台时也会校验。可检测常见意外修改，不能抵抗有权限重写整个数据库及哈希链的攻击者，不是外部不可篡改账本。

## 失败时是什么行为

| 情况 | 行为 |
| --- | --- |
| 重复导入同一已完成行情 | 不增加订单或记账事件 |
| 两个进程同时导入同一批行情 | 一个更新，另一个返回 unchanged |
| 过去已经使用过的行情发生修订 | 阻止更新，旧账户不重写；创建新比较账户 |
| 行情过期、价格非有限或不为正、资产缺失 | 阻止更新 |
| 行情大幅跳变 | 阻止更新，要求核实价格口径 |
| 账户事件或存储行情被意外修改 | 审计失败，阻止更新和计划 |
| 下一交易日没有足够现金或手数不满足 | 缩减或跳过模拟买入 |

## 仍然有限制

当前只有日线、多头、现金、固定资产池和简化开盘成交。交易手数、最低费用、最低金额增加了执行约束，但仍未模拟 T+1、涨跌停、停牌、成交量、股息、税费、盘口和未成交订单队列，因此不能声称完整支持 A 股、ETF 或任一真实市场。费用为每笔 `max(名义金额×比例成本, 最低费用)`，不会同时叠加两项；使用时须匹配自己的费率含义。

回撤停止可能因跳空而超过阈值；无法覆盖最低费用的极小卖出会跳过，可能残留仓位。运行时间随历史增长，当前重放完整已导入区间以验证一致性，尚未优化为高频增量引擎。
