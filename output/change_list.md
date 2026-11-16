# BSCAT 分类差异改动清单

- 模型仓库：`C:\Users\zhangyuliang02\Desktop\AUS_BS_CAT_Model`（HEAD 2026-11-02，本次只读核验，未改代码）
- 明细日期：`2026-03-18` ~ `2026-10-08`；抽样窗口：`2026-09-21` ~ `2026-10-08`
- Monitor：`bscat_monitor_20261113_060324.html`，`dataDate=2026-11-12`
- 范围：20 个 category / 6,882,116 行
- 已判定流向：87 条 / 覆盖 6,574,936 行 / 95.54%
- 零金额行：55,105
- 未覆盖：575 条流向 / 307,180 行
- 覆盖内未做 cluster 判定：4,287,327 行 / 838,039 clusters / 73 条长尾 flow

## 怎么读

- **§一 可执行改动**：可以直接改代码/规则。每条先看“问题描述”和例子，再看 `现状` / `改为` / `验证`。

## P0 覆盖表

| P0 Category            | 范围内行数 | 已判定覆盖行 | 覆盖率 |
| ---------------------- | ---------: | -----------: | -----: |
| Wages                  |    592,127 |      560,727 | 94.70% |
| Centrelink             |     13,199 |       12,318 | 93.33% |
| All Other Credits      |    602,622 |      563,235 | 93.46% |
| SACC Loans             |    172,451 |      156,625 | 90.82% |
| Non SACC Loans         |    382,801 |      353,513 | 92.35% |
| Unknown Loans          |    281,862 |      269,942 | 95.77% |
| Credit Card Repayments |     71,389 |       64,877 | 90.88% |
| Debt Collection        |     67,333 |       61,054 | 90.67% |
| Debt Consolidation     |      8,344 |        7,763 | 93.04% |
| Overdrawn              |     46,666 |       46,634 | 99.93% |

## 一、可执行改动

### 1. liability_engine/domain/counterparty.py / apply_overdrawn_flag|apply_debt_collection_flag|apply_debt_consolidation_flag

- [ ] 类型=`高危`
  **问题描述**：债务/透支规则在匹配前要求 `counterparty` 和 `product_type` 都为空；但文本走到这一步时，前面的引擎往往已经写过标签，所以规则即使能匹配也不会打 flag，最终 bscat 为空或 Unknown。例：`PAYMENT TO REVIVE DEBT 808128532` 应该判 Debt Collection，现在没有。
  现状：三个入口分别调用 `_apply_flag_rules(df, rules, ["is_overdrawn"])`、`["is_debt_collection"]`、`["is_debt_consolidation"]`，均未传 `overwrite`，默认 `overwrite=False`；`_apply_flag_rules` 用 `not_classified = cp_empty & pt_empty` 过滤，已被前置引擎写入 `counterparty` 或 `product_type` 的债务文本不会置 flag。
  改为：三个入口都改为 `_apply_flag_rules(..., overwrite=True)`；`_bulk_write_metadata` 仍只写 `counterparty` / `bscat`，不写 `product_type`。
  依据：`illion对`；样本=`PAYMENT BY AUTHORITY TO REVENUENSW Debt`、`PAYMENT TO REVIVE DEBT 808128532`、`Honour Charge`；对应 CSV 规则均能匹配，但样本 bscat 为空 / Unknown。
  影响：3560 app / 40,852 笔（Debt Collection→(空)）+ 1459 app / 20,202 笔（Debt Collection→External Transfers）+ 283 app / 4,474 笔（Debt Consolidation→(空)）+ 206 app / 3,289 笔（Debt Consolidation→External Transfers）+ 3947 app / 22,185 笔（Overdrawn→(空)）；flow=`Debt Collection → (空)` / `Debt Consolidation → (空)` / `Overdrawn → (空)`
  前置：先在当前 HEAD 重放 3 条样本，记录 `is_overdrawn` / `is_debt_collection` / `is_debt_consolidation` 是否为 1；若已为 1，本项跳过。
  验证：`grep -n "apply_overdrawn_flag\|apply_debt_collection_flag\|apply_debt_consolidation_flag" -A1 liability_engine/domain/counterparty.py` 确认三个调用均带 `overwrite=True`；重跑后 3 条样本 flag=1；三条目标 flow 笔数下降；`Credit Card Repayments`、`Non SACC Loans` 总笔数不增加。

### 2. liability_engine/domain/streams.py / add_bscat

- [ ] 类型=`高危`
  **问题描述**：`add_bscat` 最后会用 `product_type + "_" + stream_base` 重建 bscat；即使第 1 项把 `is_debt_collection` 等 flag 置 1，这里仍会把 bscat 改回贷款产品类型。例：`PAYMENT TO REVIVE DEBT` 会被重建成 `personal_loan_unknown`，而不是 Debt Collection。
  现状：`add_bscat` 在 `BSCAT_MAP` 之前只对 `is_dishonours == "yes"` 强制写 `Dishonours`；`_bulk_write_metadata` 写入的 `is_overdrawn` / `is_debt_collection` / `is_debt_consolidation` bscat，会在 `valid_mask` 命中时被 `product_type + "_" + stream_base` 重建值覆盖。
  改为：在 `preserved_mask` 赋值之后、`dishonour_mask` 覆盖之前，增加以下循环；`is_dishonours` 保持最后覆盖。

  ```python
  for flag, category in (
      ("is_overdrawn", "Overdrawn"),
      ("is_debt_collection", "Debt Collection"),
      ("is_debt_consolidation", "Debt Consolidation"),
  ):
      if flag in output.columns:
          mask = output[flag].astype("string").str.lower().isin(
              {"1", "1.0", "yes", "true"}
          )
          output.loc[mask, "bscat"] = category
  ```

  依据：`illion对`；样本=`Honour Charge`、`PAYMENT TO REVIVE DEBT 808128532`、`PAYMENT BY AUTHORITY TO REVENUENSW Debt`；`add_bscat` 是最终写点。
  影响：与第 1 项相同三条 flow；flow=`Debt Collection → (空)` / `Debt Consolidation → (空)` / `Overdrawn → (空)`
  前置：完成第 1 项，并在重放中确认三个 flag 列已置 1。
  验证：`grep -n "is_debt_collection\|is_debt_consolidation\|is_overdrawn\|preserved_mask\|dishonour_mask" liability_engine/domain/streams.py` 确认循环位于 `preserved_mask` 之后、`dishonour_mask` 之前；重跑后样本 bscat 分别为 `Overdrawn` / `Debt Collection` / `Debt Consolidation`；目标 flow 笔数下降；`Non SACC Loans`、`Credit Card Repayments` 总笔数不增加。

### 3. transfer_engine/resources/transfer_internal_regex_rules.csv / internal_phrase

- [ ] 类型=`命中链路`
  **问题描述**：内部转账规则只看到 “internal transfer” 就命中，没有排除信用卡还款文本；这类文本实际是还信用卡，不是本人账户互转。例：`Payment to your Credit Card - Internal transfer` 现在判 Internal Transfer，illion 是 Credit Card Repayments。
  现状：第 7 行 `internal_phrase,\binternal transfer\b,,` 会命中 `Payment to your Credit Card - Internal transfer`，把信用卡还款标成 Internal Transfer。
  改为：第 7 行 pattern 改为 `^(?!.*\bcredit\s+card\b).*\binternal transfer\b`，其余列不变。
  依据：`illion对`；样本=`Payment to your Credit Card - Internal transfer`（illion=Credit Card Repayments，bscat=Internal Transfer）。
  影响：253 app / 10,010 笔（Credit Card Repayments→Internal Transfer 上限）；flow=`Credit Card Repayments → Internal Transfer`
  前置：无。
  验证：`grep -n "internal_phrase" transfer_engine/resources/transfer_internal_regex_rules.csv` 确认 pattern 含 `credit\s+card`；样本不再命中；重跑后该 flow 笔数下降；`External Transfers → Internal Transfer` 不增加。

### 4. liability_engine/resources/counterparty_keyword_rules.csv / Stay Finance

- [ ] 类型=`新增规则`
  **问题描述**：`counterparty_keyword_rules.csv` 里没有 Stay Finance；文本虽然含 `STAY FINANCE`，但不会设置 `counterparty=Stay Finance` / `product_type=personal_loan`，无法进入 personal_loan stream 判定。例：`Direct Debit 342190 STAY FINANCE` 现在判 Non SACC Loans，illion 是 SACC Loans。
  现状：文件无 `Stay Finance` 行；`STAY FINANCE` 文本不会设置 `counterparty=Stay Finance` / `product_type=personal_loan`。
  改为：新增一行 `STAY FINANCE; Stay Finance,Stay Finance,personal_loan,keyword`。
  依据：`illion对`；样本=`Direct Debit 342190 STAY FINANCE...`（illion=SACC Loans，bscat=Non SACC Loans）。
  影响：2158 app / 45,877 笔（SACC Loans→Non SACC Loans）中的 Stay Finance 子集；flow=`SACC Loans → Non SACC Loans`
  前置：无。
  验证：`grep -n "STAY FINANCE" liability_engine/resources/counterparty_keyword_rules.csv` 确认新行存在；样本 `counterparty=Stay Finance`、`product_type=personal_loan`；重跑后确认样本进入 personal_loan stream 判定，若匹配到 ≤2000 的放款则 bscat=`SACC Loans`。

### 5. liability_engine/resources/credit_card_rules.csv / bankwest_bare

- [ ] 类型=`删除泛词`
  **问题描述**：Bankwest 规则里有一条裸 `\bBANKWEST\b`，只要 debit 文本含 BANKWEST 就判信用卡还款，连 Bankwest 的房贷扣款也会被误判。例：`PERIODICAL PAYMENT TO BANKWEST SIMPLE HL` 现在判 Credit Card Repayments，illion 为空。
  现状：第 58 行 `90,-,debit,*,regex,\bBANKWEST\b,0,Bankwest Credit Card Repayment,bank,` 对任意 debit 含 `BANKWEST` 的文本都判信用卡还款；`PERIODICAL PAYMENT TO BANKWEST SIMPLE HL` 被误判。
  改为：删除第 58 行；保留第 56 行 `(BANKWEST\s+CREDIT\s+CARD|IB\s+TRANSFER|BANKWEST\s+LOANS?)` 和第 57 行。
  依据：`illion对`；样本=`PERIODICAL PAYMENT TO BANKWEST SIMPLE HL`（illion=空，bscat=Credit Card Repayments）。
  影响：460 app / 12,446 笔（Credit Card Repayments→External Transfers 上限）；flow=`Credit Card Repayments → External Transfers`
  前置：无。
  验证：`grep -n "\\\\bBANKWEST\\\\b" liability_engine/resources/credit_card_rules.csv` 无结果；样本不再命中；重跑后该 flow 笔数下降；`BANKWEST CREDIT CARD` 样本仍命中第 56 行。

