# -*- coding: utf-8 -*-
"""测试夹具：用 ReportLab 现场生成几种典型版面的合成 PDF。

不需要翻译模型、不联网。每份 PDF 都刻意埋了一个以前踩过的坑，
对应的断言在 test_extract.py 里。
"""

from __future__ import annotations

import os
import sys

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

W, H = A4
COLW = (W - 2 * 50 - 20) / 2
COLS = (50, 50 + COLW + 20)

SENTS = [
    "Wetland ecosystems store a disproportionate share of terrestrial carbon relative to their area.",
    "However, drainage for agriculture has released large quantities of this carbon into the atmosphere.",
    "We surveyed forty sites across three catchments over two consecutive growing seasons.",
    "Species richness declined sharply where the water table fell below thirty centimetres.",
    "These results suggest that hydrological restoration should precede any planting effort.",
    "The effect was strongest in the northern catchment, which had the longest history of drainage.",
]


def rotate(k: int) -> str:
    return " ".join(SENTS[k:] + SENTS[:k])


def wrap(c, text, x, y, width, font="Times-Roman", size=10, lead=12.5, cites=None):
    """简易排版：逐词绘制（很多真实 PDF 也是这样逐词定位的）。

    cites = {词序号: "12"} 会在该词后画一个上标引注。
    """
    words = text.split()
    lines, line = [], []
    for i, w in enumerate(words):
        trial = " ".join(t for t, _ in line + [(w, i)])
        if c.stringWidth(trial, font, size) > width and line:
            lines.append(line)
            line = []
        line.append((w, i))
    if line:
        lines.append(line)
    for ln in lines:
        cx = x
        for w, i in ln:
            c.setFont(font, size)
            c.drawString(cx, y, w)
            cx += c.stringWidth(w, font, size)
            if cites and i in cites:
                c.setFont(font, size * 0.65)
                c.drawString(cx, y + size * 0.38, cites[i])
                cx += c.stringWidth(cites[i], font, size * 0.65)
            cx += c.stringWidth(" ", font, size)
        y -= lead
    return y


def _running_head(c, page_no):
    # 放在裁切线（5.5%）以内、边缘带（10%）以内：必须靠边缘带规则去掉
    c.setFont("Times-Roman", 8)
    c.drawString(50, H - 52, "JOURNAL OF APPLIED ECOLOGY")
    c.drawCentredString(W / 2, 50, str(page_no))


def _paper(path):
    """三页双栏论文。

    p1：全大写加粗小节标题（位于页面顶部边缘带内）、上标引注、
        行尾连字符、只有 "it." 的段落末行
    p2：页面中间横插一张通栏图
    p3：右栏是全大写的 REFERENCES，之后有 Appendix
    """
    c = canvas.Canvas(path, pagesize=A4)

    # ---- p1
    _running_head(c, 1)
    for ci, x in enumerate(COLS):
        y = H - 78
        c.setFont("Times-Bold", 10)
        c.drawString(x, y, ("1. INTRODUCTION", "2. METHODS")[ci])
        y -= 16
        y = wrap(c, rotate(ci), x, y, COLW, cites={5: "1", 17: "2,7"}) - 6
        y = wrap(c, rotate(ci + 2), x, y, COLW) - 6
        c.setFont("Times-Roman", 10)
        for k, ln in enumerate([
            "The restoration benefit was largest at sites with peat",
            "deeper than one metre, a pattern we call deep accumu-",
            "lation, and the fit was good for all of",
            "it.",
        ]):
            c.drawString(x, y - 12.5 * k, ln)
    c.showPage()

    # ---- p2
    _running_head(c, 2)
    for ci, x in enumerate(COLS):
        wrap(c, rotate(ci), x, H - 78, COLW)
    c.rect(50, H / 2 - 80, W - 100, 120)
    c.setFont("Helvetica", 8)
    c.drawString(60, H / 2 + 20, "Label A")
    c.drawString(W - 120, H / 2 + 20, "Label B")
    c.setFont("Times-Italic", 9)
    c.drawString(50, H / 2 - 95,
                 "Figure 2. Species richness against water-table depth across all forty sites.")
    for ci, x in enumerate(COLS):
        wrap(c, "Below the figure. " + rotate(3 + ci), x, H / 2 - 120, COLW)
    c.showPage()

    # ---- p3
    _running_head(c, 3)
    x = COLS[0]
    c.setFont("Times-Bold", 10)
    c.drawString(x, H - 78, "4. DISCUSSION")
    wrap(c, rotate(4), x, H - 94, COLW)
    x = COLS[1]
    c.setFont("Times-Bold", 10)
    c.drawString(x, H - 78, "REFERENCES")
    c.setFont("Times-Roman", 9)
    y = H - 94
    for ref in ["Smith J. (2020) Wetland carbon budgets. Nature 5, 1-10.",
                "Jones K. (2019) Peat drainage and emissions. Ecology 7, 11-20."]:
        y = wrap(c, ref, x, y, COLW, size=9, lead=11) - 4
    y -= 14
    c.setFont("Times-Bold", 10)
    c.drawString(x, y, "Appendix A")
    wrap(c, "Site coordinates are listed in the supplementary table for every catchment.",
         x, y - 16, COLW)
    c.showPage()
    c.save()


