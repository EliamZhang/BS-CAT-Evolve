# BSCAT 分类优化工作流

**目标**：发现影响范围广、业务后果严重的 BSCAT 分类问题，生成 `output/change_list_YYYYMMDD.md`，供运维审核、供 AI 执行。

**命名**：日期取生成当天的北京时间（Asia/Shanghai）；同日重复生成依次追加 `_02`、`_03`，不覆盖已有清单。

**原则**：修正 BSCAT，不以对齐 illion 为目标；差异、规则命中和引擎摘要都不等于正确答案。只保留值得处理的问题，不凑数量。本工作流只分析和出清单，不修改模型代码。

**读者**：清单同时给运维同学和后续改代码的 AI 看。运维能直接看懂问题、影响和要做什么；AI 能按“文件 + 当前值 → 新值”直接修改。用大白话、短句，英文术语首次出现加中文解释，同一信息只写一次。

## 一、AI 分析

### 1. 核对输入与口径

先检查 `input/` 各文件的表头、日期、行数与关联字段；缺文件时继续可完成的分析，并记入“还没查清的问题”。

| 文件 | 用途 | 注意 |
| --- | --- | --- |
| `bscat_monitor_*.html` | 读取类别指标，确定 `dataDate` 和筛查范围 | 用 `dataDate`，不用文件生成时间；空告警不代表无问题 |
| `risk_*_dash_detail.csv` | 全部差异交易，用于聚类、计数和取证 | 不含双方同类 / 双方都未分类；`排查类型` 只是差异标签 |
| `risk_*_evolve_selection.csv` | 圈选的高差异类别和申请 | 不保证覆盖全部必看类别；同一申请可重复入选 |
| `risk_*_evolve_transactions.csv` | 圈选申请的完整交易上下文 | 只是圈选申请，不能外推总体错分率 |
| `risk_*_log_income_summary.csv`、`log_liability_summary.csv` | 收入 / 负债摘要，辅助判断业务影响 | 是模型输出，不是真值；缺行、空金额不等于错分 |
| `risk_*_dash_summary.csv` | 核对差异总量和构成 | 一致率 / 覆盖率不等于准确率 |

- **日期与版本**：默认取 monitor 的 `dataDate`；明细按 `sample_datetime` 取同日，`transaction_date` 只作交易日期。记录模型仓库、分支 / 版本和未提交改动；定位和当前值以工作区为准，有未提交改动时在清单注明。已排除项从模型仓库 `CHANGELOG.md`（没有就跳过）中 `dataDate` 前后 7 天的条目和 `git log -n 20 --oneline` 里找，逐条在当前工作区确认修复已生效；确认不了的写“还没查清的问题”，不直接排除。
- **关联与去重**：差异方向为 `illion → BSCAT`。交易按同日的 `application_id + job_id + bank_account_id + transaction_id` 关联；摘要另加 `log_id + stream_id`。用户按 `user_id`、申请按 `application_id` 去重；键不唯一或缺失时记录冲突和未关联量，不凭 `stream_id` 或申请号硬拼。
- **计数**：先核对明细行数与 summary 的差异总数，再排除空、零、非数值金额；对不上先查日期、导出缺失或重复。同笔交易在明细和 evolve 中只算一次。
- **读取**：CSV 用 `csv` 流式或分块读取，只为候选建索引；旧 `output/` 只作线索，每次重算。

### 2. 筛查候选

**范围**：以下 13 个必看类别全部纳入（看板 P0 的 10 类 + Dishonours、Gambling、Rent）；其余类别从 monitor 的 `DATA.categories[]` 中分别取 `coverage_gap` 最低、`diff_count` 最大、`iou_rate` 最低的前 5 类，已在这 13 类中的跳过，缺失指标跳过，指标并列按类别名升序；三组结果合并去重。

`Wages、Centrelink、All Other Credits、SACC Loans、Non SACC Loans、Unknown Loans、Credit Card Repayments、Debt Collection、Debt Consolidation、Overdrawn、Dishonours、Gambling、Rent`

先建目录 `mkdir -p _tmp/<分析日期>`，运行 `python scripts/parse_monitor.py <monitor> _tmp/<分析日期>/scope.json`，再运行 `python scripts/aggregate_clusters.py <明细> _tmp/<分析日期>/scope.json _tmp/<分析日期>`；临时目录每次覆盖重建。脚本按 `dataDate` 筛选，排除空 / 零 / 非数值金额，取任一端在 scope 的交易；流向按笔数从高到低累计到 90%，笔数并列按流向名升序，再为每个必看类别补足到 90%。输出 `flow_summary.csv`、`clusters_top.csv`、`run_stats.json`，覆盖率和候选计数以 `run_stats.json` 为准。90% 只是流向覆盖率，不是准确率；必看类别无差异写“不适用”。