### 6. liability_engine/resources/credit_card_rules.csv / mastercard_generic

- [ ] 类型=`删除泛词`
  **问题描述**：三条 MASTERCARD 规则也是裸词匹配，只要文本含 MASTERCARD 就判信用卡还款，连 PREPAID 卡消费也会被误判。例：`MASTERCARD PREPAID MANAG - Visa Purchase` 现在判 Credit Card Repayments，illion 是 External Transfers。
  现状：第 101–103 行三条 `\bMASTERCARD\b` 对任意 debit 含 `MASTERCARD` 的文本判信用卡还款；`MASTERCARD PREPAID MANAG - Visa Purchase...` 被误判。
  改为：三条 pattern 都改为 `^(?!.*\bPREPAID\b).*\bMASTERCARD\b`。
  依据：`illion对`；样本=`MASTERCARD PREPAID MANAG - Visa Purchase...`（illion=External Transfers，bscat=Credit Card Repayments）。
  影响：460 app / 12,446 笔中的 PREPAID 子集；flow=`Credit Card Repayments → External Transfers`
  前置：无。
  验证：`grep -n "MASTERCARD" liability_engine/resources/credit_card_rules.csv` 确认三条均含 `PREPAID` 负向前瞻；样本不再命中；重跑后该 flow 笔数下降；普通 `MASTERCARD` 还款样本仍命中。

### 7. liability_engine/resources/credit_card_rules.csv / withdrawal_bpay_28_degrees

- [ ] 类型=`新增规则`
  **问题描述**：BPAY 还款规则的银行列表里没有 28 DEGREES，导致 28 Degrees 信用卡还款没有被识别，落到 External Transfers。例：`WITHDRAWAL MOBILE 08542472 BPAY 28 DEGREES` 现在判 External Transfers，illion 是 Credit Card Repayments。
  现状：第 28–29 行 `WITHDRAWAL\s+(MOBILE|ONLINE)\s+\d+\s+BPAY\s+(WESTPAC|LATITUDE|COLES|COMMONWEALTH|GO\s+MASTER)` 不含 `28 DEGREES`；`WITHDRAWAL MOBILE 08542472 BPAY 28 DEGREES` 落到 External Transfers。
  改为：第 28–29 行 bank 组增加 `|28\s+DEGREES`，即 `(WESTPAC|LATITUDE|COLES|COMMONWEALTH|GO\s+MASTER|28\s+DEGREES)`。
  依据：`illion对`；样本=`WITHDRAWAL MOBILE 08542472 BPAY 28 DEGREES`（illion=Credit Card Repayments，bscat=External Transfers）。
  影响：460 app / 12,446 笔中的 28 Degrees 子集；flow=`Credit Card Repayments → External Transfers`
  前置：无。
  验证：`grep -n "28\\\\s+DEGREES" liability_engine/resources/credit_card_rules.csv` 确认两行存在；样本命中；重跑后该 flow 笔数下降；`Return ... 28 DEGREES` 的 dishonour 样本不被本行命中。

### 8. liability_engine/resources/credit_card_rules.csv / payment_to_your_credit_card

- [ ] 类型=`新增规则`
  **问题描述**：现有信用卡还款规则要求 `CREDIT CARD PAYMENT/REPAYMENT` 连续出现，`Payment to your Credit Card` 这种写法不命中；第 3 项把 Internal Transfer 排除后，它会变成未分类。例：`Payment to your Credit Card - Internal transfer` 现在判 Internal Transfer，illion 是 Credit Card Repayments。
  现状：现有 debit 规则第 94 行要求 `CREDIT CARD PAYMENT/REPAYMENT` 连续，`Payment to your Credit Card - Internal transfer` 不命中；第 3 项排除 transfer 后该文本会变成未分类。
  改为：新增一行 `90,-,debit,*,regex,PAYMENT\s+TO\s+YOUR\s+CREDIT\s+CARD,0,Credit Card Repayment,credit_card,`。
  依据：`illion对`；样本=`Payment to your Credit Card - Internal transfer`（illion=Credit Card Repayments，bscat=Internal Transfer）。
  影响：253 app / 10,010 笔（Credit Card Repayments→Internal Transfer 上限）；flow=`Credit Card Repayments → Internal Transfer`
  前置：第 3 项 `internal_phrase` 排除 credit card 文本。
  验证：`grep -n "PAYMENT\\\\s+TO\\\\s+YOUR\\\\s+CREDIT\\\\s+CARD" liability_engine/resources/credit_card_rules.csv` 确认新行存在；样本命中新行；重跑后样本 bscat=`Credit Card Repayments`；`External Transfers → Credit Card Repayments` 不增加。

### 9. liability_engine/resources/dishonours_rules.csv / StepPay Refund|DEBIT CARD REFUND Afterpay

- [ ] 类型=`删除泛词`
  **问题描述**：Afterpay / StepPay 的退款入账被当成了“扣款失败”。这两家是先买后付，退款时文本里带 `REFUND`，规则直接把整笔标成 Dishonours；但这笔钱是商户退回的消费款，illion 判 Non SACC Loans。例：`StepPay Refund, K066A00470883` 现在 bscat=Dishonours、illion=Non SACC Loans；`DEBIT CARD REFUND Afterpay afterpay.com AUS` 同样。
  现状：`liability_engine/resources/dishonours_rules.csv` 第 19–20 行为 `"keyword","StepPay Refund",` 和 `"keyword","DEBIT CARD REFUND Afterpay",`；`add_bscat` 末尾的 `dishonour_mask` 会把 `is_dishonours=yes` 的行强制写成 `Dishonours`，覆盖 `product_type=bnpl` 的结果。
  改为：删除第 19、20 行；保留第 2–15 行的 `Return ... Direct Debit` 真实退票规则，以及第 16–18 行 `Refund On Fundo Loan` / `CFRefund` / `C24 Refund`。
  依据：`illion对`；样本=`StepPay Refund, K066A00470883`（illion=Non SACC Loans，bscat=Dishonours）、`DEBIT CARD REFUND Afterpay afterpay.com AUS`（illion=Non SACC Loans，bscat=Dishonours）。
  影响：874 笔（StepPay Refund）+ 534 笔（DEBIT CARD REFUND Afterpay）= 1,408 笔；flow=`Non SACC Loans → Dishonours`
  前置：无；`counterparty_keyword_rules.csv` 已有 `CBA StepPay` / `Afterpay`，`product_type=bnpl`，删除后由 `BSCAT_MAP` 落到 `Non SACC Loans`。
  验证：`grep -n "StepPay Refund\|DEBIT CARD REFUND Afterpay" liability_engine/resources/dishonours_rules.csv` 无结果；两条样本 `is_dishonours != yes`、bscat=`Non SACC Loans`；`Return ... Direct Debit ... MyPayNow` 样本仍为 `Dishonours`；重跑后 `Non SACC Loans → Dishonours` 减少 1,408 笔，`Non SACC Loans` 增加 1,408 笔。

### 10. income_engine/resources/income_pattern_rules.csv / hard_negative PAY IN 4

- [ ] 类型=`新增规则`
  **问题描述**：PayPal 的 `Pay in 4` 是 BNPL（先买后付），但文本里带 PAYPAL，命中了 gig 收入规则，被误判成工资。例：`JacarandaFinance ... PayPal Pay in 4` 现在判 Wages，illion 是 Non SACC Loans。
  现状：`hard_negative` 有 `BNPL` / `ZIP` / `AFTERPAY`，但没有 `PayPal Pay in 4`；`JacarandaFinance ... PayPal Pay in 4` 命中 `self_employed_gig \bPAYPAL\b`，bscat=Wages。
  改为：`hard_negative` 组增加 `hard_negative,\bPAY\s*IN\s*4\b,regex,PayPal Pay in 4 BNPL`。
  依据：`illion对`；样本=`JacarandaFinance 07:38AM 08Sep ML165490 PayPal Pay in 4`（illion=Non SACC Loans，bscat=Wages）。
  影响：584 app / 8,811 笔（Non SACC Loans→Wages 上限）；flow=`Non SACC Loans → Wages`
  前置：无。
  验证：`grep -n "PAY\\\\s*IN\\\\s*4" income_engine/resources/income_pattern_rules.csv` 确认新行存在；样本 `has_gig_exclusion_keyword=1`；重跑后该 flow 笔数下降；普通 PayPal 收款样本不被 `PAY IN 4` 误伤。

### 11. income_engine/resources/income_pattern_rules.csv / centrelink CCS PAYMENT|VET AFFAIRS

- [ ] 类型=`新增规则`
  **问题描述**：Centrelink 规则里有 CENTRELINK / PENSION / CHILD SUPPORT 等词，但没有 `CCS PAYMENT`（Child Care Subsidy）和 `VET AFFAIRS`（退伍军人事务），这两类补贴会漏判或落到 Wages。例：`DEPOSIT CCS PAYMENT ...` 现在为空；`Direct Credit VET AFFAIRS ...` 现在判 Wages；illion 都是 Centrelink。
  现状：`centrelink` 组第 46–61 行有 CENTRELINK / CTRLINK / SERVICES AUSTRALIA / PENSION / CHILD SUPPORT / CARER / DISABILITY，但没有 `CCS PAYMENT` / `VET AFFAIRS`；CCS 样本 bscat 空，VET AFFAIRS 样本被 `medium_income DIRECT CREDIT` 判 Wages。
  改为：`centrelink` 组增加两行：

  ```
  centrelink,\bCCS\s*PAYMENT\b,regex,Child Care Subsidy
  centrelink,\bVET\s*AFFAIRS\b,regex,Veterans Affairs
  ```

  依据：`illion对`；样本=`DEPOSIT CCS PAYMENT 000025239364 CCS`（illion=Centrelink，bscat=空）、`Direct Credit VET AFFAIRS PPF - SM757...`（illion=Centrelink，bscat=Wages）。
  影响：1560 app / 5,876 笔（Centrelink→(空)）+ 178 app / 1,988 笔（Centrelink→Wages）上限；flow=`Centrelink → (空)` / `Centrelink → Wages`
  前置：无。
  验证：`grep -n "CCS\\\\s*PAYMENT\|VET\\\\s*AFFAIRS" income_engine/resources/income_pattern_rules.csv` 确认两行存在；样本 `rule_income_centrelink=1`；重跑后样本 bscat=Centrelink；`All Other Credits` 总笔数不增加。

