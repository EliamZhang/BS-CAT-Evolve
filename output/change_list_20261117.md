# BSCAT 分类修改清单 2026-11-17

## 一、这次查了什么

- 数据：`input/risk_000008_dash_detail.csv`，交易日期 2026-11-16；分析日期 2026-11-17。
- 模型：`C:\Users\zhangyuliang02\Desktop\AUS_BS_CAT_Model`，`operation` 分支，版本 `850fac5`（工作区干净）；只读，没有改代码。
- 范围：13 个必看类别 + 9 个补充类别，共检查 404,239 笔差异交易（当天 443,355 笔的 91.2%）；其余 39,116 笔不在范围或金额为零。
- 方法/口径：这里的“差异”指 BSCAT 和 illion 分类不一致的交易（illion 是对比用的外部分类结果）。按交易文本分组检查，主要模式覆盖 92.2% 的差异交易；上方范围与必看类别表是差异明细行数，建议修改里的影响数量按“申请 + 交易号”去重，是可能受影响的数量，不是已确认的错误数。
- 已排除：监控报告生成后模型已经修好的问题（提交 `020db20`、`85ac2f7` 等），没有重复列。

| 必看类别 | 差异交易数 |
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
| Dishonours（拒付/退票） | 2,237 |
| Gambling（博彩） | 15,932 |
| Rent（房租） | 3,412 |

## 二、建议修改（5 项）

> 编号按影响重排：上一版的 CHG-003（NDIS/育儿假）现在是 CHG-004，CHG-004（Taptap/Remitly）现在是 CHG-005；新增“银行前缀”为 CHG-003。

| 编号 | 一句话问题 | 影响 | 优先级 |
|---|---|---|---|
| CHG-001 | Sportsbet 等博彩商户名和流水号粘在一起，系统认不出 | 3,395 笔 / 18 个申请 | 高 |
| CHG-002 | 16 个博彩商户名没有配置 | 2,055 笔 / 71 个申请 | 高 |
| CHG-003 | 商户表把银行付款前缀当成商户名，消费被错分 | 1,673 笔 / 11 个申请 | 高 |
| CHG-004 | NDIS 和育儿假补贴没有算作 Centrelink 收入 | 169 笔 / 14 个申请 | 高 |
| CHG-005 | Taptap、Remitly 的转账写法只认一部分 | 623 笔 / 34 个申请 | 中 |

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

### CHG-002｜高｜16 个博彩商户名没有配置

> 现在：空 / 外部转账 / 其他收入 → 应该：Gambling（博彩）

