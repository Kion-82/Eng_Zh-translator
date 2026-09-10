# -*- coding: utf-8 -*-
"""自检：逐项确认依赖、字体、模型是否就位，并针对常见故障给出对策。

出问题时先跑这个，它会把"哪一步坏了、为什么、怎么修"一次说清楚。
"""

from __future__ import annotations

import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

FAILURES: list[tuple[str, str]] = []

# 已知故障的对策：关键词 -> 建议
HINTS = [
    ("WinError 1114", "Anaconda 的 libiomp5md.dll 和 torch 自带的撞车。用 torch<2.3 配 numpy<2，"
                      "或在启动前设 KMP_DUPLICATE_LIB_OK=TRUE（启动脚本里已经设了）。"),
    ("access violation", "某个 C 扩展加载即崩，最常见的是 sentencepiece。试："
                         "pip install --force-reinstall --no-cache-dir sentencepiece"),
    ("CVE-2025-32434", "新版 transformers 不让 torch<2.6 读 .bin 权重。把模型换成 safetensors 格式，"
                       "或把 transformers 降到 <4.42。"),
    ("No module named", "依赖没装全，运行安装脚本：install.bat（Windows）/ bash install.command（macOS）。"),
    ("couldn't connect", "下不到模型。运行 python download_model.py，它会测连通性并提供直连下载。"),
    ("LocalEntryNotFound", "模型没下下来，或者环境变量 HF_HUB_OFFLINE 被设成了 1。"
                           "运行 python download_model.py。"),
]


def check(name, fn):
    try:
        detail = fn()
        print(f"  [OK]   {name}{('：' + str(detail)) if detail else ''}")
        return True
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        print(f"  [FAIL] {name}：{msg}")
        FAILURES.append((name, msg))
        return False


def parser_check():
    import pdf_extract
    names = []
    if pdf_extract.HAS_PDFMINER:
        names.append("pdfminer.six " + __import__("pdfminer").__version__)
    if pdf_extract.HAS_PYPDF:
        names.append("pypdf " + __import__("pypdf").__version__)
    if not names:
        raise RuntimeError("pdfminer.six 和 pypdf 都没装，至少要有一个")
    used = "pdfminer.six" if pdf_extract.HAS_PDFMINER else "pypdf（精度较低的兜底）"
    return "、".join(names) + f"，实际使用 {used}"


def font_check():
    import pdf_render
    regular, bold = pdf_render.register_cjk_font()
    if regular == "Helvetica":
        raise RuntimeError("没找到任何中文字体，请把一个中文 ttf/ttc 放进 fonts/ 文件夹")
    if regular == "STSong-Light":
        return "PDF 内置中文字体（不嵌入字形，多数阅读器能正常显示）"
    return f"{regular} / {bold}"


def model_check():
    from translate_engine import Translator
    t = Translator(cache_path=None)
    where = "本地 model/ 文件夹" if os.path.isdir(t.model_name) else t.model_name
    out = t.translate(["Sound film changed how audiences perceived the screen."], beams=4)
    return f"{where} → 试译：{out[0]}"


def main():
    print("\n=== 英译中 PDF 翻译器 · 自检 ===\n")
    print(f"  系统   : {platform.platform()}")
    print(f"  Python : {sys.version.split()[0]}  ({sys.executable})")
    print()

    check("flask", lambda: __import__("flask").__version__)
    check("reportlab", lambda: __import__("reportlab").Version)
    check("PDF 解析后端", parser_check)
    check("torch", lambda: __import__("torch").__version__)
    check("numpy", lambda: __import__("numpy").__version__)
    check("transformers", lambda: __import__("transformers").__version__)
    check("sentencepiece", lambda: __import__("sentencepiece").__version__)
    check("中文字体", font_check)
    check("翻译模型", model_check)

    print()
    if not FAILURES:
        print("=== 全部通过，可以运行 run.bat / bash run.command 了。===\n")
        return 0

    print("=== 有项目没通过 ===\n")
    for name, msg in FAILURES:
        print(f"  · {name}：{msg}")
        for key, hint in HINTS:
            if key.lower() in msg.lower():
                print(f"    对策：{hint}")
                break
    print()
    return 1


if __name__ == "__main__":
    code = main()
    if sys.stdin.isatty():
        input("按回车键关闭…")
    sys.exit(code)
