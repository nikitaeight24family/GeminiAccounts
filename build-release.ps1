param([string]$Python='python')
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$build = Join-Path $PSScriptRoot 'build'
$payload = Join-Path $build 'payload'
$icon = Join-Path $PSScriptRoot 'app.ico'
$catalog = Join-Path $PSScriptRoot 'assets/cliproxy-models.json'
New-Item -ItemType Directory -Force -Path $payload | Out-Null
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {throw 'Dependency installation failed'}
& $Python -m PyInstaller --noconfirm --onefile --windowed --name GeminiAccounts --icon $icon --add-data ($icon+';.') --add-data ($catalog+';assets') --collect-all customtkinter --collect-all tzdata --distpath $payload --workpath (Join-Path $build 'app') --specpath $build app.py
if ($LASTEXITCODE -ne 0) {throw 'Manager build failed'}
& $Python -m PyInstaller --noconfirm --onefile --windowed --name GeminiQuotaQueue --collect-all tzdata --distpath $payload --workpath (Join-Path $build 'queue') --specpath $build quota_queue.py
if ($LASTEXITCODE -ne 0) {throw 'Queue build failed'}
& $Python -m PyInstaller --noconfirm --onefile --name GeminiAccounts-CLI --add-data ($catalog+';assets') --collect-all tzdata --distpath dist --workpath (Join-Path $build 'console') --specpath $build console.py
if ($LASTEXITCODE -ne 0) {throw 'Terminal build failed'}
Compress-Archive -LiteralPath 'dist/GeminiAccounts-CLI.exe','CLI.md','LICENSE','THIRD_PARTY.md' -DestinationPath 'dist/GeminiAccounts-CLI-windows-x64.zip' -Force
$archive=Join-Path $build 'CLIProxyAPI_8.0.16_windows_amd64.zip'
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest 'https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.16/CLIProxyAPI_8.0.16_windows_amd64.zip' -OutFile $archive
}
$expected='e0d999703c9af70067b15bf50e6521e76392da604d1543541361e6891c676c43'
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {throw 'CLIProxyAPI checksum mismatch'}
$upstream = Join-Path $build 'upstream'
Expand-Archive -LiteralPath $archive -DestinationPath $upstream -Force
Copy-Item -LiteralPath (Join-Path $upstream 'cli-proxy-api.exe') -Destination $payload -Force
Copy-Item -LiteralPath (Join-Path $upstream 'LICENSE') -Destination (Join-Path $payload 'CLIProxyAPI-LICENSE.txt') -Force
Copy-Item -LiteralPath 'start-proxy.ps1' -Destination $payload -Force
Copy-Item -LiteralPath $catalog -Destination $payload -Force
& $Python -m PyInstaller --noconfirm --onefile --windowed --name GeminiAccounts-Setup --icon $icon --add-data ($payload+';payload') --distpath dist --workpath (Join-Path $build 'installer') --specpath $build installer.py
if ($LASTEXITCODE -ne 0) {throw 'Installer build failed'}
$sum=(Get-FileHash 'dist/GeminiAccounts-Setup.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dist/SHA256SUMS.txt'),$sum+'  GeminiAccounts-Setup.exe'+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
Write-Output 'Release files are in dist/'
