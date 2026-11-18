# BSCAT Liability 分流检查工作流

**目标**：检查当前 Liability Engine 的贷款流分流是否正确，判断是否需要调整。只输出能用数据证明、值得改的问题；没有就写“暂不需要调整”。

**边界**：
- 只查负债分流：贷款机构识别、借款 / 还款归属、并流 / 拆流。消费分类问题交给 `WORKFLOW_CLASSIFICATION.md`。
- 摘要自洽不等于分流正确；illion 和分类差异都不是分流真值。
- 只读模型仓库，不改代码、不跑模型批次。

## 一、输入与口径

| 文件 | 用途 | 限制 |
| --- | --- | --- |
| `input/risk_000008_log_liability_summary.csv` | 核心检查对象；每行是一次运行的一条贷款流 | 无 `bank_account_id` / `counterparty` / `bscat`；覆盖多个 `sample_datetime` |
| `input/risk_000008_evolve_transactions.csv` | 原始流水；唯一能逐笔核对流成员和机构名的数据 | 只覆盖圈选申请、单个 `sample_datetime`（当前 2026-11-16）；不能外推 |
| `input/risk_000008_dash_detail.csv` | finv 与 illion 的分类差异 | 无 `stream_id`，只作线索 |
| `../AUS_BS_CAT_Model` | 引擎代码与规则 | 只读；记录分支、HEAD、未提交改动 |

先读三个事实并记录：

1. 摘要的运行日列表、申请数、流数；流水的运行日、申请数。逐笔核对只在“两边都有”的申请上做（当前：摘要 7 个运行日 / 8,103 个申请；流水 1 个运行日 / 93 个申请，交集 87 个）。
2. 关联键：摘要与流水按 `application_id + stream_id` 关联；只取 `loan_*` 负债流，`wage_*` / `centrelink_*` 是收入流，不参与。
3. 同一申请同一天可能有多条 `log_id`（当前 1,263 个申请日如此），比较流集合必须带 `job_id + log_id`，不能只按申请去重。

**版本**：当前两份输入的流号都是 `loan_NNN`；模型仓库（分支 `operation`，HEAD `850fac5`）按 `{liability_category}_NNN` 编号（如 `personal_loan_sacc_001`）。输出流号对不上，说明不是当前代码产出；旧版问题不能直接当作当前代码要改，已在当前代码修复的不列入。

## 二、执行步骤

### 1. 圈定范围

1. 摘要取流水覆盖的 `sample_datetime`（当前 2026-11-16），与流水按 `application_id + stream_id` 取交集，得到可逐笔核对的申请和负债流。
2. 摘要其余日期和申请没有流水，只做结构筛查（同申请同类流数量、状态与金额是否矛盾），用于估算影响面，不写成问题。

### 2. 逐流核对（交集内每条 `loan_*` 流）

| # | 检查 | 判定 |
| --- | --- | --- |
| 1 | 机构被合并 | 同一流内出现 ≥ 2 个不同 `counterparty`；或 `counterparty` 相同但原文含 ≥ 2 个明显不同的机构名（别名错误合并） |
| 2 | 同机构被拆 | 同一申请、同一 `counterparty`（个人贷款之外的产品再加同一 `bank_account_id`）的借还款落在 ≥ 2 条流，且日期区间重叠 |
| 3 | 借还款分离 | 同一机构的借款入账（credit）与还款（debit）分属不同流，日期和金额能对上（借款至少早 3 天，同日同额 credit 合并为一笔）；或借款已识别但没参与任何还款流的配对 |
| 4 | 流与摘要不符 | 摘要流在流水中找不到交易；流水中的 `loan_*` 流不在摘要；摘要 `liability_category` 与流内 `bscat` 不符合映射。映射：`credit_card_repayment→Credit Card Repayments`、`personal_loan_sacc→SACC Loans`、`personal_loan_unknown→Unknown Loans`、其余产品→Non SACC Loans。`Dishonours / Overdrawn / Debt Collection / Debt Consolidation` 行允许出现在任意负债流 |
| 5 | 误分流 | 流内交易原文看不出贷款迹象（无机构名、无 LOAN / FINANCE / CREDIT 类词），更像普通转账或消费；需结合前后交易确认，不凭单笔定性 |

- 每条命中都回到原文取证：`transaction_id`、日期、方向、金额、`text`、`counterparty`。
- 配对不要求借款与还款金额相等；判断依据是机构一致、日期先后、金额合理。

### 3. 只对确认的问题定位原因

- 规则表：`liability_engine/resources/counterparty_keyword_rules.csv`、`credit_card_rules.csv` 等；查机构关键词缺失、裸词误命中、规则先后覆盖。
- 规则链：`liability_engine/pipeline.py` → `counterparty.py` → `special_rules.py`；查产品类型判断顺序（房贷 / 车贷先于信用卡）、特殊覆盖。
- 流识别：`liability_engine/domain/streams.py`；查产品规则顺序、个人贷款聚类（金额容差 5%、借款匹配）、unknown 细化、zip money / credit corp 覆盖。
- 每个问题记录：文件 + 函数 / 规则 + 当前值。定位不到原因的不写进建议。

### 4. 判定是否需要调整

- **需要调整**：同一根因影响 ≥ 3 个申请或 ≥ 10 条流，且改法明确；或单笔归属错误金额 ≥ 1 万澳元。
- **暂不需要调整**：候选都是个案、无法复现，或属于旧版本已修复。
- 低于门槛的只在结论里一句话带过，不逐条展开。

## 三、输出

写入 `output/liability_stream_check_YYYYMMDD.md`（同日重复加 `_02`），同时在对话里给出结论。只写两块：

```md
## 结论
需要调整：<一句话> / 暂不需要调整：<一句话>。

## 问题
### LIAB-001｜<一句话问题>
- **问题**：哪里分错了。
- **证据**：`<文件>`；application_id / stream_id / transaction_id / 原文。
- **影响**：<N 个申请 / N 条流；全量同模式约 N 个申请日>。
- **建议**：`<文件>` + 规则 / 函数；`当前值` → `新值`。
```

- 最多 5 条，按影响从大到小；同一根因合并一条。
- 证据必须能直接从 `input/` 复现，不用截断文本。
- 写不出具体改法的不列为问题。
- 没发现问题就只写结论，并写明核对范围和盲区（多少申请没有流水可核）。

## 四、停止条件

- 交集内 `loan_*` 流全部核完；每个候选要么定性，要么写明缺什么证据。
- 不为凑数扩大范围；不审摘要状态 / 周期 / 预测日公式，除非它直接导致借还款归属错误。

## 附：代码入口

| 主题 | 入口 |
| --- | --- |
| 规则表 | `liability_engine/resources/counterparty_keyword_rules.csv`、`credit_card_rules.csv`、`debt_collection_rules.csv`、`debt_consolidation_rules.csv`、`overdrawn_rules.csv` |
| 规则链 | `liability_engine/pipeline.py`、`liability_engine/domain/counterparty.py`、`liability_engine/domain/special_rules.py` |
| 流识别与编号 | `liability_engine/domain/streams.py`：`PRODUCT_RULES`、`assign_personal_loan_rule`、`refine_unknown_personal_loan_streams`、`merge_sacc_streams_into_loc`、`apply_special_counterparty_stream_overrides`、`renumber_stream_ids_uniform` |
| 摘要 | `liability_engine/domain/summary.py`、`liability_engine/engine.py` |
