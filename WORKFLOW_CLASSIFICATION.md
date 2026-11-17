# BSCAT 分类优化工作流

**目标**：优先发现影响范围广、业务后果严重或明显不合理的 BSCAT 分类，生成可供人工审核、供 AI 后续执行的 `output/change_list_YYYYMMDD.md`。

**命名**：日期取生成当天的北京时间（Asia/Shanghai）；同日重复生成依次追加 `_02`、`_03`，不覆盖已有清单。文件日期与分析数据日期分别记录。

**原则**：修正 BSCAT，不以对齐 illion 为目标；分类差异、规则命中和引擎摘要均不等于正确答案。只保留值得处理的问题，不凑数量。本工作流只分析和出清单，不修改模型代码与配置。

## 一、AI 分析：识别、评估、出清单

### 1. 核对输入与统计口径

先检查 `input/` 各文件的表头、日期、行数与关联字段，按下表使用有价值的信息；缺文件时继续可完成的分析，注明相应盲区。

| 文件 | 价值与用途 | 使用边界 |
| --- | --- | --- |
| `bscat_monitor_*.html` | 读取 `DATA` 中的类别指标、流向、趋势，建立筛查入口 | 使用 `dataDate`，不能以文件生成时间代替数据日期；空告警 / 待办不代表无问题 |
| `risk_*_dash_summary.csv`、`dash_trend.csv` | 核对总量、差异构成、指标分母及近期变化 | 一致率、覆盖率不等于准确率；不同日期样本构成可能变化 |
| `risk_*_dash_group.csv`、`dash_category.csv` | 发现跨业务大类迁移、关键类别消失 / 异常扩张及用户 / 申请集中度 | 区分 illion 侧差异与双向变动；双向涉及量不能直接相加或当作某条规则收益 |
| `risk_*_dash_detail.csv` | 全体分类差异交易的文本、方向、金额与标识，用于聚类和影响复算 | 不含双方同类或双方都未分类的交易；`排查类型` 只是差异标签 |
| `risk_*_evolve_selection.csv` | 说明哪些类别、申请被圈选，优先查高差异申请 | 不保证 P0 覆盖；同一申请可重复入选，计数不可直接相加；无日期时通过对应导出批次核实 |
| `risk_*_evolve_transactions.csv` | 圈选申请的完整交易上下文，补查双方同错、双方未分类、同流 / 跨账户关联，并提取反例 | 是圈选申请全量，不是总体全量；不能据此外推总体错分率 |
| `risk_*_log_income_summary.csv`、`log_liability_summary.csv` | 提供收入 / 负债流类别、状态、周期、金额等引擎输出，辅助识别业务影响与流判定异常 | 是模型结果摘要，不是规则命中轨迹或独立真值；缺行、空金额、单笔 / 不规律状态本身不证明错误 |

- **日期与版本**：默认分析 monitor 的 `dataDate`，各 CSV 按 `sample_datetime` 取同日；历史日期只用于趋势和复查。`transaction_date` 是交易发生日，不能作为批次筛选字段。日志日期较新也不得跨日拼接。记录 `AUS_BS_CAT_Model` 路径、分支 / 提交及未提交改动；线上版本未核实时，区分线上观察与当前代码验证，已修复的问题不重复提案。
- **字段与关联**：`finv_Category` / `bscat` 是 BSCAT，`illion_Category` / `category` 是 illion；核对类别标准化及空值表示，差异流向为 `illion → BSCAT`。交易关联用同日的 `application_id + job_id + bank_account_id + transaction_id`，有 `log_id` 时进一步限定同次运行；摘要关联用同日的 `application_id + job_id + log_id + stream_id`。先验证键的唯一性；缺键时只在其他运行标识足以消歧后关联，记录重复、冲突和未关联量，不仅凭 `stream_id` 或申请号拼接，不用空流号关联。二级类别与 BSCAT 的映射以对应版本代码为准，不凭流号前缀猜测。
- **计数与对账**：先核对当日差异明细行数与 summary 的差异总数，再单列排除空、零、非数值及非有限金额后的分析量；无法对账先查日期、导出缺失或重复，不宣称完整覆盖。用户按 `user_id`、申请按 `application_id` 去重；缺失 ID 不计入去重数。同笔交易在明细和 evolve 中只计一次，跨运行 / 日期的重复观察不直接相加。
- **处理方式**：CSV 使用 `csv` 流式读取或分块，只为候选建立索引，禁止全量读入大文件。`output/` 旧结果仅作线索，每次重建 scope 和临时统计，确认输入、日期、口径一致后再引用。

### 2. 筛查高价值候选

