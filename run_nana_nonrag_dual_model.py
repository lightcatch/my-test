"""Run the Nana non-RAG Excel cases against two Doubao models.

The source workbook is never modified.  A separate workbook is created with
one sheet per model and exactly two appended response columns.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from copy import copy
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from config11 import (
    DOUBAO_API_KEY,
    DOUBAO_API_URL,
    MAX_TOKENS,
    SYSTEM_PROMPT_TEMPLATE,
    TEMPERATURE,
)


DEFAULT_INPUT = Path(r"D:\ai抱枕数据库\奈奈非RAG测试用例.xlsx")
DEFAULT_OUTPUT = Path(r"D:\ai抱枕数据库\奈奈非RAG双模型回答.xlsx")
MODELS = (
    "doubao-seed-2-0-mini-260215",
    "doubao-seed-2-0-lite-260428",
    "doubao-seed-2-0-lite-260215",
)
SOURCE_HEADERS = (
    "用例编号",
    "关联算法设计",
    "用例标题",
    "用例类型",
    "用例优先级",
    "前置条件",
    "用户对话",
    "期望回复结果",
    "重复执行次数",
    "自动化",
    "人工复核",
    "维护人",
    "备注",
)
RESPONSE_HEADERS = ("LLM回复1", "LLM回复2")
EXPECTED_CASE_COUNT = 100
MAX_CALL_ATTEMPTS = 3
ROLE_PREFIX = re.compile(r"^\s*(user|assistant)\s*[:：]\s*(.*)$", re.IGNORECASE)


class EmptyModelResponseError(RuntimeError):
    """Raised when a successful API stream contains no natural-language text."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dialogue(raw_value: Any) -> list[dict[str, str]]:
    """Parse bath_test-style user:/assistant: dialogue without allowing system injection."""
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError("用户对话为空")

    messages: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = ROLE_PREFIX.match(line)
        if match:
            messages.append(
                {"role": match.group(1).lower(), "content": match.group(2).strip()}
            )
        elif messages:
            messages[-1]["content"] += f"\n{line}"
        else:
            messages.append({"role": "user", "content": line})

    if not messages or not any(message["role"] == "user" for message in messages):
        raise ValueError("用户对话中没有 user: 消息")
    return messages


def build_messages(precondition: Any, raw_dialogue: Any) -> list[dict[str, str]]:
    """Build a fresh, non-RAG request for one logical test attempt."""
    condition = str(precondition or "").strip() or "无额外前置条件。"
    hidden_context = (
        "【本轮测试上下文】\n"
        f"{condition}\n\n"
        "以上内容仅用于本轮状态设定。请自然回答用户，"
        "不得提及测试、前置条件、隐藏上下文、系统提示或内部规则。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE},
        {"role": "system", "content": hidden_context},
        *parse_dialogue(raw_dialogue),
    ]


def sanitize_error(error: Exception) -> str:
    """Keep errors useful while preventing credentials from reaching logs or Excel."""
    message = str(error)
    if DOUBAO_API_KEY:
        message = message.replace(DOUBAO_API_KEY, "***")
    message = re.sub(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)", r"\1***", message)
    message = re.sub(r"(?i)(api[_ -]?key\s*[:=]\s*)([^\s,;]+)", r"\1***", message)
    message = re.sub(r"\b(sk-[A-Za-z0-9_-]+)\b", "***", message)
    message = re.sub(r"\s+", " ", message).strip()
    return message[:240] or error.__class__.__name__


def collect_stream_text(stream: Iterable[Any]) -> str:
    """Collect only assistant text, matching the streaming style of the existing runner."""
    content_parts: list[str] = []
    try:
        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                content_parts.append(text)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()

    answer = "".join(content_parts).strip()
    if not answer:
        raise EmptyModelResponseError("模型未返回自然语言文本")
    return answer


def call_model_once(client: OpenAI, model: str, messages: list[dict[str, str]]) -> str:
    """Make one streaming call.  No tools are supplied, by design."""
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"thinking": {"type": "disabled"}},
    )
    return collect_stream_text(stream)


