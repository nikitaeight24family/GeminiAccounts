$ErrorActionPreference = 'Stop'
$proxyExe = Join-Path $PSScriptRoot 'cli-proxy-api.exe'
$queueExe = Join-Path $PSScriptRoot 'GeminiQuotaQueue.exe'
foreach ($exe in @($proxyExe, $queueExe)) {
    $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe }
    if ($running) { continue }
    if ($exe -eq $proxyExe) {
        Start-Process -FilePath $exe -ArgumentList @('-config', ('"' + (Join-Path $PSScriptRoot 'config.yaml') + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'server.log') -RedirectStandardError (Join-Path $PSScriptRoot 'server-error.log')
    } else {
        Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    }
}
