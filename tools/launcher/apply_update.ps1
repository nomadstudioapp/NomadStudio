# Nomad Studio - apply a prepared update (docs/APP_UPDATES.md 7.3-7.5).
#
# Started by the running app (app/services/update_service.py) from a copy in
# <root>\.nomad-update\, never from inside app\: the folder it renames must not
# hold the script. Windows PowerShell 5.1 compatible, ASCII only.
#
#   1. wait for the app process to exit
#   2. app -> app.old, app.new -> app (with retries: antivirus, open Explorer)
#   3. copy the new launcher to the root and start it
#   4. wait for /api/health to report the new version
#   5. if it never does: stop it, put app.old back, start the old version
# Every step goes to <root>\update.log; the outcome to <root>\update-result.json.
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][int]$WaitPid,
    [Parameter(Mandatory = $true)][string]$To,
    [string]$From = "",
    [int]$Port = 5123,
    [int]$StartTimeout = 120
)

$ErrorActionPreference = 'Continue'
$App = Join-Path $Root 'app'
$New = Join-Path $Root 'app.new'
$Old = Join-Path $Root 'app.old'
$Launcher = Join-Path $Root 'NomadStudio.bat'
$LogFile = Join-Path $Root 'update.log'

function Log([string]$Message) {
    $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $Message
    try { Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 } catch { }
}

function Write-Result([bool]$Ok, [string]$Reason) {
    $data = [ordered]@{
        ok     = $Ok
        from   = $From
        to     = $To
        reason = $Reason
        at     = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    try {
        $json = $data | ConvertTo-Json
        [System.IO.File]::WriteAllText((Join-Path $Root 'update-result.json'), $json, (New-Object System.Text.UTF8Encoding $false))
    } catch { Log ('could not write update-result.json: ' + $_) }
}

function Invoke-WithRetry([scriptblock]$Action, [string]$What) {
    for ($i = 1; $i -le 20; $i++) {
        try {
            & $Action
            return $true
        } catch {
            if ($i -eq 1 -or $i -eq 20) { Log ($What + ' failed (try ' + $i + '): ' + $_.Exception.Message) }
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Start-NomadStudio {
    # The browser tab that asked for the update reloads by itself.
    $env:NOMAD_OPEN_BROWSER = '0'
    # Minimized from the start, like a normal launch: started from here the
    # .bat's own "start /min" re-launch came up as a full window (Windows
    # Terminal, Windows 11) covering the page that was reloading. With
    # NOMAD_LAUNCHER_MIN set the .bat runs the app in this very window, so
    # the process we get back is still the one that runs it.
    $env:NOMAD_LAUNCHER_MIN = '1'
    Log 'starting NomadStudio.bat'
    return Start-Process -FilePath $Launcher -WorkingDirectory $Root -WindowStyle Minimized -PassThru
}

function Stop-AppProcesses([string]$Folder, $LauncherProcess) {
    if ($LauncherProcess -and -not $LauncherProcess.HasExited) {
        & taskkill.exe /T /F /PID $LauncherProcess.Id 2>&1 | Out-Null
    }
    $exe = (Join-Path $Folder 'python\python.exe').ToLowerInvariant()
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant() -eq $exe } |
        ForEach-Object { & taskkill.exe /T /F /PID $_.ProcessId 2>&1 | Out-Null }
}

function Test-AppRunning([string]$Folder) {
    $exe = (Join-Path $Folder 'python\python.exe').ToLowerInvariant()
    $found = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLowerInvariant() -eq $exe }
    return [bool]$found
}

Log ('---- update ' + $From + ' -> ' + $To + ' (waiting for pid ' + $WaitPid + ')')

# 1. The app exits about a second after asking for this.
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
    Start-Sleep -Milliseconds 300
}
if (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) {
    Log 'the app did not exit; nothing changed'
    Write-Result $false 'app-did-not-exit'
    exit 1
}
Start-Sleep -Milliseconds 500

if (-not (Test-Path -LiteralPath (Join-Path $New 'app.py'))) {
    Log 'no prepared update in app.new'
    Write-Result $false 'no-prepared-update'
    Start-NomadStudio | Out-Null
    exit 1
}

# 2. Swap folders.
if (Test-Path -LiteralPath $Old) {
    if (-not (Invoke-WithRetry { Remove-Item -LiteralPath $Old -Recurse -Force -ErrorAction Stop } 'removing app.old')) {
        Write-Result $false 'folder-locked'
        Start-NomadStudio | Out-Null
        exit 1
    }
}
if (-not (Invoke-WithRetry { Rename-Item -LiteralPath $App -NewName 'app.old' -ErrorAction Stop } 'renaming app to app.old')) {
    Write-Result $false 'folder-locked'
    Start-NomadStudio | Out-Null
    exit 1
}
if (-not (Invoke-WithRetry { Rename-Item -LiteralPath $New -NewName 'app' -ErrorAction Stop } 'renaming app.new to app')) {
    Invoke-WithRetry { Rename-Item -LiteralPath $Old -NewName 'app' -ErrorAction Stop } 'putting app.old back' | Out-Null
    Write-Result $false 'folder-locked'
    Start-NomadStudio | Out-Null
    exit 1
}
Remove-Item -LiteralPath (Join-Path $Root 'update-pending.json') -Force -ErrorAction SilentlyContinue
Log 'folders swapped'

# 3. New launcher, then start.
$newLauncher = Join-Path $App 'launcher\NomadStudio.bat'
if (Test-Path -LiteralPath $newLauncher) { Copy-Item -LiteralPath $newLauncher -Destination $Launcher -Force }
$proc = Start-NomadStudio

# 4. Health check.
$ok = $false
$started = Get-Date
$deadline = $started.AddSeconds($StartTimeout)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $Port + '/api/health') -TimeoutSec 3
        if ($health.version -eq $To) { $ok = $true; break }
    } catch { }
    # Python gone for good (crashed on start): no point waiting the full timeout.
    if (((Get-Date) - $started).TotalSeconds -gt 20 -and -not (Test-AppRunning $App)) {
        Log 'the new version is not running'
        break
    }
    Start-Sleep -Seconds 1
}

if ($ok) {
    Log ('update to ' + $To + ' OK')
    Write-Result $true ''
    exit 0
}

# 5. Roll back.
Log ('the new version did not start; rolling back to ' + $From)
Stop-AppProcesses $App $proc
Start-Sleep -Seconds 1
$failed = 'app.failed-' + ($To -replace '[^0-9A-Za-z.-]', '_')
$failedPath = Join-Path $Root $failed
if (Test-Path -LiteralPath $failedPath) { Remove-Item -LiteralPath $failedPath -Recurse -Force -ErrorAction SilentlyContinue }
if (Invoke-WithRetry { Rename-Item -LiteralPath $App -NewName $failed -ErrorAction Stop } 'moving the failed version aside') {
    Invoke-WithRetry { Rename-Item -LiteralPath $Old -NewName 'app' -ErrorAction Stop } 'restoring app.old' | Out-Null
}
$oldLauncher = Join-Path $App 'launcher\NomadStudio.bat'
if (Test-Path -LiteralPath $oldLauncher) { Copy-Item -LiteralPath $oldLauncher -Destination $Launcher -Force }
Write-Result $false 'did-not-start'
Start-NomadStudio | Out-Null
exit 1
