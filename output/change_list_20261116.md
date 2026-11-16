# BSCAT 分类变更清单（2026-11-16）

## 一、本次范围

- **模型**：`C:\Users\zhangyuliang02\Desktop\AUS_BS_CAT_Model`，分支 `feature/traceback-optimization`，HEAD `a26ea8f`（2026-11-02）。
- **输入**：`input/risk_000008_dash_detail.csv`（交易日期 2026-03-18 至 2026-10-08，`sample_datetime` 2026-10-08，共 7,854,004 行）；`input/bscat_monitor_20261113_060324.html`（`dataDate` 2026-11-12，`generatedAt` 2026-11-13 06:03）。批次规则集接近提交 `7176ad7`（2026-10-10），与 HEAD 存在规则差，版本差条目列入「待补证据」。
- **范围**：10 个 P0 + monitor 选出的 10 个非 P0（`coverage_gap` 最低：External Transfers、Internal Transfer、Health、Groceries、Dishonours；`diff_count` 最高：External Transfers、Internal Transfer、Dining Out、Groceries、Information；`iou_rate` 最低：Pet Care、Information、Health、Retail、Travel），共 20 类、662 条流向。
- **清洗**：金额为 0 的通知类 55,105 行剔除；金额为空或非法 0 行；无流向 0 行；范围外 916,783 行；范围内 6,882,116 行。
- **覆盖率**：阈值 90%，实际选入 57 条流向、6,292,118 行，覆盖范围内 91.43%；未覆盖 605 条流向、589,998 行。范围内长尾（入选流向 Top10 之外）4,082,698 行 / 778,424 个聚类，另做第二轮补查。
- **抽查代表量**：第一轮 57 条流向各取 Top10 聚类，共 570 组；第二轮跨流向 150 组、残差前 80 组、关键词族 419 组。
- **P0 覆盖**：

| P0 类别 | 范围内笔数 | 流向覆盖率 |
| --- | ---: | ---: |
| Wages | 592,127 | 90.3% |
| Centrelink | 13,199 | 93.3% |
| All Other Credits | 602,622 | 91.3% |
| SACC Loans | 172,451 | 90.8% |
| Non SACC Loans | 382,801 | 90.9% |
| Unknown Loans | 281,862 | 95.8% |
| Credit Card Repayments | 71,389 | 90.9% |
| Debt Collection | 67,333 | 90.7% |
| Debt Consolidation | 8,344 | 93.0% |
| Overdrawn | 46,666 | 99.9% |

- **主要盲区**：未覆盖 605 条低笔数流向（589,998 行，占范围内 8.57%）；入选流向仅逐条抽查 Top10 聚类，长尾依赖第二轮的跨流向、残差和关键词族补查；明细不含 `bank_accounts` 账户归属与贷款产品状态，依赖状态的判断列入「待补证据」；illion 的 `(空)` 不视为 BSCAT 错误。已完成规则 × 流向反向扫描（transfer / fee / income / liability / dishonour），未发现清单之外的新增高 / 中根因。

## 二、变更清单

### CHG-001｜高｜CommBank App 具名转账带逗号时整类漏识别

> 匹配偏差 · (空) / Retail / Groceries / Dining Out → External Transfers · 5,734 个申请 · 265,423 笔（已证实漏分）；同族共 315,602 笔 · 证据 3064872445：`Transfer To Catherine Castillon, CommBank App jewelry, N291866795908`

- **问题**：规则 20 在 `to/from` 与 `CommBank App` 之间只接受 `[a-z][a-z .'-]+`，遇到逗号、`PayID Email from`、数字或自由文本就整段失配；这笔 P2P 转账因此落入 `(空)`，同族还有大量被初始商户库按备注词误分为 Retail / Groceries / Dining Out。该写法是本次 `(空)` 的最大单一来源。
- **改法**：`transfer_engine/resources/transfer_external_high_confidence_rules.csv`，`rule_name=external_commbank_name`（priority 20）；`\btransfer (to|from) [a-z][a-z .'-]+ commbank app\b` → `\btransfer (?:to|from) (?!xx\d{4}\b|sav\s+\d+\b|cba a/c\b).+? commbank app\b`。保留 `xx####`、`SAV <n>`、`CBA A/c` 的既有分支，不改变这些写法的当前归类。
- **风险 / 验收**：会把商户库已识别的具名转账改判为 External Transfers（Retail、Dining Out、Groceries 等）；若业务希望保留消费细分，应另设优先级，而不是维持漏分。正例：证据行 → External Transfers；反例：`Transfer to xx1095 CommBank app`、`Transfer to SAV 123 CommBank app`、`Transfer to CBA A/c CommBank app` 保持现有分类；同批匹配约 26.5 万笔，最终 `(空)` 减少量以重跑为准（后续引擎仍可覆盖）。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-002｜高｜`FAST PYMT IN` 被当成工资强关键词，覆盖了转账分类

