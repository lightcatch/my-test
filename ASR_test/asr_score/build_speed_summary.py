# -*- coding: utf-8 -*-
"""把 _bench_<asr>_<ts>.json 合并成一个 速度对比.xlsx。

- 每个 ASR 取最新一次 bench 结果 (按文件名时间戳)
- Sheet1 "汇总": 每个 ASR 一行
- Sheet2 "明细": ASR × 每条样本
- 输出到 打分结果/速度对比.xlsx
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_XLSX = Path(r"d:/PyCode/test/downloaded_audio/integrated_dialects/打分结果/速度对比.xlsx")

# 想要的 ASR 展示顺序 (含 precision 标记)
ASR_ORDER = ["mega_asr", "fire_red_asr", "sense_voice_onnx", "doubao_asr"]


def latest_bench(asr: str) -> Path | None:
    pattern = str(SCRIPT_DIR / f"_bench_{asr}_*.json")
    files = sorted(glob.glob(pattern))
    return Path(files[-1]) if files else None


def main() -> None:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    bench_data: dict[str, dict] = {}
    for asr in ASR_ORDER:
        f = latest_bench(asr)
        if f is None:
            print(f"  跳过 {asr}: 没找到 bench json")
            continue
        with open(f, "r", encoding="utf-8") as jf:
            bench_data[asr] = json.load(jf)
        print(f"  {asr}: {f.name}")

    if not bench_data:
        print("没有 bench json"); return

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="305496")
    row_label_font = Font(bold=True)
    thin = Side(border_style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ============ Sheet1 汇总 ============
    ws = wb.active
    ws.title = "汇总"
    summary_cols = [
        ("ASR (模型名称)", 22),
        ("Precision (精度)", 14),
        ("Device (推理硬件)", 18),
        ("Subset (样本子集)", 14),
        ("Valid Samples (有效样本数)", 22),
        ("Setup sec (模型加载耗时/秒)", 26),
        ("Warmup sec (首条预热耗时/秒)", 26),
        ("Bench Total sec (测速总耗时/秒)", 28),
        ("Total Audio sec (样本总音频时长/秒)", 30),
        ("min ms (最快单条/毫秒)", 22),
        ("P50 ms (中位数/毫秒)", 22),
        ("P90 ms (90分位/毫秒)", 22),
        ("P99 ms (99分位/毫秒)", 22),
        ("max ms (最慢单条/毫秒)", 22),
        ("avg ms (平均单条/毫秒)", 22),
        ("RTF avg (平均实时率=推理÷音频)", 32),
        ("RTF median (中位数实时率)", 24),
    ]
    ws.append([c[0] for c in summary_cols])
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for asr in ASR_ORDER:
        s = bench_data.get(asr, {}).get("summary")
        if not s:
            continue
        row = [
            s.get("asr", ""),
            s.get("precision", ""),
            s.get("device", ""),
            s.get("subset", ""),
            s.get("num_samples_valid", 0),
            s.get("setup_sec", 0),
            s.get("warmup_sec", 0),
            s.get("bench_total_sec", 0),
            s.get("total_audio_sec", 0),
            s.get("latency_ms_min", 0),
            s.get("latency_ms_p50", 0),
            s.get("latency_ms_p90", 0),
            s.get("latency_ms_p99", 0),
            s.get("latency_ms_max", 0),
            s.get("latency_ms_avg", 0),
            s.get("rtf_avg", 0),
            s.get("rtf_median", 0),
        ]
        ws.append(row)
    # 样式
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=1).font = row_label_font
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = border
            if isinstance(cell.value, (int, float)):
                if c in (16, 17):  # RTF 列
                    cell.number_format = "0.0000"
                else:
                    cell.number_format = "0.00"
                cell.alignment = Alignment(horizontal="right")
    for i, (_, w) in enumerate(summary_cols, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "B2"

    # ============ Sheet2 明细 ============
    ws2 = wb.create_sheet("明细")
    detail_cols = [
        ("ASR (模型名称)", 22),
        ("Precision (精度)", 14),
        ("Idx (样本序号)", 14),
        ("File (文件名)", 40),
        ("Duration s (音频时长/秒)", 22),
        ("Latency ms (推理耗时/毫秒)", 24),
        ("RTF (实时率=推理÷音频)", 24),
        ("Status (状态)", 14),
        ("Hyp Preview (识别文字前30字)", 32),
    ]
    ws2.append([c[0] for c in detail_cols])
    for cell in ws2[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for asr in ASR_ORDER:
        data = bench_data.get(asr, {})
        s = data.get("summary", {})
        for d in data.get("detail", []):
            ws2.append([
                asr,
                s.get("precision", ""),
                d.get("idx", ""),
                d.get("file", ""),
                d.get("duration_s", 0),
                d.get("latency_ms", 0),
                d.get("rtf", 0),
                d.get("status", ""),
                d.get("hyp_preview", ""),
            ])
    # 样式
    for r in range(2, ws2.max_row + 1):
        for c in range(1, ws2.max_column + 1):
            cell = ws2.cell(row=r, column=c)
            cell.border = border
            if isinstance(cell.value, (int, float)):
                if c == 7:  # RTF
                    cell.number_format = "0.0000"
                elif c in (5, 6):
                    cell.number_format = "0.00"
                cell.alignment = Alignment(horizontal="right")
    for i, (_, w) in enumerate(detail_cols, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions

    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT_XLSX)
    print(f"\n速度对比 Excel: {OUT_XLSX}")


if __name__ == "__main__":
    main()
