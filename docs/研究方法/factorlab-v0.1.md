# FactorLab v0.1：多因子风险归因与正交化引擎

状态：可运行的独立研究模块。当前演示使用可复现的合成美股面板，用于验证数据、因子、回测、风险和对冲整条链路，不是实盘业绩，也不是收益承诺。

## 1. 目标与非目标

目标：

- 从日频价格、成交额、总市值和带披露日的基本面数据构造可解释的截面因子。
- 做 MAD 缩尾、截面标准化、行业/市值/Beta 中性化和对称正交，输出可比较的纯因子分数。
- 计算 IC、RankIC、ICIR、t 值、IC 衰减、半衰期、VIF 和因子相关矩阵。
- 用滚动 ICIR 做自适应权重，加入波动率目标和规则型风险开关。
- 做 long-only 与纯因子多空回测，计入换手成本和调仓约束。
- 用 Fama-MacBeth 回归、因子协方差和特质风险做组合风险归因。
- 做历史压力重放、情景压力测试和保护性看跌期权对冲测算。

非目标：

- 当前版本不连接券商、不自动下单、不管理真实资金。
- 当前演示不是实盘回测；合成数据中的因子溢价由生成器设定，不能外推到真实市场。
- 当前版本不包含完整 Barra 风险模型、组合凸优化、跨资产 VAR 和期权曲面校准，这些在路线图中。

## 2. 架构

```text
data layer
  synthetic.py / csv_loader.py / panel.py
        |
        v
factor layer
  factors.py  ->  momentum, reversal, low_vol, illiquidity,
                  size, value, quality
        |
        v
cleaning layer
  preprocess.py  ->  MAD winsorise -> z-score -> WLS neutralise
                     -> Löwdin symmetric orthogonalisation -> z-score
        |
        +----------------------+----------------------+
        v                      v                      v
evaluation.py          portfolio.py             risk.py
IC / decay / quantile  weights / backtest       factor returns / covariance
        |                      |                      |
        +----------------------+----------------------+
                               v
                        options.py
                 Black-Scholes / Greeks / put overlay
                               |
                               v
                        pipeline.py
                               |
                               v
                 report.py -> HTML + CSV + JSON
```

## 3. 代码地图

| 文件 | 职责 |
|---|---|
| `backend/quant/panel.py` | 对齐的 symbol-major 面板、缺失值、可交易域、财报 as-of 查询、数据指纹 |
| `backend/quant/synthetic.py` | 可复现的美股合成面板，含状态切换、行业冲击、跳空、停牌和季度财报 |
| `backend/quant/csv_loader.py` | 真实 CSV 数据入口，严格保留缺失值，不向前填充 |
| `backend/quant/factors.py` | 七个截面因子的定义和计算 |
| `backend/quant/preprocess.py` | 缩尾、标准化、WLS 中性化、对称正交、相关与 VIF |
| `backend/quant/evaluate.py` | IC、ICIR、衰减、半衰期、分层组合和绩效指标 |
| `backend/quant/portfolio.py` | 复合分数、自适应权重、long-only 与 long-short 回测 |
| `backend/quant/risk.py` | Fama-MacBeth 因子收益、协方差、风险分解、压力和尾部指标 |
| `backend/quant/options.py` | Black-Scholes 定价、隐含波动率、Greeks、保护性看跌期权 |
| `backend/quant/pipeline.py` | 端到端编排和产物写出 |
| `backend/quant/report.py` | 无外部依赖的单文件 HTML 报告 |
| `backend/quant/cli.py` | `demo` 与 `csv` 两个命令行入口 |

## 4. 数据契约

### 4.1 CSV 模式

`prices.csv`：

```text
date,symbol,close,volume,market_cap,industry
2024-01-02,AAPL,185.64,52000000,2890000000000,Technology
```

- `close` 必须是拆分/分红复权后的收盘价。
- `volume` 为股数；`market_cap` 为当日总市值。
- 缺失收盘可以留空，加载器不会向前填充。
- 同一 `date + symbol` 不应重复。

