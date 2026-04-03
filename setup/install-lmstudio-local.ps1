# install-lmstudio-local.ps1
# Sets up LM Studio and Python dependencies for local use of POTranslatorLLM.
# Run from the repository root:  .\setup\install-lmstudio-local.ps1

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common-python.ps1")

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  POTranslatorLLM -- LM Studio Local Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. LM Studio installation check
# ---------------------------------------------------------------------------
Write-Host "[1/4] Checking for LM Studio..." -ForegroundColor Yellow

$lmsExePaths = @(
    "$env:LOCALAPPDATA\Programs\LM-Studio\LM Studio.exe",
    "$env:LOCALAPPDATA\LM-Studio\LM Studio.exe",
    "C:\Program Files\LM-Studio\LM Studio.exe"
)

$lmsInstalled = $false
foreach ($path in $lmsExePaths) {
    if (Test-Path $path) {
        $lmsInstalled = $true
        Write-Host "      LM Studio found at: $path" -ForegroundColor Green
        break
    }
}

if (-not $lmsInstalled) {
    Write-Host ""
    Write-Host "  LM Studio is not installed (or not found in default locations)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Please install LM Studio manually:" -ForegroundColor White
    Write-Host "    1. Download from https://lmstudio.ai/" -ForegroundColor Cyan
    Write-Host "    2. Run the installer and follow the on-screen instructions." -ForegroundColor White
    Write-Host "    3. Open LM Studio, go to the Search tab, and download a model." -ForegroundColor White
    Write-Host "       Recommended: qwen2.5-7b-instruct (good multilingual quality)" -ForegroundColor White
    Write-Host "    4. Enable the Local Server in LM Studio:" -ForegroundColor White
    Write-Host "       Developer tab → Start Server (default port: 1234)" -ForegroundColor Cyan
    Write-Host "    5. Re-run this script after installation." -ForegroundColor White
    Write-Host ""
    Write-Host "  After installation, continue with steps 2-4 below manually:" -ForegroundColor Yellow
    Write-Host ""
}

# ---------------------------------------------------------------------------
# 2. Verify LM Studio server is reachable
# ---------------------------------------------------------------------------
Write-Host "[2/4] Checking LM Studio server (http://localhost:1234)..." -ForegroundColor Yellow

try {
    $null = Invoke-RestMethod -Uri "http://localhost:1234/v1/models" -Method Get -TimeoutSec 5
    Write-Host "      LM Studio server is running." -ForegroundColor Green
} catch {
    Write-Host "      LM Studio server is not running." -ForegroundColor Yellow
    Write-Host "      Start it in LM Studio: Developer tab → Start Server." -ForegroundColor Yellow
    Write-Host "      You can still continue setup — start the server before running translations." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 3. Check Python and install dependencies
# ---------------------------------------------------------------------------
Write-Host "[3/4] Checking Python, enabling long paths, and installing dependencies..." -ForegroundColor Yellow

try {
    $pythonExe = Ensure-PythonReady
    $requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
    Install-PythonRequirements -PythonExecutablePath $pythonExe -RequirementsPath $requirementsPath
    Write-Host "      Python dependencies installed." -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to prepare Python automatically." -ForegroundColor Red
    Write-Host "       $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 4. Create / update .env
# ---------------------------------------------------------------------------
Write-Host "[4/4] Setting up configuration..." -ForegroundColor Yellow

$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repoRoot ".env"
$examplePath = Join-Path $repoRoot "config\config.example.env"

if (-not (Test-Path $envPath)) {
    if (Test-Path $examplePath) {
        Copy-Item $examplePath $envPath
        Write-Host "      Created .env from config.example.env" -ForegroundColor Green
        Write-Host "      Edit .env to set LMS_HOST and LMS_MODEL." -ForegroundColor Cyan
    } else {
        Write-Host "      config.example.env not found -- skipping .env creation." -ForegroundColor Yellow
    }
} else {
    # Check if .env already has LMS_HOST; if not, append LM Studio section.
    $envContent = Get-Content $envPath -Raw
    if ($envContent -notmatch "LMS_HOST") {
        $lmsSection = @"

# ---------------------------------------------------------------------------
# LM Studio backend (added by install-lmstudio-local.ps1)
# ---------------------------------------------------------------------------
LMS_HOST=http://localhost:1234
LMS_MODEL=
LMS_API_KEY=lm-studio
"@
        Add-Content -Path $envPath -Value $lmsSection
        Write-Host "      LM Studio settings appended to .env" -ForegroundColor Green
        Write-Host "      Edit .env and set LMS_MODEL to your model name." -ForegroundColor Cyan
    } else {
        Write-Host "      .env already contains LMS_HOST -- skipping." -ForegroundColor Green
    }
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
Write-Host "  1. Open LM Studio and download a model (if not already done)." -ForegroundColor White
Write-Host "       Recommended: qwen2.5-7b-instruct" -ForegroundColor Cyan
Write-Host "  2. Start the LM Studio local server:" -ForegroundColor White
Write-Host "       Developer tab → Start Server (default port: 1234)" -ForegroundColor Cyan
Write-Host "  3. Copy the model name from LM Studio and set it in .env:" -ForegroundColor White
Write-Host "       LMS_MODEL=<your-model-name>" -ForegroundColor Cyan
Write-Host "  4. Run a translation:" -ForegroundColor White
Write-Host "       python scripts\translate.py --folder Localization/Game --source-lang ja --target-lang en" -ForegroundColor Cyan
Write-Host ""
Write-Host "To use LM Studio alongside Ollama (mixed multi-host), set both in .env:" -ForegroundColor White
Write-Host "  OLLAMA_HOST=http://localhost:11434" -ForegroundColor Cyan
Write-Host "  LMS_HOST=http://localhost:1234" -ForegroundColor Cyan
Write-Host ""