def call_with_retry(client: OpenAI, model: str, messages: list[dict[str, str]]) -> str:
    for attempt in range(1, MAX_CALL_ATTEMPTS + 1):
        try:
            return call_model_once(client, model, messages)
        except Exception as error:  # API/network failures should be retained per cell.
            safe_error = sanitize_error(error)
            if attempt == MAX_CALL_ATTEMPTS:
                return f"[调用失败] {error.__class__.__name__}: {safe_error}"
            delay_seconds = min(2 ** (attempt - 1), 4)
            print(
                f"  重试 {attempt}/{MAX_CALL_ATTEMPTS - 1}：{error.__class__.__name__}，"
                f"{delay_seconds}s 后继续",
                flush=True,
            )
            time.sleep(delay_seconds)

    raise AssertionError("重试循环不应到达此处")


def source_data_rows(source: Worksheet) -> list[int]:
    headers = tuple(source.cell(1, column).value for column in range(1, len(SOURCE_HEADERS) + 1))
    if headers != SOURCE_HEADERS:
        raise ValueError(f"Sheet1 列头不符合预期：{headers!r}")
    if source.max_column != len(SOURCE_HEADERS):
        raise ValueError(f"Sheet1 应为 {len(SOURCE_HEADERS)} 列，实际为 {source.max_column} 列")

    rows: list[int] = []
    case_ids: set[str] = set()
    dialog_column = SOURCE_HEADERS.index("用户对话") + 1
    for row_index in range(2, source.max_row + 1):
        values = [source.cell(row_index, column).value for column in range(1, len(SOURCE_HEADERS) + 1)]
        if all(value is None or str(value).strip() == "" for value in values):
            continue
        case_id = str(values[0] or "").strip()
        dialogue = str(source.cell(row_index, dialog_column).value or "").strip()
        if not case_id:
            raise ValueError(f"第 {row_index} 行缺少用例编号")
        if case_id in case_ids:
            raise ValueError(f"用例编号重复：{case_id}")
        if not dialogue.lower().startswith("user:"):
            raise ValueError(f"第 {row_index} 行用户对话必须以 user: 开头")
        case_ids.add(case_id)
        rows.append(row_index)

    if len(rows) != EXPECTED_CASE_COUNT:
        raise ValueError(f"应有 {EXPECTED_CASE_COUNT} 条用例，实际为 {len(rows)} 条")
    expected_rows = list(range(2, EXPECTED_CASE_COUNT + 2))
    if rows != expected_rows:
        raise ValueError("用例行必须连续位于 Sheet1 的第 2 至 101 行")
    return rows


def copy_sheet(source: Worksheet, target: Worksheet) -> None:
    """Copy the source Sheet1 values and basic workbook presentation into a new sheet."""
    for row in source.iter_rows():
        for source_cell in row:
            target_cell = target[source_cell.coordinate]
            target_cell.value = source_cell.value
            if source_cell.has_style:
                target_cell._style = copy(source_cell._style)
            if source_cell.number_format:
                target_cell.number_format = source_cell.number_format
            if source_cell.alignment:
                target_cell.alignment = copy(source_cell.alignment)
            if source_cell.font:
                target_cell.font = copy(source_cell.font)
            if source_cell.fill:
                target_cell.fill = copy(source_cell.fill)
            if source_cell.border:
                target_cell.border = copy(source_cell.border)
            if source_cell.protection:
                target_cell.protection = copy(source_cell.protection)
            if source_cell.hyperlink:
                target_cell._hyperlink = copy(source_cell.hyperlink)
            if source_cell.comment:
                target_cell.comment = copy(source_cell.comment)

    # Merge after assigning values: non-anchor cells in an already merged target
    # range are read-only MergedCell objects.
    for merged_range in source.merged_cells.ranges:
        target.merge_cells(str(merged_range))

    for key, source_dimension in source.column_dimensions.items():
        target_dimension = target.column_dimensions[key]
        target_dimension.width = source_dimension.width
        target_dimension.hidden = source_dimension.hidden
        target_dimension.bestFit = source_dimension.bestFit
        target_dimension.outlineLevel = source_dimension.outlineLevel

    for key, source_dimension in source.row_dimensions.items():
        target_dimension = target.row_dimensions[key]
        target_dimension.height = source_dimension.height
        target_dimension.hidden = source_dimension.hidden
        target_dimension.outlineLevel = source_dimension.outlineLevel

    target.freeze_panes = source.freeze_panes
    target.sheet_view.showGridLines = source.sheet_view.showGridLines
    target.sheet_properties.pageSetUpPr.fitToPage = source.sheet_properties.pageSetUpPr.fitToPage
    target.page_margins = copy(source.page_margins)
    target.page_setup = copy(source.page_setup)


