# install-local.ps1
# Sets up Ollama and Python dependencies for local use of POTranslatorLLM.
# Run from the repository root:  .\setup\install-local.ps1

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  POTranslatorLLM -- Local Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Check / install Ollama
# ---------------------------------------------------------------------------
Write-Host "[1/5] Checking for Ollama..." -ForegroundColor Yellow

# Helper: find ollama.exe, refreshing PATH from the system environment first.
function Get-OllamaExe {
    # Refresh PATH in this session (picks up changes made by installers)
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $userPath    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$machinePath;$userPath"

    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }

    # Fall back to known default install locations
    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "C:\Program Files\Ollama\ollama.exe"
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$ollamaExe = Get-OllamaExe

if ($null -ne $ollamaExe) {
    Write-Host "      Ollama is already installed: $ollamaExe" -ForegroundColor Green
} else {
    Write-Host "      Ollama not found. Downloading installer..." -ForegroundColor Yellow
    $installerPath = "$env:TEMP\OllamaSetup.exe"
    $downloadUrl = "https://ollama.com/download/OllamaSetup.exe"

    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
        Write-Host "      Running Ollama installer (this may take a moment)..." -ForegroundColor Yellow
        Start-Process -FilePath $installerPath -Wait
        Write-Host "      Ollama installed." -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to download or install Ollama." -ForegroundColor Red
        Write-Host "       Please install manually from https://ollama.com/download" -ForegroundColor Red
        exit 1
    }

    # Resolve path now that the installer has finished
    $ollamaExe = Get-OllamaExe
    if ($null -eq $ollamaExe) {
        Write-Host "ERROR: Ollama was installed but ollama.exe could not be located." -ForegroundColor Red
        Write-Host "       Please restart PowerShell and re-run this script." -ForegroundColor Red
        exit 1
    }
    Write-Host "      Ollama found at: $ollamaExe" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 2. Verify Ollama service is running
# ---------------------------------------------------------------------------
Write-Host "[2/5] Verifying Ollama service..." -ForegroundColor Yellow

$ollamaRunning = $false
for ($i = 0; $i -lt 5; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 5
        $ollamaRunning = $true
        break
    } catch {
        if ($i -eq 0) {
            Write-Host "      Starting Ollama service..." -ForegroundColor Yellow
            Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
        }
        Start-Sleep -Seconds 3
    }
}

if (-not $ollamaRunning) {
    Write-Host "WARNING: Could not verify Ollama is running. Continuing anyway." -ForegroundColor Yellow
    Write-Host "         You may need to start Ollama manually before running translations." -ForegroundColor Yellow
} else {
    Write-Host "      Ollama service is running." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 3. Pull default model
# ---------------------------------------------------------------------------
$defaultModel = "qwen2.5:7b"
Write-Host "[3/5] Pulling model '$defaultModel' (this may take several minutes)..." -ForegroundColor Yellow

try {
    & $ollamaExe pull $defaultModel
    Write-Host "      Model '$defaultModel' is ready." -ForegroundColor Green
} catch {
    Write-Host "WARNING: Failed to pull model '$defaultModel'." -ForegroundColor Yellow
    Write-Host "         Run 'ollama pull qwen2.5:7b' manually after setup." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 4. Check Python and install dependencies
# ---------------------------------------------------------------------------
Write-Host "[4/5] Checking Python and installing dependencies..." -ForegroundColor Yellow

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(9|1[0-9])") {
            $pythonCmd = $cmd
            break
        }
    } catch { }
}

if ($null -eq $pythonCmd) {
    Write-Host "ERROR: Python 3.9+ is required but not found." -ForegroundColor Red
    Write-Host "       Download from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

Write-Host "      Using Python: $(& $pythonCmd --version)"

$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
try {
    & $pythonCmd -m pip install -r $requirementsPath --quiet
    Write-Host "      Python dependencies installed." -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to install Python dependencies." -ForegroundColor Red
    Write-Host "       Run manually: pip install -r setup\requirements.txt" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 5. Create .env if not present
# ---------------------------------------------------------------------------
Write-Host "[5/5] Setting up configuration..." -ForegroundColor Yellow

$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repoRoot ".env"
$examplePath = Join-Path $repoRoot "config\config.example.env"

if (-not (Test-Path $envPath)) {
    if (Test-Path $examplePath) {
        Copy-Item $examplePath $envPath
        Write-Host "      Created .env from config.example.env" -ForegroundColor Green
        Write-Host "      Edit .env to customize settings (model, server URL, etc.)" -ForegroundColor Cyan
    } else {
        Write-Host "      config.example.env not found -- skipping .env creation." -ForegroundColor Yellow
    }
} else {
    Write-Host "      .env already exists -- skipping." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Edit .env if you want to change the model or server settings." -ForegroundColor White
Write-Host "  2. Run a translation:" -ForegroundColor White
Write-Host "       python scripts\translate.py --folder Localization/Game --source-lang ja --target-lang en" -ForegroundColor Cyan
Write-Host ""
