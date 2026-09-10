@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
rem 装过 Anaconda 的机器上，它的 libiomp5md.dll 会和 torch 自带的撞车，
rem 轻则加载失败重则进程直接崩。这个开关允许两份 OpenMP 运行库共存。
set KMP_DUPLICATE_LIB_OK=TRUE
rem 模型已经在本地时彻底断网，避免任何联网调用把程序卡住
if exist "%~dp0model\config.json" set HF_HUB_OFFLINE=1
if exist "%~dp0model\config.json" set TRANSFORMERS_OFFLINE=1

if exist ".venv\Scripts\python.exe" (
  set PY=.venv\Scripts\python.exe
) else (
  echo [提示] 没找到 .venv，先用系统 Python 试试。报错的话请先运行 install.bat。
  set PY=python
)

echo.
echo   正在启动，浏览器会自动打开 http://127.0.0.1:8765
echo   用完关掉这个窗口即可退出。
echo.
"%PY%" app.py
if errorlevel 1 echo [错误] 启动失败，双击 check.bat 看看是哪一步。
pause
