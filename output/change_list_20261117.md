# BSCAT 分类修改清单 2026-11-17

## 一、这次查了什么

- 数据：`input/risk_000008_dash_detail.csv`，交易日期 2026-11-16；分析日期 2026-11-17。
- 模型：`C:\Users\zhangyuliang02\Desktop\AUS_BS_CAT_Model`，`operation` 分支，版本 `850fac5`；只读，没有改代码。
- 范围：10 个重点类别 + 10 个补充类别，共检查 402,151 笔差异交易（当天 443,355 笔的 90.7%）；其余 41,204 笔不在范围或金额为零。
- 方法/口径：这里的“差异”指 BSCAT 和 illion 分类不一致的交易（illion 是对比用的外部分类结果）。按交易文本分组检查，主要模式覆盖 90.9% 的差异交易；数量按“申请 + 交易号”去重，是可能受影响的数量，不是已确认的错误数。
- 已排除：监控报告生成后模型已经修好的问题（提交 `020db20`、`85ac2f7` 等），没有重复列。

| 重点类别 | 差异交易数 |
|---|---:|
| Wages（工资） | 25,086 |
| Centrelink（政府补助） | 682 |
| All Other Credits（其他收入） | 40,098 |
| SACC Loans（SACC 贷款） | 8,378 |
| Non SACC Loans（非 SACC 贷款） | 67,515 |
| Unknown Loans（未知贷款） | 13,796 |
| Credit Card Repayments（信用卡还款） | 1,721 |
| Debt Collection（催收） | 4,002 |
| Debt Consolidation（债务合并） | 364 |
| Overdrawn（透支） | 1,700 |

## 二、建议修改（4 项）

| 编号 | 一句话问题 | 影响 | 优先级 |
|---|---|---|---:|
| CHG-001 | Sportsbet 等博彩商户名和流水号粘在一起，系统认不出 | 3,395 笔 / 18 个申请 | 高 |
| CHG-002 | 14 个博彩商户名没有配置 | 2,010 笔 / 66 个申请 | 高 |
| CHG-003 | NDIS 和育儿假补贴没有算作 Centrelink 收入 | 169 笔 / 14 个申请 | 高 |
| CHG-004 | Taptap、Remitly 的转账写法只认一部分 | 623 笔 / 34 个申请 | 中 |

### CHG-001｜高｜博彩商户名和流水号粘在一起，系统认不出

> 现在：空 / 外部转账 → 应该：Gambling（博彩）

- **问题**：银行账单里，商户名和 EFTPOS 的时间、流水号连在一起，例如 `15:46Sportsbet`、`03:52TATTS ONLINE`。系统按完整单词找 `Sportsbet`，前面粘了数字就找不到。另外 96 笔博彩提现已经被“外部转账”规则先认领，光加关键词也改不过来。
- **影响**：3,395 笔博彩交易（18 个申请，约 41.7 万澳元）没有算进博彩支出；96 笔博彩提现被当成外部转账。
- **怎么改**：改文件 `gambling_engine/engine.py`。
  1. 在 `_INSTITUTION_RULE_ID`（L74）后面加入下面的品牌拆分代码。
  2. 把 L172-L174 的 `text_inst_clean = candidates["text"].apply(clean_text_with_channel_prefix)` 改成 `.apply(_normalize_institution_text)`。

  下面这段是给 AI 改代码用的，运维同学可以跳过：

  ```python
  _INSTITUTION_BRAND_SEAM_RE = re.compile(
      r"(?i)(SPORTSBET|LADBROKES|TATTS\s+ONLINE|POINTSBET)"
  )

  def _normalize_institution_text(value: object) -> str:
      text = "" if pd.isna(value) else str(value)
      text = _INSTITUTION_BRAND_SEAM_RE.sub(r" \1 ", text)
      return clean_text_with_channel_prefix(text)
  ```

  ```python
  text_inst_clean = candidates["text"].apply(_normalize_institution_text)
  ```

