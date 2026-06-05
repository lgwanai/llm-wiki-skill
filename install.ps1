# LLM Wiki - Windows Offline Installer (PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1
#   Or right-click → "Run with PowerShell"

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "LLM Wiki Installer"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  LLM Wiki - Windows Offline Installer" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Find project root ─────────────────────────────────────────
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ProjectRoot) {
    $ProjectRoot = Get-Location
}
Set-Location $ProjectRoot
Write-Host "  Project root: $ProjectRoot" -ForegroundColor DarkGray

# ── Helper: stopwatch for timing ──────────────────────────────
$sw = [System.Diagnostics.Stopwatch]::StartNew()

function Write-Step([int]$step, [int]$total, [string]$msg) {
    Write-Host "[$step/$total] $msg" -ForegroundColor Yellow
}

# ── Step 1: Check Python ──────────────────────────────────────
Write-Step 1 4 "Checking Python installation..."

try {
    $pyVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found"
    }
    Write-Host "  Found $pyVersion" -ForegroundColor Green
} catch {
    Write-Host @"

[ERROR] Python not found!
  Please install Python 3.10+ from:
    https://www.python.org/downloads/

  IMPORTANT: Check "Add Python to PATH" during installation.
"@ -ForegroundColor Red
    Pause
    exit 1
}

# ── Step 2: Check pip ─────────────────────────────────────────
Write-Step 2 4 "Checking pip..."

try {
    $pipVer = python -m pip --version 2>&1
    Write-Host "  pip OK" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] pip not found. Reinstall Python with pip enabled." -ForegroundColor Red
    Pause
    exit 1
}

# ── Step 3: Detect platform ───────────────────────────────────
Write-Step 3 4 "Detecting platform..."

$arch = python -c "import platform; print(platform.machine().lower())"
$arch = $arch.Trim()
if ($arch -eq "amd64") { $arch = "x86_64" }

$wheelDir = Join-Path $ProjectRoot "offline\wheels\windows-$arch"

if (-not (Test-Path $wheelDir)) {
    Write-Host "  [WARNING] No pre-downloaded wheels for windows-$arch" -ForegroundColor Yellow
    Write-Host "  Falling back to online install..." -ForegroundColor Yellow
    Write-Host ""
    Write-Step 4 4 "Installing dependencies (online)..."

    python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

    python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "online install failed" }

    goto InstallProject
}

$wheelCount = (Get-ChildItem "$wheelDir\*.whl").Count + (Get-ChildItem "$wheelDir\*.tar.gz" -ErrorAction SilentlyContinue).Count
Write-Host "  Platform: windows-$arch" -ForegroundColor Green
Write-Host "  Wheels:   $wheelCount packages in $wheelDir" -ForegroundColor Green

# ── Step 4: Install from local wheels ─────────────────────────
Write-Step 4 4 "Installing dependencies from local wheels..."
Write-Host "  This may take a few minutes..." -ForegroundColor DarkGray
Write-Host ""

$reqFile = Join-Path $wheelDir "requirements.txt"

try {
    # Upgrade pip from local wheel first
    $pipWheel = Get-ChildItem "$wheelDir\pip-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pipWheel) {
        python -m pip install --no-index --find-links $wheelDir pip
    }

    # Install all binary dependencies
    python -m pip install --no-index --find-links $wheelDir --only-binary :all: -r $reqFile

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  [WARNING] Some binary packages failed. Trying hybrid mode..." -ForegroundColor Yellow
        python -m pip install --find-links $wheelDir -r $reqFile
    }

    # jieba ships as source-only (.tar.gz), install separately
    $jiebaArchive = Get-ChildItem "$wheelDir\jieba*.tar.gz" -ErrorAction SilentlyContinue
    if ($jiebaArchive) {
        Write-Host "  Installing jieba (source distribution)..." -ForegroundColor DarkGray
        python -m pip install --no-index --find-links $wheelDir "jieba>=0.42"
    }

} catch {
    Write-Host "[ERROR] Installation failed: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Attempting fallback: hybrid install (prefer local, allow online)..." -ForegroundColor Yellow
    python -m pip install --find-links $wheelDir -r $reqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] All install methods failed." -ForegroundColor Red
        Pause
        exit 1
    }
}

:InstallProject
# ── Install llm-wiki-skill itself ─────────────────────────────
Write-Host ""
Write-Host "Installing llm-wiki-skill..." -ForegroundColor Cyan

python -m pip install -e . --no-deps 2>$null
if ($LASTEXITCODE -ne 0) {
    python -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARNING] Editable install failed, trying regular install..." -ForegroundColor Yellow
        python -m pip install .
    }
}

# ── Verify installation ───────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Verification" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$allOk = $true

$coreCheck = python -c "import yaml, requests, numpy, duckdb; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Core deps:   OK" -ForegroundColor Green
} else {
    Write-Host "  Core deps:   FAILED" -ForegroundColor Red
    $allOk = $false
}

$cliCheck = python -c "from scripts.wiki import main; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  wiki CLI:    OK" -ForegroundColor Green
} else {
    Write-Host "  wiki CLI:    FAILED" -ForegroundColor Red
    $allOk = $false
}

$searchCheck = python -c "from scripts.search import search; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Search:      OK" -ForegroundColor Green
} else {
    Write-Host "  Search:      FAILED (non-critical)" -ForegroundColor Yellow
}

# Optional OCR backends
$ocrOk = $true
$mineruCheck = python -c "import magic_pdf; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  MinerU OCR:  OK" -ForegroundColor Green
} else {
    Write-Host "  MinerU OCR:  not installed (optional)" -ForegroundColor DarkGray
    $ocrOk = $false
}

# ── Summary ───────────────────────────────────────────────────
$sw.Stop()
$elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "  Installation Complete! ($elapsed s)" -ForegroundColor Green
} else {
    Write-Host "  Installation finished with warnings ($elapsed s)" -ForegroundColor Yellow
}
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Copy wiki_config.yaml.example to wiki_config.yaml" -ForegroundColor DarkGray
Write-Host "    2. Edit wiki_config.yaml with your API keys" -ForegroundColor DarkGray
Write-Host "    3. Run: python scripts\wiki.py init" -ForegroundColor DarkGray
Write-Host "    4. Run: python scripts\wiki.py --help" -ForegroundColor DarkGray
Write-Host ""

if (-not $ocrOk) {
    Write-Host "  Optional: Install OCR backends" -ForegroundColor DarkGray
    Write-Host "    MinerU:  uv pip install -U `"mineru[all]`"" -ForegroundColor DarkGray
    Write-Host "    Paddle:  pip install paddleocr paddlepaddle" -ForegroundColor DarkGray
    Write-Host ""
}

Pause
