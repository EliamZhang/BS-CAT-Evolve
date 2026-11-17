# BSCAT 分流审计工作流

**目标**：检查 BSCAT 的交易分流是否正确，重点验证借款流、还款流、收入流的归属、拆分、编号及 `risk_*_log_income_summary.csv` / `risk_*_log_liability_summary.csv` 的口径，产出可审核、可执行的 `output/stream_change_list_YYYYMMDD.md`。

**边界**：只审计分流，不优化普通消费分类。只读 `AUS_BS_CAT_Model`，不修改代码、配置、基线，不运行模型批次；需要在模型侧执行的验证由修复执行人按第七节完成。分类问题移交 `WORKFLOW_CLASSIFICATION.md`。摘要、交易分类和 illion 均不是独立真值，摘要自洽不等于分流正确。

**命名**：日期取生成当天的北京时间（Asia/Shanghai）；同日重复生成依次追加 `_02`、`_03`，不覆盖已有清单。

**与分类工作流的分工**

| 事项 | `WORKFLOW_CLASSIFICATION.md` | 本工作流 |
| --- | --- | --- |
| 消费分类、规则命中、BSCAT 差异 | 负责 | 仅作上下文 |
| 收入流 / 负债流归属、并流、拆流、借贷配对、流号 | 仅引用摘要提示 | 负责 |
| 摘要结构、金额、状态、周期、预测日期 | 不展开 | 负责 |
| 业务影响与优先级 | 负责 | 提供流级影响，不重复分类判断 |

## 一、分流模型

| 流 | 业务含义 | 归属键（以产出代码为准） | 流号 |
| --- | --- | --- | --- |
| 收入流 | 同一账户、同一收入类型、同一付款方的连续收入 | `bank_account_id + income_type_pred + counterparty` | `wage_NNN`（工资类）或 `centrelink_NNN` |
| 分组负债流 | 同一账户、同一对手方、同一产品的借款 / 还款 | `application_id + bank_account_id + counterparty + product_type` | `{liability_category}_NNN`（现行） |
| 个人贷款流 | 同一对手方下、同一还款金额簇的借款 / 还款 | `application_id + counterparty + 金额簇` | `sacc_NNN` / `non_sacc_NNN` / `unknown_NNN` |
| 通用贷款兜底流 | 文本仅含 `LOAN`、无更具体产品的贷款 | 每申请一条 | `generic_loan_NNN` |

- **借款流**是贷款入账（credit），**还款流**是借记（debit）；同一笔贷款的两侧应在同一 stream 内配对。
- 一个摘要 stream 必须只对应一个账户、一个对手方、一个产品 / 收入类型；个人贷款允许跨账户，通用贷款兜底按申请聚合。
- 摘要由各引擎在提交后立即生成，是**引擎时点快照**，不是最终输出；后续引擎可能覆盖行级 `bscat` / `stream_id`，造成摘要与最终交易不一致。
- 流号按申请在批次内统一编号，单次运行只包含其中一部分；关联时必须同时带运行键，不得跨申请或跨批次比较流号。

## 二、输入、范围与版本门槛

| 输入 | 用途 | 边界 |
| --- | --- | --- |
| `risk_*_log_income_summary.csv` | 收入流结构、金额、状态、周期、预测日期 | 全量摘要，不是抽样；无 `bscat` / `bank_account_id` / `counterparty` |
| `risk_*_log_liability_summary.csv` | 负债流结构、放款 / 还款、状态、周期、预测关闭日 | 全量摘要；无 `bscat` / `bank_account_id` / `counterparty` |
| `risk_*_evolve_transactions.csv` | 圈选申请的完整交易，用于流成分、借贷配对、摘要对账 | 只覆盖圈选申请，不能外推总体 |
| `AUS_BS_CAT_Model` | 分流代码、规则、阈值、摘要 builder | 只读；记录分支、提交和未提交改动 |
| `risk_*_dash_detail.csv` | 分类差异线索 | 只作分类上下文，不作分流真值 |

