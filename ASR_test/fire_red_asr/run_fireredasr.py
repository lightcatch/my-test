"""FireRedASR2-AED 本地推理 runner（原生 PyTorch + CUDA）。

常用命令（在 ASR_test/fire_red_asr/ 目录下，务必用本目录 venv 的 python + -X utf8）
---------------------------------------------------------------------
识别文件夹:  .venv/Scripts/python.exe -X utf8 run_fireredasr.py
单个文件:    .venv/Scripts/python.exe -X utf8 run_fireredasr.py --audio audio_input/xxx.wav
用 CPU 跑:   .venv/Scripts/python.exe -X utf8 run_fireredasr.py --no-gpu
调 beam:     .venv/Scripts/python.exe -X utf8 run_fireredasr.py --beam-size 5

待识别音频放进 audio_input/，结果写到 results/fireredasr_时间戳.xlsx。
权重在 pretrained_models/FireRedASR2-AED/（model.pth.tar / cmvn.ark / dict.txt / train_bpe1000.model），离线可跑。
支持普通话 + 20 多种中文方言（粤语/四川话/上海话/吴语/闽南话等）+ 英文。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
# AED 推理代码在 examples_infer/asr 下（包名 fireredasr2）
sys.path.insert(0, str(ROOT_DIR / "examples_infer" / "asr"))

# Windows 终端默认 GBK，会让中文输出乱码；统一切到 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

DEFAULT_MODEL_DIR = ROOT_DIR / "pretrained_models" / "FireRedASR2-AED"
DEFAULT_AUDIO_DIR = ROOT_DIR / "audio_input"
DEFAULT_RESULTS_DIR = ROOT_DIR / "results"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用 FireRedASR2-AED 转写 audio_input/ 下的音频文件。",
    )
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR,
                        help="待识别音频所在文件夹。")
    parser.add_argument("--audio", type=Path, default=None,
                        help="只识别单个音频文件，优先级高于 --audio-dir。")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR,
                        help="FireRedASR2-AED 权重目录。")
    parser.add_argument("--no-gpu", dest="use_gpu", action="store_false", default=True,
                        help="改用 CPU 推理（默认 GPU）。")
    parser.add_argument("--use-half", action="store_true", default=False,
                        help="GPU 半精度推理（bf16/fp16），省显存。")
    parser.add_argument("--beam-size", type=int, default=3, help="beam search 宽度。")
    parser.add_argument("--decode-max-len", type=int, default=300,
                        help="最大解码长度（token 上限）。")
    parser.add_argument("--output", type=Path, default=None,
                        help="结果 Excel 输出路径。默认写到 results/ 带时间戳的文件。")
    return parser.parse_args()


def collect_audio_files(audio_dir: Path) -> list[Path]:
    if not audio_dir.exists():
        raise FileNotFoundError(f"音频文件夹不存在: {audio_dir}")
    return sorted(
        path for path in audio_dir.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def validate_model(model_dir: Path) -> None:
    required = ["model.pth.tar", "cmvn.ark", "dict.txt", "train_bpe1000.model"]
    missing = [f for f in required if not (model_dir / f).is_file()]
    # LFS 指针文件很小，按大小再判一次（真权重 > 1MB）
    too_small = [
        f for f in ("model.pth.tar",)
        if (model_dir / f).is_file() and (model_dir / f).stat().st_size < 1_000_000
    ]
    if missing or too_small:
        raise FileNotFoundError(
            f"权重不完整。缺失={missing} 疑似LFS指针={too_small}\n期望目录: {model_dir}"
        )


def build_model(args: argparse.Namespace) -> Any:
    from fireredasr2.asr import FireRedAsr2, FireRedAsr2Config

    config = FireRedAsr2Config(
        use_gpu=args.use_gpu,
        use_half=args.use_half,
        beam_size=args.beam_size,
        decode_max_len=args.decode_max_len,
    )
    return FireRedAsr2.from_pretrained("aed", str(args.model_dir), config)


def write_results_excel(rows: list[dict[str, Any]], output_path: Path) -> None:
    import pandas as pd

    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["audio_file", "text", "confidence", "dur_s", "rtf",
               "elapsed_sec", "status", "error"]
    pd.DataFrame(rows, columns=columns).to_excel(output_path, index=False)


def main() -> int:
    args = parse_args()
    try:
        validate_model(args.model_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.audio is not None:
        if not args.audio.exists():
            print(f"音频文件不存在: {args.audio}", file=sys.stderr)
            return 1
        audio_files = [args.audio]
    else:
        audio_files = collect_audio_files(args.audio_dir)

    if not audio_files:
        print(f"在 {args.audio_dir} 没有找到音频文件。把音频放进去再运行。")
        print(f"支持的扩展名: {', '.join(sorted(AUDIO_EXTENSIONS))}")
        return 0

    print(f"找到 {len(audio_files)} 个音频文件，开始加载模型...")
    load_start = time.perf_counter()
    model = build_model(args)
    print(f"模型加载完成，耗时 {time.perf_counter() - load_start:.1f}s\n")

    rows: list[dict[str, Any]] = []
    success = 0
    for idx, audio_path in enumerate(audio_files, start=1):
        print(f"[{idx}/{len(audio_files)}] {audio_path.name} ...", flush=True)
        started = time.perf_counter()
        row: dict[str, Any] = {
            "audio_file": audio_path.name, "text": "", "confidence": "",
            "dur_s": "", "rtf": "", "elapsed_sec": 0.0,
            "status": "success", "error": "",
        }
        try:
            results = model.transcribe([audio_path.stem], [str(audio_path)])
            result = results[0] if results else {}
            row["text"] = str(result.get("text", "")).strip()
            row["confidence"] = result.get("confidence", "")
            row["dur_s"] = result.get("dur_s", "")
            row["rtf"] = result.get("rtf", "")
            if not row["text"]:
                row["status"] = "error"
                row["error"] = "识别结果为空"
            else:
                success += 1
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响其余文件
            row["status"] = "error"
            row["error"] = str(exc)
            print(f"  失败: {exc}", file=sys.stderr)

        row["elapsed_sec"] = round(time.perf_counter() - started, 2)
        if row["text"]:
            print(f"  -> {row['text']}")
        print(f"  (conf={row['confidence']}, dur={row['dur_s']}s, {row['elapsed_sec']}s)\n")
        rows.append(row)

    output_path = args.output or (
        DEFAULT_RESULTS_DIR / f"fireredasr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    write_results_excel(rows, output_path)

    print("=" * 40)
    print(f"完成: {success}/{len(audio_files)} 成功")
    print(f"结果文件: {output_path}")
    return 0 if success == len(audio_files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
