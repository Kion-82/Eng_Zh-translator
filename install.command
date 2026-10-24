#!/bin/bash
# macOS / Linux 安装脚本。双击运行，或在终端里执行：bash install.command
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1

echo
echo "============================================"
echo "  英译中 PDF 翻译器 - 安装（只需运行一次）"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 没找到 python3。"
  echo "请安装 Python 3.10 以上版本：https://www.python.org/downloads/"
  read -r -p "按回车键关闭…"; exit 1
fi

# 从别的系统拷过来的 .venv 用不了，挪开重建
if [ -d .venv ] && [ ! -x .venv/bin/python3 ]; then
  echo "检测到不是本机的 .venv，挪开重建…"
  mv .venv ".venv_other_os_$(date +%s)"
fi
# torch 2.2 只有 Python 3.10-3.12 的安装包，更新的 Python 装依赖必然失败，先拦下来
if [ -x .venv/bin/python3 ]; then CHK=".venv/bin/python3"; else CHK="python3"; fi
if ! "$CHK" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)'; then
  echo "[错误] 需要 Python 3.10 到 3.12，当前是：$("$CHK" --version 2>&1)"
  echo "依赖里的 torch 2.2 没有 Python 3.13 及以上的安装包。"
  echo "请安装 Python 3.12（https://www.python.org/downloads/），"
  echo "然后用 python3.12 -m venv .venv 建环境，再重新运行本脚本。"
  echo "如果 .venv 是用不合适的版本建的，先删掉 .venv 文件夹。"
  read -r -p "按回车键关闭…"; exit 1
fi

if [ ! -x .venv/bin/python3 ]; then
  echo "[1/3] 创建独立运行环境 .venv ..."
  python3 -m venv .venv || { echo "[错误] 创建失败"; read -r -p "回车关闭…"; exit 1; }
fi
PY=".venv/bin/python3"

# 老系统缺根证书时用 certifi 自带的，避免下载时 SSL 报错
CERT="$("$PY" -c 'import certifi;print(certifi.where())' 2>/dev/null)"
[ -n "$CERT" ] && export SSL_CERT_FILE="$CERT" REQUESTS_CA_BUNDLE="$CERT"

echo
echo "[2/3] 安装依赖（含 torch，约 200MB，请耐心）..."
"$PY" -m pip install --upgrade pip
# --only-binary 让 pip 自动回退到"还有预编译包"的版本，
# 而不是在老机器上编译源码（那必然失败）
if ! "$PY" -m pip install --only-binary=:all: --prefer-binary -r requirements.txt; then
  echo
  echo "整体安装失败，改成逐个装，看是哪个包在这台机器上没有预编译版本…"
  FAILED=""
  while read -r line; do
    case "$line" in ''|\#*) continue;; esac
    echo ">>> $line"
    "$PY" -m pip install --only-binary=:all: --prefer-binary "$line" </dev/null || FAILED="$FAILED $line"
  done < requirements.txt
  if [ -n "$FAILED" ]; then
    echo
    echo "以下包没装上：$FAILED"
    echo "如果只是 pdfminer.six 没装上，程序仍可运行（自动退回 pypdf 后端，精度略低）。"
  fi
fi

echo
echo "[3/3] 下载翻译模型（约 310MB，下完即可完全离线）..."
"$PY" download_model.py

echo
echo "============================================"
echo "  安装完成。运行：bash run.command"
echo "  出问题就运行：bash check.command"
echo "============================================"
read -r -p "按回车键关闭…"
