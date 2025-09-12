@echo off
chcp 65001 >nul
title 一键卸载 Rename 右键菜单

echo.
echo ═══════════════════════════════════════
echo     一键卸载 Rename 右键菜单
echo ═══════════════════════════════════════
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ 需要管理员权限！
    echo.
    echo 请右键点击此文件，选择 "以管理员身份运行"
    echo.
    pause
    exit /b 1
)

echo ✅ 权限检查通过，开始卸载...
echo.

:: 删除所有右键菜单项（静默模式）
echo 正在删除右键菜单...

reg delete "HKCR\Directory\shell\SendToRename" /f >nul 2>&1
reg delete "HKCR\Directory\shell\SendToPowerRename" /f >nul 2>&1
reg delete "HKCR\*\shell\SendToRename" /f >nul 2>&1
reg delete "HKCR\*\shell\SendToPowerRename" /f >nul 2>&1
reg delete "HKCR\Directory\Background\shell\SendToRename" /f >nul 2>&1
reg delete "HKCR\Directory\Background\shell\SendToPowerRename" /f >nul 2>&1

echo.
echo 🎉 卸载成功！
echo.
echo 所有 Rename 相关的右键菜单项都已删除
echo.
pause