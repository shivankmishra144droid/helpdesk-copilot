# Helpdesk Copilot — single-window prototype launcher
param(
    [switch]$Stop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Script:ProjectRoot = $PSScriptRoot
$Script:BackendDir = Join-Path $ProjectRoot 'backend'
$Script:FrontendDir = Join-Path $ProjectRoot 'frontend'
$Script:RuntimeDir = Join-Path $ProjectRoot '.runtime'
$Script:LogsDir = Join-Path $RuntimeDir 'logs'
$Script:ArchiveDir = Join-Path $LogsDir 'archive'
$Script:BackendPidFile = Join-Path $RuntimeDir 'backend.pid'
$Script:FrontendPidFile = Join-Path $RuntimeDir 'frontend.pid'
$Script:FrontendPortFile = Join-Path $RuntimeDir 'frontend.port'

$Script:FrontendPort = 3000
$Script:FrontendUrl = 'http://localhost:3000'
$Script:SupervisorUrl = 'http://localhost:3000/supervisor'
$Script:FrontendPortMin = 3000
$Script:FrontendPortMax = 3099
$Script:BackendHealthUrl = 'http://127.0.0.1:8000/health'

$Script:MaxAttempts = 90
$Script:PollSeconds = 2

$Script:BackendStatusMessages = @(
    'Starting API server...'
    'Loading knowledge base...'
    'Building or loading FAISS indexes...'
    'Loading embedding model...'
    'Loading optional ML components...'
    'Starting inbox watcher...'
    'Running backend health check...'
)

function Write-Status {
    param(
        [string]$Message,
        [ValidateSet('Default', 'Green', 'Yellow', 'Red', 'Cyan', 'Gray', 'White')]
        [string]$Color = 'Default'
    )
    if ($Color -eq 'Default') {
        Write-Host $Message
    } else {
        Write-Host $Message -ForegroundColor $Color
    }
}

function Write-Banner {
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    Helpdesk Copilot' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonLauncher {
    if (Test-CommandAvailable 'py') {
        try {
            & py -3 --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return @{
                    FilePath = 'py'
                    ArgumentPrefix = @('-3')
                    DisplayName = (& py -3 --version 2>$null)
                }
            }
        } catch { }
    }
    if (Test-CommandAvailable 'python') {
        $ver = & python --version 2>$null
        return @{
            FilePath = 'python'
            ArgumentPrefix = @()
            DisplayName = $ver
        }
    }
    return $null
}

function Test-HttpEndpoint {
    param(
        [string]$Url,
        [int]$TimeoutSec = 4
    )
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Test-PortListening {
    param([int]$Port)
    try {
        $matches = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return [bool]$matches
    } catch {
        $netstat = netstat -ano | Select-String ":$Port\s" | Select-String 'LISTENING'
        return [bool]$netstat
    }
}

function Ensure-RuntimeLayout {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
}

function Archive-OldLogs {
    $files = @(
        'backend.log', 'backend-error.log', 'frontend.log', 'frontend-error.log'
    )
    $existing = $files | ForEach-Object { Join-Path $LogsDir $_ } | Where-Object { Test-Path $_ }
    if (-not $existing) { return }

    $stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
    $dest = Join-Path $ArchiveDir $stamp
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    foreach ($file in $existing) {
        Move-Item -Path $file -Destination (Join-Path $dest (Split-Path $file -Leaf)) -Force
    }
}

function Read-ManagedPid {
    param([string]$PidFile)
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content -Path $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not $raw) { return $null }
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) { return $null }
    return $pidValue
}

function Test-ProcessAlive {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction Stop
        return -not $proc.HasExited
    } catch {
        return $false
    }
}

function Set-FrontendPort {
    param([int]$Port)
    $Script:FrontendPort = $Port
    $Script:FrontendUrl = "http://localhost:$Port"
    $Script:SupervisorUrl = "http://localhost:$Port/supervisor"
}

function Read-StoredFrontendPort {
    if (-not (Test-Path $FrontendPortFile)) { return $null }
    $raw = (Get-Content -Path $FrontendPortFile -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not $raw) { return $null }
    $portValue = 0
    if (-not [int]::TryParse($raw, [ref]$portValue)) { return $null }
    if ($portValue -lt 1 -or $portValue -gt 65535) { return $null }
    return $portValue
}

