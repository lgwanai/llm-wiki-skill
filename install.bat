@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   LLM Wiki - Windows Offline Installer
echo ============================================================
echo.

:: ── Find project root (where this script lives) ──────────────
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot access project directory: %PROJECT_ROOT%
    pause
    exit /b 1
)

:: ── Check Python ─────────────────────────────────────────────
echo [1/4] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ first:
    echo   https://www.python.org/downloads/
    echo   Make sure "Add Python to PATH" is checked during installation.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo   Found Python %PYVER%

:: ── Check pip ────────────────────────────────────────────────
echo [2/4] Checking pip...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found. Please reinstall Python with pip included.
    pause
    exit /b 1
)
echo   pip OK

:: ── Detect platform ──────────────────────────────────────────
echo [3/4] Detecting platform...
set "ARCH=unknown"
for /f "tokens=*" %%a in ('python -c "import platform; print(platform.machine().lower())"') do set "ARCH=%%a"

if "%ARCH%"=="amd64" set "ARCH=x86_64"
if "%ARCH%"=="x86_64" set "WHEEL_DIR=offline\wheels\windows-x86_64"
if "%ARCH%"=="arm64" set "WHEEL_DIR=offline\wheels\windows-arm64"

if not exist "%WHEEL_DIR%" (
    echo [WARNING] No pre-downloaded wheels for windows-%ARCH%.
    echo   Falling back to online install...
    echo.
    echo [4/4] Installing dependencies ^(online^)...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Online install failed.
        pause
        exit /b 1
    )
    goto :install_project
)

echo   Platform: windows-%ARCH%
echo   Wheels:   %WHEEL_DIR%

:: ── Install from local wheels ────────────────────────────────
echo.
echo [4/4] Installing dependencies from local wheels...
echo   This may take a few minutes...
echo.

python -m pip install --upgrade pip --no-index --find-links "%WHEEL_DIR%" ^
    --only-binary :all: ^
    -r "%WHEEL_DIR%\requirements.txt" 2>&1

:: jieba ships as source-only, install it separately
for %%f in ("%WHEEL_DIR%\jieba*.tar.gz") do (
    if exist %%f (
        echo   Installing jieba from source distribution...
        python -m pip install --no-index --find-links "%WHEEL_DIR%" "jieba>=0.42"
    )
)

if errorlevel 1 (
    echo.
    echo [WARNING] Some packages failed to install from local wheels.
    echo   Attempting hybrid install (prefer local, fallback online)...
    python -m pip install --find-links "%WHEEL_DIR%" -r "%WHEEL_DIR%\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Installation failed. Please check the errors above.
        pause
        exit /b 1
    )
)

:install_project
:: ── Install llm-wiki-skill itself ────────────────────────────
echo.
echo Installing llm-wiki-skill...
python -m pip install -e . --no-deps 2>nul || python -m pip install -e .
if errorlevel 1 (
    echo [WARNING] pip install -e . failed, trying without --no-deps...
    python -m pip install -e .
)

:: ── Verify ───────────────────────────────────────────────────
echo.
echo ============================================================
echo   Verification
echo ============================================================
python -c "import yaml, requests, numpy, duckdb; print('  Core deps: OK')" 2>nul
if errorlevel 1 (
    echo [WARNING] Core dependency check failed
) else (
    echo   Core deps: OK
)
python -c "from scripts.wiki import main; print('  wiki CLI:   OK')" 2>nul
if errorlevel 1 (
    echo [WARNING] wiki CLI check failed
) else (
    echo   wiki CLI:   OK
)

echo.
echo ============================================================
echo   Installation Complete!
echo ============================================================
echo.
echo   Next steps:
echo     1. Copy wiki_config.yaml.example to wiki_config.yaml
echo     2. Edit wiki_config.yaml with your API keys
echo     3. Run: python scripts\wiki.py init
echo     4. Run: python scripts\wiki.py --help
echo.
pause
