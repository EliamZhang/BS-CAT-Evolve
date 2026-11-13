# BSCAT 分类优化工作流

**产出**：一份改动 To-do list，写到本仓库 `output/change_list.md`（可带日期）。归因、实施与回归都在 `AUS_BS_CAT_Model` 侧完成；本仓库只做对比分析与出清单。
**原则**：修 bscat 的错分规则，不是让 bscat 对齐 illion（illion 自身也有错分）。

**输入**（`input/`）
- `risk_000008_dash_detail.csv`：逐笔差异明细（785 万行，2026-10-08）→ 逐笔判定
- `risk_000008_dash_*.csv`：类别 / 大类 / 总体 / 趋势统计
- `bscat_monitor_*.html`：最新监控（2026-11-12）→ 优先级与筛选
- 明细与监控不同期，数字不要混用。
- 字段映射：`finv_*` = bscat 输出，`illion_*` = illion 输出，`(空)` = 无分类。

## 1. 定范围

- **P0（收入类+贷款类 10 类）**：全量看（明细 184.5 万行）。全量 = 按模式聚类，每个模式都有结论，不放心的边缘行单独看，不是逐笔人看。
- **P1（Rent、Gambling）**：优先看（仅 2 类）。
- **P2（其余 24 类）**：按 monitor 类别指标筛选——覆盖率差（finv 低于 illion）、`diff_rate` / `miss` / `extra` / 差异金额、`iou_rate`；按 `diff_count` 降序累计约 80% 取头部类别，叠加近期恶化趋势。
- 优先级以 monitor 的 LEVEL_BY_SEGMENT 为准，勿与 dash「建议优先级 P1/P2/P3」混用。

## 2. 判定

每个入选类别按 流向 × text/counterparty 聚类，逐簇判「bscat对 / illion对 / 都对 / 都错」；证据 = `text` / `counterparty` / `dr_cr` / `amount`。类别语义参考 `AUS_BS_CAT_Model/configs/category_catalog.json` 与 `CLAUDE.md`（只读，不执行该仓库代码）。

## 3. 出清单（终点）

每项 = **问题模式 + 具体改动建议 + 一句话依据 + 影响量**；位置能确定就写到文件/规则，不能确定标「待归因」。

```md
### transfer_engine/resources/transfer_rules.csv（或：待归因）
- [ ] 新增：pattern=`MOBILE PHONE BANKING FUNDS TRANSFER`，category=`Internal Transfer`，counterparty=`-`
  - 依据：xx 笔被错分为 External Transfers；影响 xx app / xx 笔
```

## 执行提示（给 AI）

- monitor HTML 的数据在 `const DATA = {…}` 里：截取后用 JSON 解析；类别级指标在 `DATA.categories[]`（`level` / `diff_rate` / `iou_rate` / `miss_count` / `extra_count` / `coverage_gap` / `diff_amount`）。
- 不执行 `AUS_BS_CAT_Model` 的代码，不做归因、不做回归；只读其规则/配置作为参考。

## 约束

- 修改优先落在 `resources/*.csv`；涉及引擎顺序 / `configs/` 的项单独标注高危。
- 只写「在哪改、改什么」，不写实施步骤、不做回归。
