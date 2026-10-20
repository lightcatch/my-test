"""批量测试程序：从 Excel 导入测试用例，逐条调用 LLM（流式）并回写结果。

测试用例格式参考《二宝人设身份测试用例.xlsx》，列包含：
    用例编号 / 关联算法设计 / 用例标题 / 用例类型 / 用例优先级 / 前置条件 /
    用户对话 / 期望回复结果 / 重复执行次数 / 自动化 / 人工复核 / 维护人 / 备注

流式对话与工具调用解析逻辑参考 LLM_call_test_stream11.py。

用法：
    uv run python bath_test.py
    uv run python bath_test.py --excel "C:/path/用例.xlsx" --sheet Sheet1
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openai import OpenAI
from openai.types.chat import ChatCompletionChunk

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config11 import (
    DOUBAO_AVAILABLE_MODELS, DOUBAO_API_URL, DOUBAO_API_KEY,
    Ali_API_KEY, Ali_API_URL,
    DEEPSEEK_AVAILABLE_MODELS, DEEPSEEK_API_URL, DEEPSEEK_API_KEY,
    TEMPERATURE, MAX_TOKENS, SYSTEM_PROMPT_TEMPLATE,
    get_time_function_desc,
    exit_function_desc,
    play_music_desc,
    play_story_desc,
    change_sound_desc,
)

# ==========================================================================
# 单次测试可调参数
# ==========================================================================

# 测试用例文件（默认桌面上的二宝人设身份测试用例）
EXCEL_FILE_PATH = r"C:\Users\Administrator\Desktop\二宝人设身份测试用例.xlsx"
WORKSHEET_NAME = "Sheet1"

# 本次测试所用模型（默认豆包，可切换到下方任一注释配置）
USED_MODEL = DOUBAO_AVAILABLE_MODELS[19]
USED_API_KEY = DOUBAO_API_KEY
USED_BASE_URL = DOUBAO_API_URL

# USED_MODEL = "qwen3.6-plus"
# USED_API_KEY = Ali_API_KEY
# USED_BASE_URL = Ali_API_URL

# USED_MODEL = DEEPSEEK_AVAILABLE_MODELS[0]
# USED_API_KEY = DEEPSEEK_API_KEY
# USED_BASE_URL = DEEPSEEK_API_URL

USED_PROMPT = SYSTEM_PROMPT_TEMPLATE

# 深度思考："disabled" 不使用 / "enabled" 使用 / "auto" 模型自行判断
THINKING_TYPE = "disabled"

# 传给模型的工具列表（按需增减）
TOOLS = [
    get_time_function_desc,
    exit_function_desc,
    play_music_desc,
    play_story_desc,
    change_sound_desc,
]

# 输入列名（多轮对话写在同一单元格，形如 "user:你好\nassistant:在的\nuser:你是谁"）
DIALOG_COLUMN = "用户对话"
# 重复执行次数列；缺失或非法时回退到 DEFAULT_REPEAT
REPEAT_COLUMN = "重复执行次数"
DEFAULT_REPEAT = 1

# ==========================================================================

WINDOWS_INVALID_FILENAME_CHARS = '<>:"/\\|?*'
VALID_ROLES = {"user", "assistant", "system"}


def sanitize_filename_part(name: str) -> str:
    if not name:
        return "unknown_model"
    sanitized = "".join(
        "_" if ch in WINDOWS_INVALID_FILENAME_CHARS else ch for ch in name
    )
    sanitized = sanitized.strip().strip(".")
    return sanitized or "unknown_model"


def build_output_excel_path(model_name: str) -> Path:
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_model = sanitize_filename_part(model_name)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"人设身份测试结果_{safe_model}_{timestamp}.xlsx"


def parse_dialog(raw: str) -> List[Dict[str, str]]:
    """解析对话单元格为消息列表。

    支持两种写法：
    1. 纯文本（无 role 前缀）：整体视为一条 user 消息。
    2. 带角色前缀，每行形如 "user:...", "assistant:..."，支持多轮。
       同一角色跨多行时，后续无前缀行并入上一条消息。
    """
    text = str(raw or "").strip()
    if not text:
        return []

    lines = text.splitlines()
    messages: List[Dict[str, str]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        role: Optional[str] = None
        content = stripped
        if ":" in stripped or "：" in stripped:
            sep_idx = min(
                (stripped.index(c) for c in (":", "：") if c in stripped),
                default=-1,
            )
            candidate = stripped[:sep_idx].strip().lower()
            if candidate in VALID_ROLES:
                role = candidate
                content = stripped[sep_idx + 1:].strip()

        if role is None:
            if messages:
                # 无前缀续行，并入上一条
                messages[-1]["content"] += "\n" + stripped
                continue
            role = "user"

        messages.append({"role": role, "content": content})

    # 若整体没有解析出任何 user，兜底为单条 user
    if not any(m["role"] == "user" for m in messages):
        return [{"role": "user", "content": text}]

    return messages


def resolve_repeat_count(row: pd.Series) -> int:
    if REPEAT_COLUMN not in row.index:
        return DEFAULT_REPEAT
    value = row[REPEAT_COLUMN]
    if pd.isna(value):
        return DEFAULT_REPEAT
    try:
        count = int(float(value))
    except (ValueError, TypeError):
        return DEFAULT_REPEAT
    return count if count > 0 else DEFAULT_REPEAT


class StreamTester:
    """封装单个模型客户端，负责流式调用与结果解析。"""

    def __init__(self) -> None:
        self.client = OpenAI(api_key=USED_API_KEY, base_url=USED_BASE_URL)

    def _build_extra_body(self) -> Dict[str, Any]:
        # 豆包用 thinking.type；其他厂商如需 enable_thinking 可在此调整
        return {"thinking": {"type": THINKING_TYPE}}

    def process_stream(
        self, stream_response: Any, start_time: float
    ) -> Dict[str, Any]:
        """解析流式响应，参考 LLM_call_test_stream11.py。"""
        processor: Dict[str, Any] = {
            "full_content": "",
            "tool_call_content": "",
            "reasoning_content": None,
            "tool_calls": [],
            "token_usage": None,
            "first_chunk_received": False,
            "first_package_latency": 0.0,
        }
        tool_calls_by_index: Dict[int, Dict[str, Any]] = {}

        try:
            for chunk in stream_response:
                chunk: ChatCompletionChunk = chunk

                if hasattr(chunk, "usage") and chunk.usage:
                    cached = 0
                    details = getattr(chunk.usage, "prompt_tokens_details", None)
                    if details is not None:
                        cached = getattr(details, "cached_tokens", 0) or 0
                    processor["token_usage"] = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                        "cache_tokens": cached,
                    }
                    continue

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if not processor["first_chunk_received"]:
                    processor["first_chunk_received"] = True
                    processor["first_package_latency"] = time.time() - start_time

                if hasattr(delta, "error") and delta.error:
                    raise Exception(
                        f"{delta.error.get('code', '未知错误')}: "
                        f"{delta.error.get('message', '无错误描述')}"
                    )

                if (
                    not processor["reasoning_content"]
                    and hasattr(delta, "reasoning_content")
                    and delta.reasoning_content
                ):
                    processor["reasoning_content"] = delta.reasoning_content

                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        idx = getattr(tool_call, "index", None)
                        if idx is None:
                            idx = 0 if not tool_calls_by_index else max(tool_calls_by_index) + 1

                        current = tool_calls_by_index.setdefault(
                            idx,
                            {"id": "", "type": "function",
                             "function": {"name": "", "arguments": ""}},
                        )

                        if getattr(tool_call, "id", None):
                            current["id"] = tool_call.id
                        if getattr(tool_call, "type", None):
                            current["type"] = tool_call.type

                        fn = getattr(tool_call, "function", None)
                        if fn:
                            if getattr(fn, "name", None):
                                current["function"]["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                current["function"]["arguments"] += fn.arguments
                                processor["tool_call_content"] += fn.arguments

                    processor["tool_calls"] = [
                        tool_calls_by_index[i] for i in sorted(tool_calls_by_index)
                    ]

                if hasattr(delta, "content") and delta.content:
                    processor["full_content"] += delta.content

        finally:
            stream_response.close()

        if not processor["tool_calls"]:
            processor["tool_calls"] = None

        return processor

    def call_once(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """执行一次完整对话调用并返回解析结果。"""
        start_time = time.time()
        stream_response = self.client.chat.completions.create(
            model=USED_MODEL,
            messages=messages,
            tools=TOOLS,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=self._build_extra_body(),
        )
        processor = self.process_stream(stream_response, start_time)
        processor["total_latency"] = time.time() - start_time
        return processor


def format_tool_calls(tool_calls: Optional[List[Dict[str, Any]]]) -> str:
    if not tool_calls:
        return "无"
    parts = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        parts.append(f"{fn.get('name', '')}({fn.get('arguments', '')})")
    return "；".join(parts)


def build_messages(dialog_messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [{"role": "system", "content": USED_PROMPT}, *dialog_messages]


def process_test_cases(excel_path: str, sheet_name: str) -> None:
    print(f"当前使用模型：{USED_MODEL}")
    print(f"读取用例文件：{excel_path} [{sheet_name}]\n")

    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    if DIALOG_COLUMN not in df.columns:
        raise ValueError(
            f"Excel 缺少必要列「{DIALOG_COLUMN}」，实际列：{list(df.columns)}"
        )

    # 预扫描最大重复次数，确定动态结果列数量
    max_repeat = DEFAULT_REPEAT
    for _, row in df.iterrows():
        if pd.isna(row[DIALOG_COLUMN]):
            continue
        max_repeat = max(max_repeat, resolve_repeat_count(row))

    result_columns: List[str] = []
    for i in range(1, max_repeat + 1):
        result_columns.extend([
            f"LLM回复_{i}",
            f"函数调用_{i}",
            f"首包耗时_{i}(s)",
            f"总耗时_{i}(s)",
            f"Token消耗_{i}",
        ])
    for col in result_columns:
        df[col] = ""
    df = df.astype({col: object for col in result_columns})

    tester = StreamTester()
    total = len(df)

    for index, row in df.iterrows():
        if pd.isna(row[DIALOG_COLUMN]):
            continue

        case_id = row.get("用例编号", f"row{index + 1}")
        dialog_messages = parse_dialog(row[DIALOG_COLUMN])
        if not dialog_messages:
            print(f"[{index + 1}/{total}] {case_id} 对话为空，跳过")
            continue

        repeat = resolve_repeat_count(row)
        preview = dialog_messages[-1]["content"]
        print(f"[{index + 1}/{total}] 用例 {case_id} | 重复 {repeat} 次")
        print(f"    用户输入：{preview}")

        messages = build_messages(dialog_messages)

        for r in range(1, repeat + 1):
            try:
                processor = tester.call_once(messages)
                reply = processor["full_content"] or ""
                tool_desc = format_tool_calls(processor["tool_calls"])
                usage = processor["token_usage"]
                token_total = usage["total_tokens"] if usage else 0

                df.at[index, f"LLM回复_{r}"] = reply
                df.at[index, f"函数调用_{r}"] = tool_desc
                df.at[index, f"首包耗时_{r}(s)"] = round(processor["first_package_latency"], 3)
                df.at[index, f"总耗时_{r}(s)"] = round(processor["total_latency"], 3)
                df.at[index, f"Token消耗_{r}"] = token_total

                print(f"    第{r}次回复：{reply[:60]}{'...' if len(reply) > 60 else ''}")
                if processor["tool_calls"]:
                    print(f"    第{r}次工具调用：{tool_desc}")

            except Exception as exc:  # noqa: BLE001
                print(f"    第{r}次调用失败：{exc}")
                df.at[index, f"LLM回复_{r}"] = f"调用失败: {exc}"
                df.at[index, f"函数调用_{r}"] = "调用失败"

        print()

    output_path = build_output_excel_path(USED_MODEL)
    df.to_excel(output_path, sheet_name=sheet_name, index=False)
    print(f"测试完成，结果已保存：{output_path.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 Excel 批量测试 LLM 对话/工具调用。")
    parser.add_argument("--excel", default=EXCEL_FILE_PATH, help="测试用例 Excel 路径")
    parser.add_argument("--sheet", default=WORKSHEET_NAME, help="工作表名称")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        process_test_cases(args.excel, args.sheet)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