- **运行键**：`user_id + application_id + job_id + log_id + sample_datetime`；摘要流键再加 `stream_id`。先验证键唯一，再关联；不得只用 `application_id` 或空 `stream_id` 拼接。
- **覆盖范围**：摘要为全量，`evolve_transactions` 只覆盖部分运行。凡需要逐笔交易的检查（C2、C4、C5、D1–D6），只对“覆盖运行”执行并单独报告；摘要自身可完成的检查（S、A、C1、C3、C6）对全量执行。
- **批次范围**：一次审计只取同一 `sample_datetime` 批次；多个日期分开计算，不得合并 `global_last_date`、流号范围或覆盖率。
- **版本门槛**：先执行 V1–V4，再判失败。
  - V1：记录 `git -C <MODEL> rev-parse HEAD`、分支、`git status --porcelain`。
  - V2：记录输出指纹：收入流号前缀集合、负债流号前缀集合、摘要表头、`sample_datetime` 范围。
  - V3：现行代码（2026-11-13 起）负债流号前缀等于 `liability_category`；输出若为 `loan_NNN`，说明由旧版本产出。
  - V4：输出与当前代码版本不一致时，S2、S3、A5–A9、D6 只能按产出代码判定；无法定位产出提交的，标记“需版本确认”，不得把口径差异写成代码缺陷。S1、A1–A4、C、D1–D5、D7 以及代码审计仍可执行，但代码结论只代表当前版本。

## 三、执行顺序

1. V1–V4，建立运行索引和覆盖范围。
2. S1–S6 结构检查。
3. A1–A9 公式与状态检查。
4. C1–C6 完整性与对账。
5. D1–D7 流成分检查（仅覆盖运行）。
6. E、L、R、I、T 代码与配置审计。
7. 判定根因、优先级，生成清单。
8. 按第七节验证并给出验收条件。

每项检查只记录 `通过 / 失败 / 不适用 / 需版本确认` 四种结果；失败必须给出数量、口径和最多 5 个可唯一定位的样本。

## 四、输出核验

### 4.1 结构与格式

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| S1 | 摘要主键唯一 | 两份摘要按 `user_id + application_id + job_id + log_id + sample_datetime + stream_id` 均无重复；重复即失败，不先去重再统计 |
| S2 | 流号格式与类别一致 | 收入前缀为 `wage` 或 `centrelink`；负债前缀等于 `liability_category`（现行格式）。旧 `loan_NNN` 只按版本门槛处理 |
| S3 | 流号连续 | 按申请在该批次全部运行内连续：收入为 `(application_id, label)` 的 `001..N`（label 为 `wage` 或 `centrelink`）；现行负债为 `(application_id, liability_category)`；旧 `loan_NNN` 按 `(application_id)`。单次运行可只含子集，不得要求每次运行从 001 开始；无缺号、重号、跨类别复用 |
| S4 | 日期关系 | `transaction_start_date <= transaction_end_date`；收入 `predicted_next_income_date > transaction_end_date`；负债 `predicted_closing_date >= transaction_end_date`（非空时） |
| S5 | 金额非负 | `funded_amount`、`repaid_amount`、`repayment_amount`、`recent_fn_repay_amount`、收入四项金额及 `estimated_monthly_income` 均为空或非负；空值不等同 0 |
| S6 | 枚举合法 | 收入状态属于代码枚举（至少 `single_transaction / irregular / active / inactive / unknown`），负债状态属于 `Ongoing / Closing Soon / Closed`；出现空值或未知枚举即失败 |

