# BSCAT 分类优化工作流

**目标**：优先发现影响范围广、业务后果严重、最值得修复的分类问题，生成 `output/change_list.md`，交由人工审核和后续处理。

**原则**：修正 BSCAT，不以对齐 illion 为目标；差异不等于错分。只保留值得处理的问题，不凑数量。本 Skill 只做分析和出清单，不修改模型代码与配置。

## 一、AI 分析：识别、评估、出清单

### 1. 确定输入与重点范围

- 使用 `input/` 最新适用的 `risk_*_dash_detail.csv`（交易证据）和 `bscat_monitor_*.html`（筛选指标，用 `scripts/parse_monitor.py` 解析）。记录文件名、明细日期范围及 monitor `dataDate`，不同期数字不混用。
- 明确本次 `AUS_BS_CAT_Model` 路径及分支 / 提交；用户已指定则沿用，有歧义才询问。规则、代码与类别定义均以该版本为准。
- `finv_*` = BSCAT，`illion_*` = illion，`(空)` = 未分类；核实流向两端含义。剔除金额为空或为 0 的通知类记录，异常数据单独计数。
- 千万行 CSV 用 DuckDB / polars 或 Python `csv` 流式处理，禁止 pandas 全量读入；所有计数从当前输入重算。

**重点类别**：以下 10 个 P0 类别全部纳入；P0 表示业务重点，不代表每个差异都是高优先级问题。

`Wages、Centrelink、All Other Credits、SACC Loans、Non SACC Loans、Unknown Loans、Credit Card Repayments、Debt Collection、Debt Consolidation、Overdrawn`

非 P0 从 monitor 的 `DATA.categories[]` 中，分别取 `coverage_gap` 最负、`diff_count` 最大、`iou_rate` 最低的前 5 类，合并去重，空指标跳过。这些指标只筛选候选，不直接决定严重程度。

取明细中流向任一端属于上述类别的记录，按流向笔数降序选取至覆盖至少 90%，再补足每个 P0 类别的 90%，流向去重。此为筛查覆盖量，不能当作已确认错分量。

### 2. 判定问题与优化价值

- **抽样**：每个入选流向按归一化的 `(counterparty, text)` 聚类，先看笔数最多的前 10 组，各取最早交易。`text` 转大写、数字转 `#`、其余非字母数字字符转空格（保留 `#`）、压缩空白；`counterparty` 转大写、去首尾空白，空与 `-` 合并。前 10 组只是起点：对申请覆盖广、跨流向重复出现的商户 / 关键词，以及规模大但抽样覆盖不足的流向，按商户或命中规则合并补查；无新增高 / 中优先级根因时停止扩查。
- **判定**：按 `text` → `counterparty` → `third_party` → 收支方向 / 金额取证，对照模型的 `CLAUDE.md` / `configs/category_catalog.json`，区分 `BSCAT 对 / illion 对 / 都对 / 都错 / 需引擎状态 / 信息不足`。仅输出已证实的 BSCAT 错分、漏分或误报，并独立明确正确类别；任一方未分类不代表另一方错误。账户归属、贷款流等缺少状态时不凭文本定性，疑似高影响问题列入“待补证据”。
- **影响**：按同一根因统计去重用户数或申请数、交易笔数，可得时补充金额；写清条件、期间及重叠范围。同一泛词、别名缺口或重复覆盖机制须跨商户 / 流向评估累计影响，不因单条样本量小就忽略共同问题。`application_id` 代表申请，不能等同用户数。分开记录已证实影响与候选范围 / 估计上限，不把整个流向算作单条规则的收益，不重复相加。
- **排序**：高优先级为广泛影响收入、负债、风险等关键业务判断，或少量错分即可造成严重后果的问题；中优先级为影响较集中但修复价值明确的问题。说明业务后果及依据，未验证后果标为推测；结合紧迫性、预计收益、修改成本和误伤风险排序。低价值零散问题只汇总。

### 3. 形成可审核、可执行的建议

