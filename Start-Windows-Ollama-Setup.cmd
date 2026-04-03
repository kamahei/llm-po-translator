@echo off
setlocal

cd /d "%~dp0"

echo.
echo ==================================================
echo   POTranslatorLLM -- Windows Ollama Setup
echo ==================================================
echo.
echo This window will stay open when setup finishes.
echo.

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0setup\install-ollama-local.ps1"
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo Setup finished.
    echo You can keep the default .env for one local Ollama model.
) else (
    echo Setup did not finish successfully.
    echo If Windows asked to install Python or enable long paths, allow the prompts and run this file again.
)
echo.
pause

exit /b %EXITCODE%