### 4.2 金额、状态与周期

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| A1 | 收入合计 | `total_income_amount ≈ average_income_amount × transaction_count`，绝对误差 ≤ 0.02 |
| A2 | 月收入估算 | 周期为 `weekly / fortnightly / monthly` 时，`estimated_monthly_income` 分别等于 `median × 52/12`、`median × 26/12`、`median`；其余周期必须为空；误差 ≤ 0.02 |
| A3 | 收入状态 | `transaction_count = 1` → `single_transaction`；周期为 regular 且笔数 > 1 → `active / inactive`；周期为 `irregular / one_off` 且笔数 > 1 → `irregular`。`global_last_date` 取本次输入全部收入摘要 `transaction_end_date` 的最大值；`allowed = round(typical_gap × 1.75)`，`days_since_last <= allowed` 为 `active` |
| A4 | 下次收入日期 | 仅当笔数 ≥ 2 且周期 regular 时非空，且等于 `transaction_end_date + typical_gap`（weekly 7、fortnightly 14、monthly 30）；其余必须为空 |
| A5 | 负债状态（有放款） | `funded_amount > 0` 时：`repaid <= 0.75 × funded` → `Ongoing`；`<= 1.25 × funded` → `Closing Soon`；否则 `Closed`。边界取等号，金额误差 ≤ 0.02 |
| A6 | 负债状态（无放款） | 非 BNPL：`transaction_end_date >= sample_datetime - 33 天` → `Ongoing`，否则 `Closed`。BNPL：`funded_amount` 必须为 0；先全部 `Closed`，仅每个 `(application_id, counterparty)` 中 `transaction_end_date` 最晚且距 `sample_datetime` ≤ 33 天的一条改为 `Ongoing`。旧输出版本不适用时标记“需版本确认” |
| A7 | 负债周期 | BNPL 必须为 `fortnightly`；`repaid_amount = 0` 必须为 `fortnightly`；其余在覆盖运行按成功还款日期间隔升序取中间位（偶数取上中位），单笔还款按 `fortnightly`；`<= 9` 为 `weekly`、`<= 18` 为 `fortnightly`、否则 `monthly`；失败还款不参与 |
| A8 | 还款金额字段 | `Closed` 必须为空；非 Closed 且 `repaid_amount > 0` 时 `repayment_amount` 非空。例外：`wage_advance` 最后一条非拒付交易为 credit 时可为空；BNPL 非 Closed 取还款金额众数，`recent_fn_repay_amount = min(众数, 限额)`；标准产品 `recent_fn` 按周期换算（monthly ×12/26、weekly ×2、fortnightly ×1）；`wage_advance` 按最近一笔放款的 5% 且受已还金额约束 |
| A9 | SACC 预测关闭日 | 仅 `liability_category = personal_loan_sacc`、非 Closed、`repayment_amount > 0` 时非空：`remaining = round(round(funded × 1.25, 2) - repaid, 2)`；`n = max(0, ceil(remaining / repayment_amount))`；`freq_days` 为 weekly 7、fortnightly 14、monthly 31；日期等于 `transaction_end_date + n × freq_days`。其余必须为空 |

### 4.3 完整性与对账

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| C1 | 摘要流号非空 | 两份摘要所有行 `stream_id` 非空且符合 S2 格式；空流号行单独计数 |
| C2 | 摘要流在交易中存在 | 覆盖运行内，每个摘要流键必须能在 `evolve_transactions` 找到至少一条同流交易；找不到的为孤儿流 |
| C3 | 应分流交易必须有流号 | 最终 `bscat` 属于 `Wages、Centrelink、SACC Loans、Non SACC Loans、Unknown Loans、Credit Card Repayments` 且非 `Dishonours` 的交易，`stream_id` 必须非空；空流号按申请、类别、笔数聚合 |
| C4 | 摘要与最终输出一致 | 覆盖运行内，摘要流的成员交易最终 `bscat` 必须等于摘要类别按 D7 映射出的 BSCAT，或属于该流的合法旗标 `{Overdrawn, Debt Collection, Debt Consolidation, Dishonours}`（仅负债）；出现其他 BSCAT、流号被清空或成员被移出原流即失败 |
| C5 | 金额对账 | 收入：`total_income_amount` 等于流内全部 credit 金额绝对值之和。负债：`funded_amount` 等于排除拒付后的有效 credit 绝对值之和；`repaid_amount` 等于成功 debit 绝对值之和，且“下一笔流内交易为 dishonour”的 debit 必须排除。输出中拒付行可能无流号，先按同账户、同对手方、日期相邻把拒付回填到前序 debit 所在流再计算。误差 ≤ 0.02；不一致先判定是引擎后续覆盖（C4 同时失败）还是 builder 计算 |
| C6 | 覆盖运行摘要缺失 | 覆盖运行若存在 C3 所列 BSCAT 交易，必须有对应收入或负债摘要；有路由交易但整类摘要缺失即失败；`Dishonours` 不单独要求摘要 |

