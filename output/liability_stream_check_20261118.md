# Liability 分流检查（2026-11-18）

## 结论

需要调整：两条规则。第一条把催收机构的 BPAY 付款判成信用卡还款，差异明细里 32 个申请可证；第二条因为 1 分钱的四舍五入差额，把同一笔 Sunshine 贷款拆成两条流，2 个申请 / 10 条流可证。其余候选低于门槛或属于旧版已修复，不列入。

**核对范围**：摘要 7 个运行日 / 8,103 个申请；evolve 1 个运行日（2026-11-16）/ 93 个申请，两边都有的是 87 个；交集内 157 个含贷款的 app-job-log 组、1,486 条 `loan_*` 流实例已全部核完。其余 8,016 个申请没有 evolve 流水，只能做结构筛查，不能逐笔证明分流对错。输入流号是旧版 `loan_NNN`；这两条问题在当前模型仓库（`operation`，HEAD `850fac5`，工作区无改动）里仍原样存在，不是旧版已修复项。

## 问题

### LIAB-001｜高｜BPAY 通用信用卡规则把催收机构付款判成信用卡还款

- **问题**：`credit_card_rules.csv` 第 97–99 行的通用 BPAY 规则用裸 `CREDIT` 兜底，把 `BPAY CREDIT CORP`、`BPAY PIONEER CREDIT`、`MSCREDITCOLLECT` 等催收或账单付款命中为 `Miscellaneous Credit Card Repayments`（`product_type=bank`）。命中后 `add_bscat` 不再让催收 flag 覆盖（flag 只对 `product_type` 为空的行生效），这些付款最终进入信用卡还款流。`counterparty_keyword_rules.csv` 第 88 行的 Credit Corp 关键词又没有裸 `CREDIT CORP`，接不住这些行，两个缺口叠加在一起。
- **证据**：
  - `input/risk_000008_evolve_transactions.csv`：application 2724771，单 log（`job_id=1816167`、`log_id=6afa4731f47313263e9c3d5b`）有 13 笔 `ANZ INTERNET BANKING BPAY CREDIT CORP {…}`，每笔 -$200，2026-05-21 至 2026-11-05，例如 `transaction_id=3166539428`（2026-05-21）、`3166539336`（2026-06-04）、`3166539490`（2026-08-24）。`input/risk_000008_log_liability_summary.csv` 同一个 job/log 把这 13 笔拆成 `loan_003`（12 笔，repaid $2,400）和 `loan_013`（1 笔，repaid $200），两条的 `liability_category` 都是 `credit_card_repayment`；单 log 合计 $2,600。4 个 log 是同一批交易的重复导出，不能跨 log 累加。
  - `input/risk_000008_dash_detail.csv`：按 `(application_id, transaction_id)` 全期去重后，当前正则命中 1,168 行 / 109 个申请；去掉裸 `CREDIT` 后少 438 行 / 49 个申请。少掉的部分里，373 行 / 32 个申请是 `finv_Category=Credit Card Repayments`、`illion_Category=Non SACC Loans` 或 `Debt Collection`：Credit Corp 312 行 / 21 个申请（illion Non SACC），Pioneer Credit 56 行 / 9 个申请（illion Debt Collection），其余 5 行 / 2 个申请。真正的卡还款仍在：MYCARD 167 行 / 14 个申请、humm90 Mastercard / LATITUDE VISA 等 562 行 / 47 个申请；只有 1 笔 `humm90 Mas Credit`（截断的 Mastercard）会掉，影响 1 个申请。
- **影响**：32 个申请可证（差异明细 373 笔）。这些申请本该有一条 Non SACC 贷款流（Credit Corp）或 Debt Collection（Pioneer），现在被算成信用卡还款：负债结构少一条贷款流、多一条信用卡流，贷款总额和还款历史都错。
- **建议**：
  1. `liability_engine/resources/credit_card_rules.csv` 第 97–99 行（`account_type` 分别是 `-`、`transaction`、`savings` 的三条同正则），当前值：
     ```
     \bBPAY\b.*(CARD|MASTERCARD|VISA|CREDIT)|(CARD|MASTERCARD|VISA|CREDIT).*\bBPAY\b
     ```
     改成：
     ```
     \bBPAY\b.*(CARD|MASTERCARD|VISA)|(CARD|MASTERCARD|VISA).*\bBPAY\b
     ```
     即去掉两处裸 `|CREDIT`，保留 `CARD|MASTERCARD|VISA`。不要改同表的 `exclude_pattern` 列：`load_credit_card_rules` 不读这一列，改了不生效。
  2. `liability_engine/resources/counterparty_keyword_rules.csv` 第 88 行，把 `CREDIT CORP` 加进关键词列表。当前值：
     ```
     Credit Corp Loan; Credit Corp Loans; Credit Corp Fina; Credit Corp Fins; CrediCorp; CREDIT CORP GROUP LIM; CREDIT CORP GROUP LI; CREDIT CORP CommBank app BPAY; CCFS SYDNEY; CCFS,Credit Corp,personal_loan,keyword
     ```
     改成：
     ```
     Credit Corp Loan; Credit Corp Loans; Credit Corp Fina; Credit Corp Fins; CrediCorp; CREDIT CORP; CREDIT CORP GROUP LIM; CREDIT CORP GROUP LI; CREDIT CORP CommBank app BPAY; CCFS SYDNEY; CCFS,Credit Corp,personal_loan,keyword
     ```
     关键词匹配带前后字母边界（`(?<![A-Za-z])…(?![A-Za-z])`），`CREDIT CORP` 不会命中 `CREDIT CORPORATION`；第 88 行先于第 357 行的 `generic_loan` 处理，命中后 `already=True`，后面的信用卡规则会跳过。只改第 1 步会把 Credit Corp 的信用卡流去掉，但关键词表仍接不住它，可能连 Non SACC 贷款流也一起丢掉；两步一起改才完整。另有 3 笔截断成 `CREDIT COR` 的付款会变成未分类（1 个申请），要一起收掉就在同一行再加 `CREDIT COR`。

