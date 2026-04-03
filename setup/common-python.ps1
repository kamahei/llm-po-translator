# Shared Python bootstrap helpers for POTranslatorLLM Windows setup scripts.

function Set-Tls12ForDownloads {
    try {
        [Net.ServicePointManager]::SecurityProtocol = (
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        )
    } catch {
        # Keep the current protocol settings if TLS 1.2 cannot be configured here.
    }
}

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Normalize-PathEntry {
    param([string]$PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return $null
    }

    return [System.Environment]::ExpandEnvironmentVariables(
        $PathEntry.Trim().Trim('"')
    ).TrimEnd('\').ToLowerInvariant()
}

function Test-PathContainsEntry {
    param(
        [string]$PathValue,
        [string]$TargetPath
    )

    $normalizedTarget = Normalize-PathEntry $TargetPath
    if ($null -eq $normalizedTarget) {
        return $false
    }

    foreach ($entry in ($PathValue -split ';')) {
        if ((Normalize-PathEntry $entry) -eq $normalizedTarget) {
            return $true
        }
    }

    return $false
}

function Update-SessionPathFromEnvironment {
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $segments = @()

    if (-not [string]::IsNullOrWhiteSpace($userPath)) {
        $segments += $userPath
    }
    if (-not [string]::IsNullOrWhiteSpace($machinePath)) {
        $segments += $machinePath
    }

    $env:PATH = ($segments -join ';').Trim(';')
}

function Add-PathEntry {
    param(
        [string]$PathEntry,
        [string]$Scope = "User"
    )

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return $false
    }

    $expandedPath = [System.Environment]::ExpandEnvironmentVariables(
        $PathEntry.Trim().Trim('"')
    ).TrimEnd('\')

    $currentValue = [System.Environment]::GetEnvironmentVariable("PATH", $Scope)
    if (Test-PathContainsEntry -PathValue $currentValue -TargetPath $expandedPath) {
        return $false
    }

    $newValue = if ([string]::IsNullOrWhiteSpace($currentValue)) {
        $expandedPath
    } else {
        "$expandedPath;$currentValue"
    }

    [System.Environment]::SetEnvironmentVariable("PATH", $newValue, $Scope)
    return $true
}

function Ensure-SessionPathEntry {
    param([string]$PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return $false
    }

    $expandedPath = [System.Environment]::ExpandEnvironmentVariables(
        $PathEntry.Trim().Trim('"')
    ).TrimEnd('\')

    if (Test-PathContainsEntry -PathValue $env:PATH -TargetPath $expandedPath) {
        return $false
    }

    $env:PATH = if ([string]::IsNullOrWhiteSpace($env:PATH)) {
        $expandedPath
    } else {
        "$expandedPath;$env:PATH"
    }

    return $true
}

function Get-PythonCommandInfo {
    param([string]$CommandPathOrName)

    try {
        $versionOutput = & $CommandPathOrName --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $null
        }

        $versionText = ($versionOutput | Out-String).Trim()
        if ($versionText -notmatch 'Python (?<version>\d+\.\d+\.\d+)') {
            return $null
        }

        $resolvedPath = $null
        try {
            $commandInfo = Get-Command $CommandPathOrName -ErrorAction Stop
            $resolvedPath = $commandInfo.Source
        } catch {
            if (Test-Path $CommandPathOrName) {
                $resolvedPath = (Resolve-Path $CommandPathOrName).Path
            }
        }

        return [pscustomobject]@{
            CommandName    = $CommandPathOrName
            ExecutablePath = $resolvedPath
            Version        = [Version]$Matches.version
            VersionText    = $Matches.version
        }
    } catch {
        return $null
    }
}

function Get-RegisteredPythonInstallations {
    $registryRoots = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\Software\Python\PythonCore",
        "HKLM:\Software\Wow6432Node\Python\PythonCore"
    )

    $installations = @()

    foreach ($root in $registryRoots) {
        if (-not (Test-Path $root)) {
            continue
        }

        foreach ($versionKey in (Get-ChildItem -Path $root -ErrorAction SilentlyContinue)) {
            $installKeyPath = Join-Path $versionKey.PSPath "InstallPath"
            if (-not (Test-Path $installKeyPath)) {
                continue
            }

            try {
                $version = [Version]$versionKey.PSChildName
            } catch {
                continue
            }

            try {
                $installKey = Get-Item -Path $installKeyPath -ErrorAction Stop
                $installPath = $installKey.GetValue('')
                if ([string]::IsNullOrWhiteSpace($installPath)) {
                    continue
                }

                $installations += [pscustomobject]@{
                    Version     = $version
                    InstallPath = $installPath.Trim().Trim('"')
                }
            } catch {
                continue
            }
        }
    }

    return $installations
}