### 4.4 流成分（D1–D5 仅覆盖运行；D6、D7 可对全量摘要执行，不可见流仍需交易确认）

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| D1 | 收入流成分 | 同一收入 stream 只能有一个 `bank_account_id`、一个 `counterparty`，且 `income_category` 与摘要一致；出现多账户或多付款方即并流失败 |
| D2 | 分组负债流成分 | 同一负债 stream 只能有一个 `bank_account_id`、一个 `counterparty`，且摘要类别唯一、成员 BSCAT 符合 C4。例外：个人贷款允许跨账户；`generic_loan` 每申请一条；特殊覆盖后的流按覆盖后对手方判断 |
| D3 | 借款 / 还款配对 | 个人贷款每个有还款的流，必须匹配到一笔交易日期至少早 3 天的未匹配 funding flow（同日同额 credit 合并为一笔），有多笔时取最近一笔；不要求 funding 金额等于还款金额。匹配到 funding 的流按其金额 ≤ 2000 为 SACC、> 2000 为 non-SACC；无 funding → `unknown`；未被任何还款流匹配的 funding 单独成流。有可用 funding 却落入 `unknown`（排除已被更早还款流匹配的情况），或有金额 / 日期 / 对手方证据表明同一贷款的 funding 与还款被拆到不同流，为失败 |
| D4 | 并流 / 拆流 | 同一 stream 内若存在两组各 ≥ 3 笔、金额相差 > 10% 的稳定还款，怀疑过并；同一 `(application_id, counterparty)` 下若两条流的还款金额中位数差 ≤ 5% 且日期区间重叠，怀疑过拆。两者都需回到原始交易确认，不能只凭统计判错 |
| D5 | 拒付处理 | `is_dishonours = yes` 的交易不得进入摘要；其下一笔流内交易为 dishonour 的 debit 不得计入 `repaid_amount`；仅由拒付构成、无可见交易的流必须清空流号且不占号，属于可见流的拒付行可保留流号。违反即失败 |
| D6 | 流号顺序 | 编号顺序按申请跨全部运行核对：同一 `(application_id, category / label)` 内（旧 `loan_NNN` 按 `(application_id)`），按各流最早交易日期升序编号，`k` 号流的最早日期不得晚于 `k+1` 号流；仅拒付或仅赌博的不可见流不占号，需用覆盖运行交易确认 |
| D7 | 类别映射 | 负债：产品类型 `bank`（摘要类别 `credit_card_repayment`）→ `Credit Card Repayments`；`bnpl / wage_advance / personal_loan_non_sacc / contract_loan / generic_loan / loc / home_loan / car_loan → Non SACC Loans`；`personal_loan_sacc → SACC Loans`；`personal_loan_unknown → Unknown Loans`。收入：工资类 → `Wages`，`centrelink → Centrelink` |

## 五、代码与配置审计

### 5.1 引擎顺序与覆盖

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| E1 | 引擎顺序 | `configs/pipeline.json` 的实际 priority 顺序为 transfer(1) → initial(10) → dishonour(150) → gambling(180) → income(200) → liability(300) → all_other_credit(400) → fee(500) → rent(800) → catch_all(999)；不得按 JSON 数组顺序推断 |
| E2 | 候选保护 | 逐项核对：liability 候选排除输出 `Wages / Centrelink`；income、liability 对 gambling 已占用行的预测在提交时丢弃；rent 候选排除已由 income / liability 分类的行；gambling 在 income / liability 之前，其候选排除对该时点通常无对象，需确认保护是否实际落空；all_other_credit 只处理 credit 且排除已占用行，仅保留 `External Transfers`；catch_all 只处理未分类行 |
| E3 | 摘要后覆盖 | 摘要提交后仍可能写入的引擎只有 all_other_credit、fee、rent、catch_all。逐条确认其入口限制；**fee 的具体规则没有候选排除，可覆盖已摘要的收入 / 负债行并把 `stream_id` 置空**。任何覆盖都必须在 C4 / C5 中体现，不能被摘要自洽掩盖 |
| E4 | 摘要时点 | 每个引擎的 `summarize` 在自身 commit 后立即执行；摘要只代表该时点。不得用最终输出反推摘要，也不得把摘要差异直接当作最终分类差异 |

### 5.2 负债规则链

按 `liability_engine/pipeline.py` 实际调用顺序逐项核对：

