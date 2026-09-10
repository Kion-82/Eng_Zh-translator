# -*- coding: utf-8 -*-
"""把「PDF → 段落 → 句子 → 译文 → 新 PDF」串起来。"""

from __future__ import annotations

import os

import pdf_extract
import pdf_render
import segment


def translate_pdf(src_path: str, out_path: str, translator, mode: str = "bilingual",
                  beams: int = 4, drop_refs: bool = False, on_status=None,
                  should_stop=None, display_name: str | None = None,
                  page_range: tuple | None = None) -> dict:
    """on_status(dict) 会被反复调用，用于向界面报告进度。"""

    def status(**kw):
        if on_status:
            on_status(kw)

    status(stage="extract", message="正在解析 PDF 文本…", percent=1)

    def page_progress(done, total):
        status(stage="extract", message=f"正在解析 PDF：第 {done}/{total} 页",
               percent=1 + 9 * done / max(1, total), pages_done=done, pages_total=total)

    doc = pdf_extract.extract(src_path, drop_refs=drop_refs, progress=page_progress,
                              page_range=page_range)

    if not doc.blocks:
        raise RuntimeError(
            "没有从这个 PDF 里提取到任何文字。可能是扫描件（纯图片，需要先做 OCR），"
            "也可能是页码范围填得不对。"
        )

    # 段落 -> 句子
    sentences: list[str] = []
    plan: list[tuple[int, list[int]]] = []  # (block_index, sentence indices)
    for bi, blk in enumerate(doc.blocks):
        idxs = []
        for s in segment.split_sentences(blk.text):
            idxs.append(len(sentences))
            sentences.append(s)
        plan.append((bi, idxs))

    to_translate = [s if segment.needs_translation(s) else "" for s in sentences]
    real_idx = [i for i, s in enumerate(to_translate) if s]
    status(stage="translate", message="准备翻译…", percent=10,
           sentences_total=len(real_idx), sentences_done=0)

    def tr_progress(done, total):
        status(stage="translate",
               message=f"正在翻译：{done}/{total} 句",
               percent=10 + 82 * done / max(1, total),
               sentences_done=done, sentences_total=total)

    translated = translator.translate(
        [sentences[i] for i in real_idx], beams=beams,
        progress=tr_progress, should_stop=should_stop,
        log=lambda m: status(stage="translate", message=m),
    )
    zh_map = dict(zip(real_idx, translated))

    if should_stop and should_stop():
        raise RuntimeError("已取消")

    status(stage="render", message="正在生成译文 PDF…", percent=93)
    items = []
    for bi, idxs in plan:
        blk = doc.blocks[bi]
        zh_parts = []
        for i in idxs:
            zh = zh_map.get(i)
            zh_parts.append(zh if zh else sentences[i])
        zh_text = "".join(p.strip() for p in zh_parts) if zh_parts else ""
        items.append({"en": blk.text, "zh": zh_text or blk.text, "kind": blk.kind, "page": blk.page})

    shown = display_name or os.path.basename(src_path)
    meta = {
        "source": shown,
        "title": doc.title or os.path.splitext(shown)[0],
        "n_pages": doc.n_pages,
        "empty_pages": doc.empty_pages,
        "engine": getattr(translator, "model_name", "opus-mt-en-zh") + "（本地离线）",
    }
    pdf_render.build_pdf(out_path, items, meta, mode=mode)
    status(stage="done", message="完成", percent=100)
    return {
        "out_path": out_path,
        "n_pages": doc.n_pages,
        "n_blocks": len(items),
        "n_sentences": len(real_idx),
        "empty_pages": doc.empty_pages,
    }