function Get-PythonExecutableCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($installation in (Get-RegisteredPythonInstallations)) {
        $pythonExe = Join-Path $installation.InstallPath "python.exe"
        if (Test-Path $pythonExe) {
            $candidates.Add($pythonExe)
        }
    }

    $defaultRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $defaultRoot) {
        foreach ($directory in (Get-ChildItem -Path $defaultRoot -Directory -ErrorAction SilentlyContinue)) {
            $pythonExe = Join-Path $directory.FullName "python.exe"
            if (Test-Path $pythonExe) {
                $candidates.Add($pythonExe)
            }
        }
    }

    return $candidates | Sort-Object -Unique
}

function Find-BestInstalledPython {
    param([Version]$MinimumVersion = [Version]"0.0")

    Update-SessionPathFromEnvironment

    $candidateInfos = @()

    foreach ($commandName in @("python", "python3")) {
        $info = Get-PythonCommandInfo -CommandPathOrName $commandName
        if ($null -ne $info) {
            $candidateInfos += $info
        }
    }

    foreach ($pythonExe in (Get-PythonExecutableCandidates)) {
        $info = Get-PythonCommandInfo -CommandPathOrName $pythonExe
        if ($null -ne $info) {
            $candidateInfos += $info
        }
    }

    $unique = @{}
    foreach ($info in $candidateInfos) {
        $key = if ([string]::IsNullOrWhiteSpace($info.ExecutablePath)) {
            $info.CommandName.ToLowerInvariant()
        } else {
            $info.ExecutablePath.ToLowerInvariant()
        }

        if (-not $unique.ContainsKey($key) -or $info.Version -gt $unique[$key].Version) {
            $unique[$key] = $info
        }
    }

    return $unique.Values |
        Where-Object { $_.Version -ge $MinimumVersion } |
        Sort-Object Version -Descending |
        Select-Object -First 1
}

function Find-PythonLauncherPath {
    $commandInfo = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $commandInfo -and -not [string]::IsNullOrWhiteSpace($commandInfo.Source)) {
        return $commandInfo.Source
    }

    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe"),
        (Join-Path $env:WINDIR "py.exe")
    )) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $pythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $pythonRoot) {
        $launcher = Get-ChildItem -Path $pythonRoot -Filter "py.exe" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $launcher) {
            return $launcher.FullName
        }
    }

    return $null
}

function Ensure-PythonInstallPathsOnPath {
    param([string]$PythonExecutablePath)

    if ([string]::IsNullOrWhiteSpace($PythonExecutablePath) -or -not (Test-Path $PythonExecutablePath)) {
        return
    }

    $pythonDir = Split-Path $PythonExecutablePath -Parent
    $pythonScriptsDir = Join-Path $pythonDir "Scripts"
    New-Item -ItemType Directory -Path $pythonScriptsDir -Force | Out-Null

    $addedEntries = @()
    foreach ($entry in @($pythonDir, $pythonScriptsDir)) {
        if (Add-PathEntry -PathEntry $entry -Scope "User") {
            $addedEntries += $entry
        }
        Ensure-SessionPathEntry -PathEntry $entry | Out-Null
    }

    if ($addedEntries.Count -gt 0) {
        foreach ($entry in $addedEntries) {
            Write-Host "      Added to user PATH: $entry" -ForegroundColor Green
        }
        Write-Host "      New terminals will pick up the updated PATH automatically." -ForegroundColor Cyan
    }
}

