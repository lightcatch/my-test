# Security and Compliance

模块结构、各文件职责、工作流及历史题库构建过程的归档说明，请见 [STRUCTURE.md](STRUCTURE.md)。

常用入口：

- `answer_qbanks.py`：批量生成题库回答。
- `run_pillow_evaluation.py`：抱枕和一宝的分阶段 AI 抽检；对定向修复后的工作簿同步拒答失败行样式时，使用 `--stage sync-refusal-styles`。
- `audit_random_sampling_multijudge.py --mode refusal|nonrefusal`：三模型随机抽检。
- `audit_refusal_with_deepseekpro.py`、`audit_nonrefusal_with_deepseekpro.py`、`audit_generation_compliance_with_deepseekpro.py`：DeepSeek 专项审计。
- `scan_generation_keyword_hits.py --review`：扫描关键词命中后，在同一输出工作簿执行上下文复核；`--review-model` 可覆盖复核模型。
- `repair_*_evaluation_errors.py`：仅重评工作簿中的 `evaluation_error` 记录。

已移除一次性定向修复、固定日期回滚、独立样式同步及临时关键词复核脚本。Python 字节码缓存由 `.gitignore` 忽略，不应提交。