| ID | 步骤 | 检查重点 |
| --- | --- | --- |
| L1 | 对手方关键词 / 正则 | 首次命中即生效；关键词有词边界保护，正则在关键词之后；检查规则表重复、先后覆盖、裸词误命中 |
| L2 | 房贷 / 车贷标记 | 覆盖写入；仅在 `counterparty` 为空时补对手方；会先于信用卡规则设置 `product_type`，需确认“房贷 / 车贷优先于信用卡”是否为预期 |
| L3 | 信用卡规则 | 名为覆盖模式，但仅对 `product_type` 为空的行生效；任何先前产品类型都会阻断。检查被阻断的信用卡商户是否是误分类 |
| L4 | 拒付标记 | `is_dishonours=yes` 不区分大小写，缺失按非拒付；检查摘要过滤、还款排除、最终流号清空三处一致 |
| L5 | 特殊规则 | Credit Corp 子产品 `wizit→bnpl / pup→loc / ccc→personal_loan`；Cash Converters 贷款合同号匹配 `B\d{4,}T\d+` 判贷款，门店 / SQ / EFTPOS / 卡尾判零售，零售置空 `product_type` 并改 `Retail`。检查特殊规则不会抹掉真实贷款 |
| L6 | 透支 / 催收 / 债务合并 | 透支置 `Overdrawn` 且不设产品类型；催收、债务合并只对无产品类型的行重新声明旗标；检查同一行旗标与产品流是否冲突 |
| L7 | 产品类型与流对齐 | `align_product_type_with_stream` 后，同一流不得残留多个产品类型；通用贷款兜底只处理未分类且文本含独立 `LOAN` 的行，每申请一条流 |

### 5.3 流识别与编号

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| R1 | 产品规则优先级 | `PRODUCT_RULES` 顺序为 bnpl(10) → wage_advance(20) → home_loan(25) → car_loan(27) → bank(30) → contract_loan(35) → generic_loan(37) → personal_loan(40) → loc(50)；先命中者占用，检查顺序与业务优先级一致 |
| R2 | 分组键 | 分组产品按 `application_id + bank_account_id + counterparty` 分组；空对手方跳过；缺失账户统一为空串，不能把缺失账户误并到真实账户 |
| R3 | 个人贷款聚类 | 还款 debit 按金额分桶，相对容差 5%；funding credit 按交易日期 + 金额合并为 flow，按“最近且至少提前 3 天”匹配还款流，不校验 funding 与还款金额相等；无 funding → `unknown`；未匹配 funding 单独成流；funding ≤ 2000 → SACC，> 2000 → non-SACC；拒付 credit 归入最近的前序 debit |
| R4 | unknown 细化 | 31 天窗口内可并入邻近流；unknown 还款总额 > 2000 → non-SACC；周期合并要求至少 3 个日期，中位间隔落在 4–10、11–17、27–33 天；检查是否把不同贷款错误合并 |
| R5 | LOC 合并 | 至少 3 条 SACC 流且 funding 金额的变异系数 > 0.2，并满足循环额度 / 单笔 funding 等保护条件；检查是否把普通个人贷款误并为 LOC |
| R6 | 统一重编号 | 前缀为 `liability_category`；每个 `(application_id, category)` 从 001 连续编号，按最早交易日期排序，同日期用旧流号决胜；仅拒付或仅赌博的不可见流不占号并清空流号 |
| R7 | BSCAT 派生 | 顺序为拒付优先 > 产品映射 > 仅对无产品类型的行声明透支 / 催收 / 债务合并；检查产品行被旗标覆盖或旗标行错误继承产品 BSCAT |
| R8 | 特殊流覆盖 | `zip money` 合并到 non-SACC；`credit corp` 将 SACC 流转为 non-SACC；检查覆盖发生在聚类之后、重编号之前，并同步更新类别与 BSCAT |