def add_model_sheet(workbook: Workbook, source: Worksheet, model: str) -> None:
    """Add one model sheet containing an untouched copy of the source cases."""
    header_style_source = source.cell(1, len(SOURCE_HEADERS))
    sheet = workbook.create_sheet(title=model)
    copy_sheet(source, sheet)
    for offset, header in enumerate(RESPONSE_HEADERS, start=len(SOURCE_HEADERS) + 1):
        cell = sheet.cell(1, offset, header)
        if header_style_source.has_style:
            cell._style = copy(header_style_source._style)
        cell.alignment = copy(header_style_source.alignment)
        sheet.column_dimensions[get_column_letter(offset)].width = 60
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(SOURCE_HEADERS) + len(RESPONSE_HEADERS))}{source.max_row}"


def ensure_model_sheets(workbook: Workbook, source: Worksheet) -> None:
    """Add only missing model sheets, retaining completed model answers verbatim."""
    unexpected_sheets = [name for name in workbook.sheetnames if name not in MODELS]
    if unexpected_sheets:
        raise ValueError(f"结果工作簿含有不支持的Sheet：{unexpected_sheets!r}")
    for model in MODELS:
        if model not in workbook.sheetnames:
            add_model_sheet(workbook, source, model)


def create_result_workbook(source: Worksheet) -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)
    ensure_model_sheets(workbook, source)
    return workbook


def cell_values_match(left: Any, right: Any) -> bool:
    """Treat Excel's persisted empty-string cells as blank when comparing copies."""
    left_blank = left is None or (isinstance(left, str) and not left.strip())
    right_blank = right is None or (isinstance(right, str) and not right.strip())
    return (left_blank and right_blank) or left == right


