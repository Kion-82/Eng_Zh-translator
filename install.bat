@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

echo.
echo ============================================
echo   英译中 PDF 翻译器 - 安装（只需运行一次）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有检测到 Python。
  echo 请到 https://www.python.org/downloads/ 安装 Python 3.10 以上版本，
  echo 安装时勾选 "Add python.exe to PATH"，然后重新运行本脚本。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 创建独立运行环境 .venv ...
  python -m venv .venv || goto fail
)
set PY=.venv\Scripts\python.exe

echo.
echo [2/3] 安装依赖（含 torch，约 200MB，请耐心）...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo [3/3] 下载翻译模型（约 310MB，下完即可完全离线）...
"%PY%" download_model.py

echo.
echo ============================================
echo   安装完成。双击 run.bat 开始使用。
echo   出问题就双击 check.bat 自检。
echo ============================================
echo.
pause
exit /b 0

:fail
echo.
echo [失败] 安装没有完成。双击 check.bat 可以看到更具体的原因。
pause
exit /b 1
