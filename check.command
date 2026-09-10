#!/bin/bash
# 自检。双击运行，或在终端里执行：bash check.command
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export KMP_DUPLICATE_LIB_OK=TRUE
if [ -f "model/config.json" ]; then
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
fi
if [ -x .venv/bin/python3 ]; then PY=".venv/bin/python3"; else PY="python3"; fi
"$PY" selftest.py