function Save-FrontendPort {
    param([int]$Port)
    Set-Content -Path $FrontendPortFile -Value $Port -Encoding ASCII
}

function Resolve-FrontendStartup {
    $managedPid = Read-ManagedPid $FrontendPidFile
    $storedPort = Read-StoredFrontendPort
    if ($storedPort) {
        Set-FrontendPort $storedPort
        if ($managedPid -and (Test-ProcessAlive $managedPid) -and (Test-HttpEndpoint $FrontendUrl)) {
            return @{
                Port = $storedPort
                AlreadyRunning = $true
                AlternatePort = ($storedPort -ne $FrontendPortMin)
            }
        }
    }

    Set-FrontendPort $FrontendPortMin
    if (Test-HttpEndpoint $FrontendUrl) {
        return @{
            Port = $FrontendPortMin
            AlreadyRunning = $true
            AlternatePort = $false
        }
    }

    for ($port = $FrontendPortMin; $port -le $FrontendPortMax; $port++) {
        if (-not (Test-PortListening $port)) {
            Set-FrontendPort $port
            return @{
                Port = $port
                AlreadyRunning = $false
                AlternatePort = ($port -ne $FrontendPortMin)
            }
        }
    }

    throw "No available port found for the frontend ($FrontendPortMin-$FrontendPortMax). Close other applications and try again."
}

