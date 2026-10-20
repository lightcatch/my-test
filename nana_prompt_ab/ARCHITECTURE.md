# 项目结构说明（给其他 AI / 新接手的人看）

`nana_prompt_ab` 是一个**双人对话 A/B 测试运行器**：两套完整独立的奈奈提示词（A / B）各自从空白会话起跑，由另一个模型扮演用户「冉冉」驱动对话，奈奈每一轮回复前先调 `conversation-variables` 接口取变量、拼进对话提示词，最后把所有轮次落成 `results.jsonl` + `report.xlsx`。

面向人类的使用说明在 [README.md](README.md)。本文只讲**代码结构与不可违反的设计约束**，改动前请先读完第 3 节。

---

## 1. 文件地图

| 文件 | 职责 | 改它的频率 |
|---|---|---|
| [config.py](config.py) | **唯一**的提示词与运行设置入口：A/B 的 system / dialog 提示词、模拟用户提示词、开场白、`VARIANT_PROMPTS`、`RunnerConfig`、CLI 解析、两个 client 的构造 | 高（调实验就改这里） |
| [prompts.py](prompts.py) | 变量接口封装 + 提示词填充 + 指纹：`fetch_pillow_variables` / `fill_pillow_prompt` / `prompt_hash` / `PILLOW_VAR_KEYS` | 低 |
| [runner.py](runner.py) | 运行引擎：会话循环、请求重试、历史窗口、行记录、报表、周期调度、PID 锁、CLI 入口 | 低 |
| [test_runner.py](test_runner.py) | 11 个单元测试，用假 client + 假变量接口跑完整 campaign，**不触网** | 中（改了 runner 就补） |
| [start_runner.ps1](start_runner.ps1) | PowerShell 包装，把参数转发给 `D:\PyCode\test\.venv\Scripts\python.exe runner.py` | 低 |
| [README.md](README.md) | 人类用户手册 | 中 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 本文 | 中 |
| `prompt_base.txt` / `prompt_language.txt` | **死文件**，任何代码都不读，仅作旧版备份 | 不要动 |
| `outputs/` | 运行产物，每个 campaign 一个时间戳目录 | — |

模块依赖是单向的，没有循环：

```
start_runner.ps1  →  runner.py  →  config.py  →  config11.py（上级目录，取端点与密钥）
                                ↘  prompts.py
test_runner.py    →  config.py / prompts.py / runner.py
```

---

## 2. 一次运行的调用链

```
main(argv)
 └ load_config(args)                  # 命令行优先，缺省回落到 RunnerConfig 字面量
 └ SingleRunnerLock(outputs/)         # PID 锁，防同目录并发
 └ run_main(args, cfg, output_root)
    └ make_output_dir()               # outputs/<YYYYmmdd_HHMMSS>_<8位hex>/
    └ setup_logger(runner.log)
    └ while 未超出 window_hours:
        └ run_campaign_once(run_index)
           └ for variant in ("A", "B"):
              └ for session_index in 1..loop_count:
                 └ run_session(...)   # 下面展开
           └ build_report(report.xlsx)
           └ 行数校验：等于 2 × loop_count × 2 × rounds_per_loop 且无 error/skipped
        └ sleep 到下一个 interval_minutes 边界
```

### `run_session` 的单轮流程（核心）

```python
for round_index in 1..rounds_per_loop:
    # ① 用户说一句 —— 第 1 轮用固定开场白，不耗模型调用
    if round_index == 1:
        user_text = OPENING_USER_MESSAGE
    else:
        user_text = request(用户 client, system=USER_SIMULATOR_PROMPT,
                            历史窗口=history 的角色互换版本)
    写一条 role="user" 的行                       # assembled_prompt = ""

    history.append({"role": "user", "content": user_text})   # ← 只存原话

    # ② 奈奈回一句 —— 先取变量，再拼装
    variables = fetch_pillow_variables(sn, user_text)
    assembled = fill_pillow_prompt(dialog_prompt, variables, user_text) if variables else ""

    windowed = apply_history_window(history, window_messages=cfg.window_messages)
    wire = [*windowed[:-1], {"role": "user", "content": assembled}] if assembled else windowed
    messages = [{"role": "system", "content": system_prompt}, *wire]

    text = request(奈奈 client, messages, user_side=False)
    写一条 role="assistant" 的行                   # assembled_prompt = assembled

    history.append({"role": "assistant", "content": text})   # ← 只存原话
```