> 匹配偏差 · Wages → External Transfers · 85 个申请 · 6,256 笔 · 证据 3065309515：`Fast Pymt In REF:X`

- **问题**：`strong_wage` 把 `FAST PYMT IN`（CBA 即时转账通道）当作工资强关键词；本批 6,322 笔该写法中仅 1 笔含工资词，6,256 笔被判 Wages，而 BSCAT 自己的 transfer 规则 4 已把该前缀定义为 External Transfers。结果是收入被高估、转账被 income 的 later-wins 覆盖。
- **改法**：`income_engine/resources/income_pattern_rules.csv`，`pattern_group=strong_wage` 行 `\bFAST\s*PYMT\s*IN\b` → 改为 `pattern_group=medium_income`，pattern 与 description 保留。改后由重复付款人 / 稳定金额 / 周期规则决定是否 Wages。
- **风险 / 验收**：真实工资若只写 `FAST PYMT IN` 且无工资词、又无重复或稳定金额证据，会退出 Wages，需在下一批监控 Wages 覆盖率。正例：`Fast Pymt In REF:Rent` → External Transfers；反例：`Fast Pymt In REF:ACME SALARY` 仍由 `\bSALARY\b` 判 Wages；同一付款人 ≥4 次且金额稳定 / 周期规律时仍可由行为规则判 Wages。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-003｜高｜Debt Collection 关键词命中后被前置分类门控阻断

> 流程冲突 · External Transfers / (空) → Debt Collection · 501 个申请 · 6,331 笔（已证实）；另 404 个申请 · 4,961 笔疑同因 · 证据 3065859656：`Direct Debit REVENUENSW Debt - 000000029906843`

- **问题**：`debt_collection_rules.csv` 的 `revenuensw debt` 已命中，但 `_apply_flag_rules` 的非覆盖模式只在 counterparty 和 product_type 都为空时写元数据；transfer 引擎先写入了 `Direct Debit Transfer` / `External Transfers`，债务标记因此永远落不到 bscat。另有 4,961 笔最终为空，疑似同一门控或未进入 liability 流水，需模型侧逐行确认。
- **改法**：`liability_engine/domain/counterparty.py`，`_apply_flag_rules` 内 `_write_metadata`（约 503–510 行）。在 `not_classified`（约 496–499 行）旁新增 `bscat = output.get("bscat", pd.Series("", index=output.index)).fillna("").astype(str).str.strip()` 与 `bscat_eligible = bscat.isin(["", "Internal Transfer", "External Transfers"])`；把 `effective = mask & not_classified` 改为：`target` 为 `is_debt_collection` / `is_debt_consolidation` 时 `effective = mask & (not_classified | bscat_eligible)`，其余 flag 仍用 `mask & not_classified`。`_bulk_write_metadata`（约 662–672 行）不改，counterparty 仍按 `cp_empty` 写入，product_type 不动。
- **风险 / 验收**：高风险逻辑修改，可能把只是提到债务机构的普通转账改判为 Debt Collection（如 Credit Corp 的 3,166 笔 / 197 申请），需与「待补证据」一并确认；回退方式为恢复原 `not_classified` 门控。正例：证据行 → Debt Collection；反例：`Direct Debit ORIGIN ENERGY` 仍为 External Transfers，`Transfer to John Smith` 不变；已证实 6,331 笔改判，若 4,961 笔同因则合计约 1.1 万。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-004｜中｜费类规则把空格 / 结尾写死，透支费与透支利息调整漏识别

> 匹配偏差 · Fees / (空) → Overdrawn · 2,941 个申请 · 23,677 笔（Overdraw Fee）；1,247 个申请 · 2,201 笔（Debit Excess Int Adjusted） · 证据 3063892435：`Overdraw Fee, For exceeding available funds on 06 May, ZA4FC98724871`；3063737848：`Debit Excess Int Adjusted, Value date: 01/09/2026, ZAABA92290228`

- **问题**：`^Overdraw\s+Fee\s+` 要求 `Fee` 后必须紧跟空格，`^Debit\s+Excess\s+Int\s+Adjusted\s+Value\s+Date:` 要求 `Adjusted` 后直接空格；实际文本分别是 `Overdraw Fee, ...` 和 `Adjusted, Value date:`。23,677 笔借记透支费落在 Fees，2,201 笔透支利息调整落在 `(空)`，Overdrawn 风险信号被削弱；另有 4 笔 `Overdraw Fee, REFUND...` 贷记退款，illion 为 All Other Credits，应保持 Fees。
- **改法**：