`fundamentals.csv`：

```text
symbol,publish_date,period,roe,earnings_yield,book_to_price,accruals
AAPL,2024-02-02,2023Q4,0.42,0.033,0.041,0.006
```

- `publish_date` 是报告真正公开的日期，不是财季结束日。
- 信号日 t 只能使用 `publish_date <= t-1` 的记录。
- 价值和质量因子缺少基本面时直接不参与，不伪造行业均值。

### 4.2 无未来函数协议

1. 在 t 日收盘后计算因子分数。
2. 在 t+1 日按新权重获取收益，回测记录 `close[t+1] / close[t] - 1`。
3. 财报使用 t-1 之前已公开的记录。
4. 停牌、零成交、缺失收盘的股票不进入可交易域。
5. 组合内缺失收益按 0 处理，保留现金，不用行业收益补值。
6. 调仓时按单边换手计成本，默认 5 bp。

## 5. 方法

### 5.1 因子定义

| 因子 | 定义 | 方向 |
|---|---|---|
| 动量 | `close[t-21] / close[t-252] - 1` | 高动量预期延续 |
| 短期反转 | `-(close[t] / close[t-5] - 1)` | 超跌修复 |
| 低波动 | `-stdev(daily returns, 60) * sqrt(252)` | 低波动得分高 |
| 非流动性 | `log(1 + 1e9 * mean(|r_t| / dollar_volume_t))` | 越不流动得分越高 |
| 小市值 | `-log(market_cap)` | 市值越小得分越高 |
| 价值 | 盈利收益率与账面市值比截面 z-score 的均值 | 便宜得分高 |
| 质量 | `ROE - 0.5 * accruals` | 盈利质量高得分高 |

所有因子在进入组合前都被统一为“分数越高，预期收益越高”。

### 5.2 缩尾与标准化

对每个截面：

```text
median = median(x)
MAD    = median(|x - median|)
scale  = 1.4826 * MAD
x_clip = clip(x, median - 3*scale, median + 3*scale)
z      = (x_clip - mean(x_clip)) / stdev(x_clip)
```

MAD 为 0 时退回 IQR/1.349，再退回标准差。

### 5.3 Barra 风格中性化

对因子 k 的截面分数做加权最小二乘：

```text
z_k = 1 * a + industry_dummies * b + log_size * c + beta * d + residual
weight_i = sqrt(market_cap_i)
```

残差重新标准化后作为中性化分数。

- 权重用 `sqrt(cap)` 而不是 `cap`，避免超大盘完全主导回归。
- 对 `size` 因子回归时剔除 `log_size` 自身，否则会把规模信号一起回归掉。
- 对 `low_vol` 因子回归时剔除 `beta` 自身，否则会把低波动信号一起回归掉。
- 行业基准组取排序后的第一个行业，保留截距。

### 5.4 对称正交

设中性化后的因子矩阵为 `X`（n 个股票 × k 个因子），其相关矩阵为 `G`。使用 5% 向单位阵收缩：

```text
G_shrunk = 0.95 * G + 0.05 * I
Z = X * G_shrunk^(-1/2)
```

`G_shrunk^(-1/2)` 通过 Jacobi 特征分解计算。结果列再标准化并按与原始列的相关方向对齐符号。

与逐次 Gram-Schmidt 相比，Löwdin 对称正交不依赖因子顺序，正交后两两相关接近 0；保留 5% 收缩是为了避免极端共线性时逆矩阵放大噪声。

### 5.5 IC、ICIR 与衰减

每个交易日 t：

```text
IC_t = Spearman(factor_score_t, forward_return_{t+1})
ICIR = mean(IC) / stdev(IC)
t    = ICIR * sqrt(n_days)
```

`ICIR_annual = ICIR * sqrt(252)`。

IC 衰减使用 1、2、3、5、10、20、60 日的前瞻收益；这些窗口重叠，长周期数值会放大自相关，不能当作独立样本做显著性检验。半衰期定义为第一个低于首日 IC 一半的持有期。

### 5.6 自适应权重