- **看聚类**：每个入选流向按笔数取 Top10 聚类（笔数并列按标准化文本升序）；聚类按方向及归一化 `(counterparty, text)` 分组。原始文本才是证据，不能用代表样本推断整簇。
- **补上下文**：对高差异申请看 evolve 完整交易，覆盖差异、双方同类、双方未分类三种情况。优先查转账 / 退款 / 贷款入账被当工资、还款与消费混淆、催收 / 透支漏报、泛词误命中；结合方向、账户归属和前后交易判断。
- **核摘要**：把候选关联到同次运行的收入 / 负债摘要，检查类型、周期、状态、金额是否有交易依据；缺上下文或无法核实的列入“还没查清的问题”。
- **定向扩查**：围绕已确认根因的泛词、别名缺口、错误映射，反扫当日明细和完整交易里的命中、漏命中变体和反例，按申请数 / 笔数聚合。每个根因只反扫一轮，不做全量穷举；一轮后没有新根因就停止，并写明已查范围和剩余盲区。

### 3. 判定、定位与验证

- **判定**：按类别定义（模型 `CLAUDE.md` / `configs/category_catalog.json`）→ 方向 / 金额 → 完整上下文的顺序判断正确类别，区分“BSCAT 对 / illion 对 / 都对 / 都错 / 需引擎状态 / 信息不足”。账户归属、贷款流证据不足时不凭文本定性；只有错分已证实、方案明确的才进清单。
- **影响**：笔数 = 去重后 `(application_id, transaction_id)` 行数；申请数 = 唯一 `application_id` 数；金额 = 去重后 `abs(amount)` 合计，保留 2 位小数；注明数据日期和交易期间。候选命中量、样本量和已证实错分量分开写，不把整个流向算成一条规则的收益；多条建议有交集时去重。
- **排序与门槛**：影响 13 个必看类别的为高优先级，其余为中优先级；同优先级按影响笔数从高到低，再按类别名升序。只有确认错分 ≥100 笔或 ≥10 个申请（或金额 ≥10 万澳元）的才进清单；低于门槛的只汇总。

对候选追到具体规则和最终写入点：

- **查配置**：核对 `merchant_kb.csv`、对应引擎规则和 `catch_all_rules.csv`，检查商户 / 别名 / 缩写 / 截断写法缺失、泛词误命中、类别错配、重复关键词冲突。同类问题在同一条规则文件的同一字段内一次查全；每个改动都要有样本或可复现的错误行为。
- **定位**：记录相对路径、`rule_name` / `merchant_name` / 函数名和当前值，按实际匹配和覆盖顺序追到最终 `bscat` 写入点。规则命中不等于最终生效。
- **改法**：优先改规则表。新增按实际表头写全；修改 / 删除写精确字段值；逻辑修改写清条件、输入和期望行为。全局配置、引擎顺序、跨类别覆盖标“高风险”，写回退办法。
- **预验证**：按实际清洗、大小写、方向和匹配语义，用真实正例和易误伤反例验证前后变化；正例覆盖每个新增 / 修改的词条，同一词条取 `transaction_id` 最小的一条；反例取 1 条同前缀但不该命中的交易。只在本仓库独立匹配，不运行模型代码；无法复现覆盖链时写明限制，不宣称端到端通过。

### 4. 输出可审核、可执行的清单

`change_list_YYYYMMDD.md` 固定三部分，面向没有模型背景的运维同学，同时可直接交给 AI 改代码：

1. **这次查了什么**：固定 5 项 + 1 张表，正文不超过 20 行（不含空行，含表格）；只写数据、模型、范围、口径、已排除项，不展开分析过程、聚类样本和已修复项明细。占比 = 检查笔数 ÷ 当天全部差异行数。必看类别表固定 13 行、只保留“类别 / 差异交易数”两列，类别名加中文解释；按 `dataDate`、金额有效、流向任一端等于该类别计数，同一行可同时计入两端；无差异写“不适用”。

