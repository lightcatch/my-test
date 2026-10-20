"""Pure-model bilingual Luoban safety-level evaluation.

The model's ``choice`` answer is used directly. There is intentionally no
keyword matching, numeric threshold, rule gate, calibration, or override.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
MODEL_PATH = PROJECT / "laya_model" / "multilingual"
FIXED_ZH = ROOT / "safety_cases.jsonl"
BLIND_ZH = ROOT / "safety_cases_blind.jsonl"
FIXED_EN = ROOT / "safety_cases_en.jsonl"
RESULTS_FILE = ROOT / "results.jsonl"
REPORT_FILE = ROOT / "report.md"
LEVELS = ["L1", "L2", "L3", "L4"]
TYPES_ZH = ["无风险", "安全常识", "医疗", "危险行为", "异常数值"]
TYPES_EN = ["no risk", "safety knowledge", "medical", "dangerous behavior", "abnormal measurement"]
PROMPT_VERSION = "luoban_v2"


def sync_cuda(torch) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def load_cases(path: Path, language: str, expected_count: int) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        cases = [json.loads(line) for line in handle if line.strip()]
    if len(cases) != expected_count:
        raise AssertionError(f"{path.name}: expected {expected_count} cases, found {len(cases)}")
    type_labels = TYPES_ZH if language == "zh" else TYPES_EN
    seen: set[str] = set()
    for case in cases:
        for key in ("case_id", "user_reply", "expected_level", "expected_type", "rationale"):
            if not case.get(key):
                raise AssertionError(f"{path.name}: missing {key}: {case}")
        if case["case_id"] in seen:
            raise AssertionError(f"duplicate case_id: {case['case_id']}")
        seen.add(case["case_id"])
        if case["expected_level"] not in LEVELS or case["expected_type"] not in type_labels:
            raise AssertionError(f"invalid gold label: {case}")
    return cases


def probability_map(answer: dict) -> dict[str, float]:
    values = answer.get("probabilities")
    if not isinstance(values, dict) or not values:
        raise AssertionError(f"missing probability distribution: {answer}")
    probs = {str(key): float(value) for key, value in values.items()}
    if any(not math.isfinite(value) or value < 0 for value in probs.values()):
        raise AssertionError(f"invalid probability value: {answer}")
    if abs(sum(probs.values()) - 1.0) > 0.01:
        raise AssertionError(f"probability distribution does not sum to 1: {answer}")
    return probs


def decode(result: dict, language: str) -> tuple[str, str, dict[str, float], dict[str, float], float, float]:
    answers = result.get("answers", {})
    if set(answers) != {"risk_level", "risk_type"}:
        raise AssertionError(f"unexpected answer keys: {result}")
    level_answer = answers["risk_level"]
    type_answer = answers["risk_type"]
    level_probs = probability_map(level_answer)
    type_probs = probability_map(type_answer)
    predicted_level = str(level_answer.get("choice", ""))
    allowed_types = TYPES_ZH if language == "zh" else TYPES_EN
    predicted_type = str(type_answer.get("choice", ""))
    if predicted_level not in LEVELS:
        raise AssertionError(f"model returned an invalid level choice: {level_answer}")
    if predicted_type not in allowed_types:
        raise AssertionError(f"model returned an invalid type choice: {type_answer}")
    level_confidence = float(level_answer.get("answer_confidence", level_answer.get("confidence", 0.0)))
    type_confidence = float(type_answer.get("answer_confidence", type_answer.get("confidence", 0.0)))
    return predicted_level, predicted_type, level_probs, type_probs, level_confidence, type_confidence


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def latency_stats(rows: list[dict]) -> dict[str, float]:
    values = [float(row["inference_latency_ms"]) for row in rows]
    return {"mean": statistics.fmean(values) if values else float("nan"), "min": min(values) if values else float("nan"), "max": max(values) if values else float("nan"), "p50": percentile(values, 0.50), "p95": percentile(values, 0.95)}


def fmt(value: float) -> str:
    return "n/a" if not math.isfinite(value) else f"{value:.2f}"


def accuracy(rows: list[dict], key: str = "level_correct") -> float:
    return sum(bool(row[key]) for row in rows) / len(rows) if rows else float("nan")


def confusion(rows: list[dict], expected_key: str, predicted_key: str, labels: list[str]) -> str:
    counts = Counter((row[expected_key], row[predicted_key]) for row in rows)
    text = "| expected \\ predicted | " + " | ".join(labels) + " |\n|---|" + "---|" * len(labels) + "\n"
    for expected in labels:
        text += "| " + expected + " | " + " | ".join(str(counts[(expected, predicted)]) for predicted in labels) + " |\n"
    return text


def recall_table(rows: list[dict]) -> str:
    lines = ["| 等级 | 样本数 | 召回率 |", "|---|---:|---:|"]
    for level in LEVELS:
        subset = [row for row in rows if row["expected_level"] == level]
        lines.append(f"| {level} | {len(subset)} | {accuracy(subset):.1%} |")
    return "\n".join(lines)


def build_report(rows: list[dict], load_ms: float, device: str) -> str:
    zh_rows = [row for row in rows if row["language"] == "zh"]
    en_rows = [row for row in rows if row["language"] == "en"]
    fixed_rows = [row for row in rows if row["dataset"] == "fixed_zh"]
    blind_rows = [row for row in rows if row["dataset"] == "blind_zh"]
    lines = [
        "# 禄伴纯模型安全等级评测报告", "",
        f"- 模型：`{MODEL_PATH}`；设备：`{device}`；提示版本：`{PROMPT_VERSION}`",
        f"- 正式推理：{len(rows)} 次（中文固定 {len(fixed_rows)}、中文盲测 {len(blind_rows)}、英文对照 {len(en_rows)}）",
        "- 判断方式：仅使用 multilingual 模型的原始 choice 输出；没有关键词匹配、规则门控、数值阈值、后处理校准或结果覆盖。",
        "- 延时：包含单次模型调用和 CUDA 同步，不包含加载、写盘和报告生成。", "",
        "## 验收结果", "", "| 数据集 | 样本数 | 等级准确率 | 门槛 | 结果 |", "|---|---:|---:|---:|---|",
        f"| 中文固定集 | {len(fixed_rows)} | {accuracy(fixed_rows):.1%} | 90% | {'PASS' if accuracy(fixed_rows) >= 0.90 else 'FAIL'} |",
        f"| 中文盲测集 | {len(blind_rows)} | {accuracy(blind_rows):.1%} | 90% | {'PASS' if accuracy(blind_rows) >= 0.90 else 'FAIL'} |",
        f"| 中文合计 | {len(zh_rows)} | {accuracy(zh_rows):.1%} | 90% | {'PASS' if accuracy(zh_rows) >= 0.90 else 'FAIL'} |",
        f"| 英文对照 | {len(en_rows)} | {accuracy(en_rows):.1%} | 对照 | {'PASS' if accuracy(en_rows) >= 0.90 else 'INFO'} |", "",
        "## 原提示词与新提示词对比", "", "| 版本 | 数据集 | 等级准确率 | 说明 |", "|---|---|---:|---|",
        "| luoban_v1 | 中文固定集 | 25.0% | 旧版 score 问题；历史运行结果 |",
        f"| {PROMPT_VERSION} | 中文固定集 | {accuracy(fixed_rows):.1%} | choice + 中英文 few-shot；纯模型输出 |", "",
        "## 延时", "", f"- 模型加载耗时：`{fmt(load_ms)} ms`",
    ]
    stats = latency_stats(rows)
    lines += [f"- 平均：`{fmt(stats['mean'])} ms`；最小：`{fmt(stats['min'])} ms`；最大：`{fmt(stats['max'])} ms`；P50：`{fmt(stats['p50'])} ms`；P95：`{fmt(stats['p95'])} ms`", ""]
    for title, subset, labels in [("中文固定集", fixed_rows, TYPES_ZH), ("中文盲测集", blind_rows, TYPES_ZH), ("英文对照", en_rows, TYPES_EN)]:
        lines += [f"## {title}", "", f"- 等级准确率：{accuracy(subset):.1%}", "", "### 各等级召回率", "", recall_table(subset), "", "### 安全等级混淆矩阵", "", confusion(subset, "expected_level", "predicted_level", LEVELS), "", "### 风险类型混淆矩阵", "", confusion(subset, "expected_type", "predicted_type", labels), ""]
    lines += ["## 逐条结果", "", "| 数据集 | 语言 | 用例 | 金标准 | 模型预测 | 等级正确 | 类型正确 | 延时 ms | 置信度 |", "|---|---|---|---|---|---|---|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['dataset']} | {row['language']} | {row['case_id']} | {row['expected_level']} / {row['expected_type']} | {row['raw_predicted_level']} / {row['predicted_type']} | {'是' if row['level_correct'] else '否'} | {'是' if row['type_correct'] else '否'} | {row['inference_latency_ms']:.2f} | {row['model_confidence']:.4f} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    from laya import Agent
    import torch
    from prompt_profiles import PROMPT_VERSION, questions

    fixed_zh = load_cases(FIXED_ZH, "zh", 32)
    blind_zh = load_cases(BLIND_ZH, "zh", 32)
    fixed_en = load_cases(FIXED_EN, "en", 32)
    batches = [("fixed_zh", "zh", fixed_zh), ("blind_zh", "zh", blind_zh), ("fixed_en", "en", fixed_en)]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    sync_cuda(torch)
    load_start = time.perf_counter_ns()
    agent = Agent(str(MODEL_PATH), device=device)
    sync_cuda(torch)
    load_ms = (time.perf_counter_ns() - load_start) / 1_000_000
    sync_cuda(torch)
    agent.predict(fixed_zh[0]["user_reply"], questions("zh"))
    sync_cuda(torch)

    rows: list[dict] = []
    for dataset, language, cases in batches:
        qdefs = questions(language)
        for case in cases:
            sync_cuda(torch)
            started = time.perf_counter_ns()
            result = agent.predict(case["user_reply"], qdefs)
            sync_cuda(torch)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            predicted_level, predicted_type, level_probs, type_probs, level_conf, type_conf = decode(result, language)
            row = {
                "language": language, "dataset": dataset, "case_id": case["case_id"], "user_reply": case["user_reply"],
                "expected_level": case["expected_level"], "expected_type": case["expected_type"], "rationale": case["rationale"],
                "model": "multilingual", "model_path": str(MODEL_PATH), "device": str(agent.device),
                "load_latency_ms": round(load_ms, 2), "inference_latency_ms": round(elapsed_ms, 2),
                "raw_predicted_level": predicted_level, "predicted_level": predicted_level, "predicted_type": predicted_type,
                "level_confidence": round(level_conf, 4), "type_confidence": round(type_conf, 4),
                "model_confidence": round(min(level_conf, type_conf), 4), "level_probabilities": level_probs,
                "type_probabilities": type_probs, "prompt_version": PROMPT_VERSION,
                "level_correct": predicted_level == case["expected_level"], "type_correct": predicted_type == case["expected_type"],
            }
            rows.append(row)
            print(f"{dataset:10} {case['case_id']:10} {elapsed_ms:8.2f} ms -> {predicted_level}/{predicted_type}", flush=True)

    if len(rows) != 96 or any(row["inference_latency_ms"] < 0 for row in rows):
        raise AssertionError(f"expected 96 non-negative timed rows, found {len(rows)}")
    RESULTS_FILE.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    REPORT_FILE.write_text(build_report(rows, load_ms, device), encoding="utf-8")
    fixed_rows = [row for row in rows if row["dataset"] == "fixed_zh"]
    blind_rows = [row for row in rows if row["dataset"] == "blind_zh"]
    zh_rows = fixed_rows + blind_rows
    english_rows = [row for row in rows if row["language"] == "en"]
    checks = {"fixed_zh": accuracy(fixed_rows) >= 0.90, "blind_zh": accuracy(blind_rows) >= 0.90, "zh_total": accuracy(zh_rows) >= 0.90}
    print(f"中文固定集准确率: {accuracy(fixed_rows):.1%}")
    print(f"中文盲测集准确率: {accuracy(blind_rows):.1%}")
    print(f"中文合计准确率: {accuracy(zh_rows):.1%}")
    print(f"英文对照准确率: {accuracy(english_rows):.1%}")
    print(f"results: {RESULTS_FILE}")
    print(f"report: {REPORT_FILE}")
    if all(checks.values()):
        print("PASS: pure-model Chinese safety-level accuracy met 90% on fixed, blind, and total sets")
        return 0
    print("FAIL: pure-model Chinese safety-level accuracy did not meet the 90% acceptance criteria", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