在每次调仓日，只使用调仓日之前的 IC 序列：

```text
raw_k = max(ICIR_k, 0)
w_k   = 0.5 * raw_k / sum(raw) + 0.5 * (1/k)
```

然后：

- 单因子上限 32%，超限部分按比例分给其他因子。
- 市场 60 日波动处于过去一年 75% 分位以上时，低波动乘 1.6、质量乘 1.35、动量乘 0.55、非流动性乘 0.45，再归一化。
- 所有 ICIR 都为负时退回等权。

### 5.7 组合与回测

Long-only：

- 综合分数最高的 20% 股票等权。
- 组合波动率目标 10%，仓位上限 100%，下限 20%。
- 每 21 个交易日调仓。

Long-short：

- 最高 20% 做多、最低 20% 做空，多空各 50% 总敞口。
- 波动率目标 10%，总敞口上限 1.2 倍。
- 净市场暴露接近 0，但行业和风格暴露不一定为 0。

成本：

```text
turnover = 0.5 * sum(|w_new - w_old|) + 0.5 * |cash_new - cash_old|
cost     = turnover * 5bp
```

### 5.8 风险归因

每个交易日做截面回归：

```text
forward_return_{t+1} = alpha + beta_market * market_beta
                     + sum_k beta_k * factor_score_{k,t}
                     + residual
```

回归系数序列作为因子日收益。因子协方差按 10% 向对角阵收缩，再年化。

组合因子暴露：

```text
b_k = sum_i weight_i * score_{i,k}
```

组合因子方差 `b' Sigma b`，特质方差 `sum_i (w_i * sigma_i)^2`，其中 `sigma_i` 来自最近 120 日截面回归残差。

### 5.9 压力测试与尾部对冲

压力情景直接施加到组合 Beta 和标准化因子暴露：

```text
scenario_pnl = beta * market_shock + sum_k b_k * factor_shock_k
```

情景包括动量崩塌、流动性冲击、利率快速上行、风险偏好反转，以及样本内最差 20 日市场窗口的实际因子收益重放。

保护性看跌期权：

- 以压力损失换算“压力等效 Beta”，对冲名义本金按损失上限反推。
- 3 个月期限、10% 虚值、18% 以上定价波动率。
- Black-Scholes 计算价格、Delta、Gamma、Vega、Theta。
- 输出不同指数变动 × 波动率水平的组合损益矩阵。

## 6. 演示结果

数据：`synthetic-us-equity-80x6y`，seed 42，2020-01-02 至 2025-12-31，80 只标的，8 个行业，1512 个交易日。

组合回测：

| 组合 | 年化收益 | 年化波动 | Sharpe | 最大回撤 | 年化换手 | 平均总敞口 |
|---|---:|---:|---:|---:|---:|---:|
| ICIR 自适应 long-only | +6.13% | 11.04% | 0.59 | -13.87% | 414.15% | 57.30% |
| 等权因子 long-only | +6.52% | 10.85% | 0.64 | -11.63% | 299.27% | 56.19% |
| 纯因子多空 | +11.88% | 9.65% | 1.21 | -6.84% | 525.72% | 110.49% |
| 等权基准 | +2.06% | 18.88% | 0.20 | -30.98% | 56.06% | 100.00% |

因子 IC：

| 因子 | IC 均值 | ICIR | t 值 | 半衰期 |
|---|---:|---:|---:|---:|
| 动量 | 2.24% | 0.11 | 3.98 | >60 日 |
| 短期反转 | 3.56% | 0.21 | 7.32 | 60 日 |
| 低波动 | 0.35% | 0.02 | 0.59 | >60 日 |
| 非流动性 | 0.10% | 0.01 | 0.25 | 2 日 |
| 小市值 | 0.68% | 0.04 | 1.53 | >60 日 |
| 价值 | 0.37% | 0.02 | 0.60 | >60 日 |
| 质量 | 0.52% | 0.03 | 1.03 | >60 日 |

综合因子分层：

