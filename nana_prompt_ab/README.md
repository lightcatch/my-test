# 奈奈提示词 A/B 双人对话测试

本项目每次从空白会话开始，分别跑 A、B 两套**完整独立**的奈奈提示词。对话由另一个模型扮演的用户「冉冉」驱动，双方交替说话；A/B 不共享对话历史，也不会修改模型输出。

奈奈每一轮回复前，都会先调用 `conversation-variables` 接口取当轮的 10 个变量（世界观、故事、记忆篇章、事件、画像、天气、音量、电量、充电状态、特殊场景），拼进对话提示词再发请求。**拼装结果只出现在那一轮的请求里，不会进入对话历史**——历史始终保存用户原话，否则变量内容会一轮轮自我滚大。每轮拼装后的完整文本会写进报表的 `assembled_prompt` 列供查看。

全程不装配 function / tool：请求只带 `model` 和采样参数。

代码结构与设计约束（给要改代码的 AI / 开发者看）另见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 提示词在哪里改

全部提示词文本集中在 `config.py`，改这一个文件就能重定义实验（模型、轮数、时长等运行设置同样写在 `config.py` 的 `RunnerConfig` 里，没有单独的配置文件）：

| 变量 | 作用 |
|---|---|
| `_NANA_SYSTEM_BASE` | A/B 共用的奈奈人设正文 |
| `NANA_SYSTEM_PROMPT_A` / `_B` | A/B 各自的系统提示词，当前都指向共用正文（内容相同） |
| `_NANA_DIALOG_TEMPLATE` | 每轮对话提示词，必须保留全部 10 个 `{{占位符}}` |
| `NANA_DIALOG_PROMPT_A` / `_B` | A/B 各自的对话提示词，默认共用同一份模板 |
| `USER_SIMULATOR_PROMPT` | 扮演用户「冉冉」的提示词 |
| `OPENING_USER_MESSAGE` | 每段会话的开场白 |
| `VARIANT_PROMPTS` | A/B 各自的 `sn`、system、dialog，两组可用不同设备 |

要让 A/B 真正跑出两种提示词，把 `NANA_SYSTEM_PROMPT_B` 或 `NANA_DIALOG_PROMPT_B` 换成自己的独立三引号字面量即可；测试会检查接线是否正确、以及对话模板的 10 个占位符是否齐全。

`prompt_base.txt` / `prompt_language.txt` 是旧版本的固定输入，现已不被任何代码读取，仅作备份保留。

## 直接怎么运行

```powershell
& D:\PyCode\test\nana_prompt_ab\start_runner.ps1
```

使用 `config.py` 里 `RunnerConfig` 的默认配置：连续 8 小时、每 30 分钟一批，每批 A/B 各 2 段会话、每段 4 轮。**一轮 = 用户说一句 + 奈奈回一句（2 行）**，所以一批共 `2 组 × 2 段 × 4 轮 × 2 行 = 32 行`，其中奈奈调用 16 次、模拟用户调用 12 次（第 1 轮用固定开场白，不耗模型调用）。

## 一次联调

```powershell
& D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -Once -LoopCount 1 -RoundsPerLoop 4
```

等价于直接调 python：

```powershell
& D:\PyCode\test\.venv\Scripts\python.exe D:\PyCode\test\nana_prompt_ab\runner.py --once
```

会在 `outputs/<campaign_id>/` 生成 `results.jsonl`、`report.xlsx` 和 `runner.log`。全部轮次成功才输出 `PASS`，否则输出 `FAIL` 并返回非零退出码。

## 常驻测试

程序启动后立即执行一批，之后按间隔执行，达到测试窗口后停止。任一批次出现连接、超时或其他完整性失败，程序会记录 `FAIL` 并立即停止，不会继续等待下一周期。

```powershell
& D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -DurationHours 8 -IntervalMinutes 30 -LoopCount 3 -RoundsPerLoop 5
```

换奈奈模型或模拟用户模型：

```powershell
& D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -Model doubao-seed-2-1-turbo-260628 -UserModel deepseek-v4-flash -DurationHours 2
```

关闭终端会停止常驻进程；再次启动会创建新的 campaign 目录。进程带 PID 锁，同一输出目录不能同时起两个 runner。

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--model` | 奈奈的模型 ID |
| `--user-model` | 扮演用户的模型 ID |
| `--loop-count` | 每批跑几段会话 |
| `--rounds-per-loop` | 每段会话几轮，一轮 = 用户说一句 + 奈奈回一句（奈奈每轮调用 1 次，第 1 轮的用户句用固定开场白） |
| `--duration-hours` | 总测试窗口 |
| `--interval-minutes` | 批次间隔 |
| `--timeout-seconds` | 单次请求超时 |
| `--retry-times` | 单次请求最多尝试几次 |
| `--once` | 只跑一批就退出 |
| `--output-dir` | 输出根目录 |

命令行参数优先于 `config.py` 里的默认值。其余不开放给命令行的字段（`window_messages`、`temperature`、`max_tokens`、`top_p`、`proxy_url`、`retry_backoff_seconds`）直接改 [config.py](config.py) 中 `RunnerConfig` 的字面量，每个字段上方都写了中文注释。

## 模型与网络

模型端点和密钥复用上级目录的 `config11.py`，密钥不会写入输出文件或日志。

- 奈奈走豆包公网端点，默认 `doubao-seed-2-1-lite-260915`，请求带 `temperature=0.8`、`max_tokens=1024`、`extra_body={"thinking":{"type":"disabled"}}`；默认显式使用本机 HTTP 代理 `http://127.0.0.1:10809`（改 `config.py` 里 `RunnerConfig.proxy_url`，设为 `None` 才是直连）。
- 模拟用户走内网 DeepSeek，默认 `deepseek-v4-flash`，该端点不认 `extra_body`，代理被硬置为 `None`，因此不受 `proxy_url` 影响。

## 离线测试

```powershell
& D:\PyCode\test\.venv\Scripts\python.exe -m unittest D:\PyCode\test\nana_prompt_ab\test_runner.py -v
```

用假 client + 假变量接口跑完整 campaign，覆盖：A/B 提示词独立性、10 个占位符齐全、`fill_pillow_prompt` 的空值降级、行数与角色交替、**拼装文本不泄漏进后续请求**、两侧请求参数差异、报表列结构、runner 锁。

## 输出字段

`results.jsonl` 每行一句话（一轮两行：先 user 后 assistant），字段包括：`timestamp`、`campaign_id`、`run_index`、`variant`、`model`、`session`、`round`、`role`、`raw_user_message`（用户原话）、`assembled_prompt`（本轮拼装结果，用户轮为空）、`reply_text`、`latency_ms`、`attempt_latencies_ms`、`attempts`、`error`、`skipped`、格式观测项、`prompt_hash`。

`report.xlsx` 三个工作表：

- `逐轮记录`：全部轮次明细，含 `assembled_prompt` 列。
- `汇总`：A/B 分列统计总行数、奈奈轮数、模拟用户轮数、成功率、平均/P50/P95 延时、平均输出字符数、语气标记出现率、括号出现率、**拼装降级轮数**。
- `运行批次`：每批的起止与整体结果。

变量接口不可用（8 秒超时或返回异常）时会走降级路径：该轮直接发用户原话，不拼装。这不算失败，只会在汇总的「拼装降级轮数」里体现。

格式观测（语气标记、括号动作描写）只记录，不会覆盖或过滤模型输出。
