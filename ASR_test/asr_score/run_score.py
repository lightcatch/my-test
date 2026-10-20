# -*- coding: utf-8 -*-
"""通用方言 ASR 打分 runner。

特性:
- 自动递归查找 metadata.csv (支持 mixed_noise 这种嵌套目录)
- 复用 downloaded_audio/integrated_dialects/打分模版.xlsx 作为输出模板
- 自动计算 CER (S/D/I/N/CER), 同时回填到模板, Excel 中 CER 列也有公式
- 内置 ASR 抽象层, 当前支持 mega_asr; 接口型 ASR 可通过 --workers N 并发

示例 (在 ASR_test/mega_asr/.venv 中):
  .venv\\Scripts\\python.exe -X utf8 ^
    d:\\PyCode\\test\\ASR_test\\asr_score\\run_score.py ^
    --root d:\\PyCode\\test\\downloaded_audio\\integrated_dialects ^
    --include dongbei --asr mega_asr --device cuda --language zh
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

# 让脚本既能 `python run_score.py` 又能 `python -m asr_score.run_score`
SCRIPT_DIR = Path(__file__).resolve().parent
PARENT_DIR = SCRIPT_DIR.parent  # ASR_test
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

# Windows 终端 GBK 默认编码会让中文乱码, 强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

from asr_score.cer import compute_cer  # noqa: E402
from asr_score.recognizers.base import BaseRecognizer, RecognitionResult  # noqa: E402

# 数据集根目录: 优先读环境变量 ASR_DATA_ROOT, 否则按平台猜:
# - Windows: d:/PyCode/test/downloaded_audio/integrated_dialects
# - Linux (tc 用户): /home/tc/local_projects/integrated_dialects
import os
import platform


def _guess_default_root() -> Path:
    env = os.environ.get("ASR_DATA_ROOT")
    if env:
        return Path(env)
    if platform.system() == "Windows":
        return Path(r"d:/PyCode/test/downloaded_audio/integrated_dialects")
    return Path("/home/tc/local_projects/integrated_dialects")


DEFAULT_ROOT = _guess_default_root()
DEFAULT_TEMPLATE = DEFAULT_ROOT / "打分模版.xlsx"
DEFAULT_OUT_DIR = DEFAULT_ROOT / "打分结果"

METADATA_HEADER = [
    "编号", "语言", "文本", "saved_path", "文件名",
    "时长", "id", "speaker_id", "sample_index", "dialect",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量跑方言 ASR 并算 CER, 输出 Excel。")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="方言根目录, 会递归找其中所有 metadata.csv。")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE,
                        help="打分模板 Excel 路径。")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="输出根目录, 默认 <root>/打分结果/<asr>/。")
    parser.add_argument("--asr", default="mega_asr",
                        choices=["mega_asr", "fire_red_asr", "fire_red_asr_fp16",
                                 "glm_asr", "ark_asr",
                                 "sense_voice_onnx", "fire_red_asr2_int8",
                                 "doubao_asr", "doubao_sauc_asr"],
                        help="使用的 ASR 名称。")
    parser.add_argument("--include", nargs="*", default=None,
                        help="只跑名字匹配的子目录 (按 metadata.csv 相对路径子串匹配)。")
    parser.add_argument("--exclude", nargs="*", default=None,
                        help="排除名字匹配的子目录。")
    parser.add_argument("--language", default="auto",
                        help="ASR 语种提示: auto 表示按子集目录自动判断 (en->English, yue->Cantonese, 其余->Chinese); "
                             "也可显式指定 zh / en / yue / 空字符串(让模型自判)。")
    parser.add_argument("--device", default="cuda", help="本地 GPU 模型的 device_map。")
    parser.add_argument("--no-routing", action="store_true",
                        help="(mega_asr) 关闭音质路由器, 始终挂 LoRA。")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发数。本地 GPU ASR 强制 1; 接口型 ASR 可调大。")
    parser.add_argument("--limit", type=int, default=None,
                        help="每个子集最多跑多少条 (调试用)。")
    return parser.parse_args()


def build_recognizer(args: argparse.Namespace) -> BaseRecognizer:
    if args.asr == "mega_asr":
        from asr_score.recognizers.mega_asr import MegaASRRecognizer
        return MegaASRRecognizer(
            device_map=args.device,
            routing_enabled=not args.no_routing,
        )
    if args.asr == "fire_red_asr":
        from asr_score.recognizers.fire_red_asr import FireRedASRRecognizer
        use_gpu = args.device != "cpu"
        return FireRedASRRecognizer(use_gpu=use_gpu)
    if args.asr == "fire_red_asr_fp16":
        from asr_score.recognizers.fire_red_asr import FireRedASRRecognizer
        use_gpu = args.device != "cpu"
        rec = FireRedASRRecognizer(use_gpu=use_gpu, use_half=True)
        rec.display_name = "fire_red_ASR_FP16"
        return rec
    if args.asr == "glm_asr":
        from asr_score.recognizers.glm_asr import GLMASRRecognizer
        return GLMASRRecognizer(device=args.device)
    if args.asr == "ark_asr":
        from asr_score.recognizers.ark_asr import ARKASRRecognizer
        return ARKASRRecognizer(device=args.device)
    if args.asr == "sense_voice_onnx":
        from asr_score.recognizers.sense_voice_onnx import SenseVoiceONNXRecognizer
        return SenseVoiceONNXRecognizer()
    if args.asr == "fire_red_asr2_int8":
        from asr_score.recognizers.fire_red_asr2_int8 import FireRedASR2INT8Recognizer
        provider = "cuda" if args.device != "cpu" else "cpu"
        return FireRedASR2INT8Recognizer(provider=provider)
    if args.asr == "doubao_asr":
        from asr_score.recognizers.doubao_asr import DoubaoASRRecognizer
        return DoubaoASRRecognizer()
    if args.asr == "doubao_sauc_asr":
        from asr_score.recognizers.doubao_sauc_asr import DoubaoSAUCASRRecognizer
        return DoubaoSAUCASRRecognizer()
    raise ValueError(f"未知的 ASR: {args.asr}")


def find_metadata_files(root: Path,
                        include: list[str] | None,
                        exclude: list[str] | None) -> list[Path]:
    files = sorted(root.rglob("metadata.csv"))
    if include:
        files = [f for f in files if any(tok in str(f).replace("\\", "/") for tok in include)]
    if exclude:
        files = [f for f in files if not any(tok in str(f).replace("\\", "/") for tok in exclude)]
    return files


def read_metadata(meta_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(meta_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): (v or "").strip() for k, v in row.items()})
    return rows


def subset_name(meta_path: Path, root: Path) -> str:
    """根据 metadata.csv 相对位置生成输出名, 如 mixed_noise/dongbei -> mixed_noise__dongbei。"""
    rel = meta_path.parent.relative_to(root)
    parts = [p for p in rel.parts if p]
    return "__".join(parts) if parts else "root"


def detect_subset_language(meta_path: Path, root: Path, fallback: str | None) -> str | None:
    """按子集目录推断子集默认语种 (兜底用)。
    en -> English, yue -> Cantonese, 其余 -> Chinese。
    """
    rel_parts = meta_path.parent.relative_to(root).parts
    leaf = rel_parts[-1].lower() if rel_parts else ""
    if leaf == "en":
        return "en"
    if leaf == "yue":
        return "yue"
    return "zh" if fallback in (None, "", "auto") else fallback


# ---- 行级语种判断 -------------------------------------------------------------
import unicodedata as _ud  # noqa: E402
import re as _re  # noqa: E402

_CN_CHAR_RE = _re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_EN_WORD_RE = _re.compile(r"[A-Za-z]{2,}")
# 子集语言字段中文 -> 短码
_DIALECT_LABEL_TO_LANG = {
    "英语": "en", "english": "en", "en": "en",
    "粤语": "yue", "cantonese": "yue", "yue": "yue",
    # 噪音 / 二宝 / 普通话 / 各种方言都按中文走 (具体行可能是英文, 行级再判一次)
}


def infer_row_language(ref_text: str, subset_default: str | None,
                       dialect_label: str | None = None) -> str | None:
    """根据参考文本判断该样本的语种, 优先级:
    1) 行内若以 CJK 为主 -> zh; 以英文为主 -> en
    2) 都没有时回退到 dialect_label (元数据 '语言' 字段)
    3) 再回退到 subset_default (按子集目录推断)
    粤语 (yue) 仅当 subset_default 或 dialect_label 显式指明时使用, 避免误判。
    """
    text = ref_text or ""
    cn = len(_CN_CHAR_RE.findall(text))
    en_tokens = _EN_WORD_RE.findall(text)
    en = sum(len(t) for t in en_tokens)

    # 先按子集兜底, 处理 yue (没法从字符上区分粤语和普通话写法)
    if subset_default == "yue":
        return "yue"
    label = (dialect_label or "").strip()
    label_lang = _DIALECT_LABEL_TO_LANG.get(label.lower(), None)

    if cn == 0 and en > 0:
        return "en"
    if cn > 0 and en == 0:
        return "zh"
    if cn >= en:
        return "zh"
    if en > cn:
        return "en"
    return label_lang or subset_default or "zh"


def resolve_audio_path(meta_path: Path, saved_path: str) -> Path:
    """优先按 saved_path 相对 meta 所在目录解析。"""
    p = Path(saved_path)
    if p.is_absolute() and p.exists():
        return p
    cand = meta_path.parent / saved_path
    return cand


def process_subset(
    meta_path: Path,
    root: Path,
    template: Path,
    out_dir: Path,
    recognizer: BaseRecognizer,
    language: str | None,
    workers: int,
    limit: int | None,
    summary_csv: Path | None = None,
) -> dict[str, Any]:
    """处理一个 metadata.csv 子集, 产出一个 Excel。"""
    from openpyxl import load_workbook

    name = subset_name(meta_path, root)
    suffix = recognizer.display_name or recognizer.name
    out_path = out_dir / f"{name}_{suffix}.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = read_metadata(meta_path)
    if limit is not None:
        rows = rows[:limit]

    total = len(rows)
    print(f"\n=== 子集 {name}: {total} 条, 输出 -> {out_path} ===", flush=True)
    if total == 0:
        return {"name": name, "total": 0, "success": 0, "avg_cer": None, "out_path": str(out_path)}

    # 准备任务: idx -> (audio_path, ref_text, row_meta, row_language)
    # language: 子集 == 'auto' 时按 (语言字段 + 文本字符) 行级判断; 否则统一用传入值。
    subset_default = (
        detect_subset_language(meta_path, root, None) if language == "__auto__" else None
    )
    tasks: list[tuple[int, Path, str, dict[str, str], str | None]] = []
    for idx, r in enumerate(rows):
        audio = resolve_audio_path(meta_path, r.get("saved_path", ""))
        ref = r.get("文本", "")
        if language == "__auto__":
            row_lang = infer_row_language(ref, subset_default, r.get("语言"))
        else:
            row_lang = language
        tasks.append((idx, audio, ref, r, row_lang))

    # 推理
    use_local = recognizer.is_local_gpu
    workers_eff = 1 if use_local else max(1, workers)
    if workers != workers_eff:
        print(f"  注: 本地 GPU ASR, workers 自动改为 1 (原 {workers})", flush=True)

    results: list[tuple[int, RecognitionResult]] = [None] * total  # type: ignore[list-item]
    started_all = time.perf_counter()

    def _run(item: tuple[int, Path, str, dict[str, str], str | None]) -> tuple[int, RecognitionResult]:
        idx, audio, _ref, _meta, row_lang = item
        if not audio.exists():
            return idx, RecognitionResult(text="", status="error", error=f"音频不存在: {audio}")
        return idx, recognizer.recognize(str(audio), language=row_lang)

    if workers_eff == 1:
        for i, item in enumerate(tasks, start=1):
            idx, res = _run(item)
            results[idx] = res
            _log_one(i, total, item, res)
    else:
        with ThreadPoolExecutor(max_workers=workers_eff) as ex:
            futures = {ex.submit(_run, item): item for item in tasks}
            done = 0
            for fu in as_completed(futures):
                idx, res = fu.result()
                results[idx] = res
                done += 1
                _log_one(done, total, futures[fu], res)

    # 写 Excel: 拷贝模板, 按行回填
    wb = load_workbook(template)
    ws = wb.active

    success = 0
    cer_values: list[float] = []
    # 列索引 (1-based)
    COL = {h: i + 1 for i, h in enumerate(METADATA_HEADER)}
    COL.update({
        "识别出的文字": 11,
        "S": 12, "D": 13, "I": 14, "N": 15, "CER": 16,
    })

    for idx, r in enumerate(rows):
        excel_row = idx + 2  # 第 2 行起
        for h in METADATA_HEADER:
            ws.cell(row=excel_row, column=COL[h], value=r.get(h, ""))

        res = results[idx]
        ws.cell(row=excel_row, column=COL["识别出的文字"], value=res.text)

        cer = compute_cer(r.get("文本", ""), res.text)
        ws.cell(row=excel_row, column=COL["S"], value=cer.s)
        ws.cell(row=excel_row, column=COL["D"], value=cer.d)
        ws.cell(row=excel_row, column=COL["I"], value=cer.i)
        ws.cell(row=excel_row, column=COL["N"], value=cer.n)
        # CER 列模板里已有公式, 这里不写值, 让 Excel 打开时自动算
        # 但为了 openpyxl 读出来能直接看, 也额外把数字落到单元格;
        # 模板里的公式行只到 201 行, 超过的话补一份公式
        if excel_row > 201:
            s_ref = f"L{excel_row}"
            d_ref = f"M{excel_row}"
            i_ref = f"N{excel_row}"
            n_ref = f"O{excel_row}"
            formula = (
                f'=IF(OR({n_ref}="",{n_ref}=0),"",'
                f'ROUND(({s_ref}+{d_ref}+{i_ref})/{n_ref}*100,2))'
            )
            ws.cell(row=excel_row, column=COL["CER"], value=formula)

        if res.status == "success":
            success += 1
        if cer.n > 0:
            cer_values.append(cer.cer)

    wb.save(out_path)

    avg_cer = round(sum(cer_values) / len(cer_values), 2) if cer_values else None
    elapsed = round(time.perf_counter() - started_all, 1)
    print(f"  子集完成: {success}/{total} 成功, 平均 CER={avg_cer}%, 用时 {elapsed}s")
    summary = {
        "name": name,
        "language": "auto" if language == "__auto__" else (language or ""),
        "total": total,
        "success": success,
        "avg_cer": avg_cer,
        "elapsed_sec": elapsed,
        "out_path": str(out_path),
    }
    if summary_csv is not None:
        append_summary_row(summary_csv, summary)
    return summary


SUMMARY_FIELDS = ["name", "language", "total", "success", "avg_cer", "elapsed_sec", "out_path"]


def append_summary_row(path: Path, row: dict[str, Any]) -> None:
    """在每个子集完成后, 把它的指标追加写入汇总 CSV (持续可见)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in SUMMARY_FIELDS})