| 组合 | 年化收益 | Sharpe |
|---|---:|---:|
| Q1 | -9.57% | -0.31 |
| Q2 | +0.12% | 0.11 |
| Q3 | +0.60% | 0.13 |
| Q4 | +10.41% | 0.62 |
| Q5 | +13.45% | 0.72 |
| Q5-Q1 | +22.60% | 1.22 |

风险与对冲：

- 组合 Beta 0.59，预测总波动 5.52%，因子波动 4.34%，特质波动 3.41%。
- 风险占比：小市值 21.72%、价值 16.69%、非流动性 9.13%、质量 8.84%、动量 4.98%、特质 38.28%。
- 3 个月 10% 虚值保护性看跌期权成本约 0.241%，对冲名义本金 60.09%。
- 样本内最差 20 日情景组合损失 -16.01%，压力等效对冲后显著收窄。

这些数字来自合成市场，生成器对因子溢价、波动、状态切换和压力窗口都有明确设定。它们证明管道可运行、方向一致、指标可解释，不证明真实市场可获得同样收益。

## 7. 复现与测试

在 `backend/` 目录：

```powershell
$env:PYTHONPATH='.'
py -3.10 -m quant.cli demo --out ../reports/factorlab-demo --seed 42 --years 6 --symbols 80
```

真实 CSV：

```powershell
py -3.10 -m quant.cli csv --prices ..\data\us-prices.csv --fundamentals ..\data\us-fundamentals.csv --out ..\reports\factorlab-real
```

测试：

```powershell
py -3.10 -B tests\run_backend.py test_quant_linalg test_quant_factors test_quant_options test_quant_pipeline
```

当前机器上的 Python 3.14.3 在长循环中偶发解释器级崩溃（`Executing a cache`），因此验证使用 Python 3.10.10。模块只依赖标准库，目标兼容 Python 3.10+；仓库自带 `runtime\python.exe` 时优先使用运行时。

## 8. 与现有站点的集成

第一阶段已完成：独立 CLI、报告、测试，不触碰现有板块站路由。

第二阶段：

- 在 `backend/server.py` 增加只读接口 `/api/quant/summary`、`/api/quant/report`、`/api/quant/backtest`。
- 读取 `data/quant/` 下的缓存 JSON，不在 HTTP 线程里重算全市场。
- 复用现有登录、CSP 和局域网访问控制。

第三阶段：

- 在 `web/` 增加“因子实验室”页面，使用 ECharts 读取既有语义色。
- 展示 IC 热力图、净值、回撤、风险归因、压力测试和对冲 Greeks。
- 遵守仓库前端规范：无渐变、无 emoji、缺失值显示为“—”、红涨绿跌。

第四阶段：

- 接入真实美股/ETF 日线、复权因子、退市样本和 PIT 财报。
- 增加行业历史成员表，避免用当前行业回填过去。
- 加入组合凸优化：行业偏离、单票上限、换手惩罚、因子暴露约束。
- 跨资产模块用向量自回归和状态切换模型估计股、债、商品、利率传导。

## 9. 局限

- 合成数据不能替代真实市场验证；所有绩效数字必须标注为方法演示。
- 当前没有模拟涨跌停、融券约束、冲击成本、容量和借券费。
- 期权对冲使用 Black-Scholes 理想假设，未校准偏斜和期限结构。
- 行业分类是合成标签；真实数据必须使用历史行业成员表。
- IC 衰减的长周期窗口重叠，不能直接当作独立样本。
- 多因子筛选存在多重检验和数据挖掘风险，真实研究需要样本外验证和 deflated Sharpe 一类校正。
- 回测中的波动率目标是简化规则，不是最优仓位管理。

## 10. 下一步

1. 用真实美股数据跑同一管道，先做 20 只大盘股的样本外面板。
2. 增加 PIT 财务库和行业历史成员表。
3. 增加组合优化器和换手惩罚。
4. 增加 API 缓存与前端页面。
5. 增加跨资产传导模块和期权曲面校准。
6. 用 paper trading 记录至少 3 个月的样本外表现，再讨论实盘。