### 5.4 收入流

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| I1 | 收入类型优先级 | `salary_packaging > centrelink > salary_payg > self_employed_gig > non_income`；工资与 gig 规则有 50 金额下限，Centrelink 与 salary packaging 不受该下限约束 |
| I2 | 付款方识别 | 停用词、转账 / 退款 / 贷款 / 税 / 投资排除规则完整；付款方别名只合并空值或截断键，并受行为门槛限制，不得把不同雇主合并 |
| I3 | 收入分组 | 分组键为 `bank_account_id + income_type_pred + counterparty`，任一为空则不建流；检查同一付款方跨账户是否应拆分，以及别名合并后的流是否跨账户 |
| I4 | 收入编号 | 工资类（`salary_payg / salary_packaging / self_employed_gig`）用 `wage` 前缀，其他用收入类型前缀；每个 `(application, label)` 连续编号；赌博已占用行不参与 |
| I5 | 收入摘要 | 频次阈值 6–8 / 13–16 / 27–33 天；月收入换算、状态、预测日期按 A1–A4；检查 `derive_counterparty` 与交易对手方不一致时是否导致错误并流 |
| I6 | 收入 / 负债边界 | 贷款入账不得判为收入；工资入账不得判为负债；转账、退款、报销、博彩、投资赎回不得进入收入流；重复付款方规则需有金额与频次依据 |

### 5.5 数据与规则契约

| ID | 检查 | 通过判定 |
| --- | --- | --- |
| T1 | 账户映射 | `bank_account_id` 在交易、摘要生成、输出阶段一致；缺失账户是否被错误合并到空串组 |
| T2 | 金额 / 方向 / 日期 | 金额取绝对值前先确认 `dr_cr`；无效日期、零金额、非有限金额的处理一致；`transaction_date` 不参与批次筛选 |
| T3 | 规则表语义 | 关键词与正则的列名、大小写、词边界、优先级、覆盖模式与代码一致；新增行必须写全表头 |
| T4 | 版本指纹 | 记录代码提交、输出流号格式、摘要表头、状态枚举；三者任一不一致时，结论限定到对应版本 |

## 六、判定、优先级与清单

每项失败先归入一个固定问题类型，不按修改文件归类：

| 问题类型 | 适用情况 |
| --- | --- |
| 分流缺项 | 应有收入 / 负债流但未建流，或交易应分流却流号为空 |
| 分流错配 | 流归属到错误产品、收入类型、对手方或 BSCAT |
| 并流 / 拆流 | 不同贷款或收入被合并，或同一流被拆成多条 |
| 借贷配对 | 放款与还款未匹配、SACC 阈值错误、unknown 判定错误 |
| 摘要口径 | 摘要金额、状态、周期、预测日期与流内交易不符 |
| 流程冲突 | 引擎顺序、候选保护、后续覆盖导致摘要与最终输出不一致 |

**优先级**：以下数量按去重申请和流数分别统计，并注明是全量摘要还是覆盖运行。

- **高**：涉及 P0 摘要类别（`Wages、Centrelink、SACC Loans、Non SACC Loans、Unknown Loans、Credit Card Repayments`）的系统性错误；或 ≥ 20 个申请 / ≥ 100 条流；或将还款、放款错分为收入等严重后果项。
- **中**：5–19 个申请或 20–99 条流，且修复边界明确。
- **低**：少于 5 个申请且少于 20 条流，只汇总，不逐条展开。
- 少量但跨收入 / 负债边界的错误直接提为高优先级；同一根因合并为一项，不同根因不因改同一文件而合并。

```md
### STR-001｜高 / 中｜<问题类型>｜<一句话说明>
> <摘要现状 → 应有结果> · 影响 <申请数 / 流数 / 交易笔数> · 检查项 <S/A/C/D/E/L/R/I/T 编号>

- **问题**：<哪类流被错分 / 漏分 / 合并 → 代码或配置为什么没拦住 → 业务后果，2–3 句>
- **证据**：<文件、sample_datetime、user_id、application_id、job_id、log_id、stream_id、transaction_id；摘要原值；交易日期、方向、金额、原始 text；流内前后交易>
- **根因**：<模型相对路径 + 函数 / 规则名 + 行号或稳定定位标识；当前值和实际调用顺序>
- **改法**：<操作 新增 / 修改 / 删除>；`当前值` → `完整新值 / 精确字段 / 明确函数行为`；<依赖条目 ID 或无>
- **验证**：<离线复算结果；修复后应通过的检查项；正例应变成什么、反例保持什么；受影响流号范围>
- **审核**：`待审核`；<人工填写 已确认 / 暂缓 / 不采纳 及理由>
```

- 证据必须能唯一定位到运行、流和交易；不得用截断文本、推测的账户归属或“摘要看起来异常”作执行依据。
- 改法必须写到可执行粒度：规则表写全行，代码写清条件、输入和期望行为；不得用“复核、收紧、视情况调整”代替方案。
- 根因未确认的放入“待补证据”，写明缺什么、如何补；AI 不得自行确认条目。