对入选样本先核对知识库与规则，再按影响筛选值得深入定位的候选；使用附表查找入口，不仅停留在分类差异或引擎层面：

- **配置排查**：核对 `merchant_kb.csv`、对应引擎规则及 `catch_all_rules.csv`，检查商户 / 别名 / 缩写 / 截断写法缺失，裸地点 / 人名 / 支付通道等泛词误命中，类别错配，以及重复关键词跨行分类冲突。发现问题后，在已核对版本中查全同类配置，不只修改首个样本命中的一行；每个拟改项仍须有样本或可复现的错误行为支持，不凭词形批量删除。
- **定位根因**：记录相对路径、`rule_name` / `merchant_name` / 函数名和当前值；列明相关命中行，按实际匹配及覆盖机制确定生效项，追到最终 `bscat` 写入点。核查最长匹配、重复关键词覆盖、variant 截断、缓存加载及引擎优先级；规则命中不等于最终分类生效。
- **明确改法**：优先改规则表。新增 CSV 行按实际表头写全；修改 / 删除列明精确字段值、pattern / token 和保留项；逻辑修改写清条件、输入与期望行为。核实规则是否已存在及 variant 上限（merchant 规则现为前 50 个，以代码为准）。配置、引擎顺序及跨类别覆盖改动标“高风险”，写明回退办法。
- **预验证**：按实际清洗、大小写及匹配语义，用 1–3 条原始样本验证修改前后的生效规则，并检查易误伤的反例，不能只证明新增关键词能命中。仅在本仓库做独立匹配验证，不运行模型代码。根因、目标或方案不明确则列“待补证据”，不写模糊改动。

`change_list.md` 只保留三部分：

1. **本次范围**：模型路径 / 版本、输入及日期、范围内笔数、剔除 / 异常数、入选流向覆盖量、抽查聚类代表量、未覆盖量及主要盲区；附 10 类 P0 的范围内笔数 / 流向覆盖率，无差异行则注明。筛查覆盖量、聚类代表量与已证实错分量分开报告。
2. **变更清单**：按优先级和优化价值排序，同一根因合并为一项，跨文件修改列在同项，依赖用条目 ID 表达。同类机制、同种修复方式的配置问题可附批量明细，不必一商户一项；不同根因不因修改同一文件而合并。没有值得修改的问题时如实说明。
3. **待补证据**：仅列疑似高影响问题、缺少什么及如何补齐；其余未展开问题只记总量。

每项按已核实的根因选择一个固定问题类型，不按修改文件或表面结果归类：

| 问题类型 | 适用情况 |
|---|---|
| 规则缺项 | 缺少对应商户、关键词或交易写法的识别规则，需要补充规则。 |
| 匹配偏差 | 已有规则的匹配范围过宽、过窄或清洗方式不一致，导致误命中或漏命中。 |
| 类别错配 | 识别对象正确，但规则表或映射表配置了错误的目标类别。 |
| 流程冲突 | 规则本身正确，但被执行顺序、入口限制、优先级或后续覆盖阻断。 |
| 判定缺陷 | 账户归属、交易流、金额条件等业务判断逻辑错误或缺失，需要修改判断逻辑。 |

每项只选一个主类型；有多个独立根因则拆项，有关联原因则写入问题说明。根因未明确的放入“待补证据”。问题类型与优先级、风险分别记录，错分 / 漏分 / 误报在问题描述中说明。

每项先让运维看懂问题，再提供具体修改依据：

```md
### CHG-001｜高 / 中｜<一句话说明问题>
- 问题类型：<规则缺项 / 匹配偏差 / 类别错配 / 流程冲突 / 判定缺陷，选一>
- 状态：待审核
- 当前分类 → 目标分类：<BSCAT 当前类别或未分类> → <准确类别名或明确不分类；多组逐一列明>
- 问题与修改理由：<哪里分错、为什么发生、为什么值得改，用白话说明>
- 影响与优先理由：<去重用户 / 申请数、笔数、统计条件；实测或估计；业务后果>
- 证据：<交易 ID / 可定位来源、原始 text、判定依据>
- 修改方案：<文件 + 稳定定位标识；当前值 → 完整新行 / 精确字段值 / 明确函数行为；批量配置用下表>
- 依赖与风险：<前置条目 ID 或无；必要的缓存 / 索引重建；可能误伤的类别；高风险项的回退办法>
- 验收：<正例的预期最终分类、反例保持的结果、同批数据下应改善的指标>
- 人工意见：<人工确认、修改或不采纳的理由>
```

