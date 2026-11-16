# BSCAT 分类优化工作流

**产出**：`output/change_list.md`，主体为可执行改动项，附未覆盖 / 不改判定。本仓库只做对比分析与出清单；归因 / 实施 / 回归在 `AUS_BS_CAT_Model` 侧。
**原则**：修 bscat 的错分规则，不是对齐 illion（illion 自身也有错分）。

**输入**（`input/`，每天可能更新，以最新文件为准）
- `risk_*_dash_detail.csv`：逐笔差异明细 → 判定
- `risk_*_dash_*.csv`：类别 / 大类 / 总体 / 趋势统计（参考）
- `bscat_monitor_*.html`：监控报告 → 定范围（数据在 `const DATA = {…}`，JSON 解析；类别级指标在 `DATA.categories[]`）
- 字段映射：`finv_*` = bscat，`illion_*` = illion，`(空)` = 无分类；明细与监控可能不同期，数字不要混用。
- `AUS_BS_CAT_Model` 仓库：**开始分析前先与用户确认本次使用哪个路径**（可能存在多个副本 / 分支）；确认后所有规则 / 代码 / catalog 核对均基于该路径。未确认不得开始分析。

## 1. 定范围（按规则机械执行，不自行扩展）

**P0 全集（10 类，全部进入范围）**：
`Wages、Centrelink、All Other Credits、SACC Loans、Non SACC Loans、Unknown Loans、Credit Card Repayments、Debt Collection、Debt Consolidation、Overdrawn`

「全量」指所有 P0 行进入候选，不做抽样。

**非 P0 筛选（固定规则）**：取 `DATA.categories[]` 中 `level != "P0"` 的类别，三组各取前 5、合并去重（≤15 类）：
1. `coverage_gap` 最负的 5 类
2. `diff_count` 最大的 5 类
3. `iou_rate` 最低的 5 类

指标为 null 的类别跳过该组；不引入其他指标、不改阈值。

**判定范围**：明细中 `差异流向` 任一端属于「P0 ∪ 入选类别」的行。

**剔噪**：先剔除 `amount` 为空或数值为 0 的行（银行通知类）；这些行不进入判定。

## 2. 判定（按流向覆盖，机械执行）

1. **判定粒度**（全局 90% + P0 逐类兜底）：
   - 将判定范围内的行按 `差异流向` 汇总，按行数降序排列。
   - **全局覆盖**：从大到小取流向，直到累计行数 ≥ 判定范围总行数的 90%；这些为「已判定流向」。
   - **P0 逐类兜底**：逐个 P0 类别，取以其为任一端（左或右）的所有流向，计算行数合计；若其中「已判定流向」的累计行数 < 该合计的 90%，按流向行数降序补入该类别未判定的流向，直到 ≥ 90%。补入的流向同样参与 Top-10 聚类抽样；同一流向只计一次。
   - 每个已判定流向内，按 (`counterparty`, `text`) 归一化聚类，取笔数最大的前 10 个聚类各看 1 条样本（组内最早交易）。
   - 未进入前 10 的聚类、以及兜底后仍未判定的流向，写入附录「未覆盖」，记录行数与聚类数；不得静默省略。
   - 若某流向 Top-10 聚类覆盖率 < 50%，在该流向结论后标注「长尾」。
2. **归一化**：
   - `text`：转大写 → 数字替换为 `#` → 非字母数字替换为空格 → 压缩空白
   - `counterparty`：转大写 → 去首尾空白；`-` / 空视为同类
3. **判定证据顺序**：`text` > `counterparty` > `third_party` > `dr_cr` / `amount`。对照类别定义（`AUS_BS_CAT_Model` 的 `CLAUDE.md` / `configs/category_catalog.json`，只读）判六选一：
   - `bscat对`：语义属于 bscat 所分类别
   - `illion对`：语义属于 illion 所分类别
   - `都对`：两类都合理（边界类）
   - `都错`：两类都不符
   - `需引擎状态`：文本 / 对手方 / 金额不足以判断，需 `bank_accounts` 归属、贷款流判定或其他引擎状态（如转账归属、SACC/Non SACC、Debt Collection 流）；必须写明缺哪个字段 / 状态
   - `信息不足`：无法判断且不依赖引擎状态
