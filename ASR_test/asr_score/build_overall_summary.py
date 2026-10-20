# -*- coding: utf-8 -*-
"""把 打分结果/*/_summary.csv 汇总成总表 (透视形式)。

布局:
- 行: 方言 (15 个子集)
- 列: 5 个 ASR 模型
- 单元格: avg_cer (%)；第二张 sheet 是 elapsed_sec
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(r"d:/PyCode/test/downloaded_audio/integrated_dialects/打分结果")

DIALECT_ORDER = [
    "mandarin",
    "dongbei", "henan", "shandong", "sichuan", "yue",
    "en",
    "erbao",
    "mixed_noise_dongbei", "mixed_noise_henan", "mixed_noise_shandong",
    "mixed_noise_sichuan", "mixed_noise_yue",
    "noises_zh", "noises_en",
]
ASR_ORDER = [
    "mega_asr", "fire_red_ASR", "GLM_ASR", "ARK_ASR",
    "SenseVoice_ONNX_INT8", "Doubao_SAUC_Nostream",
]


def read_summary(asr_dir: Path) -> dict[str, dict[str, str]]:
    p = asr_dir / "_summary.csv"
    out: dict[str, dict[str, str]] = {}
    if not p.exists():
        return out
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = r.get("name", "")
            if name:
                out[name] = {
                    "avg_cer": r.get("avg_cer", ""),
                    "elapsed_sec": r.get("elapsed_sec", ""),
                }
    return out


def _to_float(v: str):
    if v in (None, ""):
        return ""
    try:
        return float(v)
    except ValueError:
        return v


def main() -> None:
    asr_dirs = sorted([d for d in ROOT.iterdir() if d.is_dir()])
    if not asr_dirs:
        print(f"在 {ROOT} 下没找到任何 ASR 输出目录")
        return

    data: dict[str, dict[str, dict[str, str]]] = {}
    for d in asr_dirs:
        data[d.name] = read_summary(d)
        print(f"  {d.name:<28}  {len(data[d.name])} 个子集")

    asr_names = [n for n in ASR_ORDER if n in data]
    asr_names += [n for n in data.keys() if n not in asr_names]

    all_dialects = {x for asr in data.values() for x in asr.keys()}
    dialects = [d for d in DIALECT_ORDER if d in all_dialects]
    dialects += sorted(d for d in all_dialects if d not in dialects)

    cer_rows, time_rows = [], []
    for d in dialects:
        cer_row = [d]
        time_row = [d]
        for a in asr_names:
            cell = data.get(a, {}).get(d, {})
            cer_row.append(_to_float(cell.get("avg_cer", "")))
            time_row.append(_to_float(cell.get("elapsed_sec", "")))
        cer_rows.append(cer_row)
        time_rows.append(time_row)

    header = ["方言名称"] + asr_names

    csv_out = ROOT / "总表.csv"
    with open(csv_out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(cer_rows)
    print(f"\nCSV (CER 透视) 已生成: {csv_out}  ({len(cer_rows)} 行 × {len(header)} 列)")

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl 未安装, 跳过 Excel 输出")
        return

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="305496")
    row_label_font = Font(bold=True)
    thin = Side(border_style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _fill_sheet(ws, rows, num_format: str) -> None:
        ws.append(header)
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
        for row in rows:
            ws.append(row)
        for r in range(2, ws.max_row + 1):
            label_cell = ws.cell(row=r, column=1)
            label_cell.font = row_label_font
            label_cell.alignment = Alignment(horizontal="left")
            label_cell.border = border
            for c in range(2, ws.max_column + 1):
                cell = ws.cell(row=r, column=c)
                cell.border = border
                if isinstance(cell.value, (int, float)):
                    cell.number_format = num_format
                    cell.alignment = Alignment(horizontal="right")
        ws.column_dimensions[get_column_letter(1)].width = 26
        for i in range(2, len(header) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 22
        ws.freeze_panes = "B2"

    ws_cer = wb.active
    ws_cer.title = "CER(%)"
    _fill_sheet(ws_cer, cer_rows, num_format="0.00")

    ws_time = wb.create_sheet("耗时(s)")
    _fill_sheet(ws_time, time_rows, num_format="0.0")

    xlsx_out = ROOT / "总表.xlsx"
    wb.save(xlsx_out)
    print(f"Excel (双 sheet) 已生成: {xlsx_out}")
    print(f"  Sheet1 'CER(%)': 行=方言, 列={asr_names}")
    print(f"  Sheet2 '耗时(s)': 行=方言, 列={asr_names}")


if __name__ == "__main__":
    main()
