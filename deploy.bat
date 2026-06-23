@echo off
setlocal

cd /d "%~dp0"

if not exist ".env" (
    echo [ERROR] File .env tidak ditemukan.
    echo Silakan salin .env.example menjadi .env dan isi nilai-nilai yang dibutuhkan.
    exit /b 1
)

echo Building and deploying Singgah...
docker compose up -d --build

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Deploy gagal.
    exit /b 1
)

echo.
echo Deploy berhasil.
echo Backend : http://localhost:8000
echo Frontend: http://localhost:3000

endlocal