### 12. income_engine/resources/income_pattern_rules.csv / self_employed_gig MABLE

- [ ] 类型=`新增规则`
  **问题描述**：Mable 是护理/残障支持用工平台，报酬入账只写 `DEPOSIT MABLE ...`，没有 SALARY / PAYROLL / WAGES 等工资词，收入引擎认不出来，bscat 留空；illion 判 Wages。例：`DEPOSIT MABLE JW 10/4 9:00 am`（281.25）现在 bscat 空、illion Wages。
  现状：`income_engine/resources/income_pattern_rules.csv` 的 `self_employed_gig` 组有 `\bUBER\b` / `\bDIDI\s+PARTNER\s+PAYMENT\b` / `\bAIRTASKER\b` / `\bTIPALTI\b` 等平台词，没有 `MABLE`；`DEPOSIT MABLE ...` 不命中 `rule_income_self_employed_gig`。
  改为：`self_employed_gig` 组新增一行：`self_employed_gig,\bMABLE\b,regex,Mable disability support platform`。
  依据：`illion对`；样本=`DEPOSIT MABLE JW 10/4 9:00 am`（281.25，illion=Wages，bscat=空）、`DEPOSIT MABLE JW 6/4 9:00 am`（585.00，同上）。
  影响：`Wages → (空)` 158 笔；MABLE 全量 952 笔中含 5 笔付款 debit 不受影响；另有 303 笔 `External Transfers → All Other Credits` 和 238 笔 `All Other Credits → (空)`（均 amount>=50）会从 AOC/空转为 Wages。
  前置：无。
  验证：`grep -n "MABLE" income_engine/resources/income_pattern_rules.csv` 确认新行存在；样本 `rule_income_self_employed_gig=1`、bscat=`Wages`；`(空) → All Other Credits` 的 `VICTORIA MABLE ROSE` 13 元样本不受影响（amount<50）；重跑后 `Wages → (空)` 减少 158 笔，`External Transfers → All Other Credits` 减少 303 笔，`All Other Credits → (空)` 减少 238 笔。

### 13. income_engine/resources/income_pattern_rules.csv / strong_wage WORKPAC

- [ ] 类型=`新增规则`
  **问题描述**：WorkPac 是劳务派遣公司，工资入账写作 `WORKPAC MINING:PAYEE...`，没有 SALARY / PAYROLL / WAGES 词，收入引擎认不出来，bscat 空；illion 判 Wages。例：`WORKPAC MINING:PAYEE1436325`（2,379.00）现在 bscat 空、illion Wages。
  现状：`strong_wage` 组有 `\bSALARY\b` / `\bPAYROLL\b` / `\bWAGES?\b` / `\bEMPLOYER\b`，没有 `WORKPAC`；该文本不命中 `rule_strong_wage_keyword`。
  改为：`strong_wage` 组新增一行：`strong_wage,\bWORKPAC\b,regex,WorkPac labour hire payroll`。
  依据：`illion对`；样本=`WORKPAC MINING:PAYEE1436325`（2,379.00，illion=Wages，bscat=空）、`WORKPAC MINING:PAYEE1436325`（94.08，同上）。
  影响：42 笔 / 1 app；flow=`Wages → (空)`；其中 17 笔 50–99.99 走 `rule_strong_wage_keyword_small_amount`，其余 25 笔走 `rule_strong_wage_keyword`。
  前置：无。
  验证：`grep -n "WORKPAC" income_engine/resources/income_pattern_rules.csv` 确认新行存在；两条样本 `has_strong_wage_keyword=1`、bscat=`Wages`；94.08 样本命中 `rule_strong_wage_keyword_small_amount`；重跑后 `Wages → (空)` 减少 42 笔。

### 14. all_other_credit_engine/resources/all_other_credit_rules.csv / interest|adjustment|refund_from

- [ ] 类型=`新增规则`
  **问题描述**：All Other Credits 规则只覆盖 `CREDIT INTEREST` / `BONUS INTEREST` / `INTEREST PAID` 等组合词，裸 `INTEREST`、`ADJUSTMENT`、`REFUND FROM` 没有规则，三类入账会留空。例：`INTEREST` 和 `Refund from CBA` 现在都为空，illion 都是 All Other Credits。
  现状：文件有 `CREDIT INTEREST` / `BONUS INTEREST` / `INTEREST PAID`，但没有裸 `INTEREST`、`ADJUSTMENT`、`REFUND FROM`；三类样本 bscat 为空。
  改为：新增三行：

  ```
  keyword,INTEREST,
  keyword,ADJUSTMENT,
  keyword,REFUND FROM,
  ```

  依据：`illion对`；样本=`INTEREST`（illion=All Other Credits，bscat=空）、`Adjust Purchase ADJUSTMENT TO ACCOUNT, Card xx1816 AUD 2.45...`、`Refund from CBA, Value date: 21/07/2026, P607228608716`。
  影响：8977 app / 135,964 笔（All Other Credits→(空) 上限）；flow=`All Other Credits → (空)`
  前置：无。
  验证：`grep -n "^keyword,INTEREST,\|^keyword,ADJUSTMENT,\|^keyword,REFUND FROM," all_other_credit_engine/resources/all_other_credit_rules.csv` 确认三行存在；三条样本命中；重跑后 `All Other Credits → (空)` 笔数下降；`INTEREST PAID` / `CREDIT INTEREST` 仍命中。

### 15. fee_engine/resources/fee_classification_rules.csv / overdraw_fee

- [ ] 类型=`命中链路`
  **问题描述**：`Overdraw Fee,` 后面是逗号，现有规则却要求 Fee 后必须是空格，所以匹配失败，落到普通 Fees；同时规则没有限制 `dr_cr=debit`，退款 credit 也会被误判成 Overdrawn。例：debit 样本现在判 Fees、illion 是 Overdrawn；credit 退款现在也判 Fees、illion 是 All Other Credits。
  现状：第 6 行 `4,overdraw_fee,Overdrawn,^Overdraw\s+Fee\s+,Overdrawn Fee,regex,false,Overdraw Fee For exceeding available funds,false,` 末尾 `\s+` 要求 Fee 后必须有空白，样本 `Overdraw Fee, For exceeding...` 是逗号，规则不命中，落到 `fee_keyword_catchall`→Fees；且未限制 `dr_cr`，会命中退款 credit。
  改为：第 6 行改为 `4,overdraw_fee,Overdrawn,^Overdraw\s+Fee\b,Overdrawn Fee,regex,false,Overdraw Fee For exceeding available funds,false,debit`。
  依据：`illion对`；debit 样本=`Overdraw Fee, For exceeding available funds on 06 May, ZA4FC98724871`（illion=Overdrawn，bscat=Fees）；credit 样本=`Overdraw Fee, REFUND REDIRECTED FROM 063-097 34811203, ZA95C67396938`（illion=All Other Credits，bscat=Fees）应保持不被本行命中。
  影响：3053 app / 24,449 笔（Overdrawn→Fees 上限）；flow=`Overdrawn → Fees`
  前置：无。
  验证：`grep -n "overdraw_fee" fee_engine/resources/fee_classification_rules.csv` 确认 pattern 含 `Fee\\\\b` 且最后一列为 `debit`；debit 样本命中、credit 样本不命中；重跑后 `Overdrawn → Fees` 下降，`All Other Credits → Fees` 不增加。

### 16. fee_engine/resources/fee_classification_rules.csv / fee_keyword_catchall

- [ ] 类型=`删除泛词`
  **问题描述**：手续费兜底规则用 `\bfees?\b` 匹配任意 “fee”，没有排除 `Fee Free`；所以 `Fee Free Txn` 这种“免手续费”的转账被当成手续费。例：`Fee Free Txn From: MCCARTHY SAMUEL` 现在判 Fees，illion 是 Internal Transfer。
  现状：第 114 行 `999,fee_keyword_catchall,fee,"^(?!.*(?:BIZ\s+CORE|SCHOOL\s+FEES|BODY\s+CORP|BOXING\s+FEES|DISHONOUR)).{0,40}?\bfees?\b",Fee,regex,true,...` 不排除 `FEE FREE`；`Fee Free Txn From/To` 被判 Fees。
  改为：第 114 行负向前瞻增加 `FEE\s*FREE`，即 `^(?!.*(?:BIZ\s+CORE|SCHOOL\s+FEES|BODY\s+CORP|BOXING\s+FEES|FEE\s*FREE|DISHONOUR)).{0,40}?\bfees?\b`。
  依据：`illion对`；样本=`Fee Free Txn From: MCCARTHY SAMUEL`（illion=Internal Transfer，bscat=Fees）、`Fee Free Txn Transfer To: 814282 50889718 MCCARTHY SAMUEL`。
  影响：82 app / 36,158 笔（Internal Transfer→Fees 上限）；flow=`Internal Transfer → Fees`
  前置：无。
  验证：`grep -n "fee_keyword_catchall" fee_engine/resources/fee_classification_rules.csv` 确认 pattern 含 `FEE\\\\s*FREE`；两条样本不再命中；重跑后 `Internal Transfer → Fees` 下降；普通 `Account Fee` 样本仍命中。

### 17. catch_all_engine/resources/catch_all_rules.csv / mobile_retail|phone_retail|shop_retail

