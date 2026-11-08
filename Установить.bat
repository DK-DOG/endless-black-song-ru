@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
where py >nul 2>&1 && (
    py -3 "%~dp0src\install.py" %*
    goto done
)
where python >nul 2>&1 && (
    python "%~dp0src\install.py" %*
    goto done
)
echo Python 3 was not found. Install it from https://www.python.org/ and run this again.
:done
echo.
pause