| 文件 / 稳定定位标识 | 操作 | 当前值 | 修改后值 / 保留内容 | 证据引用 |
| --- | --- | --- | --- | --- |
| `fee_engine/resources/fee_classification_rules.csv` / `overdraw_fee`（priority 4） | 修改 | `4,overdraw_fee,Overdrawn,^Overdraw\s+Fee\s+,Overdrawn Fee,regex,false,Overdraw Fee For exceeding available funds,false,` | `4,overdraw_fee,Overdrawn,^Overdraw\s+Fee\b,Overdrawn Fee,regex,false,Overdraw Fee For exceeding available funds,false,debit` | 3063892435 |
| `fee_engine/resources/fee_classification_rules.csv` / `debit_excess_int_adjusted`（priority 7） | 修改 | `7,debit_excess_int_adjusted,Overdrawn,^Debit\s+Excess\s+Int\s+Adjusted\s+Value\s+Date:\s+\d{2}/\d{2}/\d{4},Overdrawn Fee,regex,false,Debit Excess Int Adjusted,false,` | `7,debit_excess_int_adjusted,Overdrawn,"^Debit\s+Excess\s+Int\s+Adjusted,?\s+Value\s+Date:\s+\d{2}/\d{2}/\d{4}",Overdrawn Fee,regex,false,Debit Excess Int Adjusted,false,`（pattern 含逗号，字段必须加引号） | 3063737848 |

- **风险 / 验收**：`dr_cr=debit` 防止 4 笔 `Overdraw Fee, REFUND REDIRECTED...` 贷记退款被改判（现为 Fees，illion 为 All Other Credits）；`Debit Excess Int Adjusted` 借贷两向共 2,201 笔，illion 全部为 Overdrawn，规则不设方向限制。正例：两条证据 → Overdrawn；反例：`Overdraw Fee, REFUND REDIRECTED FROM ...` 保持 Fees；`Debit Excess Interest, ZA...` 仍由 HEAD 的 `fee_miss_f12` 命中；同批应改判 Overdraw 23,677 笔 + Debit Excess Int Adjusted 2,201 笔。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-005｜高｜银行转账写法缺硬负向，收入引擎把它覆盖成 Wages

> 规则缺项 · Wages → Internal Transfer / External Transfers · 77 个申请 · 19,833 笔（ANZ）；113 个申请 · 1,344 笔（CommBank） · 证据 3063673157：`ANZ M-BANKING FUNDS TFER TRANSFER 254674 FROM 798091676`；3064549182：`Transfer from xx5242 CommBank app, Pay, N500369634460`

- **问题**：ANZ M-Banking 的 `FUNDS TFER TRANSFER <ref> FROM <account>` 被历史付款人规则判为 Wages；CommBank App 的 `Transfer from xx#### ... Pay` 被 `rule_transfer_from_pay_signal` 判为 Wages。两者原本都由 transfer 引擎归为 Internal / External Transfers，income 的 later-wins 又把它们覆盖。
- **改法**：

| 文件 / 稳定定位标识 | 操作 | 当前值 | 修改后值 / 保留内容 | 证据引用 |
| --- | --- | --- | --- | --- |
| `income_engine/resources/income_pattern_rules.csv` / `hard_negative` | 新增 | 无 | `hard_negative,"\bANZ\s+M-BANKING\s+FUNDS\s+TFER\s+TRANSFER\s+\d+\s+FROM\s+\d{6,}\b",regex,ANZ M-Banking funds transfer from account`（`{6,}` 含逗号，必须加引号） | 3063673157 |
| `income_engine/resources/income_pattern_rules.csv` / `behavior_exclusion` | 新增 | 无 | `behavior_exclusion,\bTRANSFER\s+FROM\s+XX\d{4}\s+COMMBANK\s+APP\b,regex,Masked CommBank App transfer from own account` | 3064549182 |

- **风险 / 验收**：ANZ 行走硬负向，无工资强关键词时全部退出 Wages；CommBank 行放在 `behavior_exclusion`，只阻断 PAY 信号规则，不阻断 UBER / PAYPAL 等 gig 直接关键词（本批 859 笔 Uber 类仍为 Wages），另 225 笔含 SALARY / PAYROLL 等工资词的也保持 Wages。正例：两条证据退出 Wages；反例：`Transfer from John Smith CommBank app`、`Fast Transfer From X Salary` 不变；`Transfer from xx#### CommBank app, Uber` 仍为 Wages。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-006｜中｜TapTap / Western Union 汇款规则锚死结尾，带参考号即漏识别