function Ensure-PythonLauncherOnPath {
    $launcherPath = Find-PythonLauncherPath
    if ([string]::IsNullOrWhiteSpace($launcherPath)) {
        return $false
    }

    $launcherDir = Split-Path $launcherPath -Parent
    $addedToUserPath = Add-PathEntry -PathEntry $launcherDir -Scope "User"
    $addedToSession = Ensure-SessionPathEntry -PathEntry $launcherDir

    if ($addedToUserPath -or $addedToSession) {
        Write-Host "      Added Python launcher to PATH: $launcherDir" -ForegroundColor Green
        Write-Host "      New terminals will pick up the updated PATH automatically." -ForegroundColor Cyan
    }

    return $true
}

function Get-PythonInstallerArchitectureSuffix {
    $architecture = if (-not [string]::IsNullOrWhiteSpace($env:PROCESSOR_ARCHITEW6432)) {
        $env:PROCESSOR_ARCHITEW6432
    } else {
        $env:PROCESSOR_ARCHITECTURE
    }

    if ($architecture -match "ARM64") {
        return "-arm64"
    }

    if ([Environment]::Is64BitOperatingSystem) {
        return "-amd64"
    }

    return ""
}

function Get-LatestPythonInstallerInfo {
    Set-Tls12ForDownloads

    $response = Invoke-WebRequest -Uri "https://www.python.org/downloads/latest/python3/" -MaximumRedirection 5 -UseBasicParsing
    $content = $response.Content
    $versionMatch = [regex]::Match($content, 'Python Release Python (?<version>\d+\.\d+\.\d+)')
    if (-not $versionMatch.Success) {
        throw "Could not determine the latest Python release from python.org."
    }

    $version = $versionMatch.Groups["version"].Value
    $suffix = Get-PythonInstallerArchitectureSuffix
    $urlPattern = if ([string]::IsNullOrWhiteSpace($suffix)) {
        'href="(?<url>https://www\.python\.org/ftp/python/\d+\.\d+\.\d+/python-\d+\.\d+\.\d+\.exe)"'
    } else {
        'href="(?<url>https://www\.python\.org/ftp/python/\d+\.\d+\.\d+/python-\d+\.\d+\.\d+' +
            [regex]::Escape($suffix) + '\.exe)"'
    }

    $urlMatch = [regex]::Match($content, $urlPattern)
    $installerUrl = if ($urlMatch.Success) {
        $urlMatch.Groups["url"].Value
    } else {
        "https://www.python.org/ftp/python/$version/python-$version$suffix.exe"
    }

    return [pscustomobject]@{
        Version      = $version
        InstallerUrl = $installerUrl
        ReleasePage  = $response.BaseResponse.ResponseUri.AbsoluteUri
    }
}

function Install-LatestPython {
    $installerInfo = Get-LatestPythonInstallerInfo
    $installerFileName = [System.IO.Path]::GetFileName(([Uri]$installerInfo.InstallerUrl).LocalPath)
    $downloadDir = Join-Path $env:TEMP "POTranslatorLLM"
    $installerPath = Join-Path $downloadDir $installerFileName

    New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null

    Write-Host "      Downloading Python $($installerInfo.Version) from python.org..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $installerInfo.InstallerUrl -OutFile $installerPath -UseBasicParsing

    $arguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=1",
        "InstallLauncherAllUsers=0",
        "Include_test=0",
        "Shortcuts=0",
        "SimpleInstall=1"
    )

    Write-Host "      Running Python installer..." -ForegroundColor Yellow
    $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -PassThru -Wait
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Python installer exited with code $($process.ExitCode)."
    }

    if ($process.ExitCode -eq 3010) {
        Write-Host "      Python installed. Windows requested a restart for some changes." -ForegroundColor Yellow
    } else {
        Write-Host "      Python installed." -ForegroundColor Green
    }

    Update-SessionPathFromEnvironment
}

