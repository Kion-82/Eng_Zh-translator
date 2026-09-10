# -*- coding: utf-8 -*-
"""PDF 抽取后端：pypdf —— 兜底，纯 Python 零原生依赖。

主力后端 pdfminer.six 依赖 cryptography，而很老的系统（比如 macOS 10.14）
没有它的预编译包、又编译不动。这时就退回这个后端：只要 pypdf 一个纯
Python 包，任何环境都装得上，代价是没有版面分析、坐标要靠估算。

这里只做一件事：把页面上的文字拆成带坐标和字号的小块（chunk）。
分栏判断在 pdf_extract 里做，做完之后才把 chunk 拼成行——顺序很重要，
否则三栏排版会在同一个 y 上把三栏的文字串成一行。
"""

from __future__ import annotations

import re
import statistics


def page_chunks(page) -> tuple[list[dict], float, float]:
    """返回 (文字块列表, 页宽, 页高)。"""
    try:
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
    except Exception:
        width, height = 595.0, 842.0

    chunks: list[dict] = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not text:
            return
        try:
            x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
            y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
            # 真正的字号 = 字体标称大小 × 文本矩阵纵向缩放 × 图形矩阵纵向缩放。
            # 很多 PDF 把字号写成 1，实际大小全在矩阵里，只看 font_size 会全变成 1。
            size = abs(float(font_size) * (tm[3] or 1.0) * (cm[3] or 1.0))
        except Exception:
            return
        if size <= 0.5 or size > 200:
            size = 10.0
        name = ""
        try:
            name = str((font_dict or {}).get("/BaseFont", ""))
        except Exception:
            pass
        bold = bool(re.search(r"bold|black|heavy", name, re.I))

        # 一个 chunk 里可能塞着好几行（pypdf 用 \n 分行），必须拆开，
        # 否则整段会被当成一行，行尾既丢空格又没法还原连字符
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if not part.strip():
                continue
            top = height - (y - i * size * 1.3) - size
            chunks.append({
                "text": part,
                "x0": x if i == 0 else None,   # 续行的左边界稍后按页面左边距补
                "top": top,
                "bottom": top + size * 1.15,
                "size": size,
                "bold": bold,
            })

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return [], width, height

    known = [c["x0"] for c in chunks if c["x0"] is not None]
    left = min(known) if known else 0.0
    for c in chunks:
        if c["x0"] is None:
            c["x0"] = left
        c["x1"] = c["x0"] + max(len(c["text"].strip()), 1) * c["size"] * 0.5

    return chunks, width, height


def lines_from_chunks(chunks: list[dict]) -> list[dict]:
    """把同一区域内的文字块按 y 聚成行。"""
    if not chunks:
        return []
    rows: dict[int, list[dict]] = {}
    for c in chunks:
        rows.setdefault(int(round(c["top"] / 2.0)), []).append(c)

    lines = []
    for _, items in rows.items():
        items.sort(key=lambda c: c["x0"])
        text = re.sub(r"[ \t]+", " ", "".join(c["text"] for c in items)).strip()
        if not text:
            continue
        size = round(statistics.median([c["size"] for c in items]), 1)
        lines.append({
            "text": text,
            "x0": min(c["x0"] for c in items),
            "x1": max(c["x1"] for c in items),
            "top": min(c["top"] for c in items),
            "bottom": max(c["bottom"] for c in items),
            "_size": size,
            "_bold": sum(1 for c in items if c["bold"]) > len(items) / 2,
        })
    lines.sort(key=lambda ln: (ln["top"], ln["x0"]))
    return lines


def chunks_in_region(chunks: list[dict], bbox: tuple[float, float, float, float]) -> list[dict]:
    x0, top, x1, bottom = bbox
    out = []
    for c in chunks:
        cx = (c["x0"] + c["x1"]) / 2
        cy = (c["top"] + c["bottom"]) / 2
        if x0 <= cx < x1 and top <= cy < bottom:
            out.append(c)
    return out
