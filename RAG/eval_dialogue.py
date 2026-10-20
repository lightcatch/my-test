"""
对话触发条件 —— 向量召回评测脚本
================================
只做**向量召回**(不掺 BM25),对 200 条口语化用例,每条返回 Top-3 命中的触发条件
+ 相似度分数,并记录"期望场景"在 Top-3 里的排名。输出 xlsx + 控制台汇总。

用法(项目根 D:/PyCode/test 下,venv + -X utf8):
    .venv/Scripts/python.exe -X utf8 -m RAG.eval_dialogue
    .venv/Scripts/python.exe -X utf8 -m RAG.eval_dialogue --top-k 3 --output xxx.xlsx
"""
from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import datetime
import sys
from pathlib import Path

import openpyxl

from RAG.rag_dialogue import (
    DG_TOP_K,
    build_embeddings,
    load_dialogue_docs,
    load_dialogue_vector_store,
)

_THIS_DIR = Path(__file__).parent.resolve()
EVAL_RESULTS_DIR = _THIS_DIR / "data"

# 场景 index → 触发条件原文(供汇总展示;index 与 build 时 scenario_index 对齐)
SCENARIO_NAMES = {
    0: "加班/学习等疲惫的事",
    1: "充电、断电、没电",
    2: "同类、朋友、伙伴",
    3: "夜晚、月亮、月光、窗外夜景",
    4: "雨天、阴天、下雪等特殊天气",
    5: "卧室、床上、睡前场景",
    6: "拥抱、贴贴、靠着抱枕等动作",
    7: "难过、委屈、想哭",
    8: "开心、分享日常趣事",
    9: "疲惫、好累、提不起劲",
    10: "我陪着你/我不会丢下你",
    11: "我喜欢你/我想你了",
    12: "你是只属于我的",
    13: "不要离开我",
    14: "主动发起贴贴、抱抱等亲密请求",
}

# 语义相邻、容易互相召回的场景对(汇总时额外统计"宽松命中":期望或其相邻场景进 Top1)
ADJACENT = {
    0: {9}, 9: {0},        # 都是"累"
    6: {14}, 14: {6},      # 都是"抱"
    10: {13}, 13: {10},    # 都是"别走/陪伴承诺"
    11: {12, 13},          # 亲密表白类
}

# EVAL_CASES 在 _cases.py 里(200 条),避免本文件过长。
from RAG.eval_dialogue_cases import EVAL_CASES


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _vector_topk_with_index(vector_store, text: str, top_k: int) -> list[dict]:
    """向量召回 Top-K,带 scenario_index 和 vec_sim(=1-cosine距离)。"""
    pairs = vector_store.similarity_search_with_score(text, k=top_k)
    return [
        {
            "rank": i,
            "index": doc.metadata.get("scenario_index", -1),
            "scenario": doc.page_content,
            "vec_sim": float(1.0 - dist),
        }
        for i, (doc, dist) in enumerate(pairs, start=1)
    ]


def _rank_of(expected_idx: int, hits: list[dict]) -> int | str:
    """期望场景在 Top-K 命中里的 1-based 排名;未进 Top-K 记 '未召回'。"""
    for h in hits:
        if h["index"] == expected_idx:
            return h["rank"]
    return "未召回"


def run_eval(top_k: int = 3, output_path: Path | None = None) -> Path:
    print(f"[eval] 用例数: {len(EVAL_CASES)} | top_k={top_k} | 仅向量召回")
    embeddings = build_embeddings()
    vector_store = load_dialogue_vector_store(embeddings)
    docs = load_dialogue_docs()
    n_doc = len(docs)
    print(f"[eval] 索引已加载,共 {n_doc} 条触发条件。开始评测...\n")

    if output_path is None:
        output_path = EVAL_RESULTS_DIR / f"dialogue_vector_eval_{_timestamp()}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append([
        "序号", "用户说的话", "期望场景", "期望场景描述",
        "命中排名", "Top1命中", "Top3命中",
        "Top1触发条件", "Top1相似度",
        "Top2触发条件", "Top2相似度",
        "Top3触发条件", "Top3相似度",
    ])

    top1_hit = top3_hit = loose_top1 = 0
    # 分场景统计: idx -> [总数, top1命中, top3命中]
    per_scen: dict[int, list[int]] = {i: [0, 0, 0] for i in SCENARIO_NAMES}

    for i, (q, expected) in enumerate(EVAL_CASES, start=1):
        hits = _vector_topk_with_index(vector_store, q, top_k)
        rank = _rank_of(expected, hits)
        is_top1 = rank == 1
        is_top3 = isinstance(rank, int) and rank <= 3

        top1_idx = hits[0]["index"] if hits else -1
        if is_top1 or (top1_idx in ADJACENT.get(expected, set())):
            loose_top1 += 1
        if is_top1:
            top1_hit += 1
        if is_top3:
            top3_hit += 1

        per_scen[expected][0] += 1
        if is_top1:
            per_scen[expected][1] += 1
        if is_top3:
            per_scen[expected][2] += 1

        def cell(j: int, key: str):
            return hits[j][key] if j < len(hits) else ""

        ws.append([
            i, q, expected, SCENARIO_NAMES.get(expected, ""),
            rank, "是" if is_top1 else "否", "是" if is_top3 else "否",
            cell(0, "scenario"), round(cell(0, "vec_sim"), 4) if hits else "",
            cell(1, "scenario"), round(hits[1]["vec_sim"], 4) if len(hits) > 1 else "",
            cell(2, "scenario"), round(hits[2]["vec_sim"], 4) if len(hits) > 2 else "",
        ])

    wb.save(output_path)
    _print_summary(top1_hit, top3_hit, loose_top1, len(EVAL_CASES), per_scen)
    print(f"\n[eval] 明细已写入: {output_path}")
    return output_path


def _print_summary(top1, top3, loose, total, per_scen) -> None:
    print("=" * 60)
    print(f"总用例: {total}")
    print(f"Top1 命中率: {top1}/{total} = {top1 / total:.1%}")
    print(f"Top3 命中率: {top3}/{total} = {top3 / total:.1%}")
    print(f"Top1 宽松命中(含相邻场景): {loose}/{total} = {loose / total:.1%}")
    print("-" * 60)
    print(f"{'场景':<28}{'用例':<6}{'Top1':<8}{'Top3'}")
    for idx, (tot, t1, t3) in per_scen.items():
        if tot == 0:
            continue
        name = f"[{idx}] {SCENARIO_NAMES.get(idx, '')}"
        print(f"{name:<28}{tot:<6}{t1}/{tot:<5}  {t3}/{tot}")
    print("=" * 60)


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