任一环节失败 → `failed = True`，本轮剩下一句和后续所有轮都写 `skipped=True` 的占位行，**行数不变**，最后 `run_campaign_once` 返回 `False`，常驻模式下立即停机。

---

## 3. 不可违反的约束

### 3.1 拼装只上 wire，不进历史（最重要）

需求原话：「连续对话不把拼装的提示词放进历史对话，但每一轮拼装的提示词都要单独开一列存放」。

如果拼装结果进了 `history`，下一轮它会被当作上文再次发给模型，10 个变量（世界观、记忆篇章、画像……）会一轮轮自我滚大并互相污染，几轮后上下文就爆了。

实现方式就是上面 `wire` 那一行：**只替换本次请求列表的最后一条**，`history` 里永远只有用户原话与模型原回复。`assembled_prompt` 落到单独的行字段里供查看。

[test_runner.py](test_runner.py) 的 `test_assembled_prompt_is_recorded_but_never_enters_history` 是这条约束的回归护栏：它给 10 个变量各塞一个唯一哨兵字符串，然后断言所有历史消息里一个哨兵都不出现。**改 `run_session` 后这个用例必须保持绿色。**

### 3.2 一轮 = 用户一句 + 奈奈一句 = 2 行

不是「一次模型调用一行」，也不是「轮 = 一次往返之外的东西」。`round` 字段在同一轮的两行上取值相同（`1,1,2,2,3,3...`）。派生公式：

| 量 | 公式 | 默认值（`loop_count=2, rounds_per_loop=4`） |
|---|---|---|
| 行数 | `2 (A/B) × loop_count × rounds_per_loop × 2` | 32 |
| 奈奈调用 | `2 × loop_count × rounds_per_loop` | 16 |
| 模拟用户调用 | `2 × loop_count × (rounds_per_loop - 1)` | 12 |
| 变量接口调用 | 同奈奈调用（只在奈奈轮前调） | 16 |

`run_campaign_once` 末尾对行数做硬校验，不等就判 FAIL。

### 3.3 不发 function / tool

`request_once` 只构造 `model` + `messages` + 采样参数，**从不**带 `tools` / `tool_choice`。测试用例 `test_request_parameters_per_side` 断言了这一点。

### 3.4 密钥不外泄

密钥来自上级目录 [config11.py](../config11.py)（`DOUBAO_API_KEY` / `DEEPSEEK_API_KEY`），只活在 client 对象里。任何日志、`results.jsonl`、`report.xlsx` 都不得写入密钥。

---

## 4. 两个模型侧的区别

| | 奈奈（被测方） | 冉冉（模拟用户） |
|---|---|---|
| client 构造 | `build_client` | `build_user_client` |
| 模型字段 | `RunnerConfig.model_name` | `RunnerConfig.user_model_name` |
| 默认模型 | `doubao-seed-2-1-lite-260915`（豆包公网） | `deepseek-v4-flash`（内网） |
| 端点 | `config11.DOUBAO_API_URL` | `config11.DEEPSEEK_API_URL` |
| 代理 | `cfg.proxy_url`，默认 `http://127.0.0.1:10809` | **硬编码 `None`**，内网地址走不了本机代理 |
| 采样参数 | `cfg.request_parameters`，含 `extra_body={"thinking":{"type":"disabled"}}` | `cfg.user_request_parameters`，内网不认 `extra_body` |
| system | `VARIANT_PROMPTS[variant]["system_prompt"]` | `USER_SIMULATOR_PROMPT` |

两边都用 `httpx.Client(trust_env=False)` + `openai.OpenAI(max_retries=0)`，重试由 `call_with_retries` 自己管（`retry_times` 次、间隔 `retry_backoff_seconds × n`），空回复也算失败。

模拟用户侧的历史做了**角色互换**（`map_history_for_deepseek`）：冉冉自己的话以 `assistant` 身份、奈奈的话以 `user` 身份喂给模拟用户模型，这样它看到的是一段"自己也在说话"的对话，而不是一堆用户消息。

---

## 5. 提示词与占位符

