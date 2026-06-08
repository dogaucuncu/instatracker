@echo off
title InstaTracker
echo.
echo  ====================================
echo    InstaTracker - Baslatiliyor...
echo  ====================================
echo.

:: Check Python 3.10
py -3.10 --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python 3.10 bulunamadi. Python 3.10+ yukleyin: https://python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
echo [*] Bagimliliklar kontrol ediliyor...
py -3.10 -m pip install -r backend\requirements.txt -q --trusted-host pypi.org --trusted-host files.pythonhosted.org --disable-pip-version-check
if errorlevel 1 (
    echo [HATA] Bagimliliklar yuklenemedi.
    pause
    exit /b 1
)

echo.
echo [*] Sunucu baslatiliyor...
echo [*] Tarayici: http://localhost:8000
echo [*] Durdurmak icin: Ctrl+C
echo.

:: Open browser after a short delay
start /b cmd /c "timeout /t 2 >nul && start http://localhost:8000"

:: Start the server
cd backend
py -3.10 -m uvicorn main:app --host 127.0.0.1 --port 8000

pause
