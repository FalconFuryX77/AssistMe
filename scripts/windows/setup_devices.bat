@echo off
title AssistMe ADB Reverse Setup
echo Setting up reverse port forwarding (tcp:8000 -> tcp:8000) for connected devices...
for /f "skip=1 tokens=1" %%d in ('"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" devices') do (
    if not "%%d"=="" (
        echo Configuring %%d...
        "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" -s %%d reverse tcp:8000 tcp:8000
    )
)
echo.
echo Active reverse port forwards:
"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" reverse --list
echo.
pause
