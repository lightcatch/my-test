# -*- coding: utf-8 -*-
"""把指定输出目录下所有 _summary_*.csv 合并成一个 _summary.csv 并删除原文件。

规则:
- 按 (name, language) 去重: 时间戳较晚的覆盖较早的 (即用最新结果)。
- 排序: 按 name 字母序输出, 方便查阅。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

FIELDS = ["name", "language", "total", "success", "avg_cer", "elapsed_sec", "out_path"]


def merge(target_dir: Path) -> Path:
    # 找当前目录下所有时间戳 summary _summary_*.csv 和已合并的 _summary.csv 一起做输入
    files = sorted([p for p in target_dir.glob("_summary_*.csv")])
    existing = target_dir / "_summary.csv"
    if existing.exists():
        files = [existing, *files]
    if not files:
        # 无任何 summary, 创建空的也无意义
        return existing
    latest: dict[tuple[str, str], dict] = {}
    for f in files:
        try:
            ts = dt.datetime.strptime(f.stem.split("_summary_", 1)[1], "%Y%m%d_%H%M%S")
        except Exception:
            ts = dt.datetime.fromtimestamp(f.stat().st_mtime)
        with open(f, "r", encoding="utf-8-sig", newline="") as r:
            for row in csv.DictReader(r):
                key = (row.get("name", ""), row.get("language", ""))
                prev_ts = latest.get(key, {}).get("__ts__")
                if prev_ts is None or ts >= prev_ts:
                    row2 = dict(row)
                    row2["__ts__"] = ts
                    latest[key] = row2
    # 写入 _summary.csv
    out = target_dir / "_summary.csv"
    rows = sorted(latest.values(), key=lambda r: r.get("name", ""))
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    # 删掉旧时间戳 summary (但不要删最终的 _summary.csv 自己)
    for f in files:
        if f.name == "_summary.csv":
            continue
        f.unlink()
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dirs", nargs="+", type=Path,
                        help="包含 _summary_*.csv 的目录, 例如 .../打分结果/mega_ASR")
    args = parser.parse_args()
    for d in args.dirs:
        if not d.exists():
            print(f"跳过 (不存在): {d}")
            continue
        out = merge(d)
        print(f"已合并 -> {out}")


if __name__ == "__main__":
    main()
