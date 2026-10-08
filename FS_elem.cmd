@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 exit /b 1
where node.exe >nul 2>nul
if errorlevel 1 (
  echo Node.js 24 is required. Install it, then run setup:release.
  exit /b 1
)
node.exe "%~dp0scripts\start-release.mjs" --open %*
set "FS_ELEM_EXIT=%ERRORLEVEL%"
if not "%FS_ELEM_EXIT%"=="0" echo FS_elem stopped with exit code %FS_ELEM_EXIT%. See the error above.
exit /b %FS_ELEM_EXIT%
