# -*- coding: utf-8 -*-
"""英译中 PDF 翻译器 —— 本地网页版服务端。

启动后浏览器打开 http://127.0.0.1:8765 ，拖入 PDF 即可。

关于文件：所有处理都在本机完成，不联网、不上传。上传的原文和生成的
译文都只写在系统临时目录里 —— 原文翻完立刻删掉，译文要等你点"下载"
才由浏览器存进下载目录，程序退出时临时目录整个清空。项目文件夹里
不会堆积任何东西。
"""

from __future__ import annotations

import atexit
import glob
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template, request, send_file

import pipeline
from translate_engine import Translator

BASE = os.path.dirname(os.path.abspath(__file__))

_TMP_PREFIX = "pdftr_"


def _purge_stale_tmp(max_age_hours: float = 24.0) -> None:
    """清掉上次异常退出（比如直接叉掉窗口）留下的临时目录。"""
    cutoff = time.time() - max_age_hours * 3600
    for path in glob.glob(os.path.join(tempfile.gettempdir(), _TMP_PREFIX + "*")):
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


_purge_stale_tmp()
WORK_DIR = tempfile.mkdtemp(prefix=_TMP_PREFIX)
UPLOAD_DIR = os.path.join(WORK_DIR, "in")
OUTPUT_DIR = os.path.join(WORK_DIR, "out")
for d in (UPLOAD_DIR, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)
atexit.register(lambda: shutil.rmtree(WORK_DIR, ignore_errors=True))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 单次最大 512MB

# 翻译缓存：把翻过的句子存进 cache.db，重复内容不重算（重翻同一本书时省很多时间）。
# 它会留下你翻译过的文本，介意的话设环境变量 MT_CACHE=off 关掉，或直接删掉 cache.db。
_CACHE_OFF = os.environ.get("MT_CACHE", "").strip().lower() in ("0", "off", "no", "false")
TRANSLATOR = Translator(cache_path=None if _CACHE_OFF else os.path.join(BASE, "cache.db"))
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
WORK_Q: "queue.Queue[str]" = queue.Queue()


def _safe_name(name: str) -> str:
    name = os.path.basename(name).replace("\\", "_").replace("/", "_")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name[:120] or "document.pdf"


def _update(job_id: str, **kw):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job.update(kw)
            job["updated"] = time.time()


def worker():
    while True:
        job_id = WORK_Q.get()
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job or job["status"] == "cancelled":
            WORK_Q.task_done()
            continue
        _update(job_id, status="running", started=time.time())
        try:
            def on_status(d):
                _update(job_id, **d)

            def should_stop():
                with JOBS_LOCK:
                    return JOBS.get(job_id, {}).get("status") == "cancelled"

            result = pipeline.translate_pdf(
                job["src_path"], job["out_path"], TRANSLATOR,
                mode=job["mode"], beams=job["beams"], drop_refs=job["drop_refs"],
                on_status=on_status, should_stop=should_stop,
                display_name=job["name"],
                page_range=((job["page_from"], job["page_to"])
                            if (job["page_from"] or job["page_to"]) else None),
            )
            _update(job_id, status="done", percent=100, message="翻译完成",
                    result=result, finished=time.time())
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = str(e)
            if "No module named" in msg or "transformers" in msg or "torch" in msg:
                msg = "缺少依赖，请先运行安装脚本（install.bat / install.command）。原始错误：" + msg
            _update(job_id, status="error", message=msg, finished=time.time())
        finally:
            # 原文副本用完即删，不在机器上留底
            try:
                os.remove(job["src_path"])
            except OSError:
                pass
            WORK_Q.task_done()


threading.Thread(target=worker, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    mode = request.form.get("mode", "bilingual")
    quality = request.form.get("quality", "normal")
    drop_refs = request.form.get("drop_refs") == "1"
    beams = 4 if quality == "normal" else 1

    def _page(name):
        try:
            v = int(request.form.get(name, "").strip())
            return v if v > 0 else None
        except Exception:
            return None

    page_from, page_to = _page("page_from"), _page("page_to")

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有收到文件"}), 400

    created = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            continue
        job_id = uuid.uuid4().hex[:12]
        name = _safe_name(f.filename)
        src = os.path.join(UPLOAD_DIR, f"{job_id}_{name}")
        f.save(src)
        stem = os.path.splitext(name)[0]
        suffix = "中英对照" if mode == "bilingual" else "中文"
        span = ""
        if page_from or page_to:
            span = f"_p{page_from or 1}-{page_to or '末'}"
        out_name = f"{stem}{span}_{suffix}.pdf"
        out = os.path.join(OUTPUT_DIR, f"{job_id}_{out_name}")
        job = {
            "id": job_id, "name": name, "out_name": out_name,
            "src_path": src, "out_path": out, "mode": mode, "beams": beams,
            "drop_refs": drop_refs, "page_from": page_from, "page_to": page_to,
            "status": "queued", "percent": 0,
            "message": "排队中…", "created": time.time(),
            "created_str": datetime.now().strftime("%H:%M"),
        }
        with JOBS_LOCK:
            JOBS[job_id] = job
        WORK_Q.put(job_id)
        created.append(job_id)
    if not created:
        return jsonify({"error": "请上传 PDF 文件"}), 400
    return jsonify({"jobs": created})


@app.route("/api/jobs")
def jobs():
    with JOBS_LOCK:
        data = [
            {k: v for k, v in j.items() if k not in ("src_path", "out_path")}
            for j in sorted(JOBS.values(), key=lambda x: x["created"])
        ]
    return jsonify({"jobs": data})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    _update(job_id, status="cancelled", message="已取消")
    return jsonify({"ok": True})


@app.route("/api/download/<job_id>")
def download(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return "未完成", 404
    return send_file(job["out_path"], as_attachment=True,
                     download_name=job["out_name"])


@app.route("/api/preview/<job_id>")
def preview(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return "未完成", 404
    return send_file(job["out_path"])


@app.route("/api/env")
def env():
    ready, detail = True, ""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as e:  # noqa: BLE001
        ready, detail = False, str(e)
    try:
        import pdf_extract
        parser = "pdfminer.six" if pdf_extract.HAS_PDFMINER else "pypdf"
    except Exception:  # noqa: BLE001
        parser = "?"
    return jsonify({"ready": ready, "detail": detail, "parser": parser,
                    "model": os.path.basename(TRANSLATOR.model_name.rstrip("/\\"))})


def main():
    port = int(os.environ.get("PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  英译中 PDF 翻译器已启动：{url}")
    print(f"  临时目录：{WORK_DIR}（退出时自动清空）")
    print("  译文不会自动存盘，点网页上的「下载」才会保存到你的下载目录。")
    print("  用完关掉这个窗口即可退出。\n")
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
