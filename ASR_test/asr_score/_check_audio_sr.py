# -*- coding: utf-8 -*-
"""统计 integrated_dialects 各子集的音频采样率/位深/声道分布。"""
from __future__ import annotations

import contextlib
import csv
import wave
from collections import Counter
from pathlib import Path

ROOT = Path(r"d:/PyCode/test/downloaded_audio/integrated_dialects")


def stat_subset(meta: Path) -> tuple[Counter, int]:
    rows = list(csv.DictReader(open(meta, encoding="utf-8-sig")))
    c: Counter = Counter()
    for row in rows:
        wav = meta.parent / row["saved_path"]
        if not wav.exists():
            continue
        try:
            with contextlib.closing(wave.open(str(wav), "rb")) as wf:
                key = (wf.getframerate(), wf.getsampwidth() * 8, wf.getnchannels())
                c[key] += 1
        except Exception as exc:
            c[("error", str(exc))] += 1
    return c, len(rows)


def fmt_key(k):
    if isinstance(k[0], int):
        sr, bits, ch = k
        return f"{sr}Hz/{bits}bit/{ch}ch"
    return f"error: {k[1]}"


for meta in sorted(ROOT.rglob("metadata.csv")):
    rel = meta.parent.relative_to(ROOT)
    c, n = stat_subset(meta)
    if not c:
        continue
    print(f"{str(rel):<28} 共 {n} 条")
    for k, v in c.most_common():
        print(f"  {fmt_key(k):<25} {v}")
