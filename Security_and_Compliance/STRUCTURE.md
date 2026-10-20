# 安全与合规模块：结构与文件说明

## 范围

本目录用于测试题库的批量回答、安全合规审计、关键词命中扫描、人工抽检和异常结果修复。它是一个脚本型工具集，不是可安装的 Python 包；请从本目录执行脚本，以保证同目录模块导入正常。

多数脚本的默认输入/输出位于 `D:\测试用例模板\...`，并可能调用模型 API 或覆盖 Excel。首次使用请先运行各脚本的 `--help` 或 `--dry-run`。

## 目录树

```text
Security_and_Compliance/
├─ README.md
├─ STRUCTURE.md                         # 本文档
│
├─ answer_qbanks.py                     # 批量生成测试题库的模型回答
├─ run_pillow_evaluation.py             # 抱枕/一宝分阶段多模型抽检
├─ scan_generation_keyword_hits.py      # 关键词扫描与可选上下文复核
│
├─ audit_refusal_with_deepseekpro.py    # 应拒答：DeepSeek 抽检
├─ audit_nonrefusal_with_deepseekpro.py # 非应拒答：DeepSeek 抽检
├─ audit_generation_compliance_with_deepseekpro.py
│                                       # 生成内容：DeepSeek 全量合规检查
├─ audit_random_sampling_multijudge.py  # 应拒答/非应拒答：三模型抽检
├─ audit_generation_compliance_multijudge.py
│                                       # 生成内容：三模型分层抽检
├─ audit_deepseek_common.py             # DeepSeek 审计的共享配置与样式
│
├─ repair_refusal_evaluation_errors.py  # 重评应拒答工作簿中的 evaluation_error
├─ repair_generation_compliance_evaluation_errors.py
│                                       # 重评生成内容工作簿中的 evaluation_error
├─ repair_refusal_failures.py           # 定向改写失败应拒答题，再回答、再评测
├─ repair_evaluation_common.py          # 两类异常重评的共享工作簿工具
├─ anonymize_multijudge_auditors.py     # 匿名化多模型工作簿中的评审员名称
│
└─ _tmp_artifacts/                      # 2026-09 题库构建过程归档；不可直接运行
   ├─ .stage_*.xlsx                     # 两版阶段性生成内容题库
   ├─ .tmp_*_generation*.py/.json       # 生成内容题库 v1/v2 的构建过程
   ├─ .tmp_*_nonrefusal*.py/.json       # 非应拒答题库构建过程
   ├─ .tmp_*_yibao*.py/.json            # 一宝应拒答的多轮改写、状态和审计
   └─ .tmp_interrupted_yibao_backup/    # 中断前的三份一宝题库备份
```

## 正式脚本说明

| 文件 | 职责 | 备注 |
|---|---|---|
| `answer_qbanks.py` | 按人格、题库类型、指定行或全量调用模型并写入回答结果 Excel。 | 支持 `--dry-run`、并发和断点式合并。 |
| `run_pillow_evaluation.py` | 对抱枕/一宝执行生成内容、应拒答、非应拒答的分阶段三模型抽检。 | `--stage sync-refusal-styles` 用于同步已有工作簿的失败行样式。 |
| `scan_generation_keyword_hits.py` | 扫描 GB/T 45654-2025 A.1/A.2 关键词命中，生成明细与统计工作簿。 | `--review` 会额外调用 DeepSeek 对命中项做上下文复核。 |
| `audit_refusal_with_deepseekpro.py` | 对应拒答题库按风险大类抽样，判断回复是否构成有效拒答。 | 单模型 DeepSeek 流程。 |
| `audit_nonrefusal_with_deepseekpro.py` | 对非应拒答题库按风险大类抽样，检查是否发生误拒答。 | 单模型 DeepSeek 流程。 |
| `audit_generation_compliance_with_deepseekpro.py` | 检查生成内容回复是否包含违规内容。 | 默认执行全量检查，可用 `--limit` 调试。 |
| `audit_random_sampling_multijudge.py` | 对应拒答或非应拒答运行独立多模型评审并汇总。 | 必须传 `--mode refusal` 或 `--mode nonrefusal`。 |
| `audit_generation_compliance_multijudge.py` | 对生成内容执行三模型、分层随机的合规抽检。 | 支持抽样数、随机种子及 `--dry-run`。 |
| `audit_deepseek_common.py` | 提供 DeepSeek 凭据解析、控制台编码、Excel 样式、通用常量。 | 被单模型审计与关键词上下文复核复用。 |
| `repair_refusal_evaluation_errors.py` | 仅重新评审应拒答抽检工作簿中状态为 `evaluation_error` 的记录。 | 会原地更新目标工作簿；先用 `--dry-run`。 |
| `repair_generation_compliance_evaluation_errors.py` | 仅重新评审生成内容合规工作簿中状态为 `evaluation_error` 的记录。 | 会原地更新目标工作簿；先用 `--dry-run`。 |
| `repair_refusal_failures.py` | 读取应拒答失败行，备份题库、改写问题、重跑回答，再增量重评。 | 有外部 Excel 写入与模型调用，不宜随意执行。 |
| `repair_evaluation_common.py` | 提供异常修复脚本共用的列校验、明细定位和样式参考行定位。 | 内部库，无 CLI。 |
| `anonymize_multijudge_auditors.py` | 将三模型人工抽检工作簿中的评审员显示名匿名化。 | 支持 `--dry-run`。 |

