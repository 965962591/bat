@echo off
chcp 65001 >nul
title 一键安装 Rename 右键菜单

:: 切换到批处理文件所在目录
cd /d "%~dp0"

echo.
echo ═══════════════════════════════════════
echo     一键安装 Rename 右键菜单
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

:: 检查exe文件
if not exist "rename_single.exe" (
    echo ❌ 找不到 rename_single.exe 文件！
    echo.
    echo 请确保 rename_single.exe 与此批处理文件在同一目录
    echo.
    pause
    exit /b 1
)

echo ✅ 检查通过，开始安装...
echo.

:: 获取exe完整路径
set "EXE_PATH=%~dp0rename_single.exe"

:: 安装右键菜单（静默模式）
echo 正在注册右键菜单...

reg add "HKCR\Directory\shell\SendToRename" /ve /d "发送到 &Rename" /f >nul
reg add "HKCR\Directory\shell\SendToRename" /v "Icon" /d "\"%EXE_PATH%\",0" /f >nul
reg add "HKCR\Directory\shell\SendToRename\command" /ve /d "\"%EXE_PATH%\" --main-window \"%%1\"" /f >nul

reg add "HKCR\Directory\shell\SendToPowerRename" /ve /d "发送到 &PowerRename" /f >nul
reg add "HKCR\Directory\shell\SendToPowerRename" /v "Icon" /d "\"%EXE_PATH%\",0" /f >nul
reg add "HKCR\Directory\shell\SendToPowerRename\command" /ve /d "\"%EXE_PATH%\" --power-rename \"%%1\"" /f >nul

reg add "HKCR\*\shell\SendToRename" /ve /d "发送到 &Rename" /f >nul
reg add "HKCR\*\shell\SendToRename" /v "Icon" /d "\"%EXE_PATH%\",0" /f >nul
reg add "HKCR\*\shell\SendToRename\command" /ve /d "\"%EXE_PATH%\" --main-window \"%%1\"" /f >nul

reg add "HKCR\*\shell\SendToPowerRename" /ve /d "发送到 &PowerRename" /f >nul
reg add "HKCR\*\shell\SendToPowerRename" /v "Icon" /d "\"%EXE_PATH%\",0" /f >nul
reg add "HKCR\*\shell\SendToPowerRename\command" /ve /d "\"%EXE_PATH%\" --power-rename \"%%1\"" /f >nul

reg add "HKCR\Directory\Background\shell\SendToRename" /ve /d "在此处打开 &Rename" /f >nul
reg add "HKCR\Directory\Background\shell\SendToRename" /v "Icon" /d "\"%EXE_PATH%\",0" /f >nul
reg add "HKCR\Directory\Background\shell\SendToRename\command" /ve /d "\"%EXE_PATH%\" --main-window \"%%V\"" /f >nul

reg add "HKCR\Directory\Background\shell\SendToPowerRename" /ve /d "在此处打开 &PowerRename" /f >nul
reg add "HKCR\Directory\Background\shell\SendToPowerRename" /v "Icon" /d "\"%EXE_PATH%\",0" /f >nul
reg add "HKCR\Directory\Background\shell\SendToPowerRename\command" /ve /d "\"%EXE_PATH%\" --power-rename \"%%V\"" /f >nul

echo.
echo 🎉 安装成功！
echo.
echo 现在您可以：
echo • 右键点击文件或文件夹 → 选择 "发送到 Rename/PowerRename"
echo • 在文件夹空白处右键 → 选择 "在此处打开 Rename/PowerRename"
echo.
echo 💡 如果右键菜单没有立即显示，请重启文件管理器或重启系统
echo.
pause