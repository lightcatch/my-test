"""批量评估音乐播放工具调用时是否同时回复、是否告知用户。

本脚本只发送单轮用户输入，不会回填 ``//tool``，也不会执行真实的播放动作。
它通过 ``LLM_call_test_stream11.ConversationManager`` 发起请求，因此模型、
系统提示词和工具列表始终与手动聊天脚本保持一致。

用法：
    uv run python music_playback_batch_test.py
    uv run python music_playback_batch_test.py --limit 10
    uv run python music_playback_batch_test.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
from openai.types.chat import ChatCompletionChunk

from LLM_call_test_stream11 import ConversationManager


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "music_playback_tests"

CATEGORY_DIRECT = "明确播放"
CATEGORY_CONTROL = "音乐讨论对照"
CATEGORY_BOUNDARY = "含糊/边界"


@dataclass(frozen=True)
class TestCase:
    """一条固定的独立单轮测试用例。"""

    case_id: str
    category: str
    user_input: str


DIRECT_PLAY_PROMPTS = (
    "播放《晴天》",
    "给我放一首《孤勇者》",
    "我想听《小幸运》",
    "播放周杰伦的《稻香》",
    "帮我放《后来》",
    "来一首《夜空中最亮的星》",
    "请播放《童话》",
    "我要听《平凡之路》",
    "放一下《起风了》",
    "给我播《海阔天空》",
    "播放《虫儿飞》",
    "我想听《茉莉花》",
    "请放《成都》",
    "给我来首《小苹果》",
    "把《唯一》放出来",
    "播放《千千阙歌》",
    "想听《兰亭序》",
    "给我放一首《告白气球》",
    "请播《月亮代表我的心》",
    "我要听《星晴》",
    "播放一首轻音乐",
    "给我放点民谣",
    "想听摇滚，帮我播放",
    "来首爵士乐吧",
    "请播放古典音乐",
    "给我放一点白噪音",
    "播放 ASMR",
    "放一首流行歌",
    "我想听电子音乐",
    "请播放儿童歌曲",
    "帮我播一首适合睡觉的音乐",
    "给我放点学习时听的歌",
    "我现在想听冥想音乐",
    "播放一首适合看书的轻音乐",
    "来点做运动时听的音乐",
    "给我放一首开心的歌",
    "播放一首安静一点的音乐",
    "请放能让我放松的音乐",
    "我想听适合下雨天的歌",
    "给我播放一首晚安曲",
    "切到下一首",
    "换一首歌",
    "这首不喜欢，换首音乐",
    "把音乐切换成摇滚",
    "再来一首",
    "重新播放刚才那首歌",
    "继续播放音乐",
    "暂停后再放一首",
    "给我换成轻音乐",
    "切一首节奏快一点的",
    "来一首不同风格的歌",
    "把当前歌曲换掉",
    "再播放一次刚才的音乐",
    "给我连放三首儿歌",
    "播放两遍《两只老虎》",
    "放半小时白噪音",
    "给我播放十分钟冥想音乐",
    "睡前帮我放一首歌",
    "我在写作业，播放点背景音乐",
    "做饭的时候放首轻快的歌",
    "通勤路上给我播首歌",
    "午休时放点舒缓音乐",
    "开车时播放一些流行音乐",
    "我心情不好，放一首鼓励我的歌",
    "派对开始了，播放点热闹的音乐",
    "给宝宝放一首摇篮曲",
    "我要跳舞，放首有节奏的歌",
    "跑步时请给我播放音乐",
    "现在给我放首电影主题曲",
    "播放一些纯音乐",
)

CONTROL_PROMPTS = (
    "你喜欢什么类型的音乐？",
    "《晴天》这首歌是谁唱的？",
    "民谣和摇滚有什么区别？",
    "为什么有些音乐能让人放松？",
    "给我介绍一下爵士乐的特点。",
    "适合睡觉听的音乐一般有什么特点？",
    "周杰伦有哪些经典歌曲？",
    "你觉得学钢琴难吗？",
    "帮我推荐三首适合跑步的歌名，不用播放。",
    "《海阔天空》的歌词表达了什么？",
    "什么是白噪音？",
    "古典音乐和流行音乐有什么不同？",
    "我最近在学唱歌，应该怎么练习？",
    "一首歌的节奏通常由什么决定？",
    "介绍一下适合儿童听的音乐类型。",
)

BOUNDARY_PROMPTS = (
    "来点音乐吧。",
    "有没有适合睡前的音乐？",
    "我需要一点背景音乐。",
    "给我找首安静的歌。",
    "今天适合听什么音乐？",
    "想换个音乐风格。",
    "推荐一首轻音乐。",
    "我想要一些白噪音。",
    "有没有能让我专注的音乐？",
    "来个适合下雨天的歌单。",
    "我现在有点烦，音乐能帮我吗？",
    "给孩子选一首歌怎么样？",
    "想听点不一样的。",
    "帮我找找周杰伦的歌。",
    "放松的时候一般听什么？",
)


def build_test_cases() -> list[TestCase]:
    """构建固定的 70/15/15 用例集，并在启动时校验构成。"""
    groups = (
        (CATEGORY_DIRECT, DIRECT_PLAY_PROMPTS),
        (CATEGORY_CONTROL, CONTROL_PROMPTS),
        (CATEGORY_BOUNDARY, BOUNDARY_PROMPTS),
    )
    cases: list[TestCase] = []
    for category, prompts in groups:
        for prompt in prompts:
            cases.append(TestCase(f"M{len(cases) + 1:03d}", category, prompt))

    expected = {CATEGORY_DIRECT: 70, CATEGORY_CONTROL: 15, CATEGORY_BOUNDARY: 15}
    actual = {category: sum(c.category == category for c in cases) for category in expected}
    if len(cases) != 100 or actual != expected:
        raise RuntimeError(f"测试用例构成异常：总数={len(cases)}，分类={actual}")
    return cases


NOTICE_PATTERNS = (
    re.compile(r"(?:正在|马上|这就|现在就|立刻|即将|已).{0,18}(?:播放|放(?:歌|音乐)?|安排|切换)", re.S),
    re.compile(r"(?:我来|我给你|让我|为你|给你).{0,18}(?:播放|放(?:歌|音乐)?|安排|切换)", re.S),
    re.compile(r"(?:歌曲|音乐).{0,10}(?:已经|正在|马上|即将).{0,10}(?:播放|开始)", re.S),
)


def assess_notice(reply: str, has_play_music: bool) -> str:
    """评估是否在同轮明确告知用户播放动作。

    有调用但没有文本，确定为“未告知”；有文本而未命中明确通知模式时，
    不武断判错，标为“需人工复核”。未调用播放工具则不适用。
    """
    if not has_play_music:
        return "不适用"
    clean_reply = (reply or "").strip()
    if not clean_reply:
        return "未告知"
    if any(pattern.search(clean_reply) for pattern in NOTICE_PATTERNS):
        return "已告知"
    return "需人工复核"


def serialize_tool_calls(tool_calls: Optional[list[dict[str, Any]]]) -> str:
    return json.dumps(tool_calls or [], ensure_ascii=False, separators=(",", ":"))


def extract_play_music_arguments(tool_calls: Optional[list[dict[str, Any]]]) -> str:
    arguments = [
        str((call.get("function") or {}).get("arguments") or "")
        for call in tool_calls or []
        if (call.get("function") or {}).get("name") == "play_music"
    ]
    return "\n".join(arguments)


def process_stream(stream_response: Any, start_time: float) -> dict[str, Any]:
    """合并流式文本与按 index 分片到达的工具调用。"""
    full_content = ""
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    usage: Optional[dict[str, int]] = None
    first_chunk_latency: Optional[float] = None

    try:
        for chunk in stream_response:
            chunk: ChatCompletionChunk = chunk
            if getattr(chunk, "usage", None):
                details = getattr(chunk.usage, "prompt_tokens_details", None)
                usage = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                    "cache_tokens": getattr(details, "cached_tokens", 0) or 0,
                }
                continue

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            if first_chunk_latency is None:
                first_chunk_latency = time.perf_counter() - start_time

            delta = choices[0].delta
            if getattr(delta, "error", None):
                error = delta.error
                raise RuntimeError(f"{error.get('code', '未知错误')}: {error.get('message', '无错误描述')}")

            for tool_call in getattr(delta, "tool_calls", None) or []:
                index = getattr(tool_call, "index", None)
                if index is None:
                    index = 0 if not tool_calls_by_index else max(tool_calls_by_index) + 1
                current = tool_calls_by_index.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if getattr(tool_call, "id", None):
                    current["id"] = tool_call.id
                if getattr(tool_call, "type", None):
                    current["type"] = tool_call.type
                function = getattr(tool_call, "function", None)
                if function:
                    if getattr(function, "name", None):
                        current["function"]["name"] = function.name
                    if getattr(function, "arguments", None):
                        current["function"]["arguments"] += function.arguments

            if getattr(delta, "content", None):
                full_content += delta.content
    finally:
        stream_response.close()

    return {
        "full_content": full_content,
        "tool_calls": [tool_calls_by_index[index] for index in sorted(tool_calls_by_index)] or None,
        "token_usage": usage,
        "first_chunk_latency_s": round(first_chunk_latency or 0.0, 3),
        "total_latency_s": round(time.perf_counter() - start_time, 3),
    }


class MusicPlaybackTester:
    """以主脚本的当前运行配置执行彼此独立的单轮请求。"""

    def __init__(self, quiet_request_log: bool = True) -> None:
        self.manager = ConversationManager()
        self.quiet_request_log = quiet_request_log

    @property
    def model_name(self) -> str:
        return self.manager.used_model

    def call_once(self, user_input: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": self.manager.create_system_prompt()},
            {"role": "user", "content": user_input},
        ]
        started = time.perf_counter()
        if self.quiet_request_log:
            with contextlib.redirect_stdout(io.StringIO()):
                stream = self.manager.call_llm(messages)
        else:
            stream = self.manager.call_llm(messages)
        return process_stream(stream, started)


def make_result(case: TestCase, processor: dict[str, Any], error: str = "") -> dict[str, Any]:
    tool_calls = processor.get("tool_calls")
    reply = str(processor.get("full_content") or "")
    has_play_music = any(
        (call.get("function") or {}).get("name") == "play_music" for call in tool_calls or []
    )
    simultaneous_chat = has_play_music and bool(reply.strip())
    usage = processor.get("token_usage") or {}
    return {
        "用例编号": case.case_id,
        "用例分类": case.category,
        "用户输入": case.user_input,
        "助手完整回复": reply,
        "全部工具调用(JSON)": serialize_tool_calls(tool_calls),
        "是否调用play_music": "是" if has_play_music else "否",
        "play_music参数": extract_play_music_arguments(tool_calls),
        "是否同轮触发对话": "是" if simultaneous_chat else "否",
        "用户告知判定": assess_notice(reply, has_play_music),
        "首包耗时(秒)": processor.get("first_chunk_latency_s", 0.0),
        "总耗时(秒)": processor.get("total_latency_s", 0.0),
        "总Token": usage.get("total_tokens", 0),
        "错误": error,
    }


def summarize(results: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(results)
    play_rows = [row for row in rows if row["是否调用play_music"] == "是"]
    return {
        "总请求数": len(rows),
        "play_music调用次数": len(play_rows),
        "同轮触发对话次数": sum(row["是否同轮触发对话"] == "是" for row in play_rows),
        "明确告知次数": sum(row["用户告知判定"] == "已告知" for row in play_rows),
        "未告知次数": sum(row["用户告知判定"] == "未告知" for row in play_rows),
        "需人工复核次数": sum(row["用户告知判定"] == "需人工复核" for row in play_rows),
        "对照组误调用次数": sum(
            row["用例分类"] == CATEGORY_CONTROL and row["是否调用play_music"] == "是" for row in rows
        ),
        "调用失败次数": sum(bool(row["错误"]) for row in rows),
    }


def write_results(results: list[dict[str, Any]], model_name: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = re.sub(r'[<>:"/\\|?*]+', "_", model_name)
    base_path = OUTPUT_DIR / f"music_playback_test_{safe_model}_{timestamp}"
    dataframe = pd.DataFrame(results)
    csv_path = base_path.with_suffix(".csv")
    xlsx_path = base_path.with_suffix(".xlsx")
    dataframe.to_csv(csv_path, index=False, encoding="utf-8-sig")
    dataframe.to_excel(xlsx_path, index=False)
    return csv_path, xlsx_path


def print_summary(summary: dict[str, int]) -> None:
    total = summary["总请求数"]
    calls = summary["play_music调用次数"]
    simultaneous = summary["同轮触发对话次数"]
    print("\n" + "=" * 58)
    print("音乐播放函数 100 次测试汇总")
    print("=" * 58)
    print(f"总请求数：{total}")
    print(f"play_music 调用次数：{calls}（{calls / total:.1%}" + ")" if total else "play_music 调用次数：0")
    print(
        f"同轮触发对话次数：{simultaneous}"
        + (f"（占播放调用 {simultaneous / calls:.1%}）" if calls else "")
    )
    print(f"明确告知次数：{summary['明确告知次数']}")
    print(f"未告知次数：{summary['未告知次数']}")
    print(f"需人工复核次数：{summary['需人工复核次数']}")
    print(f"对照组误调用次数：{summary['对照组误调用次数']}")
    print(f"调用失败次数：{summary['调用失败次数']}")


def run_dry_checks(cases: list[TestCase]) -> None:
    """无网络自检：验证用例构成、告知分类和结果汇总规则。"""
    assert len(cases) == 100
    assert assess_notice("正在为你播放《晴天》。", True) == "已告知"
    assert assess_notice("好的。", True) == "需人工复核"
    assert assess_notice("", True) == "未告知"
    assert assess_notice("正在为你播放。", False) == "不适用"
    sample = [
        make_result(cases[0], {"full_content": "正在为你播放。", "tool_calls": [{"function": {"name": "play_music", "arguments": "{}"}}]}),
        make_result(cases[70], {"full_content": "爵士乐常有即兴演奏。", "tool_calls": None}),
    ]
    summary = summarize(sample)
    assert summary["总请求数"] == 2
    assert summary["play_music调用次数"] == 1
    assert summary["同轮触发对话次数"] == 1
    print("自检通过：100 条用例、告知判定和汇总规则均有效；未发起 API 调用。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量测试 play_music 工具调用与用户告知行为。")
    parser.add_argument("--limit", type=int, default=100, help="执行前 N 条用例（1-100，默认 100）。")
    parser.add_argument("--dry-run", action="store_true", help="只运行本地自检，不调用模型或写结果文件。")
    parser.add_argument("--show-request-log", action="store_true", help="显示主脚本的每次请求消息日志。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = build_test_cases()
    if not 1 <= args.limit <= len(cases):
        raise ValueError(f"--limit 必须在 1 到 {len(cases)} 之间。")
    if args.dry_run:
        run_dry_checks(cases)
        return 0

    selected = cases[:args.limit]
    tester = MusicPlaybackTester(quiet_request_log=not args.show_request_log)
    print(f"当前模型：{tester.model_name}")
    print(f"开始执行 {len(selected)} 条独立单轮音乐测试；不会回填或执行工具。")
    results: list[dict[str, Any]] = []
    for position, case in enumerate(selected, start=1):
        print(f"[{position}/{len(selected)}] {case.case_id} | {case.category} | {case.user_input}", flush=True)
        try:
            processor = tester.call_once(case.user_input)
            result = make_result(case, processor)
            print(
                f"  play_music={result['是否调用play_music']}，"
                f"同轮对话={result['是否同轮触发对话']}，"
                f"告知={result['用户告知判定']}"
            )
        except Exception as exc:  # 保留失败行，确保每条用例均可追溯
            result = make_result(case, {}, error=f"{type(exc).__name__}: {exc}")
            print(f"  调用失败：{result['错误']}", file=sys.stderr)
        results.append(result)

    summary = summarize(results)
    print_summary(summary)
    csv_path, xlsx_path = write_results(results, tester.model_name)
    print(f"\n明细 CSV：{csv_path}")
    print(f"明细 Excel：{xlsx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