### A/B 接线

`config.py` 里：

```python
_NANA_SYSTEM_BASE = """..."""           # 共用正文
NANA_SYSTEM_PROMPT_A = _NANA_SYSTEM_BASE
NANA_SYSTEM_PROMPT_B = _NANA_SYSTEM_BASE   # ← 当前与 A 完全相同

_NANA_DIALOG_TEMPLATE = """...{{weather}}..."""
NANA_DIALOG_PROMPT_A = _NANA_DIALOG_TEMPLATE
NANA_DIALOG_PROMPT_B = _NANA_DIALOG_TEMPLATE

VARIANT_PROMPTS = {
    "A": {"sn": "TBZNN76YR7UUK", "system_prompt": NANA_SYSTEM_PROMPT_A, "dialog_prompt": NANA_DIALOG_PROMPT_A},
    "B": {"sn": "TBZNN76YR7UUK", "system_prompt": NANA_SYSTEM_PROMPT_B, "dialog_prompt": NANA_DIALOG_PROMPT_B},
}
```

**要让 A/B 真正不同，只需把 `NANA_SYSTEM_PROMPT_B` 或 `NANA_DIALOG_PROMPT_B` 换成独立的三引号字面量。** `VARIANT_PROMPTS[variant]` 的 `sn` 也可以各指向一台设备。

注意：`test_variant_prompts_are_wired_to_their_own_constants` 只校验接线（每组非空、挂在自己的常量上），**不**要求 A ≠ B——因为两组内容由使用者决定，写死"必须不同"会在使用者刻意做等值时误报。

### 10 个占位符

`prompts.PILLOW_VAR_KEYS`，对话模板里必须全部存在（测试会查）：

`worldview`、`story`、`memory_chapter`、`event_section`、`profile_section`、`weather`、`Volume`、`charging_status`、`special_scenarios`、`battery_notification`

注意 `Volume` 是大写 V，与接口字段一致，别手滑改小写。

### 变量接口

```
POST http://10.10.10.24:8500/pillow/remote/device/conversation-variables
Headers: Crknife-Internal-Call: true, Accept-Language: zh-CN
Body:    {"sn": "<VARIANT_PROMPTS[variant]['sn']>", "userInput": "<用户原话>"}
Timeout: 8.0s
```

失败策略是**刻意设计**的：任何异常 / 非 dict 返回 / 超时 → 返回 `None` → `assembled = ""` → 该轮直接发用户原话。这**不算失败**，不计入 `error`，只在 `汇总` 表的「拼装降级轮数」里体现。长跑时偶发降级是正常现象。

### 填充规则

`fill_pillow_prompt` 逐键 `str.replace("{{key}}", value)`，缺失键或 `None` 一律按空串填，最后 `rstrip() + "\n" + user_input`——用户原话追加在拼装文本末尾。

---

## 6. 设置入口

**没有 `settings.json`。** 所有默认值都在 [config.py](config.py) 的 `RunnerConfig`（`@dataclass(frozen=True)`）里，每个字段上方有中文注释，直接改字面量。命令行参数经 `load_config` 覆盖同名默认值，命令行为 `None` 时回落。

| 字段 | 含义 |
|---|---|
| `model_name` / `user_model_name` | 奈奈 / 模拟用户的模型 ID |
| `loop_count` | 每批几段会话（每段 A、B 各起一次） |
| `rounds_per_loop` | 每段会话几轮（一轮 = 2 行） |
| `window_messages` | 发给模型的历史窗口长度（条消息），20 条约等于最近 10 轮 |
| `interval_minutes` / `window_hours` | 批次间隔 / 总测试窗口 |
| `temperature` / `max_tokens` / `top_p` | 采样参数，两侧共用 |
| `timeout_seconds` / `retry_times` / `retry_backoff_seconds` | 网络重试策略 |
| `proxy_url` | 仅奈奈侧生效，`None` 为直连 |

CLI（[config.py](config.py) 的 `parser()`）：`--model` `--user-model` `--loop-count` `--rounds-per-loop` `--duration-hours` `--interval-minutes` `--timeout-seconds` `--retry-times` `--once` `--output-dir`。

---

## 7. 输出产物