## 七、验证与验收

**离线验证（本仓库）**

1. 用同一批输入重跑全部失败检查，记录修复前后的数量、流键和样本。
2. 对每条修改构造至少 1 个正例和 1 个易误伤反例；正例应进入目标流 / 目标类别，反例保持原状。
3. 检查流号变化范围：只允许受影响类别内重编号；其他类别、其他申请的流号不得变化。
4. 不得通过删除摘要行、清空金额或放宽检查来“修复”；不得把新增差异解释为预期而不给依据。

**模型侧验证（由修复执行人完成，需用户确认）**

- 运行 `python baseline.py diff`，核对最终输出、引擎占用、`run_meta`、摘要四层差异；基线重建必须获得用户明确确认，不得为通过验收直接改基线。
- 运行 `python verify_model.py --input <case>.json` 和 `python check_wagego_sample.py`，确认目标样本与回归样本。
- 重新生成同一批输入，重跑 S、A、C、D，并核对版本指纹已更新。

**验收标准**

- 目标检查项由失败变为通过，且 C4 / C5 的摘要与最终输出差异没有增加。
- 未引入新的 S、A、C、D 失败；相关类别的流数、申请数变化可解释。
- 受影响的流号变化只发生在目标 `(application_id, category / label)` 内。
- 若无法在模型侧执行，结论只能写“离线匹配验证通过，端到端未验证”，不得宣称已修复。

## 八、输出与停止条件

`stream_change_list_YYYYMMDD.md` 只保留三部分：

1. **范围与版本**：模型路径 / 分支 / 提交 / 未提交改动、输出指纹、摘要全量与应用数、evolve 覆盖运行数、各项检查的适用范围和盲区。
2. **检查结果总表**：按 S、A、C、D、E、L、R、I、T 列出每项结果（`通过 / 失败 / 不适用 / 需版本确认`）、数量、口径和一个样本；失败项链接到变更条目。
3. **变更清单与待补证据**：按优先级排序；待补证据只列疑似高影响项、缺什么及如何补。

**停止条件**：所有检查项均已执行或标记不适用；失败项已定位根因或进入待补证据；清单条目可执行、互不冲突；数量可从当前输入复算。达到后停止，不扩展到消费分类优化，不为凑数增加低价值条目。

**交付前核对**：版本与输出格式匹配；覆盖范围标注正确；摘要自洽与最终输出差异分开；每条证据唯一可定位；改法包含当前值和完整新值；验证包含正反例；审核状态为待审核。

## 附 A：代码与配置索引

路径相对于模型仓库，仅作入口，以确认版本的实际调用链为准。

| 主题 | 入口 |
| --- | --- |
| 引擎顺序 / 覆盖 | `configs/pipeline.json`、`classification_core/orchestrator.py`、`classification_core/service.py` |
| 负债规则链 | `liability_engine/pipeline.py`、`liability_engine/domain/counterparty.py`、`liability_engine/domain/special_rules.py` |
| 负债流识别 / 编号 / BSCAT | `liability_engine/domain/streams.py`：`PRODUCT_RULES`、`assign_grouped_product_streams`、`assign_personal_loan_rule`、`refine_unknown_personal_loan_streams`、`merge_sacc_streams_into_loc`、`apply_special_counterparty_stream_overrides`、`renumber_stream_ids_uniform`、`add_bscat` |
| 负债摘要 | `liability_engine/domain/summary.py`、`liability_engine/engine.py` |
| 收入分类 | `income_engine/pipeline.py`、`income_engine/domain/classification.py`、`income_engine/resources/income_pattern_rules.csv` |
| 收入流 / 摘要 | `income_engine/domain/summary.py`、`income_engine/engine.py` |
| 拒付 | `liability_engine/domain/dishonours.py`、`dishonour_engine/engine.py` |
| 摘要后覆盖 | `fee_engine/engine.py`、`fee_engine/domain/classification.py`、`all_other_credit_engine/engine.py` |
| 规则配置 | `liability_engine/resources/*.csv`、`income_engine/resources/*.csv`、`fee_engine/resources/fee_classification_rules.csv` |
| 验证工具 | `baseline.py`、`verify_model.py`、`check_wagego_sample.py` |

