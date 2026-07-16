@echo off
setlocal
py -3.12 "%~dp0bootstrap_resume.py" --repo-root "%~dp0.." --state "%~dp0..\resume\state.json"
if errorlevel 1 exit /b %errorlevel%