### LIAB-002｜中｜1 分钱差额把同一笔 Sunshine 贷款拆成两条流

- **问题**：`choose_amount_cluster` 只要两个金额桶有日期交集就拒绝合并，不管金额差多少。Sunshine 同一笔贷款的每期扣款因四舍五入分成 $149.10 / $149.09（或 $82.36 / $82.35）两个桶，两桶日期完全重合，于是被拆成两条流。有放款的一条匹配成 `personal_loan_non_sacc`，另一条留 `personal_loan_unknown`，摘要里同一笔贷款变成“一条正常 + 一条 unknown”。
- **证据**：
  - 2725609，单 log（`job_id=1816180`、`log_id=6afa491300182d4b17fdda45`）：`loan_003` 有 2026-08-18 credit $3,500（`transaction_id=3166557402`）和 12 笔 $149.10 debit（2026-08-26 起每周三）；`loan_004` 同日期 12 笔 $149.09，另加 2026-09-24 一笔 $299.00（`transaction_id=3166556664`）。2026-08-26 两笔参考号相邻：`D623801676137`（$149.10）和 `D623801676141`（$149.09）。摘要：`loan_003` `personal_loan_non_sacc` Ongoing，funded $3,500 / repaid $1,789.20；`loan_004` `personal_loan_unknown` Closed，funded $0 / repaid $2,088.08。
  - 2724907，单 log（`job_id=1815569`、`log_id=6afa542cf47313263e9c432f`）：`loan_005` 有 2026-08-20 credit $2,600（`transaction_id=3165420562`）和 11 笔 $82.36 debit（2026-08-27 起每周四）；`loan_002` 同日期 11 笔 $82.35，另加 2026-08-03/10/17 每周两笔 $74.02 的旧贷款。2026-08-27 两笔参考号相邻：`DT.5v3u16`（$82.36）和 `DT.5v3tz1`（$82.35）。摘要：`loan_005` `personal_loan_non_sacc` Ongoing，funded $2,600 / repaid $905.96；`loan_002` `personal_loan_unknown` Closed，repaid $1,349.97（含新贷款的 $905.85）。
- **影响**：2 个申请 / 10 条流（按 `application_id + job_id + log_id + stream_id` 计；2725609 有 2 个 job-log × 2 条流，2724907 有 3 个 log × 2 条流）。每期还款都被拆到两条流，摘要多出一条 `personal_loan_unknown`、少掉一条有放款的正常流，还款历史和贷款笔数都被拆错。两个都是 Sunshine；其他机构有没有同样问题，现有 evolve 只覆盖 87 个申请，无法证明全量影响面。
- **建议**：`liability_engine/domain/streams.py` 的 `choose_amount_cluster`（第 368 行），当前值：
  ```python
        if buckets_have_parallel_dates(candidate, cluster):
            continue
  ```
  改成：
  ```python
        if (
            buckets_have_parallel_dates(candidate, cluster)
            and abs(candidate.amount - cluster.baseline_amount)
            > STABLE_AMOUNT_SPLIT_DELTA
        ):
            continue
  ```
  `STABLE_AMOUNT_SPLIT_DELTA` 已经是 `Decimal("0.01")`（第 44 行），这里只允许金额差 ≤ 1 分的两个桶在有日期交集时合并；差 > 1 分的桶（例如 2724907 的旧贷款 $74.02 与新贷款 $82.36，差 $8.34）仍会分开。改完后 2725609 的 $149.10/$149.09 会合成一条流，2724907 的 $82.36/$82.35 会合成一条流，旧的 $74.02 贷款留在原来的 unknown 流。

**低于门槛 / 已排除（不展开）**：2725960 MoneySpot 的 119.31 + 38.89 合并是 `merge_periodic_remaining_unknown_streams` 有意合并同机构周期性 unknown 流，总量不变；2725197 Credit Corp 单笔 $543.53 credit 无还款，证据不足；2725958 Afterpay 退款/冲正被当放款，单一申请；2726301 12 笔 $15 `FEES LOAN SERVICE FEE` 在摘要成 generic_loan、evolve 无流，单一申请 / $150；ANZ Credit Card Cash Advance 相关命中已在 commit `020db20`（2026-11-13）删除，输入是旧构建，不列入。