- [ ] 类型=`删除泛词`
  **问题描述**：catch-all 里 MOBILE / PHONE / SHOP 是裸关键词，转账文本里只要出现这些词就判 Retail，比如 `ANZ MOBILE BANKING PAYMENT` 和 `CommBank App Shop`。例：`ANZ MOBILE BANKING PAYMENT ...` 现在判 Retail，illion 是 External Transfers。
  现状：第 370 / 372 / 373 行 `MOBILE` / `PHONE` / `SHOP` 是裸 keyword，命中 `ANZ MOBILE BANKING PAYMENT`、`PayID Phone from CommBank App`、`CommBank App Shop` 等转账文本，bscat=Retail。
  改为：三行改为 `match_type=regex`，pattern 分别为：

  ```
  ^(?!.*\b(?:BANKING|TRANSFER|PAYMENT|PAYID|OSKO|IBANK|TRF)\b).*\bMOBILE\b
  ^(?!.*\b(?:BANKING|TRANSFER|PAYMENT|PAYID|OSKO|IBANK|TRF)\b).*\bPHONE\b
  ^(?!.*\b(?:BANKING|TRANSFER|PAYMENT|PAYID|OSKO|IBANK|TRF)\b).*\bSHOP\b
  ```

  依据：`illion对`；样本=`ANZ MOBILE BANKING PAYMENT 634416 TO Mia'S Face Fashion Pty Ltd`（illion=External Transfers，bscat=Retail）、`Transfer To Mia'S Face Fashion Pty Ltd, PayID Phone from CommBank App, iou...`、`Transfer To Sarah chamings, CommBank App Shop, N500369827883`。
  影响：3347 app / 52,590 笔（External Transfers→Retail 上限）；flow=`External Transfers → Retail`
  前置：无。
  验证：`grep -n "mobile_retail\|phone_retail\|shop_retail" catch_all_engine/resources/catch_all_rules.csv` 确认三行均为 `regex`；三条样本不再命中；重跑后该 flow 笔数下降；真实 `MOBILE PHONE SHOP` 类消费样本仍命中。

### 18. initial_engine/merchant_kb.csv / IBANK TRF TRANSFERRED

- [ ] 类型=`删除泛词`
  **问题描述**：商户库这一行的第一个关键词是裸 `IBANK TRF TRANSFERRED`，任何 IBank 转账都会命中 Automotive；后面那些 `REF CAR SERVICE` / `REF TYRES` 等具体关键词反而不起作用。例：`IBank Trf Transferred from MR C G LUCAS Mobile Banking` 现在判 Automotive，illion 是 External Transfers。
  现状：第 663238 行 keyword 列表第一个是裸 `IBANK TRF TRANSFERRED`，任意该标签文本命中 Automotive；`IBank Trf Transferred from MR C G LUCAS Mobile Banking` bscat=Automotive。
  改为：从该行 keyword 列表中删除裸 `IBANK TRF TRANSFERRED|`，该行其余 keyword（含 `REF CAR SERVICE`、`REF TYRES`、`LG MECHANICAL` 的具体短语）保持不变。
  依据：`illion对`；样本=`IBank Trf Transferred from MR C G LUCAS Mobile Banking`（illion=External Transfers，bscat=Automotive）。
  影响：2054 app / 76,256 笔（External Transfers→Automotive 上限）；flow=`External Transfers → Automotive`
  前置：无。
  验证：`grep -n "^IBANK TRF TRANSFERRED,IBANK TRF TRANSFERRED|" initial_engine/merchant_kb.csv` 无结果；`grep -n "REF CAR SERVICE\|REF TYRES\|LG MECHANICAL" initial_engine/merchant_kb.csv` 仍命中；样本不再命中；重跑后该 flow 笔数下降。

### 19. initial_engine/merchant_kb.csv / FAST PYMT OUT

- [ ] 类型=`删除泛词`
  **问题描述**：商户库这一行的第一个关键词是裸 `FAST PYMT OUT`，任何快速转账都会命中 Pet Care，哪怕收款人不是宠物相关。例：`Fast Pymt Out M WERIBONE` 现在判 Pet Care，illion 是 External Transfers。
  现状：第 846826 行 keyword 列表第一个是裸 `FAST PYMT OUT`，任意该标签文本命中 Pet Care；`Fast Pymt Out M WERIBONE` bscat=Pet Care。
  改为：从该行 keyword 列表中删除裸 `FAST PYMT OUT|`，该行其余 keyword（含 `FAST PYMT OUT PETS`、`FAST PYMT OUT PETBARN ORDER`、`FAST PYMT OUT CAT FOOD DARE` 的具体短语）保持不变。
  依据：`illion对`；样本=`Fast Pymt Out M WERIBONE`（illion=External Transfers，bscat=Pet Care）。
  影响：1255 app / 20,920 笔（External Transfers→Pet Care 上限）；flow=`External Transfers → Pet Care`
  前置：无。
  验证：`grep -n "^FAST PYMT OUT,FAST PYMT OUT|" initial_engine/merchant_kb.csv` 无结果；`grep -n "FAST PYMT OUT PETS\|FAST PYMT OUT PETBARN ORDER\|FAST PYMT OUT CAT FOOD DARE" initial_engine/merchant_kb.csv` 仍命中；样本不再命中；重跑后该 flow 笔数下降。

### 20. initial_engine/merchant_kb.csv / ELLIOTT

- [ ] 类型=`删除泛词`
  **问题描述**：商户库里有一条 `ELLIOTT` 裸人名关键词，任何含 ELLIOTT 的转账都会判 Groceries，包括普通人名之间的转账。例：`PAYMENT FROM LEWIS ELLIOTT` 现在判 Groceries，illion 是 External Transfers。
  现状：第 874560 行 `ELLIOTT,ELLIOTT,Groceries` 是裸人名关键词，任意含 ELLIOTT 的转账被判 Groceries；`PAYMENT FROM LEWIS ELLIOTT` bscat=Groceries。
  改为：删除第 874560 行。
  依据：`illion对`；样本=`PAYMENT FROM LEWIS ELLIOTT`（illion=External Transfers，bscat=Groceries）。
  影响：2164 app / 18,318 笔（External Transfers→Groceries 上限）；flow=`External Transfers → Groceries`
  前置：无。
  验证：`grep -n "^ELLIOTT,ELLIOTT,Groceries$" initial_engine/merchant_kb.csv` 无结果；样本不再命中；重跑后该 flow 笔数下降。

### 21. initial_engine/merchant_kb.csv / Chemist Warehouse Online

- [ ] 类型=`新增规则`
  **问题描述**：KB 这一行只匹配完整的 `ONLINE`，但明细里的商户名被截断成 `ONLIN`，所以 KB 不命中、bscat 为空；另外这一行的 category 还是 Retail。例：`CHEMISTWAREHOUSE ONLIN Preston AU AUS...` 现在为空，illion 是 Health。
  现状：第 10 行 `Chemist Warehouse Online,CHEMISTWAREHOUSE ONLINE|CHEMIST WAREHOUSE ONLINE,Retail` 只匹配完整 `ONLINE`，样本被截断为 `ONLIN`，KB 不命中，bscat 为空；category 也是 Retail。
  改为：第 10 行改为 `Chemist Warehouse Online,CHEMISTWAREHOUSE ONLIN|CHEMIST WAREHOUSE ONLIN|CHEMISTWAREHOUSE ONLINE|CHEMIST WAREHOUSE ONLINE,Health`。
  依据：`illion对`；样本=`CHEMISTWAREHOUSE ONLIN Preston AU AUS...`（illion=Health，bscat=空）。
  影响：5868 app / 24,812 笔（Health→(空) 上限）；flow=`Health → (空)`
  前置：无。
  验证：`grep -n "Chemist Warehouse Online" initial_engine/merchant_kb.csv` 确认含 `ONLIN` 变体且 category=`Health`；样本命中；重跑后 `Health → (空)` 下降；完整 `CHEMIST WAREHOUSE ONLINE` 样本仍命中。

### 22. classification_core/orchestrator.py / candidates_df

- [ ] 类型=`高危`
  **问题描述**：转账引擎已经把成对的 `Transfer from xx2559 CommBank app Rent` / `Transfer to xx9476 CommBank app Rent` 判成 Internal Transfer，但后面的 rent 引擎又按文本里的 `Rent` 覆盖成 Rent；`The Boost From:` 这类内部转账又被 initial 引擎按 `BOOST` 覆盖成 Dining Out。例：`Transfer from xx2559 CommBank app Rent` 现在 bscat=Rent、illion=Internal Transfer；`The Boost From: Carpenter Amanda-m` 现在 bscat=Dining Out、illion=Internal Transfer。
  现状：`orchestrator.py` 的 `candidates_df = original.copy()` 让 initial(10)、rent(800) 看到全部行；rent 的 keyword 层和 initial 的 KB 都会覆盖 transfer 已写入的 Internal Transfer。当前只有 income/liability 的覆盖被 gambling/rent 保护，Internal Transfer 没有保护。
  改为：在 `for spec in self.config.enabled_engines:` 循环内，把 `candidates_df = original.copy()` 之后的分支改成：
  ```python
  candidates_df = original.copy()
  if spec.engine_id in ("initial", "rent"):
      candidates_df = original.loc[
          ~output["bscat"].eq("Internal Transfer")
      ].copy()
  if spec.engine_id == "liability":
      already_income_mask = output["bscat"].isin(["Wages", "Centrelink"])
      candidates_df = original.loc[~already_income_mask].copy()
  if spec.engine_id in ("rent", "gambling"):
      already_protected_mask = output["classification_engine"].isin(
          ["income", "liability"]
      )
      if spec.engine_id == "rent":
          already_protected_mask |= output["bscat"].eq("Internal Transfer")
      candidates_df = original.loc[~already_protected_mask].copy()
  ```
  依据：`illion对`；样本=`Transfer from xx2559 CommBank app Rent`（illion=Internal Transfer，bscat=Rent）、`The Boost From: Carpenter Amanda-m`（illion=Internal Transfer，bscat=Dining Out）。
  影响：470 app / 16,919 笔（Internal Transfer→Rent）+ 88 app / 7,329 笔（Internal Transfer→Dining Out）= 24,248 笔（上限）；flow=`Internal Transfer → Rent` / `Internal Transfer → Dining Out`；同类 `Internal Transfer → Retail` 4,529 笔、`Internal Transfer → Groceries` 2,866 笔也会一并下降，下一轮复核。
  前置：无。先确认 transfer 引擎确实已把这两条样本写成 Internal Transfer；若 `The Boost` 样本未被 transfer 认领，本项只修 rent，`The Boost` 另加 internal 规则。
  验证：`grep -n "Internal Transfer" -A2 classification_core/orchestrator.py` 确认 initial/rent 都排除 Internal Transfer；重放两条样本 bscat=`Internal Transfer`；重跑后 `Internal Transfer → Rent`、`Internal Transfer → Dining Out` 下降；`Rent`、`Dining Out` 总笔数不增加。

### 23. initial_engine/merchant_kb.csv / NIB|AHM|RACI|SYNERGY|...