## 附 B：现有 `WORKFLOW_CLASSIFICATION.md` 分流规则评估

| 位置 | 现状 | 问题 | 建议 |
| --- | --- | --- | --- |
| 输入表摘要行（约 L23） | 摘要用于“辅助识别业务影响与流判定异常” | 未区分“分类证据”和“分流正确性”，容易把摘要自洽当作分流通过 | 保留摘要作为业务影响证据；分流核验明确指向本工作流 |
| 字段与关联（约 L26） | 给出摘要和交易的关联键 | 未说明摘要只覆盖摘要流、evolve 只覆盖圈选运行、旧流号格式 | 补充覆盖范围、运行键和版本门槛；跨输出检查限定覆盖运行 |
| 收入 / 负债核验（约 L42） | 检查收入类型、周期、状态、金额及逐笔一致性 | 只有方向性描述，无固定阈值、无借贷配对、无摘要时点概念，且绑定候选申请 | 分类工作流只保留“是否需要看摘要”；具体核验移到本工作流 |
| 配置排查（约 L53–L56） | 检查商户词、规则和最终写入点 | 未覆盖流分组、个人贷款聚类、SACC 阈值、编号和摘要 builder | 在索引中增加分流入口；分流类改动统一走本工作流 |
| 问题类型（约 L66–L76） | 规则缺项、匹配偏差、类别错配、流程冲突、判定缺陷 | 无“并流 / 拆流、借贷配对、摘要口径”等分流类型 | 分类清单不混入分流问题；发现后移交本工作流并引用 STR 条目 |
| 附录索引（约 L103–L121） | 主要是分类规则和摘要入口 | 缺收入摘要、流分组、编号、摘要 builder、fee 覆盖 | 增加“分流审计”一行指向本工作流，避免两套规则重复维护 |

**建议的最小改动**（按现状 / 改为 / 验证）：

1. 输入表摘要行：现状“辅助识别业务影响与流判定异常”；改为“摘要只作业务影响证据，分流正确性由 `WORKFLOW_STREAM.md` 核验”；验证：分类流程不再单独判定流对错。
2. 关联键条目：现状只列键；改为补“摘要为全量、evolve 为圈选、跨输出只查覆盖运行、流号格式需版本匹配”；验证：跨输出统计不再用全量摘要对比圈选交易。
3. 收入 / 负债核验：现状要求检查摘要；改为“仅在评估业务影响时引用摘要，分流核验转 `WORKFLOW_STREAM.md`”；验证：`WORKFLOW_CLASSIFICATION.md` 不再重复阈值和状态规则。
4. 问题类型表：现状五类；改为增加一句“分流缺项、分流错配、并流 / 拆流、借贷配对、摘要口径、流程冲突移交分流工作流”；验证：分类清单中不出现流级修复项。
5. 附录：现状无分流入口；改为增加“分流审计 | `WORKFLOW_STREAM.md` | 流识别、编号、摘要 builder、引擎覆盖”；验证：从分类文档可一跳找到分流入口。

## 附 C：输出字段与版本指纹

| 文件 | 粒度 | 可用关联字段 | 缺少字段 | 用途 |
| --- | --- | --- | --- | --- |
| 收入摘要 | 每运行每收入流 | `user_id、application_id、job_id、log_id、sample_datetime、stream_id` | `bscat、bank_account_id、counterparty` | S、A、C1、C3、C6；成分检查需交易 |
| 负债摘要 | 每运行每负债流 | 同上 | 同上 | 同上 |
| evolve 交易 | 每交易 | 上述运行键 + `bank_account_id、transaction_id` | 无（在覆盖范围内） | C2、C4、C5、D1–D7 |

**版本指纹必须记录**：

- 负债流号：现行 `{liability_category}_NNN`；旧版 `loan_NNN`。旧格式不得按现行前缀规则判错，A5–A9、S2、S3、D6 需按产出代码复核。
- 收入流号：`wage_NNN` / `centrelink_NNN`；若出现其他前缀，先查产出代码，不直接判错。
- 摘要表头：以实际 CSV 为准；缺 `application_id` 或 `sample_datetime` 时关联能力降级，必须在报告中注明。
