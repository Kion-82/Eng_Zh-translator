# -*- coding: utf-8 -*-
"""用 ReportLab 生成中英对照 / 纯中文的译文 PDF。"""

from __future__ import annotations

import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer)

# 中文字体候选（按优先级）。ReportLab 只支持 TrueType 轮廓，苹果的
# PingFang、思源系列是 PostScript(CFF) 轮廓会注册失败，所以这里逐个试，
# 并且真正检查字体里有没有汉字字形，失败就自动换下一个。
_BASE = os.path.dirname(os.path.abspath(__file__))

_FONT_CANDIDATES = [
    # 用户自备：把任意中文 ttf/ttc 丢进 fonts/ 文件夹即可优先使用
    os.path.join(_BASE, "fonts"),
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simkai.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    # Linux
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    # 兜底：整目录扫一遍，逐个测试有没有汉字字形（老系统字体路径不一样）
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    r"C:\Windows\Fonts",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts/opentype",
]

_BOLD_CANDIDATES = [
    os.path.join(_BASE, "fonts", "bold"),
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]

_PROBE = "制度变迁研究"  # 用来验证字体确实带汉字字形


def _try_register(path: str, tag: str) -> str | None:
    """尝试注册一个字体文件（.ttc 会逐个子字体试），成功返回字体名。"""
    if not os.path.isfile(path):
        return None
    indices = range(8) if path.lower().endswith((".ttc", ".otc")) else [0]
    for idx in indices:
        name = f"CJK-{tag}-{os.path.basename(path)}-{idx}"
        try:
            font = TTFont(name, path, subfontIndex=idx)
            mapping = getattr(font.face, "charToGlyph", {}) or {}
            if not all(mapping.get(ord(ch)) for ch in _PROBE):
                continue  # 没有汉字字形（比如 DejaVu），换下一个
            pdfmetrics.registerFont(font)
            return name
        except Exception:
            continue
    return None


def _expand(entry: str) -> list[str]:
    """目录展开成里面的字体文件，普通路径原样返回。"""
    if os.path.isdir(entry):
        out = []
        for fn in sorted(os.listdir(entry)):
            if fn.lower().endswith((".ttf", ".ttc", ".otc")):
                out.append(os.path.join(entry, fn))
        return out
    return [entry]


_FONT_CACHE: tuple[str, str] | None = None


def register_cjk_font() -> tuple[str, str]:
    """返回 (正文中文字体名, 粗体中文字体名)。"""
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE

    regular = None
    for entry in _FONT_CANDIDATES:
        for path in _expand(entry):
            regular = _try_register(path, "r")
            if regular:
                break
        if regular:
            break
    if regular is None:
        # 兜底：内置 CID 字体，不嵌入字形，靠阅读器自带的中文字体渲染
        # （macOS 预览、Adobe Acrobat 都能正常显示）
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            regular = "STSong-Light"
        except Exception:
            regular = "Helvetica"

    bold = None
    for entry in _BOLD_CANDIDATES:
        for path in _expand(entry):
            bold = _try_register(path, "b")
            if bold:
                break
        if bold:
            break

    _FONT_CACHE = (regular, bold or regular)
    return _FONT_CACHE


def _latin1_safe(text: str) -> bool:
    """Times/Helvetica 这类内置字体只覆盖 Latin-1，超出的字符会渲染成黑方块。"""
    try:
        text.encode("latin-1")
        return True
    except Exception:
        return False


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class _Doc(BaseDocTemplate):
    def __init__(self, filename, header_text: str, cjk_font: str, **kw):
        super().__init__(filename, pagesize=A4,
                         leftMargin=20 * mm, rightMargin=18 * mm,
                         topMargin=18 * mm, bottomMargin=16 * mm, **kw)
        self.header_text = header_text
        self.cjk_font = cjk_font
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._decorate)])

    def _decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFont(self.cjk_font, 7.5)
        canvas.setFillColor(colors.HexColor("#9aa0a6"))
        head = self.header_text[:70]
        canvas.drawString(self.leftMargin, A4[1] - 12 * mm, head)
        canvas.drawRightString(A4[0] - self.rightMargin, A4[1] - 12 * mm, "英译中对照本")
        canvas.setStrokeColor(colors.HexColor("#e3e6ea"))
        canvas.setLineWidth(0.4)
        canvas.line(self.leftMargin, A4[1] - 13.5 * mm, A4[0] - self.rightMargin, A4[1] - 13.5 * mm)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()