批量配置在对应条目的“修改方案”下逐行列明，操作固定为 `新增 / 修改 / 删除`：

| 文件 / 稳定定位标识 | 操作 | 当前值 | 修改后值 / 保留内容 | 证据引用 |
|---|---|---|---|---|
| <路径 + merchant_name / rule_name + 必要的区分字段> | <操作> | <完整原值；新增写无> | <完整新行或精确字段值；删除写明保留项> | <该行对应样本 / 可复现行为> |

不得用“收紧、复核、视情况调整”等代替修改方案，也不得用省略号或非引擎支持的通配符代替完整词条；样本必须真实、可定位，不能编造或以截断文本作为执行依据。历史清单只作排查线索，结论与影响量须按当前版本和数据重新核实，不设建议条数目标。

## 二、人工审核：确认改什么

运维核对问题、影响与方案，可直接修改、补充清单，将状态设为 `已确认 / 暂缓 / 不采纳`；也可在对话中明确确认条目 ID，由 AI 据实记录。“待补证据”问题补齐后重新提交审核。

AI 不得自行确认。清单交由人工决定并安排后续修改，本工作流到此结束。

## 附：规则与最终写入点索引

路径相对于模型仓库，仅作定位入口，以确认版本的实际调用链为准。

| 类别 | 规则 / 配置入口 | 继续追踪 |
|---|---|---|
| Wages / Centrelink | `income_engine/resources/income_pattern_rules.csv`、`income_config.csv` | `income_engine/domain/classification.py` |
| All Other Credits | `all_other_credit_engine/resources/all_other_credit_rules.csv` | `all_other_credit_engine/engine.py` |
| SACC / Non SACC / Unknown Loans | `liability_engine/resources/counterparty_keyword_rules.csv` | `liability_engine/domain/streams.py`：`SPECIAL_COUNTERPARTY_STREAM_RULES`、`apply_special_counterparty_stream_overrides`、`add_bscat` |
| Credit Card Repayments | `liability_engine/resources/credit_card_rules.csv` | `liability_engine/domain/counterparty.py`：`apply_credit_card_rules` |
| Debt Collection / Debt Consolidation | `liability_engine/resources/debt_collection_rules.csv`、`liability_engine/resources/debt_consolidation_rules.csv` | `liability_engine/domain/counterparty.py`：`_apply_flag_rules` → `liability_engine/domain/streams.py`：`add_bscat` |
| Overdrawn | `liability_engine/resources/overdrawn_rules.csv`、`fee_engine/resources/fee_classification_rules.csv` | `liability_engine/domain/counterparty.py` → `add_bscat`；`fee_engine/domain/classification.py` |
| Rent | `rent_engine/resources/rent_rules.csv` | `rent_engine/engine.py`、`classification_core/orchestrator.py` |
| Gambling | `gambling_engine/resources/gambling_rules.csv` | `gambling_engine/engine.py` |
| Internal Transfer / External Transfers | `transfer_engine/resources/transfer_*.csv` | `transfer_engine/domain/classification.py`、`classification_core/service.py` |
| Dishonours | `dishonour_engine/resources/dishonour_rules.csv` | `dishonour_engine/engine.py` |
| Fees | `fee_engine/resources/fee_classification_rules.csv` | `fee_engine/domain/classification.py` |
| 其余消费类 | `initial_engine/merchant_kb.csv`、`catch_all_engine/resources/catch_all_rules.csv` | `initial_engine/domain/classification.py`、`catch_all_engine/engine.py` |
| 引擎顺序 / 覆盖关系 | `configs/pipeline.json` | `classification_core/orchestrator.py` |