**差异筛查**：以下 10 个 P0 类别全部纳入；P0 表示重点范围，不直接决定条目优先级。

`Wages、Centrelink、All Other Credits、SACC Loans、Non SACC Loans、Unknown Loans、Credit Card Repayments、Debt Collection、Debt Consolidation、Overdrawn`

非 P0 从 monitor 的 `DATA.categories[]` 中，分别取 `coverage_gap` 最低、`diff_count` 最大、`iou_rate` 最低的前 5 类，合并去重，空指标跳过。结合 group / trend 补查收入、贷款与转账之间的跨组迁移，以及关键类别骤降、异常增长或持续恶化；先排除样本构成变化，不能只按差异量排序。

先运行 `python scripts/parse_monitor.py <monitor> <本次临时目录>/scope.json`，再运行 `python scripts/aggregate_clusters.py <明细> <scope.json> <本次临时目录>`；解析前确保临时目录存在。聚类脚本按 scope 的 `dataDate` 筛选，取流向任一端在 scope 中的交易，按流向笔数累计覆盖 90%，并补足每个 P0 至 90%。新增重点类别时补入本次 scope。90% 只是流向入选覆盖率，不是已审核率或准确率；P0 无差异行记“不适用”，不代表分类无误。

- **聚类初查**：看 `clusters_top.csv` 中每个入选流向的 Top10 聚类；聚类按方向及归一化 `(counterparty, text)` 区分。原始文本才是证据，数字归一化可能合并不同账户 / 商户，不得由代表样本推定整簇错分。对 Top10 代表量低的流向，跨流向合并同商户 / 关键词，按去重申请数及金额补查长尾，兼顾少量但后果严重的交易。
- **上下文补查**：按 selection 的去重申请检查 evolve 完整交易，覆盖差异、双方同类和双方都未分类三种情况。优先检查转账 / 退款 / 贷款入账被当作工资、还款与普通消费混淆、催收 / 透支漏报及泛词跨类别误命中；这些只是线索，须结合方向、账户归属、对手方及前后交易判断。相同文本在不同方向或场景下可有不同正确类别。
- **收入 / 负债核验**：对候选关联同次运行的摘要和流内交易，检查收入类型、周期、状态及月收入估计是否有交易依据，贷款放款 / 还款、产品类型及状态是否合理，逐笔分类与摘要是否一致。摘要还可提示圈选外的异常流：回到差异明细取证，缺完整上下文则列待补证据。先核对摘要的过滤、净额及状态定义；不将整流金额或月收入估计当作错分损失，也不将正常的摘要过滤认定为漏分。
- **定向扩查**：围绕发现的泛词、别名缺口、错误映射或覆盖机制，反扫相关规则在当日明细和可用完整交易中的命中、漏命中变体及反例，跨商户 / 流向评估共同根因。对 BSCAT 为空的交易（含 evolve 双方为空）按申请数 / 笔数聚合，优先看高影响模式；无引擎轨迹不能称“所有引擎未命中”，也不能把 catch_all 输出等同未分类。不做每条规则 × 每个流向的无差别穷举，不机械凑满 Top50；高价值线索完成一轮扩查，新增重要根因继续追查，无新增则停止，明确已查范围和剩余盲区。

### 3. 判定、定位与验证

- **判定**：结合原始 `text`、方向 / 金额、上下文与类别定义（模型 `CLAUDE.md` / `configs/category_catalog.json`）独立确定正确类别，区分 `BSCAT 对 / illion 对 / 都对 / 都错 / 需引擎状态 / 信息不足`。`counterparty`、`third_party` 及流摘要仅作辅助，并核实其是否为模型派生信息。账户归属、贷款流等证据不足时不凭文本定性。只有错分已证实、目标类别及方案明确的才进入变更清单，疑似高影响项放入“待补证据”。
- **影响**：按根因及明确匹配条件复算去重用户 / 申请、交易笔数，必要时补充绝对金额，并注明数据日期与交易期间。已证实错分量、规则候选命中量和样本代表量分别报告；只有验证同簇行为一致后才能计整簇。圈选样本内结论与总体影响分开，不将整个流向算作单条规则收益；多条建议有交集时去重或明确重叠，不累计相加。
- **排序**：高优先级为广泛影响收入、负债、风险等关键业务判断，或少量错分即可造成严重后果的问题；中优先级为影响较集中但修复价值明确的问题。说明业务后果及依据，未验证后果标为推测；结合紧迫性、预计收益、修改成本和误伤风险排序。低价值零散问题只汇总。

对值得处理的候选使用附表查找入口，追到具体规则和最终写入点：

