@echo off
chcp 65001 >nul
title 📦 安装依赖 - Qwen Helper

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 进入 backend
cd "godot-qwen-agent\backend"

:: 检查 requirements.txt 是否存在
if not exist "requirements.txt" (
    echo ⚠️ 错误：未找到 requirements.txt！
    echo 请确认 backend 目录下有该文件。
    pause
    exit /b
)

:: 激活 Conda 环境
call conda activate qwen-helper

echo.
echo 📥 正在安装 Python 依赖...
echo 请稍候，首次安装可能需要 2～5 分钟（需联网）...
echo.

:: 安装依赖
pip install -r requirements.txt

:: 检查是否成功
if %errorlevel% equ 0 (
    echo.
    echo ✅ 依赖安装成功！
    echo 现在可以运行：
    echo   python build_rag_index.py
    echo   python app.py
) else (
    echo.
    echo ❌ 安装失败！请检查网络或手动运行：
    echo   pip install -r requirements.txt
)

echo.
pause