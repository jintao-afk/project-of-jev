$ErrorActionPreference = 'Stop'
$taskStatePath = Join-Path $PSScriptRoot 'server.local.json'
if (-not (Test-Path -LiteralPath $taskStatePath)) { Write-Output '没有本项目的服务记录。'; return }
$taskState = Get-Content -LiteralPath $taskStatePath -Raw | ConvertFrom-Json
$taskServer = Get-Process -Id $taskState.pid -ErrorAction SilentlyContinue
if (-not $taskServer) { Write-Output '本项目服务已停止。'; return }
if ($taskServer.StartTime.ToUniversalTime().Ticks -ne ([datetime]$taskState.start_time_utc).ToUniversalTime().Ticks) {
    throw '进程启动时间与本项目记录不一致，未停止该进程。'
}
# Windows venv python.exe may be a launcher: the actual server is its base-Python
# child. Traverse only verified Python descendants executing this app or spawn.
$taskPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv/Scripts/python.exe'))
$taskHomeLine = Get-Content (Join-Path $PSScriptRoot '.venv/pyvenv.cfg') | Where-Object { $_ -match '^home\s*=' } | Select-Object -First 1
$taskBasePython = [IO.Path]::GetFullPath((Join-Path ($taskHomeLine -replace '^home\s*=\s*', '') 'python.exe'))
$taskAppPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'app.py'))
$taskQueue = [Collections.Generic.Queue[int]]::new()
$taskQueue.Enqueue($taskServer.Id)
$taskDescendants = [Collections.Generic.List[object]]::new()
while ($taskQueue.Count -gt 0) {
    $taskParentId = $taskQueue.Dequeue()
    $taskChildren = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId = " + $taskParentId))
    foreach ($taskChild in $taskChildren) {
        if (-not $taskChild.ExecutablePath) { continue }
        $taskChildExe = [IO.Path]::GetFullPath($taskChild.ExecutablePath)
        $taskIsApp = $taskChild.CommandLine -match [regex]::Escape($taskAppPath) -and $taskChild.CommandLine -match '\sserve\s'
        $taskIsWorker = $taskChild.CommandLine -match 'multiprocessing|spawn_main|resource_tracker'
        if ($taskChildExe -in @($taskPython,$taskBasePython) -and ($taskIsApp -or $taskIsWorker)) {
            $taskDescendants.Add($taskChild)
            $taskQueue.Enqueue([int]$taskChild.ProcessId)
        }
    }
}
for ($taskIndex = $taskDescendants.Count - 1; $taskIndex -ge 0; $taskIndex--) {
    $taskChild = $taskDescendants[$taskIndex]
    $taskChildProcess = Get-Process -Id $taskChild.ProcessId -ErrorAction SilentlyContinue
    if ($taskChildProcess -and $taskChildProcess.Path -eq $taskChild.ExecutablePath -and [Math]::Abs(($taskChildProcess.StartTime.ToUniversalTime() - $taskChild.CreationDate.ToUniversalTime()).TotalMilliseconds) -lt 1) {
        Stop-Process -Id $taskChildProcess.Id -Force -Confirm:$false
        if (-not $taskChildProcess.WaitForExit(10000)) { throw 'Verified project Python child did not stop.' }
    }
}
if (-not $taskServer.HasExited) {
Stop-Process -Id $taskServer.Id -Force -Confirm:$false
if (-not $taskServer.WaitForExit(10000)) { throw '服务未在规定时间内退出，请保留原目录。' }
}
Write-Output '本项目服务已停止。'
