# -*- coding: utf-8 -*-
"""把 PDF 还原成"按阅读顺序排列的段落"。

这是整个项目最难的一环。学术文献版面五花八门：单栏的书、双栏的期刊、
三栏的评论、页面中间横插一张带文字标签的通栏图。要处理的坑：

  1. 分栏 —— 不能把左右栏逐行交替读成一段；
  2. 页眉页脚页码 —— 每页重复的噪音要丢掉；
  3. 断行与连字符 —— "un-naturalness" 要还原成 "unnaturalness"；
  4. 参考文献角标 —— "recognition1-4" 里的上标数字必须剔除，否则翻译
     模型会被带偏，吐出一长串数字乱码；
  5. 跨页跨栏的段落 —— 上一段没写完的要接回去；
  6. 连字与生僻字形 —— fi/fl 连字、(cid:123) 之类要规范化。

两个解析后端：
  * pdfminer.six（主力）—— 自带版面分析，能把页面聚成"文本框"，这种框
    天然不跨栏；再用矩形级 XY-cut 排阅读顺序。每个字符有精确字号和坐标，
    角标才能靠"字号更小 + 基线抬高"识别出来。
  * pypdf（兜底）—— 纯 Python 零原生依赖，老系统上 pdfminer 装不上时用。
    没有版面分析，只能按字符坐标做 XY-cut，角标只能用正则去，精度稍逊。

两个后端只负责把 PDF 变成带坐标和字号的"行"，之后的分栏、合段、标题
识别、清洗逻辑完全共用。
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

try:
    import pypdf
    HAS_PYPDF = True
except Exception:
    pypdf = None
    HAS_PYPDF = False

try:
    import pdf_extract_pdfminer as _pdfminer_backend
    HAS_PDFMINER = True
except Exception:
    _pdfminer_backend = None
    HAS_PDFMINER = False


@dataclass
class Block:
    """一个可翻译的文本块（段落 / 标题 / 图表说明）。"""

    text: str
    page: int  # 原文页码，从 1 开始
    kind: str = "para"  # para | heading | caption
    size: float = 10.0

    def to_dict(self) -> dict:
        return {"text": self.text, "page": self.page, "kind": self.kind, "size": self.size}


@dataclass
class Document:
    blocks: list[Block] = field(default_factory=list)
    n_pages: int = 0
    empty_pages: list[int] = field(default_factory=list)  # 没有文字层的页（扫描件）
    title: str = ""
    backend: str = ""


# --------------------------------------------------------------------------
# 行级工具
# --------------------------------------------------------------------------

_PAGENO_RE = re.compile(r"^[\s\-–—|]*(?:page\s*)?[ivxlcdm\d]{1,6}[\s\-–—|]*$", re.I)


def _looks_like_running_head(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if _PAGENO_RE.match(t):
        return True
    if len(t) <= 3:
        return True
    # 全大写且没有句末标点的短行，通常是书眉
    letters = [c for c in t if c.isalpha()]
    if letters and len(t) < 70 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.9:
        return True
    if re.match(r"^(downloaded from|this content downloaded|©|copyright|doi:|https?://|arxiv:)", t, re.I):
        return True
    return False


def _find_gutter(chunks: list[dict], x0: float, x1: float,
                 min_gutter: float) -> float | None:
    """在 [x0, x1) 里找一条竖向的空白带（栏间缝）。找到返回它的中心 x。"""
    if len(chunks) < 40:
        return None
    lo = min(c["x0"] for c in chunks)
    hi = max(c["x1"] for c in chunks)
    span = hi - lo
    if span <= min_gutter * 3:
        return None

    nbins = 300
    bw = span / nbins
    covered = [False] * nbins
    for c in chunks:
        a = max(0, int((c["x0"] - lo) / bw))
        b = min(nbins - 1, int((c["x1"] - lo) / bw))
        for i in range(a, b + 1):
            covered[i] = True

    best = None
    i = 0
    while i < nbins:
        if not covered[i]:
            j = i
            while j < nbins and not covered[j]:
                j += 1
            width = (j - i) * bw
            centre = lo + (i + j) / 2 * bw
            rel = (centre - lo) / span
            if width >= min_gutter and 0.15 < rel < 0.85:
                left = sum(1 for c in chunks if c["x1"] <= centre)
                right = sum(1 for c in chunks if c["x0"] >= centre)
                total = len(chunks)
                if left / total >= 0.2 and right / total >= 0.2:
                    # 多条缝时取最宽的那条
                    if best is None or width > best[1]:
                        best = (centre, width)
            i = j
        else:
            i += 1
    return best[0] if best else None


def _find_hband(chunks: list[dict], top: float, bottom: float) -> float | None:
    """找一条横向的空白带（通栏图片、公式、标题上下的留白），返回切分的 y。

    只认明显大于正常行距的间隔，避免把普通段落间距也当成结构分界。
    """
    if len(chunks) < 40:
        return None
    rows = sorted(chunks, key=lambda c: c["top"])
    heights = [c["bottom"] - c["top"] for c in rows]
    line_h = statistics.median(heights) if heights else 10.0

    # 把字符按 y 合并成占用区间
    spans: list[list[float]] = []
    for c in rows:
        if spans and c["top"] <= spans[-1][1] + 0.5:
            spans[-1][1] = max(spans[-1][1], c["bottom"])
        else:
            spans.append([c["top"], c["bottom"]])

    best = None
    for a, b in zip(spans, spans[1:]):
        gap = b[0] - a[1]
        if gap < line_h * 1.8:
            continue
        centre = (a[1] + b[0]) / 2
        rel = (centre - top) / max(1.0, bottom - top)
        if not (0.05 < rel < 0.95):
            continue
        above = sum(1 for c in chunks if c["bottom"] <= centre)
        below = len(chunks) - above
        if above < 20 or below < 20:
            continue
        if best is None or gap > best[1]:
            best = (centre, gap)
    return best[0] if best else None


def _page_regions(chunks: list[dict], page_width: float,
                  top_cut: float, bot_cut: float) -> list[tuple[float, float, float, float]]:
    """把一页切成按阅读顺序排列的矩形区域 (x0, top, x1, bottom)。

    用递归的 XY-cut：先找竖向空白带切栏，切不动再找横向空白带切带，
    然后对每块继续递归。这样单栏书、双栏论文、三栏杂志，以及页面中间
    横插一张通栏图/公式的版面，都能正确还原阅读顺序——后者正是只看
    "整页有没有一条通天缝"的做法会栽跟头的地方。
    """
    chunks = [c for c in chunks if top_cut <= c["top"] <= bot_cut and c["x1"] > c["x0"]]
    if len(chunks) < 60:
        return [(0, top_cut, page_width, bot_cut)]

    min_gutter = max(page_width * 0.012, 6.0)
    out: list[tuple[float, float, float, float]] = []

    def walk(sub: list[dict], x0: float, top: float, x1: float, bottom: float, depth: int):
        if not sub:
            return
        if depth >= 6 or len(sub) < 60:
            out.append((x0, top, x1, bottom))
            return

        cut = _find_gutter(sub, x0, x1, min_gutter)
        if cut is not None:
            left = [c for c in sub if (c["x0"] + c["x1"]) / 2 < cut]
            right = [c for c in sub if (c["x0"] + c["x1"]) / 2 >= cut]
            walk(left, x0, top, cut, bottom, depth + 1)
            walk(right, cut, top, x1, bottom, depth + 1)
            return

        ycut = _find_hband(sub, top, bottom)
        if ycut is not None:
            upper = [c for c in sub if (c["top"] + c["bottom"]) / 2 < ycut]
            lower = [c for c in sub if (c["top"] + c["bottom"]) / 2 >= ycut]
            walk(upper, x0, top, x1, ycut, depth + 1)
            walk(lower, x0, ycut, x1, bottom, depth + 1)
            return

        out.append((x0, top, x1, bottom))

    walk(chunks, 0.0, top_cut, page_width, bot_cut, 0)
    return out or [(0, top_cut, page_width, bot_cut)]


def _rect_gap(boxes: list[dict], axis: str, min_gap: float) -> float | None:
    """把一组矩形投影到某个轴上，返回最大的空隙的中点（没有就 None）。"""
    lo_key, hi_key = ("x0", "x1") if axis == "x" else ("top", "bottom")
    spans = sorted(((b[lo_key], b[hi_key]) for b in boxes), key=lambda t: t[0])
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    best = None
    for a, b in zip(merged, merged[1:]):
        gap = b[0] - a[1]
        if gap >= min_gap and (best is None or gap > best[1]):
            best = ((a[1] + b[0]) / 2, gap)
    return best[0] if best else None


def _order_boxes(boxes: list[dict], depth: int = 0) -> list[list[dict]]:
    """用矩形级的 XY-cut 决定阅读顺序：先竖切分栏，切不动再横切分带。

    以 pdfminer 的文本框为原子单位，比按字符坐标猜稳得多：文本框本身
    就是版面分析的结果，天然不跨栏，所以栏间空隙是干净的。
    """
    if len(boxes) <= 1 or depth >= 8:
        return [sorted(boxes, key=lambda b: (b["top"], b["x0"]))]

    cut = _rect_gap(boxes, "x", 8.0)
    if cut is not None:
        left = [b for b in boxes if b["x1"] <= cut]
        right = [b for b in boxes if b["x0"] >= cut]
        if left and right and len(left) + len(right) == len(boxes):
            return _order_boxes(left, depth + 1) + _order_boxes(right, depth + 1)

    cut = _rect_gap(boxes, "y", 4.0)
    if cut is not None:
        upper = [b for b in boxes if b["bottom"] <= cut]
        lower = [b for b in boxes if b["top"] >= cut]
        if upper and lower and len(upper) + len(lower) == len(boxes):
            return _order_boxes(upper, depth + 1) + _order_boxes(lower, depth + 1)

    return [sorted(boxes, key=lambda b: (b["top"], b["x0"]))]


def _lines_in_region(lines: list[dict], bbox: tuple[float, float, float, float]) -> list[dict]:
    """按行的中心点落在哪个矩形里来分区（pypdf 后端用，不需要裁剪页面）。"""
    x0, top, x1, bottom = bbox
    out = []
    for ln in lines:
        cx = (ln["x0"] + ln["x1"]) / 2
        cy = (ln["top"] + ln["bottom"]) / 2
        if x0 <= cx < x1 and top <= cy < bottom:
            out.append(ln)
    return out


_END_PUNCT = tuple(".!?\"')”’]:;")
# 句子结尾：句末标点后面还可能跟着脚注上标数字（"...mouths.42"）
_ENDS_SENTENCE = re.compile(r"""[.!?…"'”’)\]:;]\s*\d{0,3}$""")
# 注意：以前这里把裸字母 o 当成项目符号，结果 "of ..."、"on ..." 开头的
# 续行全被误判成新段落，段落被切得稀碎。现在一律要求符号后面跟空白。
_BULLET_RE = re.compile(
    r"^\s*(?:[•·▪◦∙‣]\s*|o\s+|[-–—]\s+|\(?\d{1,2}[.)]\s+|[a-z]\)\s+|[IVXLC]{1,5}[.)]\s+)")


