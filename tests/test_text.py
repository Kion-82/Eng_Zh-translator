# -*- coding: utf-8 -*-
"""分句、翻译缓存的单元测试（不加载模型）。"""

from __future__ import annotations

import segment
from translate_engine import TranslationCache, Translator, _looks_degenerate


def test_split_keeps_abbreviations():
    s = segment.split_sentences(
        "As shown in Fig. 3, the effect was strong (e.g. in J. R. Smith's data). It faded later.")
    assert len(s) == 2 and s[1] == "It faded later."


def test_split_long_sentence():
    long = "; ".join(["the water table fell below thirty centimetres at site %d" % i
                      for i in range(20)]) + "."
    assert all(len(p) <= 320 * 1.6 for p in segment.split_sentences(long))


def test_needs_translation():
    assert not segment.needs_translation("12.5 ± 3")
    assert not segment.needs_translation("https://doi.org/10.1000/xyz")
    assert segment.needs_translation("Species richness declined.")


def test_degenerate_detection():
    assert _looks_degenerate("1 2 3 4 5 6 7 8 9 10 11 12", "see refs")
    assert _looks_degenerate("的的的的的的的的的")
    assert not _looks_degenerate("物种丰富度急剧下降。", "Species richness declined sharply.")


def test_cache_separates_beam_settings(tmp_path):
    cache = TranslationCache(str(tmp_path / "c.db"))
    cache.put_many([("hello", "快速译文")], "model", beams=1)
    assert cache.get("hello", "model", 1) == "快速译文"
    assert cache.get("hello", "model", 4) is None


def test_translator_uses_cache_per_beam(tmp_path):
    t = Translator(cache_path=str(tmp_path / "c.db"), model_name="model")
    t.cache.put_many([("hello", "标准译文")], t.model_name, beams=4)
    # 命中缓存时不会加载模型
    assert t.translate(["hello"], beams=4) == ["标准译文"]
    assert t._model is None


def test_cache_key_survives_project_move(tmp_path):
    cache = TranslationCache(str(tmp_path / "c.db"))
    cache.put_many([("hello", "译文")], r"C:\Users\a\old\translator\model", beams=4)
    assert cache.get("hello", "/Users/a/new/translator/model/", 4) == "译文"
