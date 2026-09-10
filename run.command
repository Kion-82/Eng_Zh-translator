#!/bin/bash
# 启动。双击运行，或在终端里执行：bash run.command
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export KMP_DUPLICATE_LIB_OK=TRUE

# 模型已在本地时彻底断网，避免任何联网调用把程序卡住
if [ -f "model/config.json" ]; then
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
fi

if [ -x .venv/bin/python3 ]; then
  PY=".venv/bin/python3"
  CERT="$("$PY" -c 'import certifi;print(certifi.where())' 2>/dev/null)"
  [ -n "$CERT" ] && export SSL_CERT_FILE="$CERT" REQUESTS_CA_BUNDLE="$CERT"
else
  echo "[提示] 没找到 .venv，先用系统 python3 试试。报错的话请先运行 bash install.command。"
  PY="python3"
fi

echo
echo "  正在启动，浏览器会自动打开 http://127.0.0.1:8765"
echo "  用完关掉这个终端窗口即可退出。"
echo
"$PY" app.py || echo "[错误] 启动失败，运行 bash check.command 看看是哪一步。"
read -r -p "按回车键关闭…"