function Remove-StalePidFiles {
    foreach ($pair in @(
        @{ File = $BackendPidFile; Name = 'backend' }
        @{ File = $FrontendPidFile; Name = 'frontend'; PortFile = $FrontendPortFile }
    )) {
        $portFile = $pair['PortFile']
        $pidValue = Read-ManagedPid $pair.File
        if ($null -eq $pidValue) {
            if (Test-Path $pair.File) { Remove-Item $pair.File -Force }
            if ($portFile -and (Test-Path $portFile)) {
                Remove-Item $portFile -Force
            }
            continue
        }
        if (-not (Test-ProcessAlive $pidValue)) {
            Remove-Item $pair.File -Force -ErrorAction SilentlyContinue
            if ($portFile) {
                Remove-Item $portFile -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Save-ManagedPid {
    param(
        [string]$PidFile,
        [int]$ProcessId
    )
    Set-Content -Path $PidFile -Value $ProcessId -Encoding ASCII
}

function Refresh-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($machine -and $user) {
        $env:Path = "$machine;$user"
    } elseif ($machine) {
        $env:Path = $machine
    } elseif ($user) {
        $env:Path = $user
    }
}

function Test-WingetAvailable {
    if (-not (Test-CommandAvailable 'winget')) { return $false }
    try {
        & winget --version 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Install-WingetPackage {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    Write-Status "[SETUP] Installing $DisplayName via winget (may take a few minutes)..." 'Yellow'
    & winget install --id $PackageId -e `
        --accept-package-agreements `
        --accept-source-agreements `
        --disable-interactivity
    # 0 = success; -1978335189 = package already installed
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        throw "Automatic installation of $DisplayName failed (winget exit code $LASTEXITCODE). Install it manually and run run.bat again."
    }
    Refresh-SessionPath
    Start-Sleep -Seconds 3
}

function Find-PythonExecutable {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
        "${env:ProgramFiles}\Python312\python.exe"
        "${env:ProgramFiles}\Python311\python.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return @{
                FilePath = $path
                ArgumentPrefix = @()
                DisplayName = (& $path --version 2>$null)
            }
        }
    }
    return $null
}

function Ensure-PythonInstalled {
    $python = Get-PythonLauncher
    if ($python) { return $python }

    $python = Find-PythonExecutable
    if ($python) { return $python }

    Write-Status '[SETUP] Python 3 not found. Attempting automatic installation...' 'Yellow'
    if (-not (Test-WingetAvailable)) {
        throw @"
Python 3 is required but was not found, and winget is not available on this PC.

Install manually:
  1. Download Python 3.12 from https://www.python.org/downloads/
  2. Run the installer and check "Add python.exe to PATH"
  3. Run run.bat again
"@
    }

    Install-WingetPackage -PackageId 'Python.Python.3.12' -DisplayName 'Python 3.12'
    Refresh-SessionPath

    $python = Get-PythonLauncher
    if (-not $python) { $python = Find-PythonExecutable }
    if (-not $python) {
        throw @"
Python was installed but is not available in this session yet.

Close this window, open a new Command Prompt, and run run.bat again.
If it still fails, reinstall Python from https://www.python.org/downloads/ and check "Add python.exe to PATH".
"@
    }
    return $python
}

function Ensure-NodeOnPath {
    if (Test-CommandAvailable 'node') { return }

    $candidates = @(
        "${env:ProgramFiles}\nodejs"
        "${env:ProgramFiles(x86)}\nodejs"
        "$env:LOCALAPPDATA\Programs\nodejs"
    )
    foreach ($dir in $candidates) {
        if ((Test-Path $dir) -and (Test-Path (Join-Path $dir 'node.exe'))) {
            $env:Path = "$dir;$env:Path"
            return
        }
    }
}

function Ensure-NodeInstalled {
    Ensure-NodeOnPath
    if ((Test-CommandAvailable 'node') -and (Test-CommandAvailable 'npm')) { return }

    Write-Status '[SETUP] Node.js not found. Attempting automatic installation...' 'Yellow'
    if (-not (Test-WingetAvailable)) {
        throw @"
Node.js is required but was not found, and winget is not available on this PC.

Install manually:
  1. Download Node.js LTS from https://nodejs.org/
  2. Run the installer (npm is included)
  3. Run run.bat again
"@
    }

    Install-WingetPackage -PackageId 'OpenJS.NodeJS.LTS' -DisplayName 'Node.js LTS'
    Refresh-SessionPath
    Ensure-NodeOnPath

    if (-not (Test-CommandAvailable 'node')) {
        throw @"
Node.js was installed but is not available in this session yet.

Close this window, open a new Command Prompt, and run run.bat again.
If it still fails, reinstall Node.js LTS from https://nodejs.org/
"@
    }
    if (-not (Test-CommandAvailable 'npm')) {
        throw 'npm was not found after installing Node.js. Reinstall Node.js LTS from https://nodejs.org/'
    }
}

function Install-BackendDependencies {
    param($Python)
    Write-Status '[SETUP] Installing backend dependencies (first run may download ML packages; allow 5-15 minutes)...' 'Yellow'
    $bootstrapArgs = @()
    if ($Python.ArgumentPrefix.Count -gt 0) { $bootstrapArgs += $Python.ArgumentPrefix }
    $bootstrapArgs += @('-m', 'pip', 'install', '--upgrade', 'pip', 'wheel', 'setuptools')
    & $Python.FilePath @bootstrapArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to upgrade pip. Review the output above.'
    }

    $req = Join-Path $BackendDir 'requirements.txt'
    $args = @()
    if ($Python.ArgumentPrefix.Count -gt 0) { $args += $Python.ArgumentPrefix }
    $args += @('-m', 'pip', 'install', '-r', $req)
    & $Python.FilePath @args
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend dependency installation failed. Review the pip output above.'
    }
}

function Install-FrontendDependencies {
    Write-Status '[SETUP] Installing frontend dependencies (npm install)...' 'Yellow'
    Push-Location $FrontendDir
    try {
        & npm install
        if ($LASTEXITCODE -ne 0) {
            throw 'Frontend dependency installation failed. Review the npm output above.'
        }
    } finally {
        Pop-Location
    }
}

function Test-BackendImports {
    param($Python)
    $args = @()
    if ($Python.ArgumentPrefix.Count -gt 0) { $args += $Python.ArgumentPrefix }
    $args += @('-c', 'import fastapi, uvicorn, pydantic')
    & $Python.FilePath @args 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Start-BackendService {
    param($Python)

    $stdout = Join-Path $LogsDir 'backend.log'
    $stderr = Join-Path $LogsDir 'backend-error.log'

    $args = @()
    if ($Python.ArgumentPrefix.Count -gt 0) { $args += $Python.ArgumentPrefix }
    $args += @(
        '-m', 'uvicorn', 'main:app',
        '--host', '127.0.0.1', '--port', '8000'
    )
    # Auto-reload is for development only (it also doubles memory: watcher + worker).
    if ($env:COPILOT_DEV_RELOAD -eq '1') { $args += '--reload' }

    $proc = Start-Process `
        -FilePath $Python.FilePath `
        -ArgumentList $args `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    Save-ManagedPid -PidFile $BackendPidFile -ProcessId $proc.Id
    return $proc
}

function Start-FrontendService {
    param(
        [int]$Port = $Script:FrontendPort
    )

    Set-FrontendPort $Port
    $stdout = Join-Path $LogsDir 'frontend.log'
    $stderr = Join-Path $LogsDir 'frontend-error.log'

    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npm) { $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source }

    $proc = Start-Process `
        -FilePath $npm `
        -ArgumentList @('run', 'dev', '--', '-p', "$Port") `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    Save-ManagedPid -PidFile $FrontendPidFile -ProcessId $proc.Id
    Save-FrontendPort $Port
    return $proc
}

function Get-ProgressBar {
    param(
        [int]$Percent,
        [int]$Width = 20
    )
    $fullChar = [string][char]0x2588
    $emptyChar = [string][char]0x2591
    $filled = [Math]::Max(0, [Math]::Min($Width, [int][Math]::Round($Width * $Percent / 100)))
    $empty = $Width - $filled
    return ('[' + ($fullChar * $filled) + ($emptyChar * $empty) + ']')
}

function Show-StartupScreen {
    param(
        [string]$FrontendLabel,
        [int]$FrontendPercent,
        [string]$BackendLabel,
        [int]$BackendPercent
    )
    Clear-Host
    Write-Banner
    Write-Status 'Starting services...' 'Yellow'
    Write-Host ''
    Write-Host ("Frontend  {0} {1}" -f (Get-ProgressBar $FrontendPercent), $FrontendLabel)
    Write-Host ("Backend   {0} {1}" -f (Get-ProgressBar $BackendPercent), $BackendLabel)
    Write-Host ''
}

function Resolve-PortConflict {
    param(
        [int]$Port,
        [string]$ServiceName,
        [scriptblock]$HealthTest
    )

    if (-not (Test-PortListening $Port)) {
        return @{ Status = 'free' }
    }

    if (& $HealthTest) {
        return @{ Status = 'already_running' }
    }

    return @{
        Status = 'blocked'
        Message = "[ERROR] Port $Port is already being used by another application.`nClose the conflicting application and run the launcher again."
    }
}

function Wait-ForServices {
    param(
        [ref]$FrontendReady,
        [ref]$BackendReady,
        [System.Diagnostics.Process]$FrontendProc,
        [System.Diagnostics.Process]$BackendProc,
        [switch]$AllowRetry
    )

    $frontendPct = 10
    $backendPct = 10
    $msgIndex = 0

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        if (-not $FrontendReady.Value -and $FrontendProc -and $FrontendProc.HasExited) {
            return @{
                Success = $false
                FailedService = 'frontend'
                Reason = 'exited'
            }
        }
        if (-not $BackendReady.Value -and $BackendProc -and $BackendProc.HasExited) {
            return @{
                Success = $false
                FailedService = 'backend'
                Reason = 'exited'
            }
        }

        if (-not $FrontendReady.Value) {
            if (Test-HttpEndpoint $FrontendUrl) {
                $FrontendReady.Value = $true
                $frontendPct = 100
            } else {
                $frontendPct = [Math]::Min(90, $frontendPct + 2)
            }
        }

        if (-not $BackendReady.Value) {
            if (Test-HttpEndpoint $BackendHealthUrl) {
                $BackendReady.Value = $true
                $backendPct = 100
            } else {
                $backendPct = [Math]::Min(90, $backendPct + 1)
            }
        }

        $feLabel = if ($FrontendReady.Value) { 'READY' } else { 'STARTING' }
        $beLabel = if ($BackendReady.Value) {
            'READY'
        } else {
            $msg = $BackendStatusMessages[$msgIndex % $BackendStatusMessages.Count]
            $msgIndex++
            "STARTING - $msg"
        }

        Show-StartupScreen -FrontendLabel $feLabel -FrontendPercent $frontendPct `
            -BackendLabel $beLabel -BackendPercent $backendPct

        if ($FrontendReady.Value -and $BackendReady.Value) {
            Show-StartupScreen -FrontendLabel 'READY' -FrontendPercent 100 `
                -BackendLabel 'READY' -BackendPercent 100
            Start-Sleep -Milliseconds 400
            return @{ Success = $true }
        }

        Start-Sleep -Seconds $PollSeconds
    }

    return @{
        Success = $false
        FailedService = if (-not $BackendReady.Value) { 'backend' } else { 'frontend' }
        Reason = 'timeout'
    }
}

function Show-StartupFailure {
    param(
        [hashtable]$Result
    )

    Clear-Host
    Write-Banner
    Write-Status 'Startup did not complete successfully.' 'Red'
    Write-Host ''

    if ($Result.Reason -eq 'exited') {
        if ($Result.FailedService -eq 'backend') {
            Write-Status '[ERROR] The backend stopped before it became ready.' 'Red'
            Write-Host ''
            Write-Status 'Review:' 'Yellow'
            Write-Host (Join-Path $LogsDir 'backend-error.log')
            Write-Host (Join-Path $LogsDir 'backend.log')
        } else {
            Write-Status '[ERROR] The frontend stopped before it became ready.' 'Red'
            Write-Host ''
            Write-Status 'Review:' 'Yellow'
            Write-Host (Join-Path $LogsDir 'frontend-error.log')
            Write-Host (Join-Path $LogsDir 'frontend.log')
        }
    } else {
        if ($Result.FailedService -eq 'backend') {
            Write-Status '[ERROR] The backend took too long to start.' 'Red'
            Write-Host ''
            Write-Status 'Review:' 'Yellow'
            Write-Host (Join-Path $LogsDir 'backend.log')
            Write-Host (Join-Path $LogsDir 'backend-error.log')
            Write-Host ''
            Write-Status 'Health URL:' 'Gray'
            Write-Host $BackendHealthUrl
        } else {
            Write-Status '[ERROR] The frontend took too long to start.' 'Red'
            Write-Host ''
            Write-Status 'Review:' 'Yellow'
            Write-Host (Join-Path $LogsDir 'frontend.log')
            Write-Host (Join-Path $LogsDir 'frontend-error.log')
            Write-Host ''
            Write-Host $FrontendUrl
        }
    }

    Write-Host ''
    Write-Status 'Press L to open logs' 'Cyan'
    Write-Status 'Press R to retry' 'Cyan'
    Write-Status 'Press Q to exit' 'Cyan'
    Write-Host ''

    while ($true) {
        $key = Read-Host 'Choice'
        switch ($key.ToUpper()) {
            'L' { Open-Logs; continue }
            'R' { return 'retry' }
            'Q' { return 'quit' }
            default { Write-Status 'Invalid choice. Enter L, R, or Q.' 'Yellow' }
        }
    }
}

function Show-CompletionScreen {
    Clear-Host
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    STARTUP COMPLETED' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Status '[COMPLETED] Frontend is running' 'Green'
    Write-Status '[COMPLETED] Backend health check passed' 'Green'
    Write-Status '[COMPLETED] Helpdesk Copilot is ready' 'Green'
    Write-Host ''
    Write-Status 'Agent Interface:' 'Cyan'
    Write-Host $FrontendUrl
    if ($FrontendPort -ne $FrontendPortMin) {
        Write-Status "(Port $FrontendPortMin was busy - using port $FrontendPort)" 'Gray'
    }
    Write-Host ''
    Write-Status 'Supervisor Interface:' 'Cyan'
    Write-Host $SupervisorUrl
    Write-Host ''
}

function Show-CompletionMenu {
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                         MENU' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Status '[Y] Open Agent and Supervisor interfaces' 'White'
    Write-Status '[A] Open Agent interface only' 'White'
    Write-Status '[S] Open Supervisor interface only' 'White'
    Write-Status '[H] Open backend health page' 'White'
    Write-Status '[L] Open logs folder' 'White'
    Write-Status '[Q] Close launcher' 'White'
    Write-Host ''
    Write-Status 'Services keep running after you close this window.' 'Gray'
    Write-Status 'Use stop.bat to shut down the prototype.' 'Gray'
    Write-Host ''

    while ($true) {
        $choice = Read-Host 'Choice'
        switch ($choice.ToUpper()) {
            'Y' {
                Start-Process $FrontendUrl
                Start-Sleep -Milliseconds 500
                Start-Process $SupervisorUrl
            }
            'A' { Start-Process $FrontendUrl }
            'S' { Start-Process $SupervisorUrl }
            'H' { Start-Process $BackendHealthUrl }
            'L' { Open-Logs }
            'Q' { return }
            default { Write-Status 'Invalid choice. Enter Y, A, S, H, L, or Q.' 'Yellow' }
        }
    }
}

function Open-Logs {
    Ensure-RuntimeLayout
    Start-Process explorer.exe $LogsDir
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    if (-not (Test-ProcessAlive $ProcessId)) { return $false }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Stop-ManagedServices {
    Write-Banner
    Write-Status 'Stopping Helpdesk Copilot services...' 'Yellow'
    Write-Host ''

    $backendPid = Read-ManagedPid $BackendPidFile
    $frontendPid = Read-ManagedPid $FrontendPidFile

    if ($backendPid) {
        if (Stop-ProcessTree $backendPid) {
            Write-Status '[OK] Backend stopped' 'Green'
        } else {
            Write-Status '[OK] Backend was not running' 'Gray'
        }
        Remove-Item $BackendPidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Status '[OK] Backend was not running' 'Gray'
    }

    if ($frontendPid) {
        if (Stop-ProcessTree $frontendPid) {
            Write-Status '[OK] Frontend stopped' 'Green'
        } else {
            Write-Status '[OK] Frontend was not running' 'Gray'
        }
        Remove-Item $FrontendPidFile -Force -ErrorAction SilentlyContinue
        Remove-Item $FrontendPortFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Status '[OK] Frontend was not running' 'Gray'
        Remove-Item $FrontendPortFile -Force -ErrorAction SilentlyContinue
    }

    Write-Host ''
    Write-Status '[COMPLETED] Helpdesk Copilot has been stopped' 'Green'
    Write-Host ''
}

function Test-ProjectStructure {
    $required = @(
        (Join-Path $BackendDir 'main.py')
        (Join-Path $BackendDir 'requirements.txt')
        (Join-Path $FrontendDir 'package.json')
    )
    foreach ($path in $required) {
        if (-not (Test-Path $path)) {
            throw "Required file not found: $path`nMake sure run.bat is in the project root."
        }
    }
}

function Invoke-Launcher {
    Clear-Host
    Write-Banner
    Write-Status 'Checking system requirements...' 'Yellow'
    Write-Status 'First launch may install Python, Node.js, and project dependencies automatically.' 'Gray'
    Write-Status 'Internet access is required on a new PC. Only a web browser is not installed for you.' 'Gray'
    Write-Host ''

    if (-not (Test-CommandAvailable 'powershell.exe')) {
        throw 'PowerShell is required but was not detected.'
    }

    Ensure-NodeInstalled
    Write-Status "[OK] Node.js detected ($(node --version))" 'Green'
    Write-Status "[OK] npm detected ($(npm --version))" 'Green'

    $python = Ensure-PythonInstalled
    Write-Status "[OK] $($python.DisplayName) detected" 'Green'

    Test-ProjectStructure
    Write-Status '[OK] Project structure verified' 'Green'
    Write-Host ''

    Ensure-RuntimeLayout
    Remove-StalePidFiles
    Archive-OldLogs

    $frontendPlan = Resolve-FrontendStartup
    $frontendReady = $frontendPlan.AlreadyRunning
    $backendReady = Test-HttpEndpoint $BackendHealthUrl

    $frontendProc = $null
    $backendProc = $null

    if ($frontendReady) {
        $portNote = if ($frontendPlan.AlternatePort) { " on port $($frontendPlan.Port)" } else { '' }
        Write-Status "[OK] Frontend is already running$portNote" 'Green'
    } else {
        if ($frontendPlan.AlternatePort) {
            Write-Status "[INFO] Port $FrontendPortMin is in use. Using port $($frontendPlan.Port) for the frontend." 'Yellow'
        }

        if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
            Install-FrontendDependencies
        }

        Write-Status "[STARTING] Launching frontend on port $($frontendPlan.Port)..." 'Yellow'
        $frontendProc = Start-FrontendService -Port $frontendPlan.Port
    }

    if ($backendReady) {
        Write-Status '[OK] Backend is already running' 'Green'
    } else {
        $portCheck = Resolve-PortConflict -Port 8000 -ServiceName 'backend' -HealthTest { Test-HttpEndpoint $BackendHealthUrl }
        if ($portCheck.Status -eq 'blocked') { throw $portCheck.Message }

        if (-not (Test-BackendImports $python)) {
            Install-BackendDependencies $python
            if (-not (Test-BackendImports $python)) {
                throw 'Backend dependencies are still unavailable after installation.'
            }
        }

        $rankerModel = Join-Path $BackendDir 'models\xgboost_ranker.pkl'
        if (-not (Test-Path $rankerModel)) {
            Write-Status '[SETUP] Training search models on the demo data (first run, a few minutes)...' 'Yellow'
            $trainArgs = @()
            if ($python.ArgumentPrefix.Count -gt 0) { $trainArgs += $python.ArgumentPrefix }
            $trainArgs += @((Join-Path $ProjectRoot 'scripts\train_all.py'))
            & $python.FilePath @trainArgs
            if ($LASTEXITCODE -ne 0) {
                Write-Status '[WARN] Model training failed; search will run without the ML extras.' 'Yellow'
            }
        }

        Write-Status '[STARTING] Launching backend...' 'Yellow'
        $backendProc = Start-BackendService $python
    }

    Write-Host ''

    if ($frontendReady -and $backendReady) {
        Show-CompletionScreen
        Show-CompletionMenu
        return 0
    }

    Show-StartupScreen -FrontendLabel 'STARTING' -FrontendPercent 10 `
        -BackendLabel 'STARTING - Loading application components...' -BackendPercent 10
    Start-Sleep -Milliseconds 300

    $feRef = [ref]$frontendReady
    $beRef = [ref]$backendReady

    while ($true) {
        $waitResult = Wait-ForServices -FrontendReady $feRef -BackendReady $beRef `
            -FrontendProc $frontendProc -BackendProc $backendProc

        if ($waitResult.Success) {
            Show-CompletionScreen
            Show-CompletionMenu
            return 0
        }

        $action = Show-StartupFailure -Result $waitResult
        if ($action -eq 'quit') { return 1 }

        if ($action -eq 'retry') {
            Remove-StalePidFiles
            $frontendReady = Test-HttpEndpoint $FrontendUrl
            $backendReady = Test-HttpEndpoint $BackendHealthUrl

            if (-not $frontendReady) {
                $alive = $false
                $pid = Read-ManagedPid $FrontendPidFile
                if ($pid) { $alive = Test-ProcessAlive $pid }
                if (-not $alive) {
                    $retryPlan = Resolve-FrontendStartup
                    if (-not $retryPlan.AlreadyRunning) {
                        if ($retryPlan.AlternatePort) {
                            Write-Status "[INFO] Port $FrontendPortMin is in use. Using port $($retryPlan.Port) for the frontend." 'Yellow'
                        }
                        $frontendProc = Start-FrontendService -Port $retryPlan.Port
                    } else {
                        $frontendReady = $true
                    }
                }
            }

            if (-not $backendReady) {
                $alive = $false
                $pid = Read-ManagedPid $BackendPidFile
                if ($pid) { $alive = Test-ProcessAlive $pid }
                if (-not $alive) {
                    $backendProc = Start-BackendService $python
                }
            }

            $feRef = [ref]$frontendReady
            $beRef = [ref]$backendReady
            continue
        }
    }
}

try {
    if ($Stop) {
        Stop-ManagedServices
        exit 0
    }

    $exitCode = Invoke-Launcher
    exit $exitCode
} catch {
    Write-Host ''
    Write-Status "[ERROR] $($_.Exception.Message)" 'Red'
    Write-Host ''
    Write-Status 'Press L to open logs, or any other key to exit.' 'Yellow'
    $key = Read-Host 'Choice'
    if ($key.ToUpper() -eq 'L') { Open-Logs }
    exit 1
}
