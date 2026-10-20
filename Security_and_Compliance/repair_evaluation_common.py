# -*- coding: utf-8 -*-
"""Shared workbook-navigation helpers for evaluation-error repair commands."""

from __future__ import annotations

from collections.abc import Callable


class RepairError(RuntimeError):
    pass


def column_map(sheet, required: tuple[str, ...], text: Callable[[object], str]) -> dict[str, int]:
    headers = [text(cell.value) for cell in sheet[1]]
    missing = [header for header in required if header not in headers]
    if missing:
        raise RepairError(f"目标工作簿缺少必要列：{missing}")
    return {header: headers.index(header) + 1 for header in required}


def detail_rows(sheet, source_row_header: str, columns: dict[str, int]) -> list[int]:
    rows = [
        row
        for row in range(2, sheet.max_row + 1)
        if isinstance(sheet.cell(row, columns[source_row_header]).value, int)
    ]
    if not rows:
        raise RepairError("目标工作簿没有明细记录")
    return rows


def find_normal_row(
    sheet,
    columns: dict[str, int],
    rows: list[int],
    *,
    status_header: str,
    decision_header: str,
    passing_decision: str,
    text: Callable[[object], str],
) -> int:
    for row in rows:
        if (
            text(sheet.cell(row, columns[status_header]).value) == "success"
            and text(sheet.cell(row, columns[decision_header]).value) == passing_decision
        ):
            return row
    raise RepairError("找不到可用于恢复明细行样式的正常记录")
