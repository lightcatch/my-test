"""
对话触发条件 —— 负样本(无关输入)向量召回评测
================================================
对 200 条与对话库毫不相关的输入,跑向量召回,统计 **top1 相似度分布**:
- 这些输入理想上都应"无命中",所以 top1 相似度应普遍偏低;
- 与正样本(eval_dialogue 里正确命中约 0.5~0.7)对比,看能否定一个"拒答阈值"
  让正样本过、负样本拦。

输出:
- 控制台:top1 相似度的分位数/直方图,以及若干候选阈值下的"误命中"条数(越少越好);
- xlsx 明细:每条负样本的 top1/top2/top3 命中场景 + 相似度。

用法(项目根 D:/PyCode/test 下,venv + -X utf8):
    .venv/Scripts/python.exe -X utf8 -m RAG.eval_dialogue_negative
    .venv/Scripts/python.exe -X utf8 -m RAG.eval_dialogue_negative --top-k 3 --output xxx.xlsx
"""
from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import datetime
import sys
from pathlib import Path

import openpyxl

from RAG.eval_dialogue import SCENARIO_NAMES, _vector_topk_with_index
from RAG.eval_dialogue_negative_cases import NEGATIVE_CASES
from RAG.rag_dialogue import (
    build_embeddings,
    load_dialogue_docs,
    load_dialogue_vector_store,
)

_THIS_DIR = Path(__file__).parent.resolve()
EVAL_RESULTS_DIR = _THIS_DIR / "data"

# 候选拒答阈值:top1 相似度 < 阈值 视为"正确拒答";>= 阈值 视为"误命中"。
_THRESHOLDS = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """简单线性插值分位数(sorted_vals 已升序)。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def run_eval(top_k: int = 3, output_path: Path | None = None) -> Path:
    print(f"[neg-eval] 负样本数: {len(NEGATIVE_CASES)} | top_k={top_k} | 仅向量召回")
    embeddings = build_embeddings()
    vector_store = load_dialogue_vector_store(embeddings)
    docs = load_dialogue_docs()
    print(f"[neg-eval] 索引已加载,共 {len(docs)} 条触发条件。开始评测...\n")

    if output_path is None:
        output_path = EVAL_RESULTS_DIR / f"dialogue_negative_eval_{_timestamp()}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "negative"
    ws.append([
        "序号", "无关输入", "Top1场景", "Top1相似度",
        "Top2场景", "Top2相似度", "Top3场景", "Top3相似度",
    ])

    top1_sims: list[float] = []
    # 记录每条 top1 的 (sim, 输入, 误命中场景),供输出最像的几条
    rows: list[tuple[float, str, str]] = []

    for i, q in enumerate(NEGATIVE_CASES, start=1):
        hits = _vector_topk_with_index(vector_store, q, top_k)
        top1_sim = hits[0]["vec_sim"] if hits else 0.0
        top1_scen = hits[0]["scenario"] if hits else ""
        top1_sims.append(top1_sim)
        rows.append((top1_sim, q, top1_scen))

        def cell(j: int, key: str):
            return hits[j][key] if j < len(hits) else ""

        ws.append([
            i, q,
            cell(0, "scenario"), round(top1_sim, 4),
            cell(1, "scenario"), round(hits[1]["vec_sim"], 4) if len(hits) > 1 else "",
            cell(2, "scenario"), round(hits[2]["vec_sim"], 4) if len(hits) > 2 else "",
        ])

    wb.save(output_path)
    _print_summary(top1_sims, rows)
    print(f"\n[neg-eval] 明细已写入: {output_path}")
    return output_path


def _print_summary(top1_sims: list[float], rows: list[tuple[float, str, str]]) -> None:
    n = len(top1_sims)
    sorted_sims = sorted(top1_sims)
    mean = sum(top1_sims) / n if n else 0.0

    print("=" * 64)
    print(f"负样本数: {n}  (这些输入都应'无命中',top1 相似度越低越好)")
    print("-" * 64)
    print("top1 相似度分布:")
    print(f"  最小  {sorted_sims[0]:.3f}   最大  {sorted_sims[-1]:.3f}   均值 {mean:.3f}")
    print(f"  P50 {_percentile(sorted_sims, 50):.3f}  "
          f"P75 {_percentile(sorted_sims, 75):.3f}  "
          f"P90 {_percentile(sorted_sims, 90):.3f}  "
          f"P95 {_percentile(sorted_sims, 95):.3f}  "
          f"P99 {_percentile(sorted_sims, 99):.3f}")
    print("-" * 64)

    # 直方图(0.0~1.0,步长 0.05)
    print("直方图(top1 相似度):")
    buckets: dict[int, int] = {}
    for s in top1_sims:
        b = min(int(s / 0.05), 19)
        buckets[b] = buckets.get(b, 0) + 1
    for b in range(20):
        cnt = buckets.get(b, 0)
        if cnt == 0:
            continue
        lo, hi = b * 0.05, (b + 1) * 0.05
        bar = "█" * cnt
        print(f"  [{lo:.2f},{hi:.2f})  {cnt:>3}  {bar}")
    print("-" * 64)

    # 各阈值下的"误命中"(top1 相似度 >= 阈值 = 没拦住)
    print("候选拒答阈值(top1>=阈值 视为误命中,越少越好):")
    print(f"  {'阈值':<8}{'误命中':<8}{'误命中率':<10}{'正确拒答率'}")
    for th in _THRESHOLDS:
        false_hits = sum(1 for s in top1_sims if s >= th)
        print(f"  {th:<8.2f}{false_hits:<8}{false_hits / n:<10.1%}{(n - false_hits) / n:.1%}")
    print("-" * 64)

    # 最像(分数最高)的 10 条负样本——它们最容易被误判
    print("最容易误命中的负样本 Top10(分数最高):")
    for sim, q, scen in sorted(rows, key=lambda x: x[0], reverse=True)[:10]:
        print(f"  {sim:.3f}  {q}  →  {scen}")
    print("=" * 64)


def _main(argv: list[str]) -> int:
    top_k = 3
    output_path: Path | None = None
    i = 0
    while i < len(argv):
        if argv[i] == "--top-k" and i + 1 < len(argv):
            top_k = int(argv[i + 1]); i += 2
        elif argv[i] in ("--output", "-o") and i + 1 < len(argv):
            output_path = Path(argv[i + 1]); i += 2
        else:
            print(f"未知参数: {argv[i]}"); return 2
    run_eval(top_k=top_k, output_path=output_path)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