```md
## 一、这次查了什么
- 数据：<明细文件>，交易日期 <dataDate>；分析日期 <当天>。
- 模型：<路径>，<分支>，版本 <HEAD>；只读，没有改代码。
- 范围：13 个必看类别 + <N> 个补充类别，共检查 <N> 笔差异交易（当天 <N> 笔的 <N>%）；其余 <N> 笔不在范围或金额为零。
- 方法/口径：“差异”指 BSCAT 和 illion 分类不一致的交易（illion 是对比用的外部分类结果）；按交易文本分组检查，主要模式覆盖 <N>%。上方范围与必看类别表是差异明细行数；建议修改里的影响数量按 <去重键> 去重，是可能受影响的数量，不是已确认的错误数。
- 已排除：模型仓库已经修好、当前版本已生效的问题（<提交号> 等），没有重复列。

| 必看类别 | 差异交易数 |
|---|---:|
| <类别（中文解释）> | <N> |
```

2. **建议修改**：开头用一张汇总表列出编号、一句话问题、影响和优先级，让运维先知道要改什么；下面每项按固定模板展开。高优先级在前，同优先级按影响笔数从高到低，编号按此顺序连续编。跨文件修改列在同项，依赖用条目 ID 表达。同类配置问题合并处理，不同根因不因改同一文件而合并。没有需要修改的问题时如实说明。
3. **还没查清的问题**：用大白话写，不写模型术语和推导。按可能影响笔数从大到小，最多 10 条；整体盲区固定放最后一条。每条固定“问题（附 2–3 个原文例子）/ 为什么 / 缺什么 / 建议的修改方案”四段，不能只写“需要更多信息”；修改方案写到具体文件、规则或数据，1–3 步能直接执行，配置类贴完整行。

同一根因合并为一项，多个独立根因拆项；根因未明确的放入“还没查清的问题”。

每项先让运维看懂问题，再给出 AI 可执行的精确修改。来源文件和日期在“这次查了什么”统一写一次；每项在“影响”写数量，在“怎么验证”写样本编号，不重复完整原文和计数推导。问题里附 2–3 个原文例子，同一文本模式取 `transaction_id` 最小的一条；涉及业务归属不确定时，在“注意”里写清需要谁确认。

```md
### CHG-001｜高｜<一句话问题>
> 现在：<现状> → 应该：<目标>

- **问题**：<1–2 句大白话，说明哪里错、系统为什么没认出来；附 2–3 个原文例子>
- **影响**：<N 笔 / N 个申请 / 约 N 澳元；一句话业务后果>
- **怎么改**：`<文件路径>`。分步骤写清定位（行号 / rule_name / 当前值）和完整新值；代码或 CSV 直接贴出，供 AI 复制执行。
- **怎么验证**：改完后重新跑同一天数据：<样本 ID> 应变成 <目标类别>；<反例> 应保持 <原类别>；不对时回退 <具体做法>。
- **注意**：<需要业务确认的归属问题、误伤范围；没有写“无”。>
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。
```

配置类修改直接在“怎么改”里贴完整 CSV 行代码块，新增多行时逐行贴全，不拆表、不省略。修改已有行时，成对写“现在”和“改成”的完整行：

```csv
# 新增：直接贴要追加的完整行
<完整新行 1>
<完整新行 2>

# 修改：先贴原行，再贴新行
现在：
<完整原行>

改成：
<完整新行>
```

每行对应的样本在“怎么验证”里列出。

交付前逐项核对：文件路径和当前值能在模型仓库唯一找到；新值能直接复制执行；验证样本真实存在；正例、反例和回退办法齐全；所有数字能按本工作流复算；运维不查代码也能看懂问题、影响和要做什么。不得用“收紧、复核、视情况调整”等模糊说法，不得用省略号或非引擎支持的通配符代替完整词条；样本必须真实，不能用截断文本作执行依据。当前值不符或关联证据不足时补查，不猜测。

## 二、人工审核：确认改什么

审核人（运维同学）核对问题、影响与方案，将状态设为 `已确认 / 暂缓 / 不采纳`；也可在对话中明确确认条目 ID，由 AI 据实记录。AI 不得自行确认。后续执行任务只处理已确认项，并复核模型版本、定位标识、当前值及依赖；不符时重新核实。本工作流到清单审核为止。

## 附：规则与最终写入点索引

路径相对于模型仓库，仅作定位入口，以确认版本的实际调用链为准。

| 类别 | 规则 / 配置入口 | 继续追踪 |
| --- | --- | --- |
| Wages / Centrelink | `income_engine/resources/income_pattern_rules.csv`、`income_engine/resources/income_config.csv` | `income_engine/domain/classification.py`、`income_engine/domain/summary.py` |
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
| 负债流摘要 / 二级类别映射 | `liability_engine/domain/summary.py`、`liability_engine/domain/streams.py` | 核对汇总过滤、状态与金额口径，以及二级类别与 BSCAT 的映射 |
| 引擎顺序 / 覆盖关系 | `configs/pipeline.json` | `classification_core/orchestrator.py` |
