@echo off
echo ============================================
echo   StockVN - Phan Tich Co Phieu Viet Nam
echo ============================================
echo.

REM Di chuyen den thu muc backend bat ke current directory
cd /d "%~dp0backend"

echo [1/4] Cap nhat ban moi nhat tu Github...
git pull origin main

echo [2/4] Kiem tra Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo LOI: Python chua duoc cai dat.
  echo Tai Python tai https://python.org va them vao PATH.
  pause
  exit /b 1
)

echo [3/4] Kiem tra dependencies...
python -c "import fastapi, uvicorn, httpx, pandas, numpy" >nul 2>&1
if errorlevel 1 (
  echo Cai dat dependencies...
  pip install -r requirements.txt
  if errorlevel 1 (
    echo LOI: Khong the cai dependencies. Hay chay thu cong:
    echo   cd %~dp0backend
    echo   pip install -r requirements.txt
    pause
    exit /b 1
  )
)

echo [4/4] Khoi dong backend...
echo.
echo ============================================
echo   Dashboard: http://localhost:8000
echo   API Docs:  http://localhost:8000/docs
echo ============================================
echo.
echo Nhan Ctrl+C de dung server
echo.

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

pause
