# -*- coding: utf-8 -*-
"""PDF 抽取后端：pdfminer.six —— 主力，几何精确。

pdfminer 自带版面分析，能按文字的邻近关系把页面聚成"文本框"。这种框
天然不跨栏，拿它当排序的原子单位，比自己按坐标猜稳得多。每个字符还带
精确的字号和坐标，参考文献角标才能靠"字号更小 + 基线抬高"识别出来。

对外只暴露两个函数：iter_page_layouts_boxes（逐页产出版面）和
page_boxes（把版面拆成文本框），排序和合段的活儿在 pdf_extract 里干。
"""

from __future__ import annotations

import re
import statistics

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine


def _walk_chars(element):
    stack = [element]
    while stack:
        el = stack.pop()
        if isinstance(el, LTChar):
            yield el
        elif hasattr(el, "__iter__"):
            stack.extend(list(el))


_SUP_CHARS = set("0123456789,.-–—*†‡§¶")


def _line_from_line(line_obj, height: float) -> dict | None:
    """把 pdfminer 的一行变成我们统一格式的行，并丢掉上标引注。

    学术文献里的参考文献角标（recognition1–4、molecules8、disease12,13）在
    纯文本里会和单词粘在一起。翻译模型没见过这种东西，喂进去经常触发
    "复读数字"式的退化输出，所以在这里就按"字号更小 + 基线抬高 + 只由
    数字标点组成"把它们识别出来剔掉。

    遍历时保留 pdfminer 推断出的空格（LTAnno）：有些 PDF 里根本没有空格
    字符，词距是靠坐标表示的，自己拼字符会把整行粘成一坨。
    """
    from pdfminer.layout import LTAnno

    items = list(line_obj)
    chars = [c for c in items if isinstance(c, LTChar) and c.get_text().strip()]
    if not chars:
        return None

    sizes = [float(getattr(c, "size", 10.0) or 10.0) for c in chars]
    body_size = statistics.median(sizes)
    baseline = statistics.median([c.y0 for c in chars
                                  if abs(float(getattr(c, "size", 10.0)) - body_size) < 0.6]
                                 or [c.y0 for c in chars])

    # 先标出哪些字符像上标
    sup_flag = {}
    for c in chars:
        size = float(getattr(c, "size", 10.0) or 10.0)
        raised = c.y0 - baseline
        sup_flag[id(c)] = (size <= body_size * 0.86
                           and raised >= body_size * 0.10
                           and c.get_text() in _SUP_CHARS)
    # 单个字母不算引注（可能是数学符号），只有成串的数字标点才算
    groups: list[list] = []
    for c in chars:
        if sup_flag[id(c)]:
            if groups and groups[-1][-1] is not None and c.x0 - groups[-1][-1].x1 < body_size:
                groups[-1].append(c)
            else:
                groups.append([c])
    for g in groups:
        if not any(ch.get_text().isdigit() for ch in g):
            for ch in g:
                sup_flag[id(ch)] = False

    parts = []
    kept = []
    for obj in items:
        if isinstance(obj, LTAnno):
            parts.append(obj.get_text())
        elif isinstance(obj, LTChar):
            if sup_flag.get(id(obj)):
                continue
            parts.append(obj.get_text())
            if obj.get_text().strip():
                kept.append(obj)

    text = re.sub(r"\s+", " ", "".join(parts)).strip()
    if not text or not kept:
        return None

    names = [str(getattr(c, "fontname", "")) for c in kept]
    bold = sum(1 for n in names if re.search(r"bold|black|heavy", n, re.I))
    ksizes = [float(getattr(c, "size", 10.0) or 10.0) for c in kept]
    return {
        "text": text,
        "x0": min(c.x0 for c in kept),
        "x1": max(c.x1 for c in kept),
        "top": height - max(c.y1 for c in kept),
        "bottom": height - min(c.y0 for c in kept),
        "_size": round(statistics.median(ksizes), 1),
        "_bold": bold > len(names) / 2 if names else False,
    }


def _line_from_chars(chars, height: float, text: str | None = None) -> dict | None:
    """没有行对象时的退路：直接从字符列表拼。"""
    items = [c for c in chars if isinstance(c, LTChar)]
    if not items:
        return None
    if text is None:
        text = "".join(c.get_text() for c in items)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    sizes = [float(getattr(c, "size", 10.0) or 10.0)
             for c in items if not c.get_text().isspace()]
    names = [str(getattr(c, "fontname", "")) for c in items if not c.get_text().isspace()]
    bold = sum(1 for n in names if re.search(r"bold|black|heavy", n, re.I))
    return {
        "text": text,
        "x0": min(c.x0 for c in items),
        "x1": max(c.x1 for c in items),
        "top": height - max(c.y1 for c in items),
        "bottom": height - min(c.y0 for c in items),
        "_size": round(statistics.median(sizes), 1) if sizes else 10.0,
        "_bold": bold > len(names) / 2 if names else False,
    }


def page_boxes(layout) -> tuple[list[dict], float, float]:
    """返回 (文本框列表, 页宽, 页高)。

    每个文本框是 pdfminer 版面分析的产物：它按文字的邻近关系聚类，
    天生不会横跨栏间空白，所以拿它当排序的原子单位比自己按坐标猜靠谱得多。
    """
    width = float(layout.width)
    height = float(layout.height)
    boxes: list[dict] = []
    for element in layout:
        if not isinstance(element, LTTextContainer):
            continue
        lines = []
        for child in element:
            if isinstance(child, LTTextLine):
                ln = _line_from_line(child, height)
                if ln:
                    lines.append(ln)
        if not lines:
            ln = _line_from_chars(list(_walk_chars(element)), height, element.get_text())
            if ln:
                lines = [ln]
        if not lines:
            continue
        lines.sort(key=lambda l: (l["top"], l["x0"]))
        for ln in lines:
            # 所在文本框有几行：页眉页脚几乎总是单独成框，正文行则属于多行的框
            ln["_nbox"] = len(lines)
        boxes.append({
            "x0": min(l["x0"] for l in lines),
            "x1": max(l["x1"] for l in lines),
            "top": min(l["top"] for l in lines),
            "bottom": max(l["bottom"] for l in lines),
            "lines": lines,
        })
    return boxes, width, height


def iter_page_layouts_boxes(path: str, page_numbers=None):
    """给 page_boxes 用的版面迭代器：开启 pdfminer 的版面分析。"""
    laparams = LAParams(detect_vertical=False, boxes_flow=0.5)
    return extract_pages(path, laparams=laparams, page_numbers=page_numbers)
