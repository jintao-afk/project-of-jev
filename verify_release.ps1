$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Project service start failed.' }
& (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -u (Join-Path $PSScriptRoot 'verify_release.py') --phase prepare
if ($LASTEXITCODE -ne 0) { throw 'R1 functional preparation failed; preserve the saved record.' }
$taskOldServer = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'server.local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'stop.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Registered project service did not stop.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Project service restart failed.' }
$taskNewServer = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'server.local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
& (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -u (Join-Path $PSScriptRoot 'verify_release.py') --phase continue --previous-server-pid $taskOldServer.pid --current-server-pid $taskNewServer.pid
if ($LASTEXITCODE -ne 0) { throw 'R1 continuation verification failed; preserve the saved record.' }
Write-Output 'PASS: R1 functional delivery, artifact integrity and continuation across service restart.'