- **怎么验证**：改完后重新跑同一天数据，确认：
  - tx 3168270318、3167300270、3167863800、3168275091 从空或外部转账变成 `Gambling`。
  - `LADBROKES AUSTRALIA`、`TATTS ONLINE` 等正常写法也变成 `Gambling`。
  - 不对时，把清洗函数换回 `clean_text_with_channel_prefix`。
- **注意**：96 笔提现目前被“外部转账”认领；改后也会变成 `Gambling`，需要业务确认提现是否算博彩支出。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

### CHG-002｜高｜14 个博彩商户名没有配置

> 现在：空 → 应该：Gambling（博彩）

- **问题**：除了上面 4 个大品牌，还有 14 个博彩商户名和网站没有配置，例如 `TCP*SBE NICOSIA`、`GEMBET PTY LTD`、`VoltRush Nicosia`，交易被漏掉。GEMBET 的 36 行提现，illion 标成“其他收入”，BSCAT 是空的。
- **影响**：2,010 笔交易（66 个申请，约 11 万澳元）没有算进博彩支出；其中 36 行提现存在“博彩”还是“其他收入”的归属分歧。
- **怎么改**：在 `gambling_engine/resources/gambling_rules.csv` 末尾追加 14 行：

  ```csv
  SBE NICOSIA,Gambling,SBE NICOSIA,keyword,0.95,SBE NICOSIA,institution
  PRV DOUGLAS,Gambling,PRV DOUGLAS,keyword,0.95,PRV DOUGLAS,institution
  GEMBET,Gambling,GEMBET,keyword,0.95,GEMBET,institution
  MNCH LIMASSOL,Gambling,MNCH LIMASSOL,keyword,0.95,MNCH LIMASSOL,institution
  MNCSH LIMASSOL,Gambling,MNCSH LIMASSOL,keyword,0.95,MNCSH LIMASSOL,institution
  SMK LARNACA,Gambling,SMK LARNACA,keyword,0.95,SMK LARNACA,institution
  SCWINNERS,Gambling,SCWINNERS,keyword,0.95,SCWINNERS,institution
  RSWINS,Gambling,RSWINS,keyword,0.95,RSWINS,institution
  DSLOTS,Gambling,DSLOTS,keyword,0.95,DSLOTS,institution
  SLOTRAVE,Gambling,SLOTRAVE,keyword,0.95,SLOTRAVE,institution
  RAZED NICOSIA,Gambling,RAZED NICOSIA,keyword,0.95,RAZED NICOSIA,institution
  ROCKETPLAY,Gambling,ROCKETPLAY,keyword,0.95,ROCKETPLAY,institution
  VOLTRUSH,Gambling,VOLTRUSH COM|VOLTRUSH NICOSIA,keyword,0.95,VoltRush,institution
  VS NICOSIA,Gambling,VS NICOSIA,keyword,0.95,VS NICOSIA,institution
  ```

  `VOLTRUSH` 不能只写这个词，要写 `VOLTRUSH COM|VOLTRUSH NICOSIA`，否则会把一笔正常转账（tx 3167287333）误判成博彩。
- **怎么验证**：14 个商户的样本交易应变成 `Gambling`（tx 3165366627、3166610169、3165583775、3167172892、3166477120、3167437836、3167340604、3168353350、3166471467、3166470909、3167438046、3167709703、3167287163、3166751121）；tx 3167287333 应保持 `External Transfers`；3 条 `SBE Automotive` 交易不应受影响。
- **注意**：36 行 GEMBET 提现会从空变成 `Gambling`；如果业务认为提现应留在“其他收入”，需要单独处理。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

### CHG-003｜高｜NDIS 和育儿假补贴没有算作 Centrelink 收入

> 现在：Wages / 其他收入 / 空 → 应该：Centrelink（政府补助）