def validate_result(path: Path, source_path: Path, source_rows: list[int]) -> None:
    # Validation performs indexed cell comparisons, so normal mode avoids the
    # repeated full-sheet scans that read-only worksheets incur for cell(...).
    source_workbook = load_workbook(source_path, read_only=False, data_only=False)
    result_workbook = load_workbook(path, read_only=False, data_only=False)
    try:
        if result_workbook.sheetnames != list(MODELS):
            raise ValueError(f"结果Sheet不符合预期：{result_workbook.sheetnames!r}")
        source_sheet = source_workbook["Sheet1"]
        expected_headers = list(SOURCE_HEADERS + RESPONSE_HEADERS)
        for model in MODELS:
            sheet = result_workbook[model]
            headers = [sheet.cell(1, column).value for column in range(1, len(expected_headers) + 1)]
            if headers != expected_headers or sheet.max_column != len(expected_headers):
                raise ValueError(f"{model} 的列结构不符合预期")
            for row_index in source_rows:
                for column in range(1, len(SOURCE_HEADERS) + 1):
                    if not cell_values_match(
                        sheet.cell(row_index, column).value,
                        source_sheet.cell(row_index, column).value,
                    ):
                        raise ValueError(f"{model} 第 {row_index} 行原始用例内容不一致")
                for column in range(len(SOURCE_HEADERS) + 1, len(expected_headers) + 1):
                    if not str(sheet.cell(row_index, column).value or "").strip():
                        raise ValueError(f"{model} 第 {row_index} 行缺少回答")
    finally:
        source_workbook.close()
        result_workbook.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="奈奈非RAG测试用例双模型批跑")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="源测试用例工作簿")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="结果工作簿")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=10,
        help="每完成多少个回答单元格保存一次检查点（默认10）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有结果和检查点；未指定时自动从检查点继续",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    checkpoint_path = output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")

    if args.checkpoint_every < 1:
        raise ValueError("--checkpoint-every 必须大于0")
    if not input_path.is_file():
        raise FileNotFoundError(f"未找到输入文件：{input_path}")
    source_hash_before = sha256_file(input_path)
    source_workbook = load_workbook(input_path, data_only=False)
    try:
        if "Sheet1" not in source_workbook.sheetnames:
            raise ValueError("输入工作簿缺少 Sheet1")
        source_sheet = source_workbook["Sheet1"]
        data_rows = source_data_rows(source_sheet)

        if args.overwrite:
            if output_path.exists():
                output_path.unlink()
            if checkpoint_path.exists():
                checkpoint_path.unlink()

        if checkpoint_path.exists():
            workbook = load_workbook(checkpoint_path)
            ensure_model_sheets(workbook, source_sheet)
            print(f"从检查点继续：{checkpoint_path}", flush=True)
        elif output_path.exists():
            # Keep the published workbook untouched until the newly added model
            # has completed; work from a separate checkpoint copy instead.
            workbook = load_workbook(output_path)
            ensure_model_sheets(workbook, source_sheet)
            workbook.save(checkpoint_path)
            print(f"已从现有结果新增模型检查点：{checkpoint_path}", flush=True)
        else:
            workbook = create_result_workbook(source_sheet)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            workbook.save(checkpoint_path)
            print(f"已创建检查点：{checkpoint_path}", flush=True)
    finally:
        source_workbook.close()

    client = OpenAI(api_key=DOUBAO_API_KEY, base_url=DOUBAO_API_URL)
    precondition_column = SOURCE_HEADERS.index("前置条件") + 1
    dialogue_column = SOURCE_HEADERS.index("用户对话") + 1
    response_start_column = len(SOURCE_HEADERS) + 1
    completed_since_checkpoint = 0
    newly_requested = 0

    try:
        for model in MODELS:
            sheet = workbook[model]
            print(f"开始模型：{model}", flush=True)
            for ordinal, row_index in enumerate(data_rows, start=1):
                precondition = sheet.cell(row_index, precondition_column).value
                dialogue = sheet.cell(row_index, dialogue_column).value
                for response_offset in range(len(RESPONSE_HEADERS)):
                    answer_cell = sheet.cell(row_index, response_start_column + response_offset)
                    if str(answer_cell.value or "").strip():
                        continue

                    print(
                        f"[{model}] 用例 {ordinal}/{len(data_rows)}，回答 {response_offset + 1}/2",
                        flush=True,
                    )
                    messages = build_messages(precondition, dialogue)
                    answer_cell.value = call_with_retry(client, model, messages)
                    newly_requested += 1
                    completed_since_checkpoint += 1

                    if completed_since_checkpoint >= args.checkpoint_every:
                        workbook.save(checkpoint_path)
                        completed_since_checkpoint = 0
                        print("  检查点已保存", flush=True)

        workbook.save(checkpoint_path)
    finally:
        workbook.close()

    if sha256_file(input_path) != source_hash_before:
        raise RuntimeError("输入工作簿在运行期间发生变化，已保留检查点但不发布正式结果")

    validate_result(checkpoint_path, input_path, data_rows)
    os.replace(checkpoint_path, output_path)
    print(f"完成：新增请求 {newly_requested} 次，结果文件：{output_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"批跑失败：{error.__class__.__name__}: {sanitize_error(error)}", file=sys.stderr, flush=True)
        raise SystemExit(1)
