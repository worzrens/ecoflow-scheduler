@echo off
rem Test, force-close the app, rebuild the exe and launch it. Options: -NoTests -NoLaunch -Minimized -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rebuild.ps1" %*
if errorlevel 1 pause
