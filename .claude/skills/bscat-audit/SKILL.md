---
name: bscat-audit
description: 按 WORKFLOW.md 审计 BSCAT 与 illion 的分类差异，生成 output/change_list_YYYYMMDD.md。用户要求跑 BSCAT 分类问题分析、差异排查或出变更清单时使用。
---

# BSCAT 分类审计

`WORKFLOW.md` 是唯一规则源，执行前完整读取并严格按其步骤、判定标准与模板输出；本文件只规定执行入口与顺序。

## 执行顺序

1. 读 `WORKFLOW.md`，确认本次模型仓库路径、分支与 `HEAD`。
2. 取 `input/` 最新 `risk_*_dash_detail.csv` 与 `bscat_monitor_*.html`；monitor 用 `scripts/parse_monitor.py` 解析，生成 / 更新 `output/scope.json`（换期重建）。
3. 跑覆盖与聚类：`python scripts/aggregate_clusters.py <明细> output/scope.json <临时输出目录>`；覆盖率阈值固定 90%。
4. 按 WORKFLOW 第 2–3 节完成两轮分析：第一轮 Top10 聚类抽样；第二轮必做（跨流向按申请覆盖数补查、规则 × 流向反扫、未命中残差前 50）。
5. 用 `scripts/find_kb.py`、`scripts/verify_patterns.py` 核对商户库与正则改法，逐项给正例 / 反例。
6. 输出 `output/change_list_YYYYMMDD.md`（北京时间，同日追加 `_02`），只含「本次范围 / 变更清单 / 待补证据」。

## 边界

- 只在本仓库做独立匹配验证，不运行模型代码、不修改模型仓库。
- AI 不得自行确认条目；状态一律 `待审核`。
- 计数全部从当前输入重算。
