[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('run', 'dev', 'build', 'doctor')]
    [string]$Mode = 'run'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$frontend = Join-Path $root 'frontend'
$python = Join-Path $root '.venv\Scripts\python.exe'
$desktop = Join-Path $frontend 'src-tauri\target\release\app.exe'
$logDir = Join-Path $root 'data\logs'
$stampPath = Join-Path $root 'data\desktop-build.json'
$env:LOCO_BOX_ROOT = $root

function Get-DesktopProcess {
    # Backend health alone does not tell us whether a desktop window exists.
    Get-Process -Name app -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and ($_.Path -eq $desktop -or
            $_.Path -eq (Join-Path $frontend 'src-tauri\target\debug\app.exe'))
    } | Select-Object -First 1
}

function Show-Desktop($process) {
    $process.Refresh()
    if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LocoBoxWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr handle, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
}
'@
        [void][LocoBoxWindow]::ShowWindowAsync($process.MainWindowHandle, 9)
        [void][LocoBoxWindow]::SetForegroundWindow($process.MainWindowHandle)
    }
    Write-Host "Loco Box is already running (PID $($process.Id))."
}

function Get-SourceFingerprint {
    # Only desktop source belongs in this key. Python is loaded on every launch.
    $files = @(
        Get-ChildItem -LiteralPath (Join-Path $frontend 'src') -File -Recurse
        Get-ChildItem -LiteralPath (Join-Path $frontend 'src-tauri\src') -File -Recurse
        Get-ChildItem -LiteralPath (Join-Path $frontend 'src-tauri\capabilities') -File -Recurse
        Get-ChildItem -LiteralPath (Join-Path $frontend 'src-tauri\icons') -File -Recurse
        Get-ChildItem -LiteralPath $frontend -File | Where-Object {
            $_.Name -match '^(package(-lock)?\.json|index\.html|vite\.config\..+|tsconfig.*\.json)$'
        }
        Get-ChildItem -LiteralPath (Join-Path $frontend 'src-tauri') -File | Where-Object {
            $_.Name -in @('Cargo.toml', 'Cargo.lock', 'build.rs', 'tauri.conf.json')
        }
        if (Test-Path -LiteralPath (Join-Path $frontend 'public')) {
            Get-ChildItem -LiteralPath (Join-Path $frontend 'public') -File -Recurse
        }
    )
    $entries = $files | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($frontend.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($entries -join "`n"))
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

function Get-Health {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8790/api/health' -TimeoutSec 2
        if ($health.service -eq 'loco_box' -and $health.ready -eq $true -and $health.protocol -eq 1) {
            return $health
        }
    } catch { }
    return $null
}

function Require-Command([string]$name, [string]$hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Missing $name. $hint"
    }
}

function Invoke-Npm([string[]]$arguments, [string]$logName) {
    Push-Location $frontend
    $savedPreference = $ErrorActionPreference
    try {
        # PowerShell 5 treats native stderr as ErrorRecord, even for progress.
        $ErrorActionPreference = 'Continue'
        & npm.cmd @arguments 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath (Join-Path $logDir $logName)
        $result = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
        Pop-Location
    }
    if ($result -ne 0) { throw "npm failed ($result). See data\logs\$logName" }
}

function Ensure-NodeModules {
    Require-Command 'node.exe' 'Install Node.js LTS to build the desktop.'
    Require-Command 'npm.cmd' 'Install Node.js LTS to build the desktop.'
    Require-Command 'cargo.exe' 'Install Rust and the Visual Studio C++ build tools.'
    $lockHash = (Get-FileHash -LiteralPath (Join-Path $frontend 'package-lock.json') -Algorithm SHA256).Hash
    $installedStamp = Join-Path $frontend 'node_modules\.loco-lock-hash'
    $installedHash = if (Test-Path -LiteralPath $installedStamp) { (Get-Content -LiteralPath $installedStamp -Raw).Trim() } else { '' }
    if ($installedHash -ne $lockHash -or -not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules\.bin\tauri.cmd'))) {
        Invoke-Npm @('ci') 'install.log'
        Set-Content -LiteralPath $installedStamp -Value $lockHash -Encoding ASCII
    }
}

