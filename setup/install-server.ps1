# install-server.ps1
# Sets up a shared Ollama server with LAN access and cloudflared for POTranslatorLLM.
# Run as Administrator from the repository root:  .\setup\install-server.ps1

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  POTranslatorLLM -- Shared Server Setup" -ForegroundColor Cyan
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
# 1. Check / install Ollama
# ---------------------------------------------------------------------------
Write-Host "[1/7] Checking for Ollama..." -ForegroundColor Yellow

# Helper: find ollama.exe, refreshing PATH from the system environment first.
function Get-OllamaExe {
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $userPath    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$machinePath;$userPath"

    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }

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
        Write-Host "      Running Ollama installer..." -ForegroundColor Yellow
        $proc = Start-Process -FilePath $installerPath -PassThru
        # Wait up to 5 minutes; installer may leave Ollama running as a background process
        $installerFinished = $proc.WaitForExit(300000)
        if (-not $installerFinished) {
            Write-Host "      Installer is still running after 5 minutes." -ForegroundColor Yellow
            Write-Host "      Please wait for the installer to finish, then re-run this script." -ForegroundColor Yellow
        }
        Write-Host "      Ollama installed." -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to download or install Ollama." -ForegroundColor Red
        Write-Host "       Install manually from https://ollama.com/download" -ForegroundColor Red
        exit 1
    }

    $ollamaExe = Get-OllamaExe
    if ($null -eq $ollamaExe) {
        if (-not $installerFinished) {
            Write-Host "ERROR: The installer has not finished yet. Please wait for it to complete, then re-run this script." -ForegroundColor Red
        } else {
            Write-Host "ERROR: Ollama was installed but ollama.exe could not be located." -ForegroundColor Red
            Write-Host "       Please restart PowerShell and re-run this script." -ForegroundColor Red
        }
        exit 1
    }
    Write-Host "      Ollama found at: $ollamaExe" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 2. Configure OLLAMA_HOST for LAN access
# ---------------------------------------------------------------------------
Write-Host "[2/7] Configuring Ollama to listen on all interfaces (LAN access)..." -ForegroundColor Yellow

[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "Machine")
$env:OLLAMA_HOST = "0.0.0.0"
Write-Host "      OLLAMA_HOST=0.0.0.0 set as system environment variable." -ForegroundColor Green
Write-Host "      A reboot (or Ollama restart) is required for this to take effect." -ForegroundColor Yellow

# ---------------------------------------------------------------------------
# 3. Pull default model
# ---------------------------------------------------------------------------
$defaultModel = "qwen2.5:7b"
Write-Host "[3/7] Pulling model '$defaultModel' (this may take several minutes)..." -ForegroundColor Yellow

# Start Ollama serve in background so we can pull
Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 5

try {
    & $ollamaExe pull $defaultModel
    Write-Host "      Model '$defaultModel' is ready." -ForegroundColor Green
} catch {
    Write-Host "WARNING: Failed to pull model. Run 'ollama pull qwen2.5:7b' manually." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 4. Register Ollama as a Windows Scheduled Task (auto-start on login)
# ---------------------------------------------------------------------------
Write-Host "[4/7] Registering Ollama as a startup scheduled task..." -ForegroundColor Yellow

$taskName = "OllamaServer"

# Remove existing task if present
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $ollamaExe -Argument "serve"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Description "Starts Ollama LLM server on login" | Out-Null

Write-Host "      Scheduled task '$taskName' registered." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 5. Open Windows Firewall for port 11434 (LAN only)
# ---------------------------------------------------------------------------
Write-Host "[5/7] Opening Windows Firewall for port 11434 (Private/LAN networks)..." -ForegroundColor Yellow

$ruleName = "Ollama LLM Port 11434"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName $ruleName
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 11434 `
    -Action Allow `
    -Profile Private `
    -Description "Allow LAN access to Ollama LLM service" | Out-Null

Write-Host "      Firewall rule '$ruleName' created (Private profile only)." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 6. Check Python and install dependencies
# ---------------------------------------------------------------------------
Write-Host "[6/7] Checking Python and installing dependencies..." -ForegroundColor Yellow

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
# 7. Install cloudflared
# ---------------------------------------------------------------------------
Write-Host "[7/7] Checking for cloudflared..." -ForegroundColor Yellow

$cfDir = "C:\cloudflared"
$cfExe = "$cfDir\cloudflared.exe"

$cfInstalled = $false
try {
    $null = & cloudflared --version 2>&1
    $cfInstalled = $true
    Write-Host "      cloudflared is already installed." -ForegroundColor Green
} catch { }

if (-not $cfInstalled -and -not (Test-Path $cfExe)) {
    Write-Host "      Downloading cloudflared..." -ForegroundColor Yellow
    $cfUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    New-Item -ItemType Directory -Path $cfDir -Force | Out-Null

    try {
        Invoke-WebRequest -Uri $cfUrl -OutFile $cfExe -UseBasicParsing
        Write-Host "      cloudflared downloaded to $cfExe" -ForegroundColor Green
    } catch {
        Write-Host "WARNING: Failed to download cloudflared. Install manually from:" -ForegroundColor Yellow
        Write-Host "         https://github.com/cloudflare/cloudflared/releases/latest" -ForegroundColor Yellow
    }

    # Add to system PATH if not present
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    if ($machinePath -notlike "*$cfDir*") {
        [System.Environment]::SetEnvironmentVariable("PATH", "$machinePath;$cfDir", "Machine")
        $env:PATH += ";$cfDir"
        Write-Host "      $cfDir added to system PATH." -ForegroundColor Green
    }
} elseif (Test-Path $cfExe) {
    Write-Host "      cloudflared found at $cfExe" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Create .env if not present
# ---------------------------------------------------------------------------
$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repoRoot ".env"
$examplePath = Join-Path $repoRoot "config\config.example.env"

if (-not (Test-Path $envPath) -and (Test-Path $examplePath)) {
    Copy-Item $examplePath $envPath
    Write-Host "      Created .env from config.example.env" -ForegroundColor Green
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
Write-Host "Server LAN address:  http://$lanIp:11434" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Reboot (or restart Ollama) so OLLAMA_HOST takes effect." -ForegroundColor White
Write-Host "  2. Verify LAN access from another PC:" -ForegroundColor White
Write-Host "       curl http://$lanIp:11434/v1/models" -ForegroundColor Cyan
Write-Host "  3. Set up Cloudflare Tunnel for external access:" -ForegroundColor White
Write-Host "       cloudflared tunnel login" -ForegroundColor Cyan
Write-Host "       Then follow: docs\cloudflare-setup.md" -ForegroundColor Cyan
Write-Host "  4. Share the LAN IP (or tunnel URL) with your team." -ForegroundColor White
Write-Host ""
Write-Host "To manage models:" -ForegroundColor White
Write-Host "  ollama list              # list installed models" -ForegroundColor Cyan
Write-Host "  ollama pull qwen2.5:14b  # pull a larger model" -ForegroundColor Cyan
Write-Host ""