function Enable-WindowsLongPaths {
    $registryPath = "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem"
    $valueName = "LongPathsEnabled"
    $currentValue = (Get-ItemProperty -Path $registryPath -Name $valueName -ErrorAction SilentlyContinue).$valueName

    if ($currentValue -eq 1) {
        Write-Host "      Windows long paths are already enabled." -ForegroundColor Green
        return $true
    }

    Write-Host "      Enabling Windows long paths..." -ForegroundColor Yellow

    try {
        if (Test-IsAdministrator) {
            New-ItemProperty -Path $registryPath -Name $valueName -PropertyType DWord -Value 1 -Force | Out-Null
        } else {
            $elevatedCommand = "New-ItemProperty -Path '$registryPath' -Name '$valueName' -PropertyType DWord -Value 1 -Force | Out-Null"
            $process = Start-Process -FilePath "powershell.exe" `
                -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $elevatedCommand) `
                -Verb RunAs `
                -Wait `
                -PassThru

            if ($process.ExitCode -ne 0) {
                throw "Elevated command exited with code $($process.ExitCode)."
            }
        }

        Write-Host "      Windows long paths are enabled." -ForegroundColor Green
        Write-Host "      New terminals will use the updated setting. Some apps may need a restart." -ForegroundColor Cyan
        return $true
    } catch {
        Write-Host "WARNING: Could not enable Windows long paths automatically." -ForegroundColor Yellow
        Write-Host "         Approve the UAC prompt next time, or set LongPathsEnabled manually." -ForegroundColor Yellow
        return $false
    }
}

function Ensure-PythonReady {
    param([Version]$MinimumVersion = [Version]"3.9")

    $pythonInfo = Find-BestInstalledPython -MinimumVersion $MinimumVersion
    if ($null -ne $pythonInfo) {
        Ensure-PythonInstallPathsOnPath -PythonExecutablePath $pythonInfo.ExecutablePath
        Ensure-PythonLauncherOnPath | Out-Null
        Update-SessionPathFromEnvironment
    }

    $pythonInfo = Find-BestInstalledPython -MinimumVersion $MinimumVersion
    $pyInfo = Get-PythonCommandInfo -CommandPathOrName "py"

    if ($null -eq $pythonInfo -or $null -eq $pyInfo) {
        $anyPython = Find-BestInstalledPython
        if ($null -eq $pythonInfo) {
            if ($null -ne $anyPython) {
                Write-Host "      Found Python $($anyPython.VersionText), but Python $MinimumVersion+ is required." -ForegroundColor Yellow
            } else {
                Write-Host "      Python $MinimumVersion+ not found." -ForegroundColor Yellow
            }
        }

        if ($null -eq $pyInfo) {
            Write-Host "      Python launcher 'py' is not available on PATH." -ForegroundColor Yellow
        }

        Install-LatestPython

        $pythonInfo = Find-BestInstalledPython -MinimumVersion $MinimumVersion
        if ($null -eq $pythonInfo) {
            throw "Python $MinimumVersion+ could not be located after installation."
        }

        Ensure-PythonInstallPathsOnPath -PythonExecutablePath $pythonInfo.ExecutablePath
        Ensure-PythonLauncherOnPath | Out-Null
        Update-SessionPathFromEnvironment
        $pyInfo = Get-PythonCommandInfo -CommandPathOrName "py"
    }

    if ($null -eq $pythonInfo) {
        throw "Python $MinimumVersion+ is required but could not be located."
    }

    if ($null -eq $pyInfo) {
        throw "The Python launcher 'py' could not be located after installation."
    }

    Write-Host "      Using Python: Python $($pythonInfo.VersionText)" -ForegroundColor Green
    Enable-WindowsLongPaths | Out-Null

    return $pythonInfo.ExecutablePath
}

function Install-PythonRequirements {
    param(
        [string]$PythonExecutablePath,
        [string]$RequirementsPath
    )

    if ([string]::IsNullOrWhiteSpace($PythonExecutablePath)) {
        throw "Python executable path is required."
    }

    if (-not (Test-Path $RequirementsPath)) {
        throw "requirements.txt not found: $RequirementsPath"
    }

    & $PythonExecutablePath -m pip install -r $RequirementsPath --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit code $LASTEXITCODE."
    }
}
