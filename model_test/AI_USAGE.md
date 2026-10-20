# 统一模型测试套件使用说明

## 入口

统一入口是：

```powershell
python model_test/run_model_test_suite.py --tests all
```

The unified suite evaluates long-dialog results against the current
`suite_config.py` `ASSISTANT_PROMPT_ACTIVE`. The legacy standalone scorer may
continue using its own `score_dialog_config.py` prompt for compatibility.

提示词沿用原测试配置：速度和延迟阶段使用 `config11.py` 的 `SYSTEM_PROMPT_TEMPLATE`；长对话阶段使用已显式复制到 `suite_config.py` 的用户/助手提示词；Function Call 和评分阶段继续使用各自原脚本的提示词配置。统一入口不再读取 `dialog_config.py`。

长对话的循环、重试、上下文窗口、函数调用、Memobase、用户模型温度与思考控制、助手温度与思考控制均在 `suite_config.py` 的 `DIALOG_*` 配置中维护。当前 `DIALOG_FUNCTION_CALL_ENABLED = False`，因此长对话请求不会发送 `tools` 或 `tool_choice`；独立的 `function_call` 阶段仍由 `functiontestformat.py` 使用完整工具集测试。长对话助手的地址、密钥和模型跟随 `TEST_BASE_URL`、`TEST_API_KEY`、`--test-model`；因此修改 `TEST_MODEL` 或使用 `--test-model` 会改变统一入口实际测试的助手模型。

默认测试模型和评审模型写在 `model_test/suite_config.py`：

- `TEST_MODEL`：被测模型，默认是豆包 2.1。
- `REVIEW_MODEL`：第 5 项对话评分使用的模型，默认是 `qwen3-max`。

也可以只对当前运行覆盖模型，不修改配置文件：

```powershell
python model_test/run_model_test_suite.py `
  --test-model doubao-seed-2-1-lite-260915 `
  --review-model qwen3-max `
  --tests all
```

## 测试项目

| 名称 | 内容 |
| --- | --- |
| `speed` | 5 次非流式和 5 次流式调用，记录总耗时、TTFT 和输出长度 |
| `dialog` | 3 个会话、每个 100 轮，DeepSeek 生成用户侧内容，被测模型生成助手侧内容 |
| `function_call` | 使用项目内 Function Call 用例，两次尝试，错误结果标红；不会执行工具 |
| `latency` | 10 次流式调用，统计 TTFT、总耗时、P50/P90 和 Token |
| `score` | 使用评审模型对对话 Excel 做三维评分 |

单项运行示例：

```powershell
python model_test/run_model_test_suite.py --tests speed
python model_test/run_model_test_suite.py --tests dialog
python model_test/run_model_test_suite.py --tests function_call
python model_test/run_model_test_suite.py --tests latency
python model_test/run_model_test_suite.py --tests score --input path\to\dialog.xlsx
```

先检查配置和输入文档、不调用 API：

```powershell
python model_test/run_model_test_suite.py --tests all --dry-run
```

## 输出

每次运行生成一个时间戳目录：

```text
model_test/outputs/model_suite/<timestamp>/
```

其中最终用户可查看的结果是：

- `<被测模型名>_总表.xlsx`：统一总表；包含测试概览、速度汇总/明细、长对话、Function Call、延迟汇总/明细和评分各维度 Sheet。只运行部分测试项时，仅写入本次已运行项并在概览中标注其余项为“未运行”。
- `run_manifest.json`：模型、阶段状态和失败原因。

各阶段原始结果只会写入运行期的 `_temporary/` 目录；总表生成成功后会自动清理。Function Call 阶段中断时，`03_function_call_running.xlsx` 会保留在结果目录根部，使用相同 `--output-dir` 重跑后可续跑。

`--tests all` 会在对话阶段成功后自动把临时对话结果传给评分阶段；单独运行 `score` 时必须提供 `--input`，该外部对话也会复制到总表的“长对话”Sheet。

速度冒烟的 10 次调用全部失败时，命令会以非零退出码结束，并在 `run_manifest.json` 和总表概览中记录失败原因。

Function Call 阶段每完成 10 次调用会写入 `03_function_call_running.xlsx`。如果运行被中断，请使用相同的 `--output-dir` 重跑 `--tests function_call`，统一脚本会从该文件中已完成的单元格继续；成功汇总后该断点文件会自动清理。

## 输入文档和配置

Function Call 用例位于：

```text
model_test/test_data/functioncall测试用例.xlsx
```

速度、Function Call、延迟和评审阶段的 API 地址与密钥仍由项目根目录的 `config11.py` 管理；长对话用户侧的模型、温度和思考控制在 `suite_config.py` 的 `DIALOG_USER_*` 中维护，其中地址和密钥读取 `config11.py` 的 DeepSeek 服务配置；助手侧跟随 `TEST_*` 与 `--test-model`。不要把密钥复制到新的脚本、日志或提交信息中。统一脚本只打印模型 ID、阶段状态和错误类型。

默认会仅对配置中的模型服务域名绕过环境代理，以避免失效的本地代理阻断测试；如环境必须通过可用代理访问这些服务，请在 `suite_config.py` 将 `BYPASS_ENV_PROXY_FOR_MODEL_HOSTS` 改为 `False`。

## 给未来 AI 的操作规则

1. 先运行 `--list-tests` 或阅读本文件，确认测试范围。
2. 修改被测模型时优先使用 `suite_config.py` 的 `TEST_MODEL`，或使用 `--test-model` 临时覆盖。
3. 修改评分模型时使用 `REVIEW_MODEL` 或 `--review-model`。
4. 首次运行先执行 `--dry-run`，确认模型配置和本地 Excel 存在。
5. 不要恢复对项目外绝对路径的依赖；测试用例必须使用 `model_test/test_data/` 内的副本。
6. Function Call 测试只评估模型是否请求了正确工具，不会执行真实工具。
7. 失败阶段会写入 `run_manifest.json`；最终退出码为非零时，应先查看对应阶段的错误信息。