def _log_one(done: int, total: int, item: tuple,
             res: RecognitionResult) -> None:
    idx, audio = item[0], item[1]
    lang = item[4] if len(item) >= 5 else ""
    snippet = (res.text[:30] + "…") if len(res.text) > 30 else res.text
    lang_tag = f"[{lang}] " if lang else ""
    if res.status == "success":
        print(f"  [{done}/{total}] {lang_tag}{audio.name} -> {snippet}  ({res.elapsed_sec}s)",
              flush=True)
    else:
        print(f"  [{done}/{total}] {lang_tag}{audio.name} FAIL: {res.error}",
              flush=True)


def main() -> int:
    args = parse_args()

    meta_files = find_metadata_files(args.root, args.include, args.exclude)
    if not meta_files:
        print(f"在 {args.root} 没找到匹配的 metadata.csv (include={args.include}, exclude={args.exclude})")
        return 1

    out_dir = args.out_dir or (DEFAULT_OUT_DIR / args.asr)
    print(f"将处理 {len(meta_files)} 个子集:")
    for m in meta_files:
        print(f"  - {m}")

    print(f"\n构建 ASR: {args.asr}")
    recognizer = build_recognizer(args)
    load_t0 = time.perf_counter()
    recognizer.setup()
    print(f"ASR 准备完成, 用时 {time.perf_counter() - load_t0:.1f}s")

    # 单次运行使用同一个 summary csv, 每个子集完成都追加一行 (即使中途崩溃也能看到进度)
    summary_csv = out_dir / f"_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    overall_t0 = time.perf_counter()
    summaries: list[dict[str, Any]] = []
    for meta in meta_files:
        # 子集级语言策略:
        # - auto: 行级判断 (按参考文本 + metadata "语言" 字段)
        # - 显式 zh/en/yue/...: 全子集统一传该值
        # - 空字符串: 让模型自判, 不传 language
        if args.language == "auto":
            sub_lang: str | None = "__auto__"
            display_lang = "auto(行级)"
        else:
            sub_lang = args.language or None
            display_lang = sub_lang or "(模型自判)"
        print(f"\n--- {meta} | language={display_lang} ---", flush=True)

        summary = process_subset(
            meta_path=meta,
            root=args.root,
            template=args.template,
            out_dir=out_dir,
            recognizer=recognizer,
            language=sub_lang,
            workers=args.workers,
            limit=args.limit,
            summary_csv=summary_csv,
        )
        summaries.append(summary)

    overall_elapsed = round(time.perf_counter() - overall_t0, 1)
    print("\n" + "=" * 60)
    print(f"全部完成, 总耗时 {overall_elapsed}s, 输出目录: {out_dir}")
    print(f"{'子集':<28}{'lang':<8}{'成功/总数':<14}{'平均CER':<10}{'用时':<10}")
    for s in summaries:
        ok = f"{s['success']}/{s['total']}"
        cer = "-" if s["avg_cer"] is None else f"{s['avg_cer']}%"
        et = f"{s.get('elapsed_sec', '-')}s"
        lang = s.get("language", "") or "-"
        print(f"{s['name']:<28}{lang:<8}{ok:<14}{cer:<10}{et:<10}")
    print(f"汇总: {summary_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