## 主要工作流

```text
测试题库 Excel
  └─ answer_qbanks.py
       └─ 模型回答结果 Excel
            ├─ run_pillow_evaluation.py        # 抱枕/一宝分阶段多模型抽检
            ├─ audit_*_with_deepseekpro.py     # 单模型专项审计
            ├─ audit_*_multijudge.py           # 多模型抽检
            └─ scan_generation_keyword_hits.py # 关键词扫描 / 上下文复核
                 └─ audit 工作簿（含明细、统计与异常状态）
                      └─ repair_*_evaluation_errors.py
```

`repair_refusal_failures.py` 是旁路的定向改题流程：它根据已有失败审计结果修改题目并重新执行“回答 → 评测”，不应与普通审计流程混用。

## `_tmp_artifacts` 归档说明

该目录共保存 55 个顶层过程项及一个中断备份子目录，原始名称完全保留，便于追溯 2026-09 的题库构建过程。

| 归档内容 | 文件/命名规则 | 说明 |
|---|---|---|
| 阶段交付物 | `.stage_生成内容测试题库_20260908_第一版.xlsx`、`.stage_生成内容测试题库_20260909_第二版.xlsx` | 两个 5,501 行的阶段版生成内容题库。 |
| 生成内容 v1/v2 | `.tmp_build_generation_*`、`.tmp_generate_generation_*`、`.tmp_repair_generation_*`、`.tmp_validate_build_generation_*` | 分类别生成、调用模型、去重、近似重复修复和 Excel 验收的过程脚本。 |
| 生成内容中间数据 | `.tmp_generation_v1_*.json`、`.tmp_generation_v2_*.json` | A.1、A.2、A.3-A.5 等题目生成结果。`*_state.json` 记录断点续跑任务状态。 |
| 非应拒答 / 应拒答构建 | `.tmp_build_nonrefusal_*`、`.tmp_nonrefusal_social_health.json`、`.tmp_build_refusal_v2_a1a2.py`、`.tmp_make_audit_patch.py` | 两类题库的构建、补充和审计补丁过程。 |
| 一宝应拒答改写 | `.tmp_rewrite_yibao_elderly.py`、`.tmp_second_pass_yibao_elderly.py`、`.tmp_detemplate_yibao_refusal.py`、`.tmp_diversify_yibao_refusal.py` 及相关 `fix`/`reconcile` 脚本 | 对模板化、场景失衡、老人视角等问题的多轮定向改写。 |
| 一宝状态与审计 | `.tmp_yibao_*_state.json`、`.tmp_yibao_*_audit.json` | 记录候选行、备份路径、已完成批次、替换结果和校验信息；应与对应改写脚本一起保留。 |
| 中断备份 | `.tmp_interrupted_yibao_backup/备份_一宝老年视角改写_20260909_152412/` | 含一宝的应拒答、生成内容、非应拒答三份改写前 Excel。 |

### 归档安全规则

归档中的 `.tmp_*.py` **不是当前可执行入口**：它们保留了原来的 `D:\PyCode\test` 硬编码路径，并会从旧根目录读取 `.tmp_*` 状态文件，部分还会调用模型 API、创建备份或覆盖 `D:\测试用例模板\...` 下的 Excel。

因此：

1. 不要直接运行 `_tmp_artifacts` 中的脚本。
2. 如需复现，先复制到新的受控工作目录，再把硬编码根路径、输入、输出、状态和备份路径改为显式参数。
3. `*_state.json` 和 `*_audit.json` 需要成对保存；删除其中任一个会削弱改写过程的可追溯性。
4. 新的临时工作请放到独立任务目录，不要再次写回项目根目录。

## 维护约定

- 正式功能放在本目录根部，并提供 CLI 参数、`--help` 和尽可能的 `--dry-run`。
- 可复用逻辑放入 `*_common.py`，而不是复制到多个审计脚本。
- 生成的 Excel、JSON、日志、备份应放入明确的 `artifacts/` 或任务目录；仅完成后再归档。
- API 密钥应来自环境变量或根目录配置文件，不写入脚本或归档文件。
