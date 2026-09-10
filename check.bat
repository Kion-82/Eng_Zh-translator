@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set KMP_DUPLICATE_LIB_OK=TRUE
if exist "%~dp0model\config.json" set HF_HUB_OFFLINE=1
if exist "%~dp0model\config.json" set TRANSFORMERS_OFFLINE=1
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
"%PY%" selftest.py