4. **差异类型固定解读**：
   - 分类不一致（双方都有分类）→ 判谁对
   - 仅 illion 有分类（bscat 空）→ illion对 ⇒ bscat 漏识别；illion错 ⇒ 不改
   - 仅 bscat 有分类（illion 空）→ bscat对 ⇒ 不改；bscat错 ⇒ 误报，需收紧

## 3. 出清单

**位置由类别决定（固定映射，不猜）**：

| 类别 | 规则 / 配置 | 最终写入 / 逻辑（必须继续追） |
|---|---|---|
| Wages / Centrelink | `income_engine/resources/income_pattern_rules.csv`、`income_config.csv` | `income_engine/domain/classification.py` |
| All Other Credits | `all_other_credit_engine/resources/all_other_credit_rules.csv` | `all_other_credit_engine/engine.py` |
| SACC / Non SACC / Unknown Loans | `liability_engine/resources/counterparty_keyword_rules.csv` | `liability_engine/domain/streams.py`：`SPECIAL_COUNTERPARTY_STREAM_RULES`、`apply_special_counterparty_stream_overrides`、`add_bscat` |
| Credit Card Repayments | `liability_engine/resources/credit_card_rules.csv` | `liability_engine/domain/counterparty.py`：`apply_credit_card_rules` |
| Debt Collection | `liability_engine/resources/debt_collection_rules.csv` | `liability_engine/domain/counterparty.py`：`_apply_flag_rules` → `liability_engine/domain/streams.py`：`add_bscat` |
| Debt Consolidation | `liability_engine/resources/debt_consolidation_rules.csv` | 同上 |
| Overdrawn | `liability_engine/resources/overdrawn_rules.csv`、`fee_engine/resources/fee_classification_rules.csv` | `counterparty.py` → `add_bscat`；费用侧 `fee_engine/domain/classification.py` |
| Rent | `rent_engine/resources/rent_rules.csv` | `rent_engine/engine.py`、`classification_core/orchestrator.py` |
| Gambling | `gambling_engine/resources/gambling_rules.csv` | `gambling_engine/engine.py` |
| Internal Transfer / External Transfers | `transfer_engine/resources/transfer_*.csv` | `transfer_engine/domain/classification.py`、`classification_core/service.py` |
| Dishonours | `dishonour_engine/resources/dishonour_rules.csv` | `dishonour_engine/engine.py` |
| Fees | `fee_engine/resources/fee_classification_rules.csv` | `fee_engine/domain/classification.py` |
| 其余消费类（Dining Out / Retail / Groceries 等） | `initial_engine/merchant_kb.csv`、`catch_all_engine/resources/catch_all_rules.csv` | `initial_engine/domain/classification.py`、`catch_all_engine/engine.py` |
| 引擎顺序 / 覆盖关系 | `configs/pipeline.json` | `classification_core/orchestrator.py` |

### 3.1 施工前核对（每项必做，缺一不可）

1. **定位到行 / 函数**：写出 `file` + `rule_name` / `merchant_name` / 函数名，并把当前值抄进 `现状`。行号可写，但以 `rule_name` / `merchant_name` 为准（行号会漂移）。
2. **样本回放**：从该聚类取 1–3 条原始 `text`，按对应引擎的匹配方式验证拟改 pattern 是否命中（regex 用 `re.search`；keyword 按引擎实现，可能是子串 / 整词 / 最长关键词优先）。不命中就重写 pattern，不得直接写进清单。只在本仓库用 `re.search` / 字符串匹配验证，不执行 `AUS_BS_CAT_Model` 代码。
3. **CSV 结构核对**：不同引擎表头不同，先读表头，按实际列写。常见列：`match_type`（keyword / regex）、`priority` / `confidence`、`dr_cr`、`zero_amount_reject`、`unclassified_only`。`merchant_kb.csv` 每个 merchant 只取前 `_MAX_VARIANTS_PER_MERCHANT = 50` 个 variant（`initial_engine/domain/classification.py`），新增 / 保留关键词必须落在前 50。
4. **追最终写入点**：规则文件命中 ≠ 最终 `bscat`；若后续会重算 / 覆盖，位置写最终函数、不写规则文件，并在 `现状` 中说明覆盖链路。
5. **事实核对**：`merchant_name` / category / 规则是否已存在均须 grep 确认，不得凭印象；不得写「同时存在」「等」而不列全。