> 规则缺项 · (空) → External Transfers · 332 个申请 · 13,111 笔（TapTap）；188 个申请 · 2,526 笔（WU） · 证据 3063645201：`TapTap Send SYDNEY AUS, Card xx9467, Value date: 03/07/2026, H243582863958`；3065172413：`WU 6855992572, H135270763779`

- **问题**：两条规则都用 `$` 锚死结尾，且不接受逗号 / 尾随参考号；TapTap 还要求逗号位置固定。实际文本带 `, H...` / `, N...` 参考号，规则全部落空，合计 1.56 万笔落入 `(空)`，汇款通道无法进入 External Transfers。
- **改法**：

| 文件 / 稳定定位标识 | 操作 | 当前值 | 修改后值 / 保留内容 | 证据引用 |
| --- | --- | --- | --- | --- |
| `transfer_engine/resources/transfer_external_high_confidence_rules.csv` / `external_taptap_send`（priority 31） | 修改 | `^taptap send sydney aus card xx\d{4} value date: \d+/\d+/\d+$` | `^taptap send sydney aus\b` | 3063645201 |
| `transfer_engine/resources/transfer_external_high_confidence_rules.csv` / `external_wu`（priority 28） | 修改 | `^wu \d+$` | `^wu \d+\b` | 3065172413 |

- **风险 / 验收**：前缀匹配会接受同一通道的更多尾随写法；`WU 123ABC` 不会命中（`\b` 要求数字后是边界）。正例：两条证据 → External Transfers；反例：`WESTERN UNION`、`DEBIT CARD PURCHASE TAPTAP SEND SYDNEY` 不命中本规则（后者由 priority 3 处理）。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-007｜中｜`Returned Item Credit` 未进退票规则，被收入引擎判为 Wages

> 规则缺项 · (空) / Wages → Dishonours · 50 个申请 · 668 笔 · 证据 3063419093：`Returned Item Credit`

- **问题**：`Returned Item Credit` 是退票 / 退单的贷记回执，illion 标 Dishonours；dishonour 规则表没有该关键词，income 引擎把它当成重复收入判 Wages（137 笔）或留空（531 笔），退票事件无法完整计入。
- **改法**：

| 文件 / 稳定定位标识 | 操作 | 当前值 | 修改后值 / 保留内容 | 证据引用 |
| --- | --- | --- | --- | --- |
| `dishonour_engine/resources/dishonour_rules.csv` / `keyword` | 新增 | 无 | `keyword,Returned Item Credit,` | 3063419093 |
| `liability_engine/resources/dishonours_rules.csv` / `keyword` | 新增 | 无 | `keyword,Returned Item Credit,` | 3063419093 |
| `income_engine/resources/income_pattern_rules.csv` / `hard_negative` | 新增 | 无 | `hard_negative,\bRETURNED\s+ITEM\s+CREDIT\b,regex,Returned item credit is not income` | 3063419093 |

- **风险 / 验收**：把退票贷记归入 Dishonours；若业务把退款单独统计，需在 Dishonours 内再细分。income 的硬负向用于防止后续引擎再次覆盖。正例：证据行 → Dishonours；反例：`Item Credit` 不命中，`Returned Item Debit`（如存在）不命中该关键词。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

### CHG-008｜中｜收入规则 CSV 未加引号，4 条排除规则静默失效

> 匹配偏差 · Wages → 转账类（按实际命中的 transfer 规则） · 25 个申请 · 575 笔（已量化）；4 条规则整体失效 · 证据 3065396535：`TFR from 111219168 MOB, 472256414`

- **问题**：`income_pattern_rules.csv` 有 4 行正则含未加引号的 `{m,n}` 逗号，`csv.DictReader` 把 pattern 截断为 `\d{6`、`match_type` 变成 `}\b`，规则静默失效：两条 `behavior_exclusion`（自转账）和两条 `gig_personal_exclusion`（按账号 / 长账号识别自我转账）从未生效；前两条的 Wages 影响已量化，后两条未单独量化。
- **改法**：

