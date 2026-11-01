@echo off
rem A1/A2 BlockPy practice setup without AI: files + robot panel fix + voice parts + check, then voice model.
set "PY=%APPDATA%\blockpy-harness-playground\runtime\python\python.exe"
if not exist "%PY%" (echo BlockPy runtime not found: install BlockPy and run it once first & pause & exit /b 1)
"%PY%" "%~dp0setup.py"
"%PY%" "%~dp0setup.py" --model
pause
