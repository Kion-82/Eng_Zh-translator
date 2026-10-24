# -*- coding: utf-8 -*-
"""版面还原的回归测试（pdfminer 后端）。"""

from __future__ import annotations

import pytest

import pdf_extract

pytestmark = pytest.mark.skipif(not pdf_extract.HAS_PDFMINER, reason="需要 pdfminer.six")


def texts(doc):
    return [b.text for b in doc.blocks]


def full(doc):
    return "\n".join(texts(doc))


def find(doc, needle):
    hits = [b for b in doc.blocks if needle in b.text]
    assert hits, f"没找到 {needle!r}"
    return hits[0]


# ---------------------------------------------------------------- 页眉页脚 / 标题

def test_allcaps_headings_kept(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    for h in ("1. INTRODUCTION", "2. METHODS", "4. DISCUSSION", "REFERENCES"):
        assert find(doc, h).kind == "heading"


def test_running_head_and_page_numbers_removed(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    assert "JOURNAL OF APPLIED ECOLOGY" not in full(doc)
    assert not any(t.strip() in {"1", "2", "3"} for t in texts(doc))


def test_mixed_case_running_head_removed_by_repetition(pdfs):
    doc = pdf_extract.extract(pdfs["crosspage"])
    assert "Pu et al." not in full(doc)


def test_repetition_does_not_eat_identical_body_text(pdfs):
    doc = pdf_extract.extract(pdfs["twins"])
    assert "Pu et al." not in full(doc)
    starts = [b.page for b in doc.blocks if b.text.startswith("Wetland ecosystems store")]
    assert starts == [1, 2, 3]


def test_book_running_head_removed(pdfs):
    doc = pdf_extract.extract(pdfs["book"], page_range=(1, 5))
    assert "THE ECOLOGY OF WETLANDS" not in full(doc)


def test_short_last_line_kept(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    assert "the fit was good for all of it." in full(doc)


# ---------------------------------------------------------------- 行内清洗

def test_superscript_citations_removed(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    t = full(doc)
    assert "2,7" not in t
    assert "share of terrestrial carbon" in t


def test_hyphenation_rejoined(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    assert "deep accumulation, and" in full(doc)


# ---------------------------------------------------------------- 阅读顺序

def test_two_column_order(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    t = texts(doc)
    assert t.index(find(doc, "1. INTRODUCTION").text) < t.index(find(doc, "2. METHODS").text)


def test_full_width_figure_order(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    p2 = [b for b in doc.blocks if b.page == 2]
    cap = [i for i, b in enumerate(p2) if b.text.startswith("Figure 2.")]
    below = [i for i, b in enumerate(p2) if b.text.startswith("Below the figure.")]
    above = [i for i, b in enumerate(p2) if b.text.startswith(("Wetland", "However"))]
    assert cap and len(below) == 2 and len(above) == 2
    assert max(above) < cap[0] < min(below)
    assert find(doc, "Figure 2.").kind == "caption"


# ---------------------------------------------------------------- 页码与小节

def test_cross_page_merge_records_page_span(pdfs):
    doc = pdf_extract.extract(pdfs["crosspage"])
    blk = find(doc, "The decline was steepest")
    assert (blk.page, blk.page_end) == (1, 2)
    assert "steepest at sites where the water table fell below thirty centimetres for most" in blk.text
    assert find(doc, "Wetland ecosystems").page_end == 1


def test_sections_tagged(pdfs):
    doc = pdf_extract.extract(pdfs["paper"])
    assert find(doc, "deep accumulation").section == "1. INTRODUCTION"
    assert find(doc, "Smith J.").section == "References"
    assert find(doc, "Site coordinates").section == "Appendix A"


def test_drop_refs_allcaps_and_resume_at_appendix(pdfs):
    doc = pdf_extract.extract(pdfs["paper"], drop_refs=True)
    t = full(doc)
    assert "REFERENCES" not in t and "Smith J." not in t and "Jones K." not in t
    assert "Site coordinates" in t          # 附录恢复
    assert "4. DISCUSSION" in t


def test_drop_refs_plain_literature_cited(pdfs):
    doc = pdf_extract.extract(pdfs["crosspage"], drop_refs=True)
    assert "Literature Cited" not in full(doc) and "Smith J." not in full(doc)
    kept = pdf_extract.extract(pdfs["crosspage"])
    assert find(kept, "Smith J.").section == "References"


def test_drop_fragments(pdfs):
    assert "Label A" in full(pdf_extract.extract(pdfs["paper"]))
    doc = pdf_extract.extract(pdfs["paper"], drop_fragments=True)
    assert "Label A" not in full(doc) and "Label B" not in full(doc)
    assert "Figure 2." in full(doc) and "2. METHODS" in full(doc)


# ---------------------------------------------------------------- 页码范围

def test_page_range_only_parses_requested_pages(pdfs, monkeypatch):
    # pdfminer 每产出一页都已经做完了版面分析（慢的部分），所以数它产出了几页
    backend = pdf_extract._pdfminer_backend
    yielded = []
    orig = backend.iter_page_layouts_boxes

    def spy(*a, **kw):
        for layout in orig(*a, **kw):
            yielded.append(layout)
            yield layout

    monkeypatch.setattr(backend, "iter_page_layouts_boxes", spy)
    doc = pdf_extract.extract(pdfs["book"], page_range=(3, 5))
    assert len(yielded) == 3
    assert doc.n_pages == 30
    assert {b.page for b in doc.blocks} == {3, 4, 5}
    assert "This is page 4." in full(doc)


def test_page_range_open_ended(pdfs):
    doc = pdf_extract.extract(pdfs["book"], page_range=(29, None))
    assert {b.page for b in doc.blocks} == {29, 30}
    assert doc.empty_pages == []