| 文件 / 稳定定位标识 | 操作 | 当前值 | 修改后值 / 保留内容 | 证据引用 |
| --- | --- | --- | --- | --- |
| `income_engine/resources/income_pattern_rules.csv` 第 148 行 / `behavior_exclusion` | 修改 | `behavior_exclusion,\bTFR\s*FROM\s+\d{6,}\b,regex,...`（未加引号，解析为 pattern=`\bTFR\s*FROM\s+\d{6`、match_type=`}\b`） | `behavior_exclusion,"\bTFR\s*FROM\s+\d{6,}\b",regex,Self-transfer: TFR FROM with account number` | 3065396535 |
| `income_engine/resources/income_pattern_rules.csv` 第 149 行 / `behavior_exclusion` | 修改 | `behavior_exclusion,\bFUNDS\s*TFER\b.*\bFROM\s+\d{6,}\b,regex,...`（同样被截断） | `behavior_exclusion,"\bFUNDS\s*TFER\b.*\bFROM\s+\d{6,}\b",regex,Self-transfer: funds transfer from account number` | 3063673157 |
| `income_engine/resources/income_pattern_rules.csv` 第 206 行 / `gig_personal_exclusion` | 修改 | `gig_personal_exclusion,\bFROM\s+\d{3,4}-\d{3}-\d{3,}\b,regex,...`（同样被截断） | `gig_personal_exclusion,"\bFROM\s+\d{3,4}-\d{3}-\d{3,}\b",regex,Self-transfer: transfer from account number` | 跨族扫描命中 |
| `income_engine/resources/income_pattern_rules.csv` 第 207 行 / `gig_personal_exclusion` | 修改 | `gig_personal_exclusion,\bFROM\s+\d{7,}\b,regex,...`（同样被截断） | `gig_personal_exclusion,"\bFROM\s+\d{7,}\b",regex,Self-transfer: transfer from long account number` | 跨族扫描命中 |

- **风险 / 验收**：修复后 `behavior_exclusion` 只影响高频付款人行为规则，不阻断 strong_wage / gig 直接关键词；`gig_personal_exclusion` 只影响 gig repeat-payer 路径。正例：`TFR from 111219168`、`FUNDS TFER ... FROM 798091676` 命中排除；反例：`TFR FROM 12345`（5 位）不命中。全量资源表已扫描，仅此 4 行存在字段数异常。
- **审核**：`待审核`；待运维确认、暂缓或不采纳并补理由。

## 三、待补证据

- **CommBank `xx####` 账户归属**：debit 485,392 笔 / 1,378 申请、credit 440,985 笔 / 1,356 申请，BSCAT 为 External Transfers、illion 为 Internal Transfer，是本次最大未决项。缺 `bank_accounts` 的账户归属 / 产品类型；补齐方式：用模型账户状态或卡号后四位匹配后重跑该组，再决定是否放宽内部转账规则。
- **Credit Corp 产品线冲突**：57,183 笔 / 2,886 申请 BSCAT 为 Unknown Loans、illion 为 Non SACC；另有 6,337 笔 / 466 申请 `(空)`、3,166 笔 / 197 申请 External Transfers，illion 为 Debt Collection。`counterparty_keyword_rules.csv` 指向 personal_loan，`debt_collection_rules.csv` 指向 Debt Collection，文本无法区分产品线；需确认账户产品类型与催收状态后再定目标类别。
- **Fundo 贷款 stream**：17,538 笔 / 1,866 申请 BSCAT 为 Unknown Loans、illion 为 SACC，另有 3,994 笔 / 313 申请 Non SACC → SACC。缺贷款产品 / 合同类型，无法判断 SACC 与 Non SACC；需补 Fundo 产品状态。
- **Rent via CommBank App 的方向与账户归属**：credit 24,351 笔 / 1,033 申请（`Transfer from xx#### CommBank app, Rent`，入账方向仍标 Rent，illion 为 External Transfers）、debit 19,726 笔 / 862 申请（illion 为 External Transfers）。入账贷记标成支出类 Rent 本身不合业务语义；缺 `xx####` 账户归属（是否本人账户）与借记侧租金口径，补齐后再定改法。
- **RevenueNSW `(空)` 子组**：4,961 笔 / 404 申请命中 `revenuensw debt` 但最终为空，疑未进入 liability 流水或受同一门控影响；需模型侧逐行 trace 确认，再纳入 CHG-003 的影响量。
- **批次版本滞后**：明细 `sample_datetime` 为 2026-10-08，批次规则集约在 `7176ad7`（2026-10-10），HEAD 已新增以下规则，预计已修复但当前明细无法验证，需用 HEAD 重跑同批明细后复核：`^CREDIT\s+CARD\s+PAYMENT\b`（8,912 笔 / 272 申请）、`PAYMENT RECEIVED, THANK YOU`（22,253 笔 / 448 申请）、`DIRECT DR DISH`（4,029 笔 / 169 申请）、`fee_miss_f12` Debit Excess Interest（20,907 笔 / 3,882 申请）、`UBERDIRECTAU` 商户库（6,324 笔 / 1,367 申请）。
