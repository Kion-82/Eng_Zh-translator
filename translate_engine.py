# -*- coding: utf-8 -*-
"""本地离线翻译引擎：Helsinki-NLP/opus-mt-en-zh（Marian NMT）。

特点：
  * 完全本地推理，不联网（首次需下载约 300MB 模型）；
  * 逐句翻译，不会像大模型那样"自由发挥"或漏译整段；
  * 带 SQLite 缓存，重复句子（尤其是重复的图注、脚注）直接命中。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading

def _default_model() -> str:
    """优先用文件夹里自带的 model/（手动下载模型时用），否则走 HuggingFace 仓库名。"""
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
    if os.path.isfile(os.path.join(local, "config.json")):
        return local
    return "Helsinki-NLP/opus-mt-en-zh"


MODEL_NAME = os.environ.get("MT_MODEL") or _default_model()
_CACHE_LOCK = threading.Lock()


class TranslationCache:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS mt (k TEXT PRIMARY KEY, src TEXT, dst TEXT)"
        )
        self.conn.commit()

    @staticmethod
    def _key(text: str, model: str, beams: int) -> str:
        # key 里带上 beam 数：「快速」(beam=1) 的结果不能被「标准」(beam=4) 复用。
        # 模型只取文件夹名，项目目录搬家后缓存照样能用。
        model = re.split(r"[\\/]", model.rstrip("/\\"))[-1] or model
        return hashlib.sha1(f"{model}\x00b{beams}\x00{text}".encode("utf-8")).hexdigest()

    def get(self, text: str, model: str, beams: int):
        with _CACHE_LOCK:
            row = self.conn.execute(
                "SELECT dst FROM mt WHERE k=?", (self._key(text, model, beams),)
            ).fetchone()
        return row[0] if row else None

    def put_many(self, pairs: list[tuple[str, str]], model: str, beams: int):
        with _CACHE_LOCK:
            self.conn.executemany(
                "INSERT OR REPLACE INTO mt (k, src, dst) VALUES (?,?,?)",
                [(self._key(s, model, beams), s, d) for s, d in pairs],
            )
            self.conn.commit()


class Translator:
    """懒加载的 Marian 翻译器。线程安全（同一时刻只有一个批次在跑）。"""

    def __init__(self, cache_path: str | None = None, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self.cache = TranslationCache(cache_path) if cache_path else None
        self._model = None
        self._tok = None
        self._prefix = ""
        self._lock = threading.Lock()
        self.device = "cpu"

    # ---------------- 模型加载 ----------------
    def ensure_loaded(self, log=None):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            if log:
                if os.path.isdir(self.model_name):
                    log(f"正在加载本地模型（{os.path.basename(self.model_name)}/ 文件夹，约 300MB，"
                        "首次加载十几秒）…")
                else:
                    log("正在加载翻译模型（首次运行需要下载约 300MB，请耐心等待）…")
            import torch  # noqa: F401
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            tok = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            model.eval()
            # opus-mt-en-zh 支持多种中文变体；显式要求简体普通话，避免输出繁体/粤语
            codes = list(getattr(tok, "supported_language_codes", []) or [])
            self._prefix = ">>cmn_Hans<< " if ">>cmn_Hans<<" in codes else ""
            try:
                torch.set_num_threads(max(1, (os.cpu_count() or 4)))
            except Exception:
                pass
            self._tok, self._model = tok, model
            if log:
                log("模型加载完成。")

    # ---------------- 翻译 ----------------
    def translate(self, sentences: list[str], beams: int = 4, batch_size: int = 12,
                  progress=None, should_stop=None, log=None) -> list[str]:
        """按顺序返回译文；命中缓存的句子不会重复计算。"""
        results: list[str | None] = [None] * len(sentences)
        todo: list[int] = []

        for i, s in enumerate(sentences):
            hit = self.cache.get(s, self.model_name, beams) if self.cache else None
            if hit is not None:
                results[i] = hit
            else:
                todo.append(i)

        done = len(sentences) - len(todo)
        if progress:
            progress(done, len(sentences))
        if not todo:
            return [r or "" for r in results]

        self.ensure_loaded(log=log)
        import torch

        # 按长度排序分批，padding 更少、速度更快
        order = sorted(todo, key=lambda i: len(sentences[i]))
        for start in range(0, len(order), batch_size):
            if should_stop and should_stop():
                break
            idxs = order[start:start + batch_size]
            batch = [sentences[i] for i in idxs]
            outs = self._run_batch(batch, beams=beams)
            for i, out in zip(idxs, outs):
                results[i] = out
            if self.cache:
                self.cache.put_many(list(zip(batch, outs)), self.model_name, beams)
            done += len(idxs)
            if progress:
                progress(done, len(sentences))
        return [r if r is not None else "" for r in results]

    def _run_batch(self, batch: list[str], beams: int = 4) -> list[str]:
        import torch

        with self._lock:
            enc = self._tok([self._prefix + s for s in batch], return_tensors="pt",
                            padding=True, truncation=True, max_length=512)
            with torch.no_grad():
                gen = self._model.generate(
                    **enc,
                    num_beams=beams,
                    max_length=512,
                    no_repeat_ngram_size=8,
                    length_penalty=1.0,
                    early_stopping=True,
                )
            outs = self._tok.batch_decode(gen, skip_special_tokens=True)

        cleaned = []
        for src, out in zip(batch, outs):
            out = _postprocess(out)
            if _looks_degenerate(out, src):
                # 退化（复读机）时用贪心解码重试一次
                with self._lock:
                    enc1 = self._tok([self._prefix + src], return_tensors="pt",
                                     truncation=True, max_length=512)
                    with torch.no_grad():
                        g1 = self._model.generate(**enc1, num_beams=1, max_length=512,
                                                  no_repeat_ngram_size=4)
                    retry = _postprocess(self._tok.batch_decode(g1, skip_special_tokens=True)[0])
                out = retry if not _looks_degenerate(retry, src) else (retry or out)
            cleaned.append(out.strip())
        return cleaned


# ------------------------------------------------------------------
def _postprocess(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+([，。；：、！？）】」》])", r"\1", text)
    text = re.sub(r"([（【「《])\s+", r"\1", text)
    # 中文字符之间多余的空格
    text = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)
    return text


def _looks_degenerate(text: str, src: str | None = None) -> bool:
    """检测复读机输出：重复的字、重复的句子，或者凭空冒出一大串数字。"""
    t = text.strip()
    if not t:
        return True
    if src is not None:
        out_digits = sum(1 for c in t if c.isdigit())
        src_digits = sum(1 for c in src if c.isdigit())
        # 原文没几个数字，译文却吐出一长串 —— 典型的引注角标引发的退化
        if out_digits > 8 and out_digits > src_digits * 2 + 6:
            return True
    if re.search(r"(.{1,6}?)\1{5,}", t):
        return True
    if len(t) > 40:
        chunks = re.split(r"[，。；！？]", t)
        chunks = [c for c in chunks if len(c) > 3]
        if chunks and len(set(chunks)) <= max(1, len(chunks) // 4):
            return True
    return False


class EchoTranslator(Translator):
    """离线自测用：不加载模型，直接回显（仅开发调试）。"""

    def translate(self, sentences, beams=4, batch_size=12, progress=None,
                  should_stop=None, log=None):
        if progress:
            progress(len(sentences), len(sentences))
        return ["【测试译文】" + s for s in sentences]