def build_pdf(out_path: str, items: list[dict], meta: dict, mode: str = "bilingual") -> str:
    """items: [{en, zh, kind, page}]，按顺序排版。

    mode: bilingual（中英对照）| zh（纯中文）
    """
    cjk, cjk_bold = register_cjk_font()
    title = meta.get("title") or os.path.splitext(os.path.basename(meta.get("source", "文档")))[0]

    zh_body = ParagraphStyle("zh", fontName=cjk, fontSize=10.8, leading=17.5,
                             alignment=TA_JUSTIFY, spaceAfter=2,
                             textColor=colors.HexColor("#111418"), wordWrap="CJK")
    en_body = ParagraphStyle("en", fontName="Times-Roman", fontSize=8.8, leading=12.6,
                             alignment=TA_JUSTIFY, spaceAfter=3,
                             textColor=colors.HexColor("#6b7280"))
    zh_head = ParagraphStyle("zh_h", parent=zh_body, fontName=cjk_bold, fontSize=13.5,
                             leading=20, spaceBefore=10, spaceAfter=2, alignment=TA_LEFT,
                             textColor=colors.HexColor("#0b1220"))
    en_head = ParagraphStyle("en_h", parent=en_body, fontSize=9.2, leading=13,
                             textColor=colors.HexColor("#8a94a6"), spaceAfter=6)
    zh_cap = ParagraphStyle("zh_c", parent=zh_body, fontSize=9.6, leading=15,
                            textColor=colors.HexColor("#2f3742"), leftIndent=8)
    en_cap = ParagraphStyle("en_c", parent=en_body, fontSize=8.2, leading=11.6, leftIndent=8)
    marker = ParagraphStyle("mk", fontName=cjk, fontSize=7.6, leading=12, spaceBefore=8,
                            spaceAfter=4, textColor=colors.HexColor("#b6bcc6"))
    cover_title = ParagraphStyle("ct", fontName=cjk_bold, fontSize=22, leading=30,
                                 textColor=colors.HexColor("#0b1220"), spaceAfter=6)
    cover_sub = ParagraphStyle("cs", fontName=cjk, fontSize=10.5, leading=18,
                               textColor=colors.HexColor("#5b6472"))

    story = []
    # 封面
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph(_esc(title), cover_title))
    story.append(Paragraph("英译中" + ("对照" if mode == "bilingual" else "") + "译本", cover_sub))
    story.append(Spacer(1, 8 * mm))
    info = [
        f"原文件：{_esc(os.path.basename(meta.get('source', '')))}",
        f"原文页数：{meta.get('n_pages', '?')} 页",
        f"翻译引擎：{_esc(meta.get('engine', ''))}",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if meta.get("empty_pages"):
        ep = meta["empty_pages"]
        shown = ", ".join(str(p) for p in ep[:12]) + ("…" if len(ep) > 12 else "")
        info.append(f"无文字层（疑似扫描图片）的页：{shown}")
    for line in info:
        story.append(Paragraph(line, cover_sub))
    story.append(Paragraph("机器翻译仅供快速理解，关键结论请以原文为准。", cover_sub))
    story.append(PageBreak())

    last_page = None
    for it in items:
        if it.get("page") and it["page"] != last_page:
            last_page = it["page"]
            story.append(Paragraph(f"—— 原文 第 {last_page} 页 ——", marker))
        kind = it.get("kind", "para")
        zh_style = zh_head if kind == "heading" else (zh_cap if kind == "caption" else zh_body)
        en_style = en_head if kind == "heading" else (en_cap if kind == "caption" else en_body)
        flow = [Paragraph(_esc(it["zh"]) or "&nbsp;", zh_style)]
        if mode == "bilingual" and it.get("en"):
            style = en_style
            if not _latin1_safe(it["en"]):
                # 含有希腊字母、音标之类 Times 覆盖不到的字符，改用中文字体渲染
                style = ParagraphStyle("en_fb", parent=en_style, fontName=cjk)
            flow.append(Paragraph(_esc(it["en"]), style))
        if kind == "heading" or len(it.get("en", "")) < 400:
            story.append(KeepTogether(flow))
        else:
            story.extend(flow)
        story.append(Spacer(1, 3))

    _Doc(out_path, header_text=title, cjk_font=cjk).build(story)
    return out_path
