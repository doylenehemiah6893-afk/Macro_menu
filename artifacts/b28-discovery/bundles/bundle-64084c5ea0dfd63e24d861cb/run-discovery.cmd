@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "BUNDLE_ROOT=%~dp0"
set "COLLECTOR=%BUNDLE_ROOT%target-discovery.pyz"
if not exist "%COLLECTOR%" (
  echo ERROR: target-discovery.pyz is not beside run-discovery.cmd. 1>&2
  exit /b 9009
)
where py >nul 2>&1
if errorlevel 1 goto python_fallback
py -3.12 -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto python_fallback
py -3.12 "%COLLECTOR%" %*
exit /b %ERRORLEVEL%

:python_fallback
where python >nul 2>&1
if errorlevel 1 goto python_missing
python -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto python_missing
python "%COLLECTOR%" %*
exit /b %ERRORLEVEL%

:python_missing
echo ERROR: native CPython 3.12 is required. 1>&2
exit /b 9009
