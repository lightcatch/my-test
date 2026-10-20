# -*- coding: utf-8 -*-
"""ASR 单条延迟基准测试。

- 从 dongbei/metadata.csv 取前 100 条固定样本 (长度分布典型)
- 对指定 ASR (--asr) 跑一次:
  - 用第 1 条做 warmup, 不计入统计
  - 剩余 99 条串行 recognize()
  - 每条记录: 文件名, 音频时长(s), 推理耗时(ms), RTF
- 输出:
  - JSON: ASR_test/asr_score/_bench_<asr>_<timestamp>.json
    * summary: min/P50/P90/P99/max/avg latency + avg RTF + 总耗时 + 模型 setup 时间 + warmup 时间
    * detail: 每条样本记录

用法 (每个 ASR 用它自己 venv):
  ASR_test\\mega_asr\\.venv\\Scripts\\python.exe -X utf8 benchmark_speed.py --asr mega_asr
  ASR_test\\fire_red_asr\\.venv\\Scripts\\python.exe -X utf8 benchmark_speed.py --asr fire_red_asr --precision fp16
  ASR_test\\sense_voice_onnx\\.venv\\Scripts\\python.exe -X utf8 benchmark_speed.py --asr sense_voice_onnx
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
import wave
import contextlib
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PARENT_DIR = SCRIPT_DIR.parent  # ASR_test
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

DEFAULT_ROOT = Path(r"d:/PyCode/test/downloaded_audio/integrated_dialects")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--asr", required=True,
                   choices=["mega_asr", "fire_red_asr", "sense_voice_onnx", "doubao_asr"],
                   help="要测试的 ASR")
    p.add_argument("--precision", default=None,
                   choices=["fp32", "fp16", "int8"],
                   help="精度覆盖 (仅 fire_red_asr 支持 fp16, 其它 asr 忽略)")
    p.add_argument("--subset", default="dongbei",
                   help="从哪个子集抽样本, 默认 dongbei")
    p.add_argument("--num-samples", type=int, default=100,
                   help="抽多少条 (含 1 条 warmup, 默认 100)")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="输出目录, 默认 ASR_test/asr_score/")
    p.add_argument("--device", default="cuda")
    return p.parse_args()


def build_recognizer(args: argparse.Namespace):
    if args.asr == "mega_asr":
        from asr_score.recognizers.mega_asr import MegaASRRecognizer
        return MegaASRRecognizer(device_map=args.device)
    if args.asr == "fire_red_asr":
        from asr_score.recognizers.fire_red_asr import FireRedASRRecognizer
        use_half = (args.precision == "fp16")
        return FireRedASRRecognizer(use_gpu=(args.device != "cpu"), use_half=use_half)
    if args.asr == "sense_voice_onnx":
        from asr_score.recognizers.sense_voice_onnx import SenseVoiceONNXRecognizer
        return SenseVoiceONNXRecognizer()
    if args.asr == "doubao_asr":
        from asr_score.recognizers.doubao_asr import DoubaoASRRecognizer
        return DoubaoASRRecognizer()
    raise ValueError(f"未知 ASR: {args.asr}")


def wav_duration(path: Path) -> float:
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return round(frames / rate, 3) if rate else 0.0
    except Exception:
        return 0.0


def load_samples(root: Path, subset: str, num: int) -> list[dict]:
    meta = root / subset / "metadata.csv"
    if not meta.exists():
        raise FileNotFoundError(meta)
    rows = []
    with open(meta, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            wav = meta.parent / r.get("saved_path", "")
            if wav.exists():
                rows.append({
                    "编号": r.get("编号", ""),
                    "文件名": r.get("文件名", ""),
                    "文本": r.get("文本", ""),
                    "wav": wav,
                })
            if len(rows) >= num:
                break
    return rows


def pctile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir or SCRIPT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"ASR = {args.asr}, precision = {args.precision or '(默认)'}, subset = {args.subset}, num = {args.num_samples}")

    samples = load_samples(DEFAULT_ROOT, args.subset, args.num_samples)
    if len(samples) < 2:
        print(f"样本太少: {len(samples)}"); return 1
    print(f"加载 {len(samples)} 条样本")

    # 每条音频时长
    for s in samples:
        s["duration_s"] = wav_duration(s["wav"])

    # 构建 recognizer + setup 计时
    print("加载模型...")
    t0 = time.perf_counter()
    rec = build_recognizer(args)
    rec.setup()
    setup_sec = round(time.perf_counter() - t0, 2)
    print(f"模型 setup 用时 {setup_sec} s")

    # warmup (第 1 条)
    print("warmup...")
    w0 = time.perf_counter()
    _ = rec.recognize(str(samples[0]["wav"]))
    warmup_sec = round(time.perf_counter() - w0, 2)
    print(f"warmup (第 1 条) 用时 {warmup_sec} s")

    # 正式测速 (第 2 条起)
    details = []
    print(f"开始测速: {len(samples) - 1} 条...")
    bench_start = time.perf_counter()
    for i, s in enumerate(samples[1:], start=2):
        t = time.perf_counter()
        res = rec.recognize(str(s["wav"]))
        elapsed_ms = round((time.perf_counter() - t) * 1000, 2)
        dur = s["duration_s"] or 0.001
        rtf = round(elapsed_ms / 1000 / dur, 4) if dur > 0 else 0.0
        hyp = (res.text or "")[:30]
        details.append({
            "idx": i,
            "file": s["文件名"],
            "duration_s": dur,
            "latency_ms": elapsed_ms,
            "rtf": rtf,
            "status": res.status,
            "hyp_preview": hyp,
        })
        if i % 10 == 0 or i == len(samples):
            print(f"  [{i}/{len(samples)}] {elapsed_ms:>7.2f} ms  RTF={rtf:.3f}  dur={dur:.2f}s")
    bench_total = round(time.perf_counter() - bench_start, 2)

    # 统计
    lat = [d["latency_ms"] for d in details]
    rtfs = [d["rtf"] for d in details if d["rtf"] > 0]
    total_audio = round(sum(d["duration_s"] for d in details), 2)
    summary = {
        "asr": args.asr,
        "precision": args.precision or "(默认)",
        "device": args.device if args.asr != "sense_voice_onnx" else "cpu",
        "subset": args.subset,
        "num_samples_loaded": len(samples),
        "num_samples_valid": len(details),
        "setup_sec": setup_sec,
        "warmup_sec": warmup_sec,
        "bench_total_sec": bench_total,
        "total_audio_sec": total_audio,
        "latency_ms_min": round(min(lat), 2) if lat else 0,
        "latency_ms_p50": pctile(lat, 0.5),
        "latency_ms_p90": pctile(lat, 0.9),
        "latency_ms_p99": pctile(lat, 0.99),
        "latency_ms_max": round(max(lat), 2) if lat else 0,
        "latency_ms_avg": round(statistics.mean(lat), 2) if lat else 0,
        "rtf_avg": round(statistics.mean(rtfs), 4) if rtfs else 0,
        "rtf_median": round(statistics.median(rtfs), 4) if rtfs else 0,
    }

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = out_dir / f"_bench_{args.asr}_{ts}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "detail": details}, f, ensure_ascii=False, indent=2)
    print(f"\n结果 JSON: {out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