- [ ] 类型=`新增规则`
  **问题描述**：保险公司、gym、教育机构和电力公司的扣款文本里只有缩写或截断名（`NIB`、`AHM`、`RACI`、`UWU FEES`、`HUBHELLO`、`BPAY ORIGIN ENE`），KB 里只有全称或没有，initial 认不出来；这些行又被 transfer 的 Direct Debit/BPAY 泛规则先抢走，最后 bscat=External Transfers。例：`Direct Debit 000488 NIB` 现在 bscat=External Transfers、illion=Insurance；`Direct Debit 604133 UWU FEES` 现在 bscat=External Transfers、illion=Gyms。
  现状：KB 已有 `NIB HEALTH FUNDS`、`AHM HEALTH INSURANCE`、`ENERGYAUSTRALIA`、`EDSTART`、`NSWNMA`、`HOLLARDINS` 等全称，但没有样本里的裸缩写/截断名（`NIB`、`AHM`、`HOLLARD INSURANC`、`ORIGIN QLD`、`VICROADS`、`RACT`）；`HUBHELLO`、`BAAKA`、`GOULBURN WATER`、`UWU FEES`、`PSA NSW`、`TWU NSW`、`AMIEU` 完全没有行。
  改为：按下面清单新增或追加关键词（都在前 50 个变体内）：
  ```text
  line 1688  nib Health Funds            keywords 追加 NIB
  line 6544  ahm Health Insurance        keywords 追加 AHM
  新增行     RACI,RACI,Insurance
  line 3491  Origin Energy               keywords 追加 ORIGIN ENE|ORIGIN QLD|ORIGIN QLD LPG
  line 874766 HOLLARDINS                  keywords 追加 HOLLARD INSURANC
  line 8083  SYNERGY COMMBANK APP BPAY   keywords 追加 SYNERGY
  line 8030  Ergon Energy                keywords 追加 ERGON ENER
  line 6616  Fernwood Fitness            keywords 追加 FERNWOOD WOMENS
  新增行     Vicroads,VICROADS,Automotive
  新增行     RACT,RACT PTY LTD|RACT,Automotive
  新增行     Goulburn Water,GOULBURN WATER,Utilities
  新增行     Wellness Hurstville,WELLNESSHURSTVIL,Gyms and other memberships
  新增行     United Workers Union,UWU FEES,Gyms and other memberships
  新增行     PSA NSW,PSA NSW,Gyms and other memberships
  新增行     TWU NSW,TWU NSW,Gyms and other memberships
  新增行     AMIEU,AMIEU,Gyms and other memberships
  line 566599 Stella Maris College        keywords 追加 STELLA MARIS
  新增行     Baaka Day Care,BAAKA DAY CARE|BAAKA,Education
  新增行     HubHello,HUBHELLO,Education
  新增行     St Marys Primary School,STMARYSPS,Education
  新增行     RAA of SA,RAA OF SA,Automotive
  ```
  依据：`illion对`；样本=`Direct Debit 000488 NIB`（illion=Insurance，bscat=External Transfers）、`Direct Debit 010758 AHM`、`Direct Debit 250930 RACI`、`Direct Debit 604133 UWU FEES`（illion=Gyms，bscat=External Transfers）、`Direct Debit 382220 HUBHELLO`（illion=Education）、`WITHDRAWAL MOBILE 8849882 BPAY ORIGIN ENE`（illion=Utilities）、`Direct Debit ###### HOLLARD INSURANC`（304 笔，illion=Insurance）、`Transfer debit internet BPAY VICROADS`（151 笔，illion=Automotive）、`Direct Debit ###### RACT PTY LTD`（92 笔，illion=Automotive）。
  影响：951 app / 15,525 笔（Gyms→External Transfers）+ 900 app / 7,158 笔（Insurance→External Transfers）+ 978 app / 7,082 笔（Education→External Transfers）+ 1,293 app / 6,150 笔（Utilities→External Transfers）+ 2,493 app / 10,849 笔（Automotive→External Transfers）中的对应 cluster；上限 46,764 笔。
  前置：修改 KB 后运行 `python build_automaton_cache.py` 重新生成 automaton pickle；否则运行时仍用旧 pickle。
  验证：`grep -n "NIB\|AHM\|RACI\|HUBHELLO\|UWU FEES\|VICROADS\|RACT\|HOLLARD INSURANC" initial_engine/merchant_kb.csv` 确认新增行/关键词存在；重建 cache；重放样本 bscat 分别为 Insurance/Gyms/Education/Utilities/Automotive；重跑后上述 flow 下降；`External Transfers → Gyms`（bscat 对的流向）不下降。

### 24. transfer_engine/resources/transfer_external_high_confidence_rules.csv / external_direct_debit_with_bsb|external_direct_debit_in_text|external_withdrawal_mobile_bpay|external_bpay_bill_payment|external_nab_transfer_debit

- [ ] 类型=`删除泛词`
  **问题描述**：transfer 的 Direct Debit/BPAY 规则只按格式匹配，不看收款人是谁：`^direct debit \d+`、`\bdirect debit\b` 和 `^transfer debit` 会把所有保险、gym、教育、电费、路局扣款先打成 External Transfers；`WITHDRAWAL MOBILE ... BPAY` / `BPAY BILL PAYMENT` 同理。后面的 initial 只有在 KB 能匹配收款人时才会覆盖；KB 缺别名（如 `NIB`、`AHM`）时，这些行就停在 External Transfers。例：`Direct Debit 000488 NIB` 现在 bscat=External Transfers、illion=Insurance。
  现状：`transfer_external_high_confidence_rules.csv` 第 43 行 `42,external_direct_debit_with_bsb,...,^direct debit \d+,debit`、第 37 行 `36,external_nab_transfer_debit,...,^transfer debit (?!online\b),,`；`transfer_external_medium_confidence_rules.csv` 第 29/30/32 行 `128 external_withdrawal_mobile_bpay`、`129 external_bpay_bill_payment`、`131 external_direct_debit_in_text`。
  改为：五条规则都改成“带账单方排除”的 pattern，排除列表统一为：
  ```text
  nib|ahm|raci|hollardins|hollard insuranc|edstart|stella maris|hubhello|baaka|stmarysps|energyaustralia|origin|synergy|ergon|goulburn water|uwu|fernwood|wellnesshurstvil|nswnma|psa nsw|twu nsw|amieu|raa of sa|vicroads|ract
  ```
  五条 pattern 分别改为：
  ```text
  42  ^direct debit \d+(?!.*\b(?:<EXCLUDE>)\b)
  131 \bdirect debit\b(?!.*\b(?:<EXCLUDE>)\b)
  128 \bwithdrawal mobile\b.*\bbpay\b(?!.*\b(?:<EXCLUDE>)\b)
  129 \bbpay bill payment\b(?!.*\b(?:<EXCLUDE>)\b)
  36  ^transfer debit (?!online\b)(?!.*\b(?:<EXCLUDE>)\b)
  ```
  其余规则（`^direct debit$`、PayPal direct debit、`^direct debit /`、`^transfer debit internet transfer funds trns$`、`commbank app bpay`、PayID/Osko）不动。
  依据：`illion对`；样本=`Direct Debit 000488 NIB`、`Direct Debit 304177 EnergyAustralia`、`Direct Debit ###### HOLLARD INSURANC`、`TRANSFER DEBIT INTERNET BPAY SYNERGY`、`TRANSFER DEBIT INTERNET BPAY VICROADS`、`DIRECT DEBIT ###### RACT PTY LTD`、`WITHDRAWAL MOBILE 8849882 BPAY ORIGIN ENE`；个人 direct debit 样本=`Direct Debit 123456 JOHN SMITH` 应保持 External Transfers。
  影响：951 app / 15,525 笔 + 900 app / 7,158 笔 + 978 app / 7,082 笔 + 1,293 app / 6,150 笔 + 2,493 app / 10,849 笔 = 46,764 笔（上限）；flow=`Gyms and other memberships → External Transfers` / `Insurance → External Transfers` / `Education → External Transfers` / `Utilities → External Transfers` / `Automotive → External Transfers`。
  前置：先完成 §一-23（补缩写/截断名）；否则排除后 initial 仍认不出，bscat 会留空。
  验证：`grep -n "external_direct_debit_with_bsb\|external_direct_debit_in_text\|external_withdrawal_mobile_bpay\|external_bpay_bill_payment\|external_nab_transfer_debit" transfer_engine/resources/*.csv` 确认五条 pattern 都含 `?!`；重放上述账单样本 bscat 不再是 External Transfers；个人 direct debit 样本仍为 External Transfers；重跑后五个 flow 下降。

### 25. gambling_engine/resources/gambling_rules.csv / BLUEBET|SWIFTBET|MYBET|COLOSSALBET

- [ ] 类型=`新增规则`
  **问题描述**：明细里的博彩品牌常写成无空格或缩写（`BlueBet`、`SWIFTBET`、`MyBet`、`COLOSSALBET`），现有 gambling_rules 只有 `NEDS`、`BETR`、`SWIFT BET`、`MY BET DARWIN CITY` 等写法，匹配不上；这些转账又被 transfer 的 Osko/PayID 规则先认领，最后 bscat=External Transfers。例：`Bb:Osko dcdcp2c0nl0j@pay.bluebet.c` 现在 bscat=External Transfers、illion=Gambling。
  现状：规则里已有 `NEDS`、`TABCORP ASSETS PTY LTD`、`BETR`、`SWIFT BET`、`MY BET DARWIN CITY`、`KENOGO`、`MILLETT BOOKMAKING PTY LTD`，但没有 `BLUEBET`、`SWIFTBET`、`MYBET`、`COLOSSALBET`、`ULTRABET`、`BETREAL`、`BAGGYBET`、`WIZBET`，也没有银行截断后的 `MILLETT BOOKMAKI`。
  改为：在 `gambling_rules.csv` 末尾新增以下 9 行（`source=institution`，可覆盖 transfer 已认领的行）：
  ```csv
  BlueBet,Gambling,BLUEBET,keyword,0.95,BlueBet,institution
  SwiftBet,Gambling,SWIFTBET,keyword,0.95,SwiftBet,institution
  MyBet,Gambling,MYBET,keyword,0.95,MyBet,institution
  ColossalBet,Gambling,COLOSSALBET,keyword,0.95,ColossalBet,institution
  UltraBet,Gambling,ULTRABET,keyword,0.95,UltraBet,institution
  BetReal,Gambling,BETREAL,keyword,0.95,BetReal,institution
  BaggyBet,Gambling,BAGGYBET,keyword,0.95,BaggyBet,institution
  WizBet,Gambling,WIZBET,keyword,0.95,WizBet,institution
  Millett Bookmaking,Gambling,MILLETT BOOKMAKI,keyword,0.95,Millett Bookmaking,institution
  ```
  依据：`illion对`；样本=`Bb:Osko dcdcp2c0nl0j@pay.bluebet.c`（2,003 笔，illion=Gambling，bscat=External Transfers）、`Transfer To SWIFTBET, PayID Email from CommBank App`（310 笔）、`WITHDRAWAL-OSKO PAYMENT 1441293 MyBet`（145 笔）、`FAST TRANSFER FROM MILLETT BOOKMAKI CREDIT TO ACCOUNT`（31 笔）。
  影响：721 app / 12,056 笔（上限）；Top-10 cluster 3,204 笔；flow=`Gambling → External Transfers`
  前置：无。
  验证：`grep -n "BLUEBET\|SWIFTBET\|MYBET\|COLOSSALBET\|ULTRABET\|BETREAL\|BAGGYBET\|WIZBET\|MILLETT BOOKMAKING" gambling_engine/resources/gambling_rules.csv` 确认新增 9 行存在；重放三条样本 bscat=`Gambling`；重跑后 `Gambling → External Transfers` 下降；`External Transfers → Gambling`（bscat 对的流向）不下降。

