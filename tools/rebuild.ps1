<#
.SYNOPSIS
  Test, force-close the running app, rebuild dist\EcoFlowScheduler.exe and launch it again.
.PARAMETER NoTests   skip the test run
.PARAMETER NoLaunch  do not start the new exe afterwards
.PARAMETER Minimized start the new exe minimized to the tray (--minimized)
.PARAMETER DryRun    only print what would happen
#>
param([switch]$NoTests, [switch]$NoLaunch, [switch]$Minimized, [switch]$DryRun)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$exe = Join-Path $root "dist\EcoFlowScheduler.exe"
function Step($text) { Write-Host "==> $text" -ForegroundColor Green }
function Run($text, [scriptblock]$action) { Step $text; if (-not $DryRun) { & $action } }

if (-not $NoTests) {
    Run "Running tests (a failure stops here, the running app is left alone)" {
        python -m pytest -q tests
        if ($LASTEXITCODE -ne 0) { throw "Tests failed - not rebuilding." }
    }
}

Run "Force-closing running copies of the app" {
    $procs = Get-Process EcoFlowScheduler -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force
        $procs | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue
        Write-Host "    stopped $(@($procs).Count) process(es)"
    } else { Write-Host "    not running" }
}

Run "Building dist\EcoFlowScheduler.exe (PyInstaller, about 40 s)" {
    $log = Join-Path $env:TEMP "ecoflow-build.log"
    # PyInstaller logs to stderr; Windows PowerShell 5.1 would turn that into a terminating error under "Stop"
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name EcoFlowScheduler --icon assets/app.ico `
        --collect-submodules keyring.backends main.py *> $log
    $code = $LASTEXITCODE; $ErrorActionPreference = $prev
    if ($code -ne 0) { Get-Content $log -Tail 25; throw "Build failed (full log: $log)" }
    Remove-Item -Recurse -Force (Join-Path $root "build") -ErrorAction SilentlyContinue
    $f = Get-Item $exe
    Write-Host ("    built {0:N1} MB at {1:HH:mm:ss}" -f ($f.Length / 1MB), $f.LastWriteTime)
}

if (-not $NoLaunch) {
    Run "Launching the new build" {
        if ($Minimized) { Start-Process $exe -ArgumentList "--minimized" } else { Start-Process $exe }
    }
}
Step "Done"
