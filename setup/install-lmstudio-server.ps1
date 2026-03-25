# install-lmstudio-server.ps1
# Sets up a shared LM Studio server with LAN access for POTranslatorLLM.
# Run as Administrator from the repository root:  .\setup\install-lmstudio-server.ps1

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  POTranslatorLLM -- LM Studio Shared Server Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator." -ForegroundColor Red
    Write-Host "       Right-click PowerShell and choose 'Run as Administrator'." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 1. LM Studio installation check
# ---------------------------------------------------------------------------
Write-Host "[1/5] Checking for LM Studio..." -ForegroundColor Yellow

$lmsExePaths = @(
    "$env:LOCALAPPDATA\Programs\LM-Studio\LM Studio.exe",
    "$env:LOCALAPPDATA\LM-Studio\LM Studio.exe",
    "C:\Program Files\LM-Studio\LM Studio.exe"
)

$lmsExe = $null
foreach ($path in $lmsExePaths) {
    if (Test-Path $path) {
        $lmsExe = $path
        Write-Host "      LM Studio found at: $lmsExe" -ForegroundColor Green
        break
    }
}

if ($null -eq $lmsExe) {
    Write-Host ""
    Write-Host "  LM Studio is not installed (or not found in default locations)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Please install LM Studio manually:" -ForegroundColor White
    Write-Host "    1. Download from https://lmstudio.ai/" -ForegroundColor Cyan
    Write-Host "    2. Run the installer and follow the on-screen instructions." -ForegroundColor White
    Write-Host "    3. Open LM Studio and download your preferred model." -ForegroundColor White
    Write-Host "    4. Re-run this script after installation." -ForegroundColor White
    Write-Host ""
    Write-Host "  Continuing with firewall and Python setup..." -ForegroundColor Yellow
    Write-Host ""
}

# ---------------------------------------------------------------------------
# 2. Open Windows Firewall for LM Studio port 1234 (LAN only)
# ---------------------------------------------------------------------------
Write-Host "[2/5] Opening Windows Firewall for port 1234 (Private/LAN networks)..." -ForegroundColor Yellow

$ruleName = "LM Studio LLM Port 1234"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName $ruleName
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 1234 `
    -Action Allow `
    -Profile Private `
    -Description "Allow LAN access to LM Studio LLM service" | Out-Null

Write-Host "      Firewall rule '$ruleName' created (Private profile only)." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. LM Studio server configuration guidance
# ---------------------------------------------------------------------------
Write-Host "[3/5] LM Studio server configuration..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  LM Studio must be configured to accept connections from other machines:" -ForegroundColor White
Write-Host ""
Write-Host "  In LM Studio:" -ForegroundColor White
Write-Host "    1. Open the Developer tab." -ForegroundColor White
Write-Host "    2. Under 'Server Settings', set the server address to:" -ForegroundColor White
Write-Host "       0.0.0.0  (to listen on all network interfaces)" -ForegroundColor Cyan
Write-Host "    3. Set port: 1234 (default)" -ForegroundColor White
Write-Host "    4. Optionally enable API key authentication and set a key." -ForegroundColor White
Write-Host "    5. Click 'Start Server'." -ForegroundColor White
Write-Host ""
Write-Host "  NOTE: LM Studio does not have a built-in auto-start service." -ForegroundColor Yellow
Write-Host "        You must start the LM Studio server manually after each reboot," -ForegroundColor Yellow
Write-Host "        or set up a scheduled task manually." -ForegroundColor Yellow
Write-Host ""

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
    Write-Host "WARNING: Python 3.9+ not found. Install from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "         Then run: pip install -r setup\requirements.txt" -ForegroundColor Yellow
} else {
    $requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
    & $pythonCmd -m pip install -r $requirementsPath --quiet
    Write-Host "      Python dependencies installed." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 5. Create / update .env
# ---------------------------------------------------------------------------
Write-Host "[5/5] Setting up configuration..." -ForegroundColor Yellow

$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repoRoot ".env"
$examplePath = Join-Path $repoRoot "config\config.example.env"

if (-not (Test-Path $envPath)) {
    if (Test-Path $examplePath) {
        Copy-Item $examplePath $envPath
        Write-Host "      Created .env from config.example.env" -ForegroundColor Green
    }
} else {
    $envContent = Get-Content $envPath -Raw
    if ($envContent -notmatch "LMS_HOST") {
        $lmsSection = @"

# ---------------------------------------------------------------------------
# LM Studio backend (added by install-lmstudio-server.ps1)
# ---------------------------------------------------------------------------
LMS_HOST=http://localhost:1234
LMS_MODEL=
LMS_API_KEY=lm-studio
"@
        Add-Content -Path $envPath -Value $lmsSection
        Write-Host "      LM Studio settings appended to .env" -ForegroundColor Green
    } else {
        Write-Host "      .env already contains LMS_HOST -- skipping." -ForegroundColor Green
    }
}

# ---------------------------------------------------------------------------
# Print server LAN IP
# ---------------------------------------------------------------------------
$lanIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1).IPAddress
if ($null -eq $lanIp) { $lanIp = "<SERVER_IP>" }

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Server setup complete!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Server LAN address:  http://$lanIp:1234" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Open LM Studio and download your model (if not already done)." -ForegroundColor White
Write-Host "  2. In LM Studio Developer tab: set address to 0.0.0.0, then Start Server." -ForegroundColor White
Write-Host "  3. Verify LAN access from another PC:" -ForegroundColor White
Write-Host "       curl http://$lanIp:1234/v1/models" -ForegroundColor Cyan
Write-Host "  4. Share the server address with your team." -ForegroundColor White
Write-Host "     Each team member sets in their .env:" -ForegroundColor White
Write-Host "       LMS_HOST=http://$lanIp:1234" -ForegroundColor Cyan
Write-Host "       LMS_MODEL=<model-name>" -ForegroundColor Cyan
Write-Host ""
Write-Host "API authentication (optional):" -ForegroundColor White
Write-Host "  If you enabled API auth in LM Studio, set in each user's .env:" -ForegroundColor White
Write-Host "       LMS_API_KEY=<your-api-key>" -ForegroundColor Cyan
Write-Host ""