function Write-Diagnostics {
    Write-Host "Workspace: $root"
    Write-Host "Python:    $(Test-Path -LiteralPath $python)"
    Write-Host "Desktop:   $(Test-Path -LiteralPath $desktop)"
    Write-Host "Logs:      $logDir"
    foreach ($name in @('node.exe', 'npm.cmd', 'cargo.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        $location = if ($command) { $command.Source } else { 'not installed (needed only for builds)' }
        Write-Host "${name}: $location"
    }
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Missing .venv. Create the Python environment and install requirements.txt first.'
    } else {
        & $python -c "import importlib.util; modules = ('fastapi', 'uvicorn', 'websockets', 'serial', 'numpy', 'PIL', 'mss', 'tkinter'); missing = [m for m in modules if importlib.util.find_spec(m) is None]; print('Missing Python modules: ' + (', '.join(missing) or 'none')); raise SystemExit(bool(missing))"
        if ($LASTEXITCODE -ne 0) { throw 'Install backend dependencies: .venv\Scripts\python.exe -m pip install -r requirements.txt' }
    }
    $health = Get-Health
    if ($health) { Write-Host "Backend ready (PID $($health.pid))." }
    else { Write-Host 'Backend is stopped or incompatible. This is normal before launch.' }
}

$mutex = $null
$locked = $false
try {
    if ($Mode -eq 'doctor') { Write-Diagnostics; exit 0 }
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Missing .venv. Run: py -3.9 -m venv .venv, then .venv\Scripts\python.exe -m pip install -r requirements.txt'
    }
    [void][IO.Directory]::CreateDirectory($logDir)
    $mutex = [Threading.Mutex]::new($false, 'Local\LocoBoxLauncher')
    try { $locked = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { Write-Host 'Another Loco Box launch/build is in progress.'; exit 0 }

    $existing = Get-DesktopProcess
    if ($existing) {
        if ($Mode -eq 'build') { throw 'Close Loco Box before rebuilding its executable.' }
        Show-Desktop $existing
        exit 0
    }

    if ($Mode -eq 'dev') {
        Ensure-NodeModules
        Write-Host 'Development mode: Vite + Rust watcher. Close this terminal with Ctrl+C to stop.'
        Invoke-Npm @('run', 'desktop:dev') 'dev.log'
        exit 0
    }

    $fingerprint = Get-SourceFingerprint
    $stamp = $null
    if (Test-Path -LiteralPath $stampPath) {
        try {
            $stamp = Get-Content -LiteralPath $stampPath -Raw | ConvertFrom-Json
            if (-not $stamp -or -not $stamp.PSObject.Properties['fingerprint']) { $stamp = $null }
        } catch { $stamp = $null }
    }
    if ($Mode -eq 'build' -or -not (Test-Path -LiteralPath $desktop) -or
        -not $stamp -or $stamp.fingerprint -ne $fingerprint) {
        Ensure-NodeModules
        Write-Host 'Building desktop assets (first build or source changed).'
        Write-Host 'The first Rust release build can take several minutes. Later launches skip compilation.'
        Invoke-Npm @('run', 'desktop:build') 'build.log'
        if (-not (Test-Path -LiteralPath $desktop)) { throw "Build did not produce $desktop" }
        @{ fingerprint = (Get-SourceFingerprint); built_at = [DateTimeOffset]::Now.ToString('o') } |
            ConvertTo-Json | Set-Content -LiteralPath $stampPath -Encoding UTF8
    }
    if ($Mode -eq 'build') { Write-Host "Desktop ready: $desktop"; exit 0 }

    $watch = [Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $desktop -WorkingDirectory $root -PassThru
    Write-Host "Starting Loco Box (PID $($process.Id))..."
    while ($watch.Elapsed.TotalSeconds -lt 45) {
        $process.Refresh()
        if ($process.HasExited) {
            throw "Desktop exited ($($process.ExitCode)). See data\logs\backend.log."
        }
        if ($process.MainWindowHandle -ne [IntPtr]::Zero -and (Get-Health)) {
            Write-Host ('Window and backend ready in {0:N1}s.' -f $watch.Elapsed.TotalSeconds)
            exit 0
        }
        Start-Sleep -Milliseconds 200
    }
    throw 'Startup timed out. Check the connection message in the app and data\logs\backend.log; run start.bat doctor for diagnostics.'
} catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
