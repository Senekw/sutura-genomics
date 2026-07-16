<#
Make `sutura` and `sutura-app` runnable from ANY terminal with no venv
activation. Creates .cmd launchers on your PATH that wrap the venv's console
entry points (which already embed the venv's Python, so they run standalone).

Idempotent — safe to re-run. From the repo root:

    powershell -ExecutionPolicy Bypass -File cli\scripts\install-windows.ps1

Then open a NEW terminal and type:  sutura
#>
param(
  # a per-user bin directory; defaults to one that's usually already on PATH
  [string]$Bin = (Join-Path $env:USERPROFILE ".local\bin")
)
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venv = Join-Path $root ".venv\Scripts"

foreach ($exe in @("sutura.exe", "sutura-app.exe")) {
  if (-not (Test-Path (Join-Path $venv $exe))) {
    throw "Missing $venv\$exe. Install the packages first:`n" +
          "  $venv\python.exe -m pip install -e `"$root\cli`" -e `"$root\app`""
  }
}

New-Item -ItemType Directory -Force $Bin | Out-Null
Set-Content -Path (Join-Path $Bin "sutura.cmd") -Encoding ascii `
  -Value "@echo off`r`n`"$venv\sutura.exe`" %*"
Set-Content -Path (Join-Path $Bin "sutura-app.cmd") -Encoding ascii `
  -Value "@echo off`r`n`"$venv\sutura-app.exe`" %*"

# ensure $Bin is on the persistent (registry) user PATH so new shells see it
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $Bin) {
  [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $Bin), 'User')
  Write-Host "Added $Bin to your user PATH."
} else {
  Write-Host "$Bin is already on your PATH."
}

Write-Host "Installed launchers -> $venv"
Write-Host "sutura     : $Bin\sutura.cmd"
Write-Host "sutura-app : $Bin\sutura-app.cmd"
Write-Host "`nOpen a NEW terminal and run:  sutura"