_NOTE_MARK_RE = re.compile(r"^[\d\s.,·*†‡]{1,6}$")


def _group_lines(lines: list[dict], body_size: float) -> list[tuple[str, str, float]]:
    """把行合并成 (text, kind, size)。"""
    # 脚注/尾注的上标数字会单独成"行"，字号又比正文小，
    # 留着会把一个段落从中间劈开，所以先剔掉
    lines = [ln for ln in lines
             if not (ln["_size"] < body_size - 0.5 and _NOTE_MARK_RE.match(ln["text"]))]
    if not lines:
        return []

    gaps = []
    for a, b in zip(lines, lines[1:]):
        g = b["top"] - a["bottom"]
        if -5 < g < 40:
            gaps.append(g)
    med_gap = statistics.median(gaps) if gaps else 2.0

    right_edge = max(ln["x1"] for ln in lines)
    left_edge = min(ln["x0"] for ln in lines)

    paras: list[list[dict]] = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        newpara = False
        gap = cur["top"] - prev["bottom"]
        if gap > med_gap + max(3.0, med_gap * 1.6):
            newpara = True
        if abs(cur["_size"] - prev["_size"]) > 0.6:
            newpara = True
        if cur["_bold"] != prev["_bold"] and gap > med_gap * 0.6:
            newpara = True
        # 上一行提前结束（右侧留白）且以句末标点结尾
        if prev["text"].endswith(_END_PUNCT) and prev["x1"] < right_edge - (right_edge - left_edge) * 0.12:
            newpara = True
        if _BULLET_RE.match(cur["text"]):
            newpara = True
        # 首行缩进
        if cur["x0"] > left_edge + 8 and gap >= med_gap * 0.8:
            newpara = True
        if newpara:
            paras.append([cur])
        else:
            paras[-1].append(cur)

    out = []
    for p in paras:
        text = _join_lines([ln["text"] for ln in p])
        if not text:
            continue
        size = round(statistics.median([ln["_size"] for ln in p]), 1)
        bold = sum(1 for ln in p if ln["_bold"]) > len(p) / 2
        kind = "para"
        words = len(text.split())
        if (size > body_size + 0.8 or (bold and size >= body_size)) and words <= 30 and not text.endswith("."):
            kind = "heading"
        elif re.match(r"^(fig(ure)?|table|tab|chart|scheme|eq(uation)?|plate)\s*\.?\s*\d+\s*[.:：)]", text, re.I):
            kind = "caption"
        elif size < body_size - 0.8 and words < 60:
            kind = "caption"
        out.append((text, kind, size))
    return out