- **问题**：除了上面 4 个大品牌，还有 16 个博彩商户名和网站没有配置，例如 `TCP*SBE NICOSIA`、`GEMBET PTY LTD`、`VoltRush Nicosia`、`MULTIS COM AU PTY LTD`、`Right Platform`。交易被漏掉；GEMBET 的 36 行提现，illion 标成“其他收入”，BSCAT 是空的；MULTIS 和 Right Platform 的部分提现已经被“外部转账”认领。
- **影响**：2,055 笔交易（71 个申请，约 11.3 万澳元）没有算进博彩支出；其中 36 行 GEMBET 提现存在“博彩”还是“其他收入”的归属分歧，MULTIS 和 Right Platform 共有 6 笔提现被当成外部转账。SBE Nicosia 有 3 笔要等 CHG-003 先改，否则仍会被 `RETAIL PURCHASE` 抢走。
- **怎么改**：在 `gambling_engine/resources/gambling_rules.csv` 末尾追加 16 行：

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
  MULTIS,Gambling,MULTIS COM AU|MULTIS PTY LTD,keyword,0.95,MULTIS,institution
  RIGHT PLATFORM,Gambling,RIGHT PLATFORM,keyword,0.95,Right Platform,institution
  ```

  `VOLTRUSH` 不能只写这个词，要写 `VOLTRUSH COM|VOLTRUSH NICOSIA`，否则会把一笔正常转账（tx 3167287333）误判成博彩。`MULTIS` 也不能只写 `MULTIS`，否则会把一笔普通人名转账（tx 3165848854，`3 Multis Cameron Rawding`）误判成博彩。
- **怎么验证**：16 个商户的样本交易应变成 `Gambling`（tx 3165366627、3166610169、3165583775、3167172892、3166477120、3167437836、3167340604、3168353350、3166471467、3166470909、3167438046、3167709703、3167287163、3166751121、3167466502、3165928178、3165584761、3167023493）；tx 3167287333 应保持 `External Transfers`；tx 3165848854 应保持 `All Other Credits`；SBE Nicosia 的 tx 3168285163、3168285174、3168285175 在 CHG-003 改完后应变成 `Gambling`。
- **注意**：36 行 GEMBET 提现会从空变成 `Gambling`；如果业务认为提现应留在“其他收入”，需要单独处理。MULTIS 和 Right Platform 是 institution 行，会覆盖已经认领的“外部转账”，不需要再改转账规则。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

### CHG-003｜高｜商户表把银行付款前缀当成商户名，消费被错分

> 现在：Automotive（汽车）/ Pet Care（修复前输出）→ 应该：Groceries、Dining Out、External Transfers 等真实类别

- **问题**：商户表把银行通用前缀 `RETAIL PURCHASE` 当成商户名；系统按最长关键词匹配，任何以它开头的交易都先被认成“汽车”，`COLES`、`KFC` 等真实商户名反而匹配不上。`FAST PYMT OUT` 的裸关键词已经在提交 `85ac2f7` 删除，本次明细里的 1,093 笔宠物误判是修复前输出；但删掉后这些个人付款没有外部转账规则接住，重跑会变成空。
- **影响**：明细里共 1,673 笔（11 个申请，约 20.3 万澳元）：580 笔 `RETAIL PURCHASE` 仍是当前版本的汽车误判；1,093 笔 `FAST PYMT OUT` 是修复前输出，重跑后会变空，其中 1,066 笔 illion 标成外部转账；剩下 27 笔是其他类别。SBE Nicosia 的 3 笔博彩也被 `RETAIL PURCHASE` 挡住，必须先改本项，CHG-002 才会生效。
- **怎么改**：改一个商户行，再加一条外部转账规则；第 846818 行不要重复改。

  1. `initial_engine/merchant_kb.csv` 第 667315 行，只删掉单独的关键词 `RETAIL PURCHASE`，保留两个带具体商户的写法：

  现在：

  ```csv
  RETAIL PURCHASE,RETAIL PURCHASE|RETAIL PURCHASE BUDGET PETROL|RETAIL PURCHASE SUN FUELS,Automotive
  ```

  改成：

  ```csv
  RETAIL PURCHASE,RETAIL PURCHASE BUDGET PETROL|RETAIL PURCHASE SUN FUELS,Automotive
  ```

  2. 确认第 846818 行的裸关键词已删除。当前工作区应为 `FAST PYMT OUT,FAST PYMT OUT PETS|FASTPYMTOUTREF KENNELDOT|...`；如果还能看到开头的 `FAST PYMT OUT|`，说明工作区不是 `85ac2f7` 之后的版本，先核对版本，不要直接再删。

  3. 在 `transfer_engine/resources/transfer_external_high_confidence_rules.csv` 末尾追加一行，把 `FAST PYMT OUT` 后面的个人付款接住：

  ```csv
  148,external_fast_pymt_out,transfer,^fast pymt out\s+\S,, "Fast payment out"
  ```

- **怎么验证**：改完后重新跑同一天数据，确认：
  - tx 3168285938（`RETAIL PURCHASE / COLES`）应从 Automotive 变成 `Groceries`；tx 3168285952（`RETAIL PURCHASE / KFC`）应从 Automotive 变成 `Dining Out`。
  - tx 3166490237（`Fast Pymt Out ash Ashraf Abu-dabat`）当前明细是 Pet Care（修复前）；重跑当前工作区后应不再是 Pet Care（变空），加第 3 条规则后应变成 `External Transfers`。
  - tx 3168285163（`RETAIL PURCHASE-INTERNATIONAL / SBe, Nicosia`）在 CHG-002 也改完后应变成 `Gambling`。
  - 反例：tx 3165920231（`BUDGET PETROL`）应保持 `Automotive`；tx 3165772744（`Fast Pymt Out R PETTS`）加规则后应变成 `External Transfers`（`R PETTS` 是人名，不是宠物商户）。
  - 不对时，把 `RETAIL PURCHASE` 商户行恢复原样，并删掉追加的转账规则。
- **注意**：1,093 笔 `FAST PYMT OUT` 里还有 9 笔 Home Improvement、9 笔 Non SACC Loans、6 笔 Gym、2 笔 Automotive、1 笔 Centrelink；加外部规则后会统一变成 `External Transfers`，比空更接近，但具体类别还要后续补商户规则。NDIS 那一笔是支出，不是 Centrelink 收入。`RETAIL PURCHASE` 删除后，580 笔里能匹配真实商户的会归位，匹配不到的会变空，需要下一批补商户。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

### CHG-004｜高｜NDIS 和育儿假补贴没有算作 Centrelink 收入

> 现在：Wages / 其他收入 / 空 → 应该：Centrelink（政府补助）

- **问题**：Centrelink 的 NDIS（残障补助）和 Parental Leave Pay（育儿假补贴）写法没有配置，收入被算成工资或普通收入。例如 `Nat Disability Ins A NDIS NSW PAYMENT`、`DEPOSIT PARENTALLEAVEPAY`。
- **影响**：169 笔补助收入（14 个申请，约 13 万澳元）被算进工资或一般收入，可能高估工资收入。
- **怎么改**：在 `income_engine/resources/income_pattern_rules.csv` 末尾追加 2 行：

  ```csv
  centrelink,\bNDIS\b,regex,National Disability Insurance Scheme
  centrelink,\bPARENTAL\s*LEAVE\s*PAY\b,regex,Parental Leave Pay
  ```

- **怎么验证**：tx 3168306622（NDIS）、tx 3165370978（育儿假）应从工资、其他收入或空变成 `Centrelink`。
- **注意**：`NDIS` 是通用缩写，以后如果出现在非 Centrelink 的收入里可能误判；本批 169 笔都是补助收入。
- **审核**：`待审核`（运维确认后改成 `已确认` / `暂缓` / `不采纳`）。

### CHG-005｜中｜Taptap、Remitly 的转账写法只认一部分

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

这些不影响上面 5 项修改。每条都给出为什么、缺什么和下一步怎么做，按可能影响笔数从大到小。

- **外部转账还有约 4.9 万笔没认出来**（最多 49,087 笔）
  - **问题**：illion 说是“外部转账”，BSCAT 是空的。这笔数里有一部分其实是本人账户之间的转账，应该算“内部转账”，不是外部转账。
  - **为什么**：转账规则大多是银行专用的整句写法，没覆盖通用的“储蓄罐”名称；`ERROR / ERROR` 这种没有可用文本；人名转账又缺少账户归属，无法判断是本人还是他人。
  - **缺什么**：人名转账的账户归属或配对记录；没有这些，不能安全地把所有人名转账都算外部。
  - **例子**：`From Instant Access Savings`（tx 3167744935）、`Transfer from Spare funds`（tx 3167658887）、`Cover to Spending`（tx 3165591386）。这些是本人子账户之间的转账。
  - **建议的修改方案**：
    1. 在 `transfer_engine/resources/transfer_internal_regex_rules.csv` 末尾追加 6 条，覆盖 1,902 笔（12 个申请，约 19.8 万澳元）：
       ```csv
       28,internal_instant_access_savings,^(from|to) instant access savings$,, "Instant Access Savings own-account transfer"
       29,internal_spare_funds,^transfer (from|to) spare funds( c)?$,, "Spare funds own-account transfer"
       30,internal_quarterly,^transfer (from|to) quarterly$,, "Quarterly own-account transfer"
       31,internal_cover_pots,^cover (to spending|from bills)$,, "Cover to/from own-account transfer"
       32,internal_investing,^transfer (from|to) investing$,, "Investing own-account transfer"
       33,internal_rainy_day_joint,^transfer from (rainy day|joint savings)$,, "Rainy Day / joint savings own-account transfer"
       ```
    2. 先做 CHG-005（Taptap/Remitly），它会消掉其中一部分。
    3. 剩下的人名转账（如 `Dylan Harrison` 1,306 笔、`Transfer from Skyla Jane` 484 笔）不要加泛规则；下一批按银行格式分组，每种格式有 ≥10 笔样本再加精确规则。`ERROR / ERROR`（329 笔去重 / 26 个申请）没有可用文本，保持空，不要猜。
  - **验证**：tx 3167744935、3167658887、3165591386 应变成 Internal Transfer；tx 3167538889（`TRANSFER DEBIT DEBRA THORNE`）应保持 External Transfers。

- **信用卡还款被标成外部转账**（最多 623 笔 / 20 个申请 / 约 9.4 万澳元）
  - **问题**：illion 说是“信用卡还款”，BSCAT 说是“外部转账”。共 623 笔（去重后），20 个申请。分组：Westpac `TFR FROM WESTPA C CHOICE/ESAVER` 532 笔 / 13 个申请 / 约 8.1 万澳元；St George `Phone/Internet Tfr From` 45 笔 / 4 个申请 / 约 7,869 澳元；28 Degrees `Direct Debit ... 28 DEGREES` 10 笔 / 2 个申请 / 约 3,356 澳元；`MB TFR TO 44...` 36 笔 / 1 个申请 / 约 1,769 澳元。
  - **为什么**：转账规则先跑，看到 `TFR FROM ...` 就先认成外部转账；信用卡还款规则后跑，但它只对“账户类型=信用卡”的账户生效，部分还限定发卡行。账户类型不对、发卡行不在规则里，或像 28 Degrees 这样没有规则，就改不回来。
  - **缺什么**：其余申请的那笔钱在哪个账户、该账户是不是信用卡。已经抽查 3 个 Westpac 收款申请（2721989、2724164、2724663），收款账户都有 Coles、BP、PlayStation 这类日常消费，是交易账户，不是信用卡；所以这些笔更像本人从 Westpac 账户转钱进来，illion 的“信用卡还款”不一定对。
  - **例子**：tx 3166708718（app 2724164，+110.00，`C77587 TFR FROM Westpa c Choice`）的账户 5306108 有 BP、Coles、PlayStation 消费，是交易账户；tx 3165785762（app 2725156，-148.81，`Direct Debit 095574 28 DEGREES101126`）是从交易账户付 28 Degrees 信用卡，BSCAT 确实错了。
  - **建议的修改方案**：
    1. 先做 1 分钟判断：打开这笔交易的 `bank_account_id`，看同一账户有没有 Coles、BP、KFC 这类日常消费。有 → 交易账户，保持“外部转账”，把 illion 标错，不改模型；没有、只有还款/利息 → 信用卡，进入第 2 步。
    2. 对确认是信用卡的入账，在 `liability_engine/resources/credit_card_rules.csv` 追加一条不限发卡行的规则：
       ```csv
       90,credit card,credit,*,regex,\bTFR\s+FROM\s+WESTPA\s+C\s+(?:CHOICE|ESAVER)\b,0,Miscellaneous Credit Card Repayments,bank,
       ```
    3. 28 Degrees 现在就改，在同一文件追加：
       ```csv
       90,-,debit,*,regex,DIRECT\s+DEBIT\s+\d+\s+28\s+DEGREES,0,Latitude Credit Card Repayment,bank,
       ```
       注意 `DEGREES` 后面直接粘着日期（`DEGREES101126`），规则末尾不要加 `\b`，否则匹配不上。
  - **验证**：28 Degrees 组 tx 3165785762、app 2725156 应变成 Credit Card Repayments；Westpac 组先按第 1 步核对账户，如果 tx 3166708718 的账户确认是交易账户，应保持 External Transfers。

- **申请 2726138 的本人转账被算成工资**（103 笔 / 约 1.06 万澳元）
  - **问题**：`TRANSFER CREDIT DEBRA THORNEdeb` 这类本人账户之间的转入，被算成 Wages；申请人还有一笔真正的工资 `SALARY ... DEPT OF EDUCATIO`。
  - **为什么**：系统用“付款人姓名”判断是不是同一个人。转入的姓名被粘上了 `deb`/`tpg`/`feed` 后缀（`DEBRA THORNEDEB`），转出的姓名是 `DEBRA THORNE`；两者对不上，系统就当成不同的人，没拦住。
  - **缺什么**：没有；姓名和转出记录都在。
  - **例子**：tx 3167539603（+50.00，`TRANSFER CREDIT DEBRA THORNEdeb`）现在是 Wages；tx 3167538889（-200.00，`TRANSFER DEBIT DEBRA THORNE`）是同一申请人的转出；tx 3167538939（+1,023.63，`SALARY 4119168 DEPT OF EDUCATIO DEBRA A THORNE`）是真工资，应保持 Wages。
  - **建议的修改方案**：改 `income_engine/domain/classification.py` 的 `make_payer_key`（L385）。在 `tokens = [token for token in tokens if token not in PAYER_STOP_WORDS]` 后面加：
    ```python
    tokens = [
        re.sub(r"(?:DEB|TPG|FEED)$", "", token) if len(token) > 6 else token
        for token in tokens
    ]
    tokens = [token for token in tokens if len(token) >= 3]
    ```
    改完后 `DEBRA THORNEDEB` / `DEBRA THORNETPG` / `DEBRA THORNEFEED` 都会变成 `DEBRA THORNE`，和转出的 `DEBRA THORNE` 对上，`has_payer_debit` 就能拦住。
  - **验证**：tx 3167539603 应从 Wages 变成 External Transfers（或 Internal Transfer，取决于账户归属）；tx 3167538939 应保持 Wages；tx 3167538889 应保持 External Transfers。
  - **注意**：还有 5 笔 `TRANSFER CREDIT ONLINE ... deb THORNE D` 是更短的简写，这次改法覆盖不到；如果业务要求一起修，再单独处理，避免把别人的姓也当成同一个人。

- **还没纳入的博彩商户：SAC、TBR**（78 笔 / 5 个申请 / 约 4,231 澳元）
  - **问题**：illion 说是 Gambling，BSCAT 是空的。MULTIS 和 RIGHT PLATFORM 已经放进 CHG-002；剩下 SAC 73 笔（4 个申请，约 3,841 澳元）和 TBR 5 笔（1 个申请，390 澳元）。
  - **为什么**：SAC 只以 `SAC 131238003`、`SAC 1312380030`、`SAC . CYP` 这 3 种带数字或后缀的形式出现；单独写 `SAC` 会误伤普通人名或缩写。TBR 只有 1 个申请，证据不够。
  - **缺什么**：业务确认 SAC、TBR 是不是博彩商户；TBR 还需要更多申请样本。
  - **例子**：tx 3166260766（`MISCELLANEOUS DEBIT V8596 29/06 SAC +131238003 74537606180`，-1,001.00）、tx 3167346956（`VISA DEBIT PURCHASE CARD 0078 SAC 1312380030`，-10.00）、tx 3165968846（`SAC . CYP`，-10.00）、tx 3167393762（`VISA PURCHASE TCP*TBR 0236`，-100.00）。
  - **建议的修改方案**：
    1. 业务确认 SAC 是博彩后，在 `gambling_engine/resources/gambling_rules.csv` 末尾追加：
       ```csv
       SAC,Gambling,SAC 131238003|SAC 1312380030|SAC CYP,keyword,0.95,SAC,institution
       ```
       不要写单独的 `SAC`。
    2. TBR 先不加；等出现 ≥10 笔 / ≥3 个申请，再追加 `TBR,Gambling,TCP TBR,keyword,0.95,TBR,institution`。
  - **验证**：tx 3166260766、3167346956、3165968846 应变成 Gambling；tx 3167393762 保持现状，等下一批。

- **6 个申请没有负债摘要**（不涉及模型修改）
  - **问题**：`2714689`、`2722628`、`2725355`、`2725541`、`2725684`、`2726391` 有收入摘要，没有负债摘要。
  - **为什么**：已核对这 6 个申请的完整交易，没有任何贷款或信用卡类交易，模型输出空负债摘要是正确行为，不是漏跑。
  - **缺什么**：没有；如果业务仍期望有负债，需要补这些申请的账户数据。
  - **建议的修改方案**：不改模型。把这 6 个申请记到运维核对清单，下次监控再出现时直接标“无负债数据”，不要重复排查。
  - **例子**：上述 6 个申请号。

- **整体盲区：还有 239,711 笔没有逐条展开**（31,472 笔未覆盖流向 + 208,239 笔长尾）
  - **问题**：这次只看了每个入选流向的 Top10 聚类；其余 404 条未入选流向和 59,322 个长尾聚类没有逐条看。
  - **为什么**：按工作流，Top10 聚类覆盖不到的长尾不在本轮范围；这不等于没有差异，只是没查。
  - **缺什么**：下一批的时间和范围。
  - **建议的修改方案**（按顺序）：
    1. 先重跑 CHG-003，确认 `Automotive → Groceries`（1,066 笔）和 `External Transfers → Automotive`（1,003 笔）是否缩小；再查 Top15 未入选流向（11,205 笔）：`Retail → Subscription TV` 1,084；`Automotive → Groceries` 1,066；`External Transfers → Automotive` 1,003；`(空) → Health` 974；`External Transfers → Groceries` 925；`Automotive → External Transfers` 824；`Gyms and other memberships → External Transfers` 749；`External Transfers → Transport` 708；`Groceries → Retail` 679；`Dining Out → Gyms and other memberships` 654；`Non SACC Loans → (空)` 551；`Dining Out → Travel` 515；`Dining Out → Retail` 499；`Groceries → Pet Care` 495；`Dining Out → Entertainment` 479。
    2. 对 208,239 笔长尾按高风险关键词抽样：`CREDIT CARD`、`LOAN`、`DIRECT DEBIT`、`TRANSFER`、博彩品牌名，每种抽 100 笔；确认有根因再进下一版清单。
    3. 申请 2719571 除 `RETAIL PURCHASE` 外还有 60 笔跨类别差异，下一批一起看。
  - **例子**：以上流向名和笔数都来自本次 `flow_summary.csv`，可按同一脚本复算。