每个 campaign 一个目录 `outputs/<YYYYmmdd_HHMMSS>_<8位hex>/`：

- **`results.jsonl`** — 每行一句话（逐行追加、立即 flush，进程被杀也不丢已完成的轮次）。字段 21 个：

  `timestamp` `campaign_id` `run_index` `variant` `model` `session` `round` `role`
  `raw_user_message` `assembled_prompt` `reply_text` `latency_ms` `attempt_latencies_ms`
  `attempts` `error` `skipped` `output_chars` `starts_with_tone_marker`
  `contains_parentheses` `empty_output` `prompt_hash`

  语义易混点：
  - `raw_user_message` = **本轮的输入**。奈奈行上它是驱动本轮的用户原话（不是奈奈的输出）；只有结合 `role` 才能判断这行是谁说的。
  - `reply_text` = 本行角色实际说的话。用户轮等于 `raw_user_message`。
  - `assembled_prompt` = 奈奈轮发出去的完整拼装文本；用户轮恒为空串。
  - `prompt_hash` = `system_prompt + "\n---DIALOG---\n" + dialog_prompt` 的 SHA-256，用于区分版本。

- **`report.xlsx`** — 三个工作表：
  - `逐轮记录`：全部明细，21 列，含 `assembled_prompt`。
  - `汇总`：A / B 分列统计总行数、奈奈轮数、模拟用户轮数、成功率、奈奈轮成功率、平均 / P50 / P95 延时、平均输出字符数、语气标记出现率、括号出现率、拼装降级轮数；下方附「配置」块，dump 整个 `RunnerConfig`。
  - `运行批次`：每个 `(campaign_id, run_index, variant)` 的 records / success / failed / mean_latency_ms。

- **`runner.log`** — 与 stdout 相同的日志。

格式观测字段（`starts_with_tone_marker` / `contains_parentheses` / `empty_output` / `output_chars`）**只记录，不过滤、不改写模型输出**。

---

## 8. 运行与自检

```powershell
# 默认 8 小时 / 每 30 分钟一批 / 每批 32 行
& D:\PyCode\test\nana_prompt_ab\start_runner.ps1

# 单批联调：2 组 × 1 段 × 4 轮 × 2 行 = 16 行
& D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -Once -LoopCount 1 -RoundsPerLoop 4

# 等价裸 python
& D:\PyCode\test\.venv\Scripts\python.exe D:\PyCode\test\nana_prompt_ab\runner.py --once

# 离线单元测试（不触网，主要判据）
& D:\PyCode\test\.venv\Scripts\python.exe -m unittest D:\PyCode\test\nana_prompt_ab\test_runner.py -v
```

退出码：`0` = PASS，`1` = FAIL（有失败轮次），`2` = 启动异常（含锁冲突），`130` = Ctrl-C。全部轮次成功才会打印 `PASS`。

`SingleRunnerLock` 在 `<output_root>/.runner.lock` 写 `{"pid": ..., "started_at": ...}`；PID 已死则判定为残留锁并自动回收，PID 存活则抛 `RuntimeError("another runner is active; lock=...")`。

---

## 9. 改动指引

| 想做的事 | 改哪里 | 注意 |
|---|---|---|
| 换提示词 / 让 A B 不同 | `config.py` 的 `NANA_SYSTEM_PROMPT_*` / `NANA_DIALOG_PROMPT_*` | dialog 模板必须保住 10 个占位符 |
| 改轮数规模 | `RunnerConfig.loop_count` / `rounds_per_loop` | 同步检查测试里的行数断言 |
| 换模型 | `RunnerConfig.model_name` / `user_model_name` | 内网不认的模型只能实测确认 |
| 加一个新观测指标 | `runner.observation()` + `build_report` 的 `fields` | 两处都要加，否则报表缺列 |
| 改一轮的流程 | `runner.run_session` | 别破坏「2 行 / 轮」「拼装不进历史」两条约束 |
| 加第 3 个 variant | `VARIANTS` 常量 + `VARIANT_PROMPTS` | `VARIANTS` 是写死的 `("A", "B")`，汇总表也只有两列 |

跑完任何改动后，先跑 `test_runner.py`，再做一次 `-Once -LoopCount 1 -RoundsPerLoop 2` 的真实联调（4 行，成本最低）。