_CITATION_RE = re.compile(r"(?<=[a-z])\d{1,3}(?:[,–—-]\d{1,3})*(?=[\s.,;:)\]]|$)")


def _strip_citations(text: str) -> str:
    """pypdf 没有字号信息，只能用正则去掉粘在词尾的引注数字。

    只在"小写字母 + 数字 + 后面是空白或标点"时才动手，像 CO2、H2O、
    COVID19、1990s 这些都不会被误伤。
    """
    return _CITATION_RE.sub("", text)


def _normalize(text: str) -> str:
    """规范化排版字符：连字 ﬁ/ﬂ 拆开、全角转半角、奇怪空格统一。

    书籍 PDF 里 fi、fl 常常是单个连字字符（U+FB01/FB02），留着有两个害处：
    英文原文用 Times 字体渲染时显示成黑方块，翻译模型也没见过这种字符。
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u2028", " ").replace("\ufeff", "")
    # pdfminer 遇到没法映射的字形会输出 (cid:123)，直接删掉，别送去翻译
    text = re.sub(r"\(cid:\d+\)", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _join_lines(lines: list[str]) -> str:
    """合并断行：处理行尾连字符，其余用空格连接。"""
    buf = ""
    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if not buf:
            buf = ln
            continue
        if re.search(r"[A-Za-z]([-‐‑–])$", buf):
            # 行尾连字符：若下一行以小写字母开头，认为是被拆开的单词
            if re.match(r"^[a-z]", ln):
                buf = buf[:-1] + ln
            else:
                buf = buf + ln
        else:
            buf = buf + " " + ln
    return re.sub(r"\s{2,}", " ", buf).strip()


_JUNK_RE = re.compile(r"^[\s\d\W_]+$")


def _clean_title(raw: str) -> str:
    """PDF 元数据里的标题经常是垃圾（(anonymous)、Microsoft Word - xx.doc）。"""
    t = (raw or "").strip()
    if not t or len(t) < 4:
        return ""
    if re.match(r"^\(?(anonymous|untitled|unknown|无标题)\)?$", t, re.I):
        return ""
    t = re.sub(r"^Microsoft Word\s*-\s*", "", t, flags=re.I)
    t = re.sub(r"\.(docx?|pdf|tex|indd|qxd|qxp)$", "", t, flags=re.I)
    t = t.strip()
    # 排版软件留下的内部文件名，例如 "2.5 comm mx"、"jan04 final"
    if len(t) < 15 or not t[:1].isalpha():
        return ""
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) < 3:
        return ""
    if sum(1 for w in words if re.fullmatch(r"[A-Za-z][A-Za-z\-\u2019\']+", w)) < len(words) * 0.6:
        return ""
    return t


def _pdf_meta_title(path: str) -> str:
    """尽量拿到 PDF 元数据里的标题，拿不到就算了。"""
    try:
        if HAS_PYPDF:
            return str((pypdf.PdfReader(path).metadata or {}).get("/Title") or "")
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfparser import PDFParser
        with open(path, "rb") as fh:
            info = PDFDocument(PDFParser(fh)).info
        if info:
            val = info[0].get("Title")
            if isinstance(val, bytes):
                return val.decode("utf-8", "ignore").strip("\x00")
            return str(val or "")
    except Exception:
        pass
    return ""


def extract(path: str, drop_refs: bool = False, progress=None,
            backend: str = "auto", page_range: tuple | None = None) -> Document:
    """解析 PDF，返回按阅读顺序排列的文本块。

    progress:    可选回调 progress(done_pages, total_pages)
    page_range:  (起始页, 结束页)，都是从 1 开始、含两端；None 表示整本
    """
    def in_range(idx0: int) -> bool:      # idx0 从 0 开始
        if not page_range:
            return True
        a, b = page_range
        return (a is None or idx0 + 1 >= a) and (b is None or idx0 + 1 <= b)

    doc = Document()
    all_sizes: list[float] = []
    per_page_lines: list[list[list[dict]]] = []  # page -> regions -> lines

    def keep(lines):
        return [ln for ln in lines
                if len(ln["text"]) > 70 or not _looks_like_running_head(ln["text"])]

    if backend == "auto":
        backend = "pdfminer" if HAS_PDFMINER else "pypdf"
    if backend == "pdfminer" and not HAS_PDFMINER:
        backend = "pypdf"
    if not (HAS_PDFMINER or HAS_PYPDF):
        raise RuntimeError("没有可用的 PDF 解析库，请先安装 pdfminer.six 或 pypdf")
    doc.backend = backend

    if backend == "pdfminer":
        backend_mod = _pdfminer_backend
        try:
            from pdfminer.pdfpage import PDFPage
            with open(path, "rb") as fh:
                total_pages = sum(1 for _ in PDFPage.get_pages(fh))
        except Exception:
            total_pages = 0
        doc.title = _clean_title(_pdf_meta_title(path))
        for i, layout in enumerate(backend_mod.iter_page_layouts_boxes(path)):
            if not in_range(i):
                per_page_lines.append([])
                continue
            boxes, width, height = backend_mod.page_boxes(layout)
            top_cut = height * 0.055
            bot_cut = height * 0.945
            boxes = [b for b in boxes
                     if b["bottom"] > top_cut and b["top"] < bot_cut]
            page_regions = []
            for group in _order_boxes(boxes):
                lines = [ln for b in group for ln in b["lines"]]
                sub = keep(lines)
                page_regions.append(sub)
                all_sizes.extend([ln["_size"] for ln in sub])
            if not any(page_regions):
                doc.empty_pages.append(i + 1)
            per_page_lines.append(page_regions)
            doc.n_pages = max(total_pages, i + 1)
            if progress:
                progress(i + 1, doc.n_pages)
        doc.n_pages = max(total_pages, len(per_page_lines))

    else:
        import pdf_extract_pypdf as backend_mod

        reader = pypdf.PdfReader(path)
        doc.n_pages = len(reader.pages)
        try:
            doc.title = _clean_title((reader.metadata or {}).get("/Title") or "")
        except Exception:
            doc.title = ""
        for i, page in enumerate(reader.pages):
            if not in_range(i):
                per_page_lines.append([])
                continue
            chunks, width, height = backend_mod.page_chunks(page)
            top_cut = height * 0.055
            bot_cut = height * 0.945
            chunks = [c for c in chunks if top_cut <= c["top"] <= bot_cut]
            page_regions = []
            # 必须先分栏、再把文字块拼成行，否则三栏排版会在同一个 y 上串行
            for bbox in _page_regions(chunks, width, top_cut, bot_cut):
                sub = keep(backend_mod.lines_from_chunks(
                    backend_mod.chunks_in_region(chunks, bbox)))
                page_regions.append(sub)
                all_sizes.extend([ln["_size"] for ln in sub])
            if not any(page_regions):
                doc.empty_pages.append(i + 1)
            per_page_lines.append(page_regions)
            if progress:
                progress(i + 1, doc.n_pages)

    body_size = statistics.median(all_sizes) if all_sizes else 10.0

    stop = False
    for pno, page_regions in enumerate(per_page_lines, start=1):
        for lines in page_regions:
            for text, kind, size in _group_lines(lines, body_size):
                if drop_refs and kind == "heading" and re.match(
                    r"^\s*\d*\.?\s*(references|bibliography|works cited|参考文献)\s*$", text, re.I
                ):
                    stop = True
                if stop:
                    continue
                if _JUNK_RE.match(text) or len(text) < 2:
                    continue
                clean = _normalize(text)
                if backend == "pypdf":
                    clean = _strip_citations(clean)
                doc.blocks.append(Block(text=clean, page=pno, kind=kind, size=size))

    doc.blocks = _merge_continuations(doc.blocks)
    return doc


def _merge_continuations(blocks: list[Block]) -> list[Block]:
    """把跨栏 / 跨页被切断的段落接回去。

    判断依据保守一些：上一块确实没写完（结尾不是句末标点，也不是"句末标点 +
    脚注号"），并且下一块以小写字母开头，才认为是同一段的后半截。否则宁可
    留成两段——错误合并会把整页文字塞进上一页，比多切一刀难受得多。
    """
    out: list[Block] = []
    for blk in blocks:
        if out:
            prev = out[-1]
            same_kind = prev.kind == blk.kind == "para"
            prev_text = prev.text.rstrip()
            prev_open = not _ENDS_SENTENCE.search(prev_text)
            starts_lower = bool(re.match(r"^[a-z,;)]", blk.text))
            hyphen_open = bool(re.search(r"[A-Za-z][-‐‑]$", prev_text))
            if same_kind and abs(prev.size - blk.size) < 0.4 and \
                    ((prev_open and starts_lower) or hyphen_open):
                prev.text = _join_lines([prev.text, blk.text])
                continue
        out.append(blk)
    return out