def _crosspage(path):
    """三页单栏：段落跨页；页眉是大小写混排（只能靠跨页重复检测去掉）；
    参考文献标题是 "Literature Cited"，与正文同字号、不加粗。"""
    c = canvas.Canvas(path, pagesize=A4)
    for p in (1, 2, 3):
        c.setFont("Times-Roman", 8)
        c.drawString(72, H - 55, f"Pu et al. · Wetland carbon and drainage · {p}")
        y = H - 100
        if p == 1:
            y = wrap(c, rotate(0), 72, y, W - 144, size=11, lead=14) - 10
            wrap(c, "The decline was steepest at sites where the water table",
                 72, 120, W - 144, size=11, lead=14)
        elif p == 2:
            y = wrap(c, "fell below thirty centimetres for most of the summer.",
                     72, y, W - 144, size=11, lead=14) - 10
            wrap(c, rotate(2), 72, y, W - 144, size=11, lead=14)
        else:
            y = wrap(c, rotate(4), 72, y, W - 144, size=11, lead=14) - 20
            c.setFont("Times-Roman", 11)
            c.drawString(72, y, "Literature Cited")
            wrap(c, "Smith J. (2020) Wetland carbon budgets. Nature 5, 1-10.",
                 72, y - 20, W - 144, size=11, lead=14)
        c.showPage()
    c.save()


def _twins(path):
    """三页版面、正文完全相同：重复检测只能删页眉，不能把相同位置的正文也删掉。"""
    c = canvas.Canvas(path, pagesize=A4)
    for p in (1, 2, 3):
        c.setFont("Times-Roman", 8)
        c.drawString(72, H - 55, f"Pu et al. · Wetland carbon and drainage · {p}")
        wrap(c, rotate(0), 72, H - 80, W - 144, size=11, lead=14)
        c.showPage()
    c.save()


def _book(path, n=30):
    c = canvas.Canvas(path, pagesize=A4)
    for p in range(1, n + 1):
        c.setFont("Times-Roman", 9)
        c.drawCentredString(W / 2, H - 52, "THE ECOLOGY OF WETLANDS")
        c.drawCentredString(W / 2, 50, str(p))
        wrap(c, rotate(p % 6) + f" This is page {p}.", 72, H - 100, W - 144, size=11, lead=14)
        c.showPage()
    c.save()


@pytest.fixture(scope="session")
def pdfs(tmp_path_factory):
    d = tmp_path_factory.mktemp("pdfs")
    out = {}
    for name, fn in (("paper", _paper), ("crosspage", _crosspage), ("twins", _twins),
                     ("book", _book)):
        p = str(d / f"{name}.pdf")
        fn(p)
        out[name] = p
    return out