### 26. transfer_engine/resources/transfer_external_high_confidence_rules.csv / missfix_e9c

- [ ] 类型=`新增规则`
  **问题描述**：`Transfer from Holiday` / `Transfer to Holiday` 是银行 App 的储蓄目标转账，不是旅行消费；现有 transfer 规则 `missfix_e9c` 已覆盖 `^transfer (to|from) ... holiday|cruise`，这两类本应已判 External Transfers；真正漏的是带 `Quick save ` 前缀的 `Quick save transfer to Holiday`，规则以 `^transfer` 开头匹配不到，catch_all 的 `HOLIDAY` 又把它判成 Travel。例：`Quick save transfer to Holiday` 现在 bscat=Travel、illion=External Transfers。
  现状：`transfer_external_high_confidence_rules.csv` 第 61 行 `147,missfix_e9c,transfer,"^transfer (?:to|from) (?:...|cruise|...|holiday|...)(?:,|$)"` 已覆盖 `Transfer from Holiday` / `Transfer to Holiday`；没有覆盖 `Quick save ` 前缀。若重跑当前 HEAD 后前两类仍是 Travel，先查 transfer 的候选过滤和 initial 是否覆盖；catch_all 已排除 prior claims，不会覆盖 transfer 已认领行。
  改为：把第 61 行 pattern 改为：
  ```csv
  "^(?:quick save )?transfer (?:to|from) (?:spending|savings|bills|everyday|moving|home|spend|life|thailand|emergency|car|course|off|work|general|christmas|shopping|cruise|japan|meow|holiday|fun|create|tami|house|books|fuel)(?:,|$)"
  ```
  其余字段不变（priority=147、rule_name=missfix_e9c、category=transfer、dr_cr 空）。
  依据：`illion对`；样本=`Transfer from Holiday`（3,731 笔，illion=External Transfers，bscat=Travel）、`Transfer to Holiday`（1,489 笔）、`Quick save transfer to Holiday`（119 笔）、`Transfer from Cruise`（87 笔）。
  影响：119 笔确定（Quick save 子集）；若重跑后前两类仍错，则上限 7,727 笔 / 673 app；flow=`External Transfers → Travel`
  前置：先按当前 HEAD 重跑 `Transfer from Holiday` / `Transfer to Holiday`；已正确则本项只改 `Quick save` 前缀；仍错误则查 transfer 候选过滤和 initial，不是补 transfer 规则。
  验证：`grep -n "missfix_e9c" transfer_engine/resources/transfer_external_high_confidence_rules.csv` 确认 pattern 含 `(?:quick save )?`；重放 `Quick save transfer to Holiday` / `Transfer from Holiday` bscat=`External Transfers`；`Transfer from Holiday Inn` 样本仍为 Travel；重跑后 `External Transfers → Travel` 下降。

### 27. initial_engine/domain/classification.py / _clean_transaction_text

- [ ] 类型=`引擎逻辑`
  **问题描述**：航司/彩票文本把品牌名和票号直接粘在一起（`QANTAS0812385507469`、`VIRGIN AU7952121190046`）；`_classify_one` 只认空格或字符串边界，`QANTAS` / `VIRGIN AU` 后面是数字，整条匹配失败，bscat 留空。例：`DEBIT CARD PURCHASE QANTAS0812385507469 NSW AUS` 现在 bscat 空、illion=Travel。
  现状：`_clean_transaction_text` 先去非字母数字、再折叠空格，但不拆字母/数字边界；`_classify_one` 的边界检查 `if end < text_len and text_clean[end] != " ": continue` 会拒绝 `QANTAS081...`。
  改为：在 `_clean_transaction_text` 的 Step 1 之后、Step 2 之前增加一行：
  ```python
  s = s.str.replace(r"(?<=[A-Z])(?=[0-9])|(?<=[0-9])(?=[A-Z])", " ", regex=True)
  ```
  依据：`illion对`；样本=`DEBIT CARD PURCHASE QANTAS0812385507469 NSW AUS`（205 笔，illion=Travel，bscat=空）、`VIRGIN AU7952121190046 BRISBANE QL AUS`（189 笔）。
  影响：3,367 app / 13,056 笔（上限）；Top-10 cluster 394 笔；flow=`Travel → (空)`；同时会让 `BP123`、`IGA123`、`7ELEVEN` 等粘连品牌更容易命中，需观察 `Automotive` / `Groceries` 是否增加。
  前置：无。
  验证：对两条样本执行 `_clean_transaction_text`，输出应含 `QANTAS 0812385507469` / `VIRGIN AU 7952121190046`；重放后 bscat=`Travel`；重跑后 `Travel → (空)` 下降；`Gambling`、`Automotive` 总笔数不异常增加。

### 28. initial_engine/merchant_kb.csv / 裸地点词

