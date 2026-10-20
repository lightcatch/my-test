# -*- coding: utf-8 -*-
"""单条调试: 把一条失败的 noises_en 样本喂给 FireRedASR2-AED, 看它返回什么 + 是否报错。"""
from __future__ import annotations

import csv
import sys
import wave
import contextlib
from pathlib import Path

ROOT = Path(r"d:/PyCode/test/ASR_test/fire_red_asr")
sys.path.insert(0, str(ROOT / "examples_infer" / "asr"))

from fireredasr2.asr import FireRedAsr2, FireRedAsr2Config  # type: ignore

META = Path(r"d:/PyCode/test/downloaded_audio/integrated_dialects/noises_en/metadata.csv")
CASES = ["noise_0002", "noise_0006", "noise_0008", "noise_0024", "noise_0033"]  # 失败样本

rows = {r["编号"]: r for r in csv.DictReader(open(META, encoding="utf-8-sig"))}

print("加载 FireRedASR2-AED ...")
model = FireRedAsr2.from_pretrained(
    "aed",
    str(ROOT / "pretrained_models" / "FireRedASR2-AED"),
    FireRedAsr2Config(use_gpu=True, use_half=False, beam_size=3, decode_max_len=300),
)
print("加载完成\n")

for code in CASES:
    rec = rows[code]
    wav_path = META.parent / rec["saved_path"]
    abs_wav = wav_path.resolve()
    with contextlib.closing(wave.open(str(abs_wav), "rb")) as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        nframes = wf.getnframes()
        dur = nframes / sr
    print(f"[{code}] dur={dur:.2f}s sr={sr} ch={nch} sw={sw}B  ref={rec['文本']!r}")
    try:
        # 默认参数
        r1 = model.transcribe([code], [str(abs_wav)])
        print(f"   default       -> {r1!r}")
    except Exception as exc:
        print(f"   default FAIL  -> {exc!r}")
    try:
        # 加大 beam / decode_max_len
        m2 = FireRedAsr2.from_pretrained(
            "aed",
            str(ROOT / "pretrained_models" / "FireRedASR2-AED"),
            FireRedAsr2Config(use_gpu=True, use_half=False, beam_size=8, decode_max_len=600),
        )
        r2 = m2.transcribe([code], [str(abs_wav)])
        print(f"   beam=8 max600 -> {r2!r}")
    except Exception as exc:
        print(f"   beam=8 FAIL   -> {exc!r}")
    print()