### 3.2 改动类型与写法

| 类型 | 位置 | 必须写清 |
|---|---|---|
| 新增规则 | 规则 CSV | 新行全文（含所有列）或精确 pattern |
| 删除泛词 | 规则 CSV | 要删的完整 token；保留哪些具体 variant；是否受 variant 上限影响 |
| 命中链路 | 规则 / 引擎 | 现有规则为何不生效：命中条件、优先级、覆盖顺序、非 overwrite 守卫 |
| 引擎逻辑 | `domain/*.py` / `orchestrator.py` | 函数名、入口条件、需要的输入字段、期望行为 |
| 高危 | `configs/*.json` / 引擎顺序 | 影响的引擎和类别、回退风险 |

`改为` 不得写成「复核 / 确认 / 收紧 / 建议 / 视情况 / 等」动作描述。

### 3.3 每项格式

```md
### <file> / <rule_name|merchant_name|function>
- [ ] 类型=`新增规则|删除泛词|命中链路|引擎逻辑|高危`
  **问题描述**：<...>
  现状：`...`（当前 CSV 行 / 当前函数行为）
  改为：`...`（完整替换行 / 精确 pattern / 函数行为）
  依据：<判定>；样本=`<原始 text，截断 80 字符>`
  影响：<app> app / <笔数> 笔；flow=`<流向>`
  前置：<需先改的函数 / 数据；无则写「无」>
  验证：<重跑后目标 flow 笔数变化；相关类别总笔数不增加；grep 确认旧行 / 旧 pattern 消失；样本应命中 / 不再命中>
```

`问题描述` 写法固定：

- 只写「哪里错了 → 规则为什么没拦住 → 交易长什么样」，不写改法；改法只写在 `改为`。
- 每条至少 1 个具体例子；例子必须是实际样本 `text` 或可复现的规则行为，不得编造。
- 用白话，不复述 `现状` 里的字段名 / 函数细节；目标是让不做实现的人也能判断要不要改。
- 仅 `## 一、可执行改动` 的每项需要；`## 二` / `## 三` 不需要。

### 3.4 修改顺序

1. 先修最终写入 / 优先级（如 `add_bscat` 的 flag 覆盖、engine order）。
2. 再补账户归属 / 流判定能力（transfer / rent / SACC）。
3. 最后加 / 删关键词和正则。

### 3.5 漏项检查

- 每个 P0 类别在清单中至少出现一次（含「不改」）。
- 判定范围内无差异行的 P0 类别，在清单中记「无差异行」。

### 3.6 清单结构

清单头部固定写：`AUS_BS_CAT_Model` 路径、detail 日期范围、monitor `dataDate`、范围类别数 / 行数、已判定流向覆盖行数及其占比、剔除零金额行数、未覆盖行数、P0 逐类判定覆盖率（每个 P0 类别：行数 / 已判定流向覆盖行数 / 覆盖率）。

1. `## 一、可执行改动`（按目标文件分组；按 3.4 顺序排列）
2. `## 二、需引擎状态`（P0 优先，写明需要的状态 / 数据 / 前置）
3. `## 三、未覆盖`（Top-90% 以外的流向 / 聚类，记录行数）
4. `## 四、判定为 bscat对 / 都对 / 信息不足`（不改，简述原因）

`都错` 按能否给出正确类别拆分：能 → 一；不能 → 二。

## 约束

- 明细是千万行级 CSV，优先 DuckDB / polars 流式聚合；环境没有时用纯 Python `csv` 流式聚合，禁止 pandas 全量读入。
- 规则优先改 `resources/*.csv`；配置 / 引擎顺序改动标 `高危`。
- 所有计数从当前输入重新计算，不沿用历史文档中的数字。