- [ ] 类型=`删除泛词`
  **问题描述**：KB 里有很多只含地点的行（`WERRIBEE VI`、`HELENSVALE QL`、`PASCOE VALE`、`ALBION PARK`、`POINT COOK`、`REDLAND BAY` 等），分类是随手挂的；匹配又是“最长关键词优先”，地点词比 `WOOLWORTHS` / `COLES` / `7 ELEVEN` 长，于是超市、加油站、餐饮都被地点词抢走。例：`WOOLWORTHS 2713 HELENSVALE QL` 现在 bscat=Retail、illion=Groceries；`MCDONALDS ALBIONPK R ALBION PARK NS` 现在 bscat=Pet Care、illion=Dining Out。
  现状：KB 的 `WERRIBEE VI`（line 866875, Retail）、`HELENSVALE QL`（856988, Retail）、`PASCOE VALE`（848325, Pet Care）等行把地点当商户；`ALBION PARK`（799035）、`POINT COOK`（805797）、`REDLAND BAY`（806171）、`SWAN HILL`（742520）、`ARANA HILLS`（845684）、`WINSTON GLADES`（825419）、`TOOWOOMBA QL`（865846）、`EMERALD HILLS`（813796）、`MAIN STREET`（817649/817650/847770）、`HIGH STREET`（780387/815701/857059）、`ST GEORGE`（657846/768321/807132）、`PASCOE VALE`（727550）等行还混着真实宠物医院/球场/诊所/银行关键词。
  改为：按下表删除裸地点关键词或整行；保留同一行里的具体商户短语：
  | 行号 | merchant_name | 操作 |
  |---:|---|---|
  | 866875 | WERRIBEE VI | 删除关键词 `WERRIBEE VI`，保留 `WERRIBEE INDOOR SP WERRIBEE VI` |
  | 856988 | HELENSVALE QL | 删除整行 |
  | 866876 | WERRIBEE WERRIBEE VI | 删除整行 |
  | 865846 | TOOWOOMBA QL | 删除整行 |
  | 848325 | PASCOE VALE | 删除裸词 `PASCOE VALE`，保留 `PASCOE VALE VETERINA*` |
  | 727550 | PASCOE VALE HOT BR | 删除裸词 `PASCOE VALE`，保留 `PASCOE VALE HOT BR*` |
  | 851422 | ARMSTRONG CREEK | 删除裸词 `ARMSTRONG CREEK`，保留 `ARMSTRONG CREEK TOWN CE*` |
  | 857151 | HOLLYWOOD PLAZA | 删除裸词 `HOLLYWOOD PLAZA`，保留 `HOLLYWOOD PLAZA NEWSAG*`、`HOLLYWOOD PLAZA SALISBURY*`、`ZLR HOLLYWOOD PLAZA` |
  | 860932 | NORTH LAKES QL | 删除裸词 `NORTH LAKES QL`，保留 `SKATE CONNECTION SP NORTH LAKES` |
  | 866734 | WARNBRO WARNBRO | 删除整行 |
  | 866762 | WARRNAMBOOL VI | 删除裸词 `WARRNAMBOOL VI`，保留 `SP WARRNAMBOOL VI` |
  | 799035 | ALBION PARK | 删除裸词 `ALBION PARK`，保留 `ALBION PARK VET*` |
  | 805797 | POINT COOK SOCCER CLUB | 删除裸词 `POINT COOK`，保留 `POINT COOK SOCCER CLU*` |
  | 806171 | REDLAND BAY GOLF CLUB | 删除裸词 `REDLAND BAY`，保留 `REDLAND BAY GOLF CLU*` |
  | 825419 | WINSTON GLADES FAMILY | 删除裸词 `WINSTON GLADES`，保留 `WINSTON GLADES FAMILY*` |
  | 845684 | ARANA HILLS | 删除裸词 `ARANA HILLS`，保留 `ARANA HILLS VETERINA*` |
  | 742520 | SWAN HILL | 删除裸词 `SWAN HILL`，保留 `SWAN HILL VETERINARY*` |
  | 813796 | EMERALD HILLS MEDICAL | 删除裸词 `EMERALD HILLS`，保留 `EMERALD HILLS MEDICAL*` |
  | 817649 | MAIN STREET COSMETIC | 删除裸词 `MAIN STREET`，保留 `MAIN STREET COSMETIC*` |
  | 817650 | MAIN STREET MEDICAL | 删除裸词 `MAIN STREET`，保留 `MAIN STREET MEDICAL*` |
  | 847770 | MAIN STREET | 删除裸词 `MAIN STREET`，保留 `MAIN STREET VETERINAR*`、`MAIN STREET VET CLINIC` |
  | 780387 | HIGH STREET DAIRY OTAHUHU | 删除裸词 `HIGH STREET`，保留 `HIGH STREET DAIRY OTAHUHU` |
  | 815701 | HIGH STREET MEDICAL | 删除裸词 `HIGH STREET`，保留 `HIGH STREET MEDICAL*` |
  | 857059 | HIGH STREET | 删除裸词 `HIGH STREET`，保留 `HIGH STREET MUSICA*` |
  | 768321 | ST GEORGE | 删除裸词 `ST GEORGE`，保留 `ST GEORGE ILLAWARRA*` |
  | 807132 | ST GEORGE OZTAG PADSTOW | 删除裸词 `ST GEORGE`，保留 `ST GEORGE OZTAG*` |
  | 657846 | St George Community Housing | 删除裸词 `ST GEORGE`，保留 `ST GEORGE COMMUNITY*`、`OSKO WITHDRAWAL RENT ST GEORGE`、`TRANSFER TO ST GEORGE COMMBANK*` |
  | 739602 | ST PETERS BAKEHOUSE RIDGEHAVEN | 删除裸词 `ST PETERS`，保留 `ST PETERS BAKEHOUSE*` |
  | 739604 | ST PETERS BAKEHOUSE THEBARTON | 删除裸词 `ST PETERS`，保留 `ST PETERS BAKEHOUSE*` |
  | 693380 | EAGLE DOVETON EUMEMMERRING | 删除裸词 `EAGLE RICHMOND RICHMOND`、`EAGLE RICHMOND`，保留其他 `EAGLE *` |
  | 756021 | YARRA GLEN BAKE HO | 删除裸词 `YARRA GLEN`，保留 `*YARRA GLEN BAKE HO*` |
  | 751003 | TREENDALE AUSTRALIND | 删除整行（`VIBE TREENDALE` 由 §一-30 新增） |
  | 874557 | DANDENONG | 删除整行（`BP DANDENONG` 由 §一-30 新增） |
  依据：`illion对`；样本=`WOOLWORTHS 2713 HELENSVALE QL`（350 笔，illion=Groceries，bscat=Retail）、`7 ELEVEN 1240 POINT COOK VI`（333 笔，illion=Groceries，bscat=Gyms）、`MCDONALDS ALBIONPK R ALBION PARK NS`（178 笔，illion=Dining Out，bscat=Pet Care）、`Wdl ATM CBA ATM WINSTON GLADES QLD`（187 笔，illion=空，bscat=Health）、`Transfer To Niels Erlandsen, CommBank App st George`（105 笔，illion=External Transfers，bscat=Gyms）。
  影响：2,667 app / 17,565 笔（Groceries→Retail）+ 1,814 app / 13,376 笔（Dining Out→Gyms）+ 791 app / 6,384 笔（Groceries→Pet Care）+ 588 app / 5,222 笔（Groceries→Gyms）+ 876 app / 5,204 笔（Dining Out→Pet Care）+ 2,877 app / 11,307 笔（Dining Out→Retail）+ 3,148 app / 12,636 笔（(空)→Health）+ 1,838 app / 12,329 笔（(空)→Pet Care）+ 810 app / 6,639 笔（External Transfers→Gyms）中对应地点 cluster；上限见各 flow。
  前置：修改 KB 后运行 `python build_automaton_cache.py` 重建 pickle。
  验证：`grep -n "^HELENSVALE QL,\|^DANDENONG,\|^TOOWOOMBA QL,\|^WERRIBEE WERRIBEE VI,\|^WARNBRO WARNBRO," initial_engine/merchant_kb.csv` 无结果；`python -c "import csv;csv.field_size_limit(10**9);B={'HIGH STREET','MAIN STREET','ST GEORGE','PASCOE VALE','WERRIBEE VI','HELENSVALE QL','TOOWOOMBA QL','ALBION PARK','POINT COOK','REDLAND BAY','WINSTON GLADES','ARANA HILLS','SWAN HILL','EMERALD HILLS','YARRA GLEN','DANDENONG','ARMSTRONG CREEK','HOLLYWOOD PLAZA','NORTH LAKES QL','WARNBRO WARNBRO','WARRNAMBOOL VI','ST PETERS'};E={'EAGLE RICHMOND','EAGLE RICHMOND RICHMOND'};print([(r['merchant_name'],k) for r in csv.DictReader(open('initial_engine/merchant_kb.csv',encoding='utf-8-sig')) for k in r['keywords'].split('|') if k in B or (r['merchant_name']=='EAGLE DOVETON EUMEMMERRING' and k in E)])"` 输出 `[]`；`grep -n "ALBION PARK VET\|POINT COOK SOCCER\|SWAN HILL VETERINARY\|ST GEORGE OZTAG\|ST GEORGE COMMUNITY\|PASCOE VALE HOT BR\|HIGH STREET DAIRY\|HIGH STREET MEDICAL\|HIGH STREET MUSICA\|ARMSTRONG CREEK TOWN CE\|HOLLYWOOD PLAZA NEWSAG\|SKATE CONNECTION SP NORTH LAKES\|SP WARRNAMBOOL VI\|MAIN STREET VETERINAR"` 仍命中；重建 cache；重放样本 bscat 分别回到 Groceries/Dining Out/空/External Transfers；上述 flow 下降。

### 29. initial_engine/merchant_kb.csv / 泛词行与重复行

- [ ] 类型=`删除泛词+改分类`
  **问题描述**：KB 里还有 `PAYPAL AUSTRALIANP`、`PURCH W/D`、`ANDROID PAY` 这类泛词行，任意 PayPal/刷卡/钱包交易都会命中 Pet Care；同一关键词又在后面出现一次，代码是“最后一行赢”，后面的错误分类会覆盖前面的正确分类。例：`POS PURCH W/D PAINE` 现在 bscat=Pet Care、illion=空；`MAROOCHY BRIDGE HOTEL` 先出现 Dining Out、后面又被 Travel 覆盖，现在 bscat=Travel、illion=Dining Out。
  现状：`PAYPAL AUSTRALIANP`（771166, Pet Care）、`PURCH W/D`（848698, Pet Care）、`ANDROID PAY`（845588, Pet Care）、`Free Choice`（4716, Pet Care）都是泛词/错误行；`LAURA STORE LAURA`（858677, Retail）覆盖前面的 Groceries 行；`VIBE OAKFORD...`（752598, Dining Out）覆盖前面的 Vibe Automotive 行；`HOTEL MAROOCHYDORE`（650820）里的 `MAROOCHY BRIDGE HOTEL` 覆盖前面的 Dining Out 行；`BEACH ROAD HOTEL BONDI BEACH`（869759, Travel）覆盖前面的 Dining Out 行；`QUEST`（874530, Travel）覆盖 `CURRY QUEST`；`GLENBOURNE INVESTMEN`（870912-870915, Travel）把餐饮消费标成 Travel。
  改为：按下表删除整行或关键词（`FAST PYMT OUT` 已在 §一-19 处理，不重复）：
  | 行号 | merchant_name | 操作 |
  |---:|---|---|
  | 771166 | PAYPAL AUSTRALIANP | 删除整行 |
  | 848698 | PURCH W/D | 删除裸词 `PURCH W D`，保留 `PURCH W D PETBARN*` |
  | 845588 | ANDROID PAY | 删除整行 |
  | 4716 | Free Choice | 删除整行（让前面 Groceries 行生效） |
  | 858677 | LAURA STORE LAURA | 删除整行（让 line 783214 的 Groceries 行生效） |
  | 752598 | VIBE OAKFORD OAKFORD AU CASH OUT PURCHASE | 删除整行（让 line 670130 的 Automotive 行生效） |
  | 650820 | HOTEL MAROOCHYDORE PTY LTD | 删除关键词 `MAROOCHY BRIDGE HOTEL`，保留 `HOTEL MAROOCHYDORE*` |
  | 869759 | BEACH ROAD HOTEL BONDI BEACH | 删除整行（让 line 676279 的 Dining Out 行生效） |
  | 874530 | QUEST | 删除整行（`Quest Hotels` 的具体酒店关键词仍保留在 5270/6785/8850/657711/872693） |
  | 870912-870915 | GLENBOURNE INVESTMEN / CANLEY VALE / CABRAMATTA / CANLEY VALE | 四行 category `Travel` → `Dining Out` |
  依据：`illion对`；样本=`POS PURCH W/D PAINE`（194 笔，illion=空，bscat=Pet Care）、`VISA Android Pay-ALH VENUES/631 ANZAC HWY GLENELG NORTH`（176 笔，illion=Dining Out，bscat=Pet Care）、`Maroochy Bridge Hotel Maroochydore`（1,788 笔，illion=Dining Out，bscat=Travel）、`Free Choice Tobacconi BANKSTOWN`（137 笔，illion=Groceries，bscat=Pet Care）、`SQ *CURRY QUEST Lucas`（144 笔，illion=Dining Out，bscat=Travel）、`Glenbourne Investmen Potts Poi`（151 笔，illion=Dining Out，bscat=Travel）。
  影响：1,838 app / 12,329 笔（(空)→Pet Care）+ 876 app / 5,204 笔（Dining Out→Pet Care）+ 1,602 app / 11,325 笔（Dining Out→Travel）+ 2,667 app / 17,565 笔（Groceries→Retail）中对应 cluster；上限见各 flow。
  前置：修改 KB 后运行 `python build_automaton_cache.py` 重建 pickle。
  验证：`python -c "import csv;csv.field_size_limit(10**9);B={'PAYPAL AUSTRALIANP','ANDROID PAY','QUEST','PURCH W D'};print([(r['merchant_name'],k) for r in csv.DictReader(open('initial_engine/merchant_kb.csv',encoding='utf-8-sig')) for k in r['keywords'].split('|') if k in B])"` 输出 `[]`；`grep -n "PURCH W D PETBARN\|HOTEL MAROOCHYDORE\|QUEST HOTELS"` 仍命中；重建 cache；重放样本 bscat 分别为空（PURCH W/D）/Dining Out（Android Pay、Maroochy、Curry Quest、Glenbourne）/Groceries（Free Choice）；上述 flow 下降。

### 30. initial_engine/merchant_kb.csv / 商户分类纠错