- **配置排查**：核对 `merchant_kb.csv`、对应引擎规则及 `catch_all_rules.csv`，检查商户 / 别名 / 缩写 / 截断写法缺失，裸地点 / 人名 / 支付通道等泛词误命中，类别错配，以及重复关键词跨行分类冲突。发现问题后，在已核对版本中查全同类配置，不只修改首个样本命中的一行；每个拟改项仍须有样本或可复现的错误行为支持，不凭词形批量删除。
- **定位根因**：记录相对路径、`rule_name` / `merchant_name` / 函数名和当前值；列明相关命中行，按实际匹配及覆盖机制确定生效项，追到最终 `bscat` 写入点。核查最长匹配、重复关键词覆盖、variant 截断、缓存加载及引擎优先级；规则命中不等于最终分类生效。
- **明确改法**：优先改规则表。新增 CSV 行按实际表头写全；修改 / 删除列明精确字段值、pattern / token 和保留项；逻辑修改写清条件、输入与期望行为。核实规则是否已存在及 variant 上限（以代码为准）。全局配置、引擎顺序、跨类别覆盖或宽泛匹配改动标“高风险”，写明回退办法。
- **预验证**：按实际清洗、大小写、方向限制与匹配语义，用少量真实正例（覆盖主要写法）及易误伤反例验证前后变化，检查规则是否最终生效。仅在本仓库做独立匹配验证，不运行模型代码；无法复现流状态或覆盖链时写明限制，不宣称已通过端到端验证。`find_kb.py` 仅用于查词；历史固定样本不作为本次验收依据。

### 4. 输出可审核、可执行的清单

`change_list_YYYYMMDD.md` 只保留三部分：

1. **本次范围**：模型路径 / 版本、输入与分析日期、当日差异总量 / 剔除量、scope 范围量、入选流向量 / 比率和聚类代表量；附 10 类 P0 的差异量 / 流向入选率，无差异记“不适用”。简记 evolve 覆盖的去重申请 / 交易量、摘要关联情况、实际扩查范围及主要盲区。分母及统计口径只解释一次，不把筛查量写成已审核或已证实错分量。
2. **变更清单**：按优先级和优化价值排序，同一根因合并为一项，跨文件修改列在同项，依赖用条目 ID 表达。同类机制、同种修复方式的配置问题可附批量明细，不必一商户一项；不同根因不因修改同一文件而合并。没有值得修改的问题时如实说明。
3. **待补证据**：仅列疑似高影响问题、缺少什么及如何补齐；其余未展开问题只记总量。

每项按已核实的根因选择一个固定问题类型，不按修改文件或表面结果归类：

| 问题类型 | 适用情况                                                               |
| -------- | ---------------------------------------------------------------------- |
| 规则缺项 | 缺少对应商户、关键词或交易写法的识别规则，需要补充规则。               |
| 匹配偏差 | 已有规则的匹配范围过宽、过窄或清洗方式不一致，导致误命中或漏命中。     |
| 类别错配 | 识别对象正确，但规则表或映射表配置了错误的目标类别。                   |
| 流程冲突 | 规则本身正确，但被执行顺序、入口限制、优先级或后续覆盖阻断。           |
| 判定缺陷 | 账户归属、交易流、金额条件等业务判断逻辑错误或缺失，需要修改判断逻辑。 |

每项只选一个主类型；有多个独立根因则拆项，有关联原因则写入问题说明。根因未明确的放入“待补证据”。问题类型与优先级、风险分别记录，错分 / 漏分 / 误报在问题描述中说明。

每项先让审核人看懂问题，再提供 AI 可执行的精确修改；证据至少保留来源文件、数据日期和足以唯一定位的交易 / 运行标识。正文可引用样本编号，完整原文和批量修改明细放在同一清单对应条目下，避免来回查找。

```md
### CHG-001｜高 / 中｜<问题类型>｜<一句话说明问题>
> <当前分类 → 目标分类> · 已证实 <去重用户 / 申请数，交易笔数> · 证据 <样本编号>

- **问题**：<哪里分错 → 规则为什么没拦住 → 业务后果，2–3 句白话>
- **证据 / 影响**：<来源文件、sample_datetime、application_id、job_id、transaction_id，必要时加账户 / log / stream；原始 text、方向 / 金额、流上下文；计数条件与候选上限（如有）>
- **改法**：<模型相对路径 + 唯一定位标识>；操作 <新增 / 修改 / 删除>，`当前值` → `完整新行 / 精确字段值 / 明确函数行为`；<依赖条目 ID 或无>
- **验证 / 风险**：<已做的匹配验证及限制；正例应变成什么、反例保持什么；后续同批回放的验收条件；高风险项的误伤范围与回退办法>
- **审核**：`待审核`；<人工填写 已确认 / 暂缓 / 不采纳 及理由>
```

