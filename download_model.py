# -*- coding: utf-8 -*-
"""把翻译模型 opus-mt-en-zh 下到本地 model/ 文件夹。

正常情况下不用手动跑这个 —— 安装脚本会调它，程序首次翻译时也会自动
下载。只有在下载卡住或失败时才需要单独运行，它会：

  1. 先测两个站点的连通性，告诉你是不是网络层的问题；
  2. 用 huggingface_hub 逐个文件下载，每个文件独立重试、单独超时，
     卡住时你能看出卡在哪个文件；
  3. 库下载失败就退回直接 HTTP 下载（很多网络环境下这条路反而通）；
  4. 支持 --proxy 走本地代理。

用法：
    python download_model.py                  # 自动
    python download_model.py --proxy 7890     # 走本地代理端口
    python download_model.py --direct         # 直接跳到 HTTP 直连下载
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import urllib.request

REPO = "Helsinki-NLP/opus-mt-en-zh"
NEEDED = ["config.json", "pytorch_model.bin", "source.spm", "target.spm",
          "tokenizer_config.json", "vocab.json"]
OPTIONAL = ["generation_config.json", "model.safetensors"]
BASE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE, "model")
ENDPOINTS = ["https://huggingface.co", "https://hf-mirror.com"]


def ping(url: str, timeout: float = 8.0) -> str:
    try:
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return f"HTTP {r.status}  {time.time() - t0:.1f}s"
    except Exception as e:  # noqa: BLE001
        return f"失败（{type(e).__name__}）"


def have_all() -> bool:
    if not os.path.isdir(MODEL_DIR):
        return False
    if not os.path.isfile(os.path.join(MODEL_DIR, "config.json")):
        return False
    weights = any(os.path.isfile(os.path.join(MODEL_DIR, n))
                  for n in ("model.safetensors", "pytorch_model.bin"))
    others = all(os.path.isfile(os.path.join(MODEL_DIR, n))
                 for n in NEEDED if not n.endswith(".bin"))
    return weights and others


def download_direct(endpoint: str) -> bool:
    """不经过 huggingface_hub，直接按 URL 拉文件。"""
    os.makedirs(MODEL_DIR, exist_ok=True)
    ok = True
    for name in NEEDED + OPTIONAL:
        dst = os.path.join(MODEL_DIR, name)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0:
            print(f"  [已有] {name}")
            continue
        url = f"{endpoint}/{REPO}/resolve/main/{name}"
        try:
            t0 = time.time()
            with urllib.request.urlopen(url, timeout=30) as r, open(dst, "wb") as f:
                shutil.copyfileobj(r, f, length=1 << 20)
            mb = os.path.getsize(dst) / 1e6
            print(f"  [OK]   {name:24s} {mb:7.1f} MB  {time.time() - t0:5.1f}s")
        except Exception as e:  # noqa: BLE001
            if os.path.exists(dst):
                os.remove(dst)
            if name in OPTIONAL:
                print(f"  [跳过] {name}（可选）")
                continue
            print(f"  [失败] {name}：{type(e).__name__}: {str(e)[:90]}")
            ok = False
    return ok and have_all()


def download_via_hub(endpoint: str) -> bool:
    os.environ["HF_ENDPOINT"] = endpoint
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "20")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # Xet 传输常被网络策略挡掉
    try:
        from huggingface_hub import snapshot_download
    except Exception as e:  # noqa: BLE001
        print(f"  huggingface_hub 不可用：{e}")
        return False
    try:
        snapshot_download(REPO, local_dir=MODEL_DIR,
                          allow_patterns=NEEDED + OPTIONAL)
        return have_all()
    except Exception as e:  # noqa: BLE001
        print(f"  库下载失败：{type(e).__name__}: {str(e)[:120]}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", help="本地代理端口或完整地址，如 7890 或 http://127.0.0.1:7890")
    ap.add_argument("--direct", action="store_true", help="跳过库，直接 HTTP 下载")
    args = ap.parse_args()

    if args.proxy:
        proxy = args.proxy if "://" in args.proxy else f"http://127.0.0.1:{args.proxy}"
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = proxy
        print(f"使用代理：{proxy}")

    print(f"目标目录：{MODEL_DIR}")
    if have_all():
        print("模型已经齐了，无需下载。")
        return 0

    print("\n--- 连通性 ---")
    for ep in ENDPOINTS:
        print(f"  {ep:28s} {ping(ep)}")

    for ep in ENDPOINTS:
        if not args.direct:
            print(f"\n--- 用 huggingface_hub 从 {ep} 下载 ---")
            if download_via_hub(ep):
                break
        print(f"\n--- 直接 HTTP 从 {ep} 下载 ---")
        if download_direct(ep):
            break
    else:
        print("\n[失败] 两个源都没成功。")
        print("可以试：python download_model.py --proxy 你的代理端口")
        print("或者用浏览器打开下面的地址，手动下载 6 个文件放进 model/ 文件夹：")
        print(f"  {ENDPOINTS[0]}/{REPO}/tree/main")
        return 1

    print("\n--- 验证能否加载 ---")
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(MODEL_DIR)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_DIR)
        enc = tok(["Sound film changed how audiences perceived the screen."],
                  return_tensors="pt")
        print("试译：", tok.batch_decode(model.generate(**enc, max_length=64),
                                       skip_special_tokens=True)[0])
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 文件下全了但加载失败：{type(e).__name__}: {e}")
        return 1

    print("\n[成功] 模型就位，以后完全离线。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