- **问题**：Centrelink 的 NDIS（残障补助）和 Parental Leave Pay（育儿假补贴）写法没有配置，收入被算成工资或普通收入。例如 `Nat Disability Ins A NDIS NSW PAYMENT`、`DEPOSIT PARENTALLEAVEPAY`。
- **影响**：169 笔补助收入（14 个申请，约 13 万澳元）被算进工资或一般收入，可能高估工资收入。
- **怎么改**：在 `income_engine/resources/income_pattern_rules.csv` 末尾追加 2 行：

  ```csv
  centrelink,\bNDIS\b,regex,National Disability Insurance Scheme
  centrelink,\bPARENTAL\s*LEAVE\s*PAY\b,regex,Parental Leave Pay
  ```

- **怎么验证**：tx 3168306622（NDIS）、tx 3165370978（育儿假）应从工资、其他收入或空变成 `Centrelink`。
- **注意**：`NDIS` 是通用缩写，以后如果出现在非 Centrelink 的收入里可能误判；本批 129 笔都是残障补助。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

### CHG-004｜中｜Taptap、Remitly 的转账写法只认一部分

> 现在：空 → 应该：External Transfers（外部转账）

- **问题**：Taptap 只认 `Taptap Send Sydney Aus`，`Taptap Send` 认不出；Remitly 只认 `RMTLY`，`Remitly Australia` 认不出，交易被留空。
- **影响**：623 笔转账（34 个申请，约 12.8 万澳元）没有算进外部转账。
- **怎么改**：改文件 `transfer_engine/resources/transfer_external_high_confidence_rules.csv` 的两行。

  现在：

  ```csv
  31,external_taptap_send,transfer,^taptap send sydney aus\b,, "TapTap Send Sydney"
  48,external_remitly,transfer,\brmtly\b,,"Remitly international money transfer (RMTLY card)"
  ```

  改成：

  ```csv
  31,external_taptap_send,transfer,^taptap send\b,, "TapTap Send Sydney"
  48,external_remitly,transfer,\b(?:rmtly|remitly)\b,,"Remitly international money transfer (RMTLY card)"
  ```

- **怎么验证**：tx 3161158721（`Taptap Send`）、tx 3161158823（`Remitly Australia`）应从空变成 `External Transfers`；原来已经认出的 931 + 279 笔保持不变。
- **注意**：还有 36 笔 Taptap 文本以 `Authorisation only` 或 `Miscellaneous debit` 开头，这次改法覆盖不到，仍然留空。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

## 三、还没查清的问题

这些不影响上面 4 项修改，但建议后续补齐信息：

- **信用卡还款被标成外部转账**：最多 1,071 笔 / 20 个申请 / 约 9.4 万澳元。明细里没有银行名称和卡类型，判断不了是规则问题还是数据问题。需要：银行名称、账户类型，或模型运行日志。
- **外部转账还有约 4.9 万笔没认出来**：最多 49,087 笔。只看明细无法确认是不是转账。需要：完整的转账配对记录或账户归属信息。
- **申请 2726138 的转账被当成收入**：270 笔 `TRANSFER CREDIT` / 约 2.6 万澳元，无法确认付款人是不是本人。需要：申请人姓名或对手方账户信息。
- **申请 2719571 的分类异常**：691 笔跨多个类别，其中 3 笔 `SBE Nicosia` 没有计入 CHG-002。需要：该申请的引擎运行日志。
- **NDIS 支出 tx 3167529160 被归到宠物**：-446.18 澳元。CHG-003 只改收入，管不到支出。需要：确认这笔应该归哪一类。
- **还没纳入的博彩商户**：MULTIS、RIGHT PLATFORM、SAC、TBR 共 133 笔 / 约 6,934 澳元，商户证据不足。需要：商户资料和目标类别。
- **6 个申请没有负债摘要**：`2714689`、`2722628`、`2725355`、`2725541`、`2725684`、`2726391`。需要：确认是漏跑，还是申请本身没有负债数据。
- **其余交易没有逐条展开**：36,738 笔（395 类交易）+ 204,394 笔（56,834 个文本分组）。下一批继续查。
