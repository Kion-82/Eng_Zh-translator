# -*- coding: utf-8 -*-
"""英文分句：把段落切成一句一句，交给翻译模型逐句处理。

翻译模型（opus-mt）是按句子训练的，喂整段容易漏译；逐句翻译
既稳定又便于把译文和原文对齐。
"""

from __future__ import annotations

import re

# 句号不代表句子结束的常见缩写
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "rev", "hon", "pres", "gen", "col", "capt",
    "fig", "figs", "eq", "eqs", "ref", "refs", "tab", "tabs", "ch", "chap", "sec", "vol", "no",
    "nos", "pp", "p", "ed", "eds", "trans", "repr", "cf", "vs", "viz", "al", "etc", "ibid", "op",
    "cit", "approx", "est", "min", "max", "avg", "dept", "univ", "inc", "ltd", "co", "corp",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun", "e.g", "i.e", "u.s", "u.k", "e.g.", "i.e.",
}

_SPLIT_RE = re.compile(r"(?<=[.!?。！？])[\"'”’\)\]]*\s+")
_INITIAL_RE = re.compile(r"\b[A-Z]\.$")


def _keep_together(left: str) -> bool:
    """判断 left 结尾的句点是否其实不是句子结束。"""
    tail = left.rstrip()
    if not tail:
        return True
    if not tail.endswith("."):
        return False
    word = re.split(r"[\s(\[]", tail)[-1].rstrip(".").lower()
    if word in _ABBREV:
        return True
    if _INITIAL_RE.search(tail):  # 人名缩写 J. R. R. Tolkien
        return True
    if re.search(r"\d\.$", tail) and len(tail) < 6:  # 编号 "1."
        return True
    if re.search(r"\b[A-Za-z]\.[A-Za-z]\.$", tail):  # U.S. / e.g.
        return True
    return False


def split_sentences(paragraph: str, max_chars: int = 320) -> list[str]:
    text = re.sub(r"\s+", " ", paragraph).strip()
    if not text:
        return []

    parts = _SPLIT_RE.split(text)
    sents: list[str] = []
    for part in parts:
        if sents and _keep_together(sents[-1]):
            sents[-1] = sents[-1] + " " + part
        else:
            sents.append(part)

    out: list[str] = []
    for s in sents:
        s = s.strip()
        if not s:
            continue
        out.extend(_split_long(s, max_chars))
    return out


def _split_long(s: str, max_chars: int) -> list[str]:
    """超长句子再按分号 / 冒号 / 连接词切开，避免模型截断。"""
    if len(s) <= max_chars:
        return [s]
    pieces = re.split(r"(?<=[;:；])\s+", s)
    if max(len(p) for p in pieces) > max_chars:
        merged: list[str] = []
        for p in pieces:
            merged.extend(re.split(r"(?<=,)\s+(?=(?:and|but|which|while|whereas|although|because)\b)", p))
        pieces = merged
    out: list[str] = []
    buf = ""
    for p in pieces:
        if not buf:
            buf = p
        elif len(buf) + len(p) + 1 <= max_chars:
            buf += " " + p
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    # 仍然超长（比如一整段没有标点）就硬切
    final: list[str] = []
    for p in out:
        while len(p) > max_chars * 1.6:
            cut = p.rfind(" ", 0, int(max_chars * 1.6))
            cut = cut if cut > 0 else int(max_chars * 1.6)
            final.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            final.append(p)
    return final


_NO_TRANSLATE = re.compile(
    r"^(?:[\W\d_]+|(?:https?://|www\.|doi:)\S*|[A-Za-z]{1,2})$"
)


def needs_translation(s: str) -> bool:
    """纯数字、公式、网址、单个字母之类不送去翻译。"""
    t = s.strip()
    if len(t) < 2 or _NO_TRANSLATE.match(t):
        return False
    letters = sum(1 for c in t if c.isalpha())
    return letters >= max(2, len(t) * 0.3)