批量配置在对应条目的“改法”下逐行列明，操作固定为 `新增 / 修改 / 删除`：

| 文件 / 稳定定位标识                                 | 操作   | 当前值               | 修改后值 / 保留内容                    | 证据引用                    |
| --------------------------------------------------- | ------ | -------------------- | -------------------------------------- | --------------------------- |
| <路径 + merchant_name / rule_name + 必要的区分字段> | <操作> | <完整原值；新增写无> | <完整新行或精确字段值；删除写明保留项> | <该行对应样本 / 可复现行为> |

交付前逐项核对：证据能唯一定位，目标类别有依据，影响量能复算，修改位置和当前值能唯一匹配，操作完整且各条目不冲突，验收包含正反例。不得用“收紧、复核、视情况调整”等代替方案，不得用省略号或非引擎支持的通配符代替完整词条；样本必须真实，不能用截断文本作执行依据。当前值不符或关联证据不足时补查，不猜测。

## 二、人工审核：确认改什么

审核人核对问题、影响与方案，将状态设为 `已确认 / 暂缓 / 不采纳`；也可在对话中明确确认条目 ID，由 AI 据实记录。AI 不得自行确认。后续执行任务只处理已确认项，并复核模型版本、定位标识、当前值及依赖；不符时重新核实。本工作流到清单审核为止。

## 附：规则与最终写入点索引

路径相对于模型仓库，仅作定位入口，以确认版本的实际调用链为准。

| 类别                                   | 规则 / 配置入口                                                                                                       | 继续追踪                                                                                                                                      |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Wages / Centrelink                     | `income_engine/resources/income_pattern_rules.csv`、`income_engine/resources/income_config.csv`                   | `income_engine/domain/classification.py`、`income_engine/domain/summary.py`                                                                   |
| All Other Credits                      | `all_other_credit_engine/resources/all_other_credit_rules.csv`                                                      | `all_other_credit_engine/engine.py`                                                                                                         |
| SACC / Non SACC / Unknown Loans        | `liability_engine/resources/counterparty_keyword_rules.csv`                                                         | `liability_engine/domain/streams.py`：`SPECIAL_COUNTERPARTY_STREAM_RULES`、`apply_special_counterparty_stream_overrides`、`add_bscat` |
| Credit Card Repayments                 | `liability_engine/resources/credit_card_rules.csv`                                                                  | `liability_engine/domain/counterparty.py`：`apply_credit_card_rules`                                                                      |
| Debt Collection / Debt Consolidation   | `liability_engine/resources/debt_collection_rules.csv`、`liability_engine/resources/debt_consolidation_rules.csv` | `liability_engine/domain/counterparty.py`：`_apply_flag_rules` → `liability_engine/domain/streams.py`：`add_bscat`                   |
| Overdrawn                              | `liability_engine/resources/overdrawn_rules.csv`、`fee_engine/resources/fee_classification_rules.csv`             | `liability_engine/domain/counterparty.py` → `add_bscat`；`fee_engine/domain/classification.py`                                         |
| Rent                                   | `rent_engine/resources/rent_rules.csv`                                                                              | `rent_engine/engine.py`、`classification_core/orchestrator.py`                                                                            |
| Gambling                               | `gambling_engine/resources/gambling_rules.csv`                                                                      | `gambling_engine/engine.py`                                                                                                                 |
| Internal Transfer / External Transfers | `transfer_engine/resources/transfer_*.csv`                                                                          | `transfer_engine/domain/classification.py`、`classification_core/service.py`                                                              |
| Dishonours                             | `dishonour_engine/resources/dishonour_rules.csv`                                                                    | `dishonour_engine/engine.py`                                                                                                                |
| Fees                                   | `fee_engine/resources/fee_classification_rules.csv`                                                                 | `fee_engine/domain/classification.py`                                                                                                       |
| 其余消费类                             | `initial_engine/merchant_kb.csv`、`catch_all_engine/resources/catch_all_rules.csv`                                | `initial_engine/domain/classification.py`、`catch_all_engine/engine.py`                                                                   |
| 负债流摘要 / 二级类别映射               | `liability_engine/domain/summary.py`、`liability_engine/domain/streams.py`                                       | 核对汇总过滤、状态与金额口径，以及二级类别与 BSCAT 的映射                                                                                       |
| 引擎顺序 / 覆盖关系                    | `configs/pipeline.json`                                                                                             | `classification_core/orchestrator.py`                                                                                                       |
