---
name: bscat-audit
description: 按 WORKFLOW_CLASSIFICATION.md 结合分类差异、完整交易上下文及流摘要审计 BSCAT，生成 output/change_list_YYYYMMDD.md。用户要求分类问题分析、差异排查或出变更清单时使用。
---

# BSCAT 分类审计

`WORKFLOW_CLASSIFICATION.md` 是唯一规则源，执行前完整读取并严格按其步骤、判定标准与模板输出；本文件只规定执行入口与顺序。

## 执行顺序

1. 完整读取 `WORKFLOW_CLASSIFICATION.md`，核对输入批次、日期、字段与模型版本。
2. 依次完成筛查、上下文与摘要核验、定向扩查、根因定位和预验证；命令、统计口径、停止条件以该文档为准。
3. 按该文档模板输出清单，不复用未经当前输入核实的旧统计或历史结论。

## 边界

- 只在本仓库做独立匹配验证，不运行模型代码、不修改模型仓库。
- AI 不得自行确认条目；状态一律 `待审核`。
- 计数全部从当前输入重算。