- [ ] 类型=`新增规则`
  **问题描述**：有些商户行第一次出现时分类是对的，后面又出现一行错误分类，最后一行赢；还有些乡村俱乐部、酒店、加油站/便利店被固定成 Gyms/Travel/Groceries。例：`KATHERINE COUNTRY CLUB` 现在 bscat=Gyms、illion=Dining Out；`LS Dirran Servo` 现在 bscat=Groceries、illion=Automotive。
  现状：`DKS VENDING PTY LTD`（604952, Retail）、`KITE RETAIL GROUP`（547542, Retail）应为 Groceries；`KATHERINE COUNTRY CLUB`（4168）、`CANBERRA RAIDERS`（765239/800426/800427/800428/800429/807626）、`REDCLIFFE LEAGUES CL`（732125/806162）、`MAGPIES WAITARA`（717513/804127）、`AKSHAYA BLACKTOWN`（769893）是带餐饮的俱乐部/餐馆，被标 Gyms/Entertainment；`ROBIN HOOD BUSINESS PTY LTD`（506070）是酒吧，被标 Travel；`LS DIRRAN SERVO`（784089, Groceries）、`MEDCO INVERELL`（785386, Groceries）覆盖前面的 Automotive 行；`GVR PTY LTD STANHOPE`（779708, Groceries）、`SOUTH GRANVIL`（738642, Dining Out）是加油站相关商户，被标错。另有 `RED CATTLE DOG CONDO CONDOBOLIN`（862484, Retail）、`THANK YOU LOVE`（865056, Retail）、`KARRATHA SPORTING AND RE`（858160, Retail）在后面重复出现，覆盖前面的 Dining Out 行；`WILDFLOWER MACARTHUR`（754604）、`LOCKINGTON COMMUNITY`（858986）、`LUCY MY LOVE`（859124）、`MSDA ENTERPRISES`（860384）直接标成 Retail。
  改为：按下表修改 category、删除重复行或新增具体商户行：
  | 行号 | merchant_name | 操作 |
  |---:|---|---|
  | 604952 | DKS VENDING PTY LTD | category `Retail` → `Groceries` |
  | 547542 | KITE RETAIL GROUP PTY LTD | category `Retail` → `Groceries` |
  | 4168 | Katherine Country Club | category `Gyms and other memberships` → `Dining Out` |
  | 765239 | CANBERRA RAIDERS | category `Gyms and other memberships` → `Dining Out` |
  | 800426 | CANBERRA RAIDERS MSHIP | category `Gyms and other memberships` → `Dining Out` |
  | 800427 | CANBERRA RAIDERS P | category `Gyms and other memberships` → `Dining Out` |
  | 800428 | CANBERRA RAIDERS SPO | category `Gyms and other memberships` → `Dining Out` |
  | 800429 | CANBERRA RAIDERS SPO GUN GAHLIN | category `Gyms and other memberships` → `Dining Out` |
  | 807626 | THE CANBERRA RAIDERS | category `Gyms and other memberships` → `Dining Out` |
  | 769893 | AKSHAYA BLACKTOWN | category `Gyms and other memberships` → `Dining Out` |
  | 732125 | REDCLIFFE LEAGUES CL | category `Entertainment` → `Dining Out` |
  | 806162 | REDCLIFFE LEAGUES CL REDCLIFFE | category `Gyms and other memberships` → `Dining Out` |
  | 717513 | MAGPIES WAITARA WAITARA | category `Gyms and other memberships` → `Dining Out` |
  | 804127 | MAGPIES WAITARA | category `Gyms and other memberships` → `Dining Out` |
  | 506070 | ROBIN HOOD BUSINESS PTY LTD | category `Travel` → `Dining Out` |
  | 784089 | LS DIRRAN SERVO | 删除整行（让 line 664409 的 Automotive 行生效） |
  | 785386 | MEDCO INVERELL INVERELL AU CASH OUT PURCHASE | 删除关键词 `MEDCO INVERELL INVERELL`、`MEDCO INVERELL INVERELL AU CASH OUT PURCHASE`、`MEDCO INVERELL INVERELL NS`，保留其他 MEDCO 地点 |
  | 779708 | GVR PTY LTD STANHOPE | category `Groceries` → `Automotive` |
  | 738642 | SOUTH GRANVIL | category `Dining Out` → `Automotive` |
  | 862484 | RED CATTLE DOG CONDO CONDOBOLIN | 删除整行（让 line 731955 的 Dining Out 行生效） |
  | 865056 | THANK YOU LOVE | 删除整行（让 line 744523-744525 的 Dining Out 行生效；裸 `THANK YOU LOVE` 由新增行覆盖） |
  | 754604 | WILDFLOWER MACARTHUR SYDNEY | category `Retail` → `Dining Out` |
  | 858986 | LOCKINGTON COMMUNITY LOCKINGTON | category `Retail` → `Dining Out` |
  | 859124 | LUCY MY LOVE | category `Retail` → `Dining Out` |
  | 860384 | MSDA ENTERPRISES L | category `Retail` → `Dining Out` |
  | 858160 | KARRATHA SPORTING AND RE | category `Retail` → `Dining Out` |
  | 新增 | BP Express | `BP EXPRESS,BP EXPRESS,Automotive` |
  | 新增 | BP Dandenong | `BP DANDENONG,BP DANDENONG,Automotive` |
  | 新增 | United Yarra Glen | `UNITED YARRA GLEN,UNITED YARRA GLEN,Automotive` |
  | 新增 | Vibe Treendale | `VIBE TREENDALE,VIBE TREENDALE,Automotive` |
  | 新增 | High Street Boonah | `HIGH STREET BOONAH,HIGH STREET BOONAH,Dining Out` |
  | 新增 | Thank You Love | `THANK YOU LOVE,THANK YOU LOVE,Dining Out` |
  依据：`illion对`；样本=`KATHERINE COUNTRY CLUB KATHERINE`（279 笔，illion=Dining Out，bscat=Gyms）、`LS Dirran Servo Dirranbandi`（311 笔，illion=Automotive，bscat=Groceries）、`ROBIN HOOD HOTEL Orange`（187 笔，illion=Dining Out，bscat=Travel）、`DKS VENDING PTY LTD Portsmith`（540 笔，illion=Groceries，bscat=Retail）、`CANBERRA RAIDERS SPO GUNGAHLIN`（174 笔，illion=Dining Out，bscat=Gyms）、`AKSHAYA BLACKTOWN`（155 笔，illion=Dining Out，bscat=Gyms）、`BP EXPRESS 2210 ST PETERS`（226 笔，illion=Automotive，bscat=Dining Out）、`Miscellaneous Debit ... HIGH STREET BOONAH`（540 笔，illion=Dining Out，bscat=Retail）、`RED CATTLE DOG CONDO CONDOBOLIN`（109 笔）、`THANK YOU LOVE TFD GRANVILLE`（77 笔）、`WILDFLOWER MACARTHUR`（88 笔）、`LOCKINGTON COMMUNITY`（94 笔）、`LUCY MY LOVE`（77 笔）、`MSDA ENTERPRISES`（76 笔）、`KARRATHA SPORTING AND RE`（64 笔），均为 illion=Dining Out、bscat=Retail。
  影响：1,814 app / 13,376 笔（Dining Out→Gyms）+ 1,602 app / 11,325 笔（Dining Out→Travel）+ 2,646 app / 14,099 笔（Automotive→Groceries）+ 2,667 app / 17,565 笔（Groceries→Retail）+ 588 app / 5,222 笔（Groceries→Gyms）+ 1,626 app / 6,905 笔（Automotive→Dining Out）+ 2,877 app / 11,307 笔（Dining Out→Retail）中对应 cluster；上限见各 flow。
  前置：修改 KB 后运行 `python build_automaton_cache.py` 重建 pickle。
  验证：`grep -n "KATHERINE COUNTRY CLUB\|DKS VENDING\|GVR PTY LTD STANHOPE\|AKSHAYA BLACKTOWN\|SOUTH GRANVIL\|THANK YOU LOVE\|RED CATTLE DOG\|WILDFLOWER MACARTHUR\|LOCKINGTON COMMUNITY\|LUCY MY LOVE\|MSDA ENTERPRISES\|KARRATHA SPORTING" initial_engine/merchant_kb.csv` 确认 category 已改且重复 Retail 行已删；`grep -n "MEDCO INVERELL INVERELL NS"` 只命中 Automotive 行；`grep -n "BP EXPRESS\|BP DANDENONG\|UNITED YARRA GLEN\|VIBE TREENDALE\|HIGH STREET BOONAH"` 只命中新增行；重建 cache；重放样本 bscat 分别为 Dining Out/Automotive/Groceries；上述 flow 下降。

### 31. catch_all_engine/resources/catch_all_rules.csv / club_membership

- [ ] 类型=`删除泛词`
  **问题描述**：catch_all 有一条裸词 `CLUB → Gyms`，任何带 `CLUB` 的商户都会被兜底成 Gyms；`NXT*CLUB RYDE`、`NXT*CSI - Club Southport` 这类俱乐部/餐饮消费因此变成 Gyms。例：`EFTPOS NXT*CLUB RYDE 728 VICTO \RYDENS AU` 现在 bscat=Gyms、illion=Dining Out。
  现状：`catch_all_rules.csv` 第 228 行 `club_membership,Gyms and other memberships,CLUB,keyword,0.7`；前面的 `LEAGUES CLUB`、`RSL CLUB`、`WORKERS CLUB`、`BOWLING CLUB` 等 confidence > 0.7 的具体规则已经能命中，裸 `CLUB` 只会误伤餐饮/场馆。
  改为：删除 `club_membership,Gyms and other memberships,CLUB,keyword,0.7`；保留所有 `*_club_*` 具体规则。另新增两行：
  ```csv
  nxt_club_dining,Dining Out,NXT CLUB,keyword,0.75
  nxt_csi_club_dining,Dining Out,NXT CSI CLUB,keyword,0.75
  ```
  依据：`illion对`；样本=`EFTPOS NXT*CLUB RYDE 728 VICTO \RYDENS AU`（258 笔，illion=Dining Out，bscat=Gyms）、`EFTPOS NXT*Csi - Club Southpo SOUTHPORT AUS`（135 笔）。
  影响：1,814 app / 13,376 笔（Dining Out→Gyms）中的 NXT 两个 cluster（258 + 135 = 393 笔）；其余只靠裸 `CLUB` 的场馆会从 Gyms 变为空。
  前置：无。
  验证：`grep -n "club_membership\|nxt_club_dining\|nxt_csi_club_dining" catch_all_engine/resources/catch_all_rules.csv` 确认裸 `CLUB` 行已删、两行新增；重放两条样本 bscat=`Dining Out`；重跑后 `Dining Out → Gyms` 下降；`Gyms and other memberships` 总笔数不异常下降。
