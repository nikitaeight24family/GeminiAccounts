# Read-only diagnostics for an installed Gemini Accounts gateway. No inference calls.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$roots = @((Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local'), $env:LOCALAPPDATA)
$runtimeRoot = $roots | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'GeminiAccounts\management-key.dpapi') } | Select-Object -First 1
if (-not $runtimeRoot) { throw 'Gemini Accounts installation not found.' }
$protectedKey = [IO.File]::ReadAllBytes((Join-Path $runtimeRoot 'GeminiAccounts\management-key.dpapi'))
$managementKey = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($protectedKey,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
$headers = @{Authorization=('Bearer '+$managementKey)}
$report = [ordered]@{collected_utc=[DateTime]::UtcNow.ToString('o'); accounts=@(); model_aliases=$null; jobs=$null; native_sha256=$null; client_models=@(); errors=@()}
try {
    $files = Invoke-RestMethod -Uri 'http://127.0.0.1:8318/v0/management/auth-files' -Headers $headers -TimeoutSec 10
    $number = 0
    foreach ($account in $files.files) {
        $number++
        $report.accounts += [ordered]@{account=('account-'+$number);provider=$account.provider;disabled=$account.disabled;status=$account.status;status_message=$account.status_message;cooldowns=$account.cooldowns}
    }
} catch { $report.errors += 'Account state unavailable: '+$_.Exception.GetType().Name }
try { $report.model_aliases = Invoke-RestMethod -Uri 'http://127.0.0.1:8318/v0/management/oauth-model-alias' -Headers $headers -TimeoutSec 10 } catch { $report.errors += 'Model mappings unavailable' }
try { $report.jobs = Invoke-RestMethod -Uri 'http://127.0.0.1:8317/v0/management/quota-wait' -Headers $headers -TimeoutSec 10 } catch { $report.errors += 'Gateway state unavailable' }
$nativePath = Join-Path $runtimeRoot 'ClaudeGemini\cli-proxy-api.exe'
if (Test-Path -LiteralPath $nativePath) { $report.native_sha256=(Get-FileHash -LiteralPath $nativePath -Algorithm SHA256).Hash }
$library = Join-Path $env:LOCALAPPDATA 'Claude-3p\configLibrary'
try {
    $meta = Get-Content -LiteralPath (Join-Path $library '_meta.json') -Raw | ConvertFrom-Json
    if ($meta.appliedId -match '^[a-fA-F0-9-]{36}$') {
        $preset=Get-Content -LiteralPath (Join-Path $library ($meta.appliedId+'.json')) -Raw | ConvertFrom-Json
        $report.client_models=@($preset.inferenceModels | Select-Object name,labelOverride,supports1m,prefer1m,anthropicFamilyTier)
    }
} catch { $report.errors += 'Claude model preset unavailable' }
$text=$report | ConvertTo-Json -Depth 30
$text=$text.Replace($managementKey,'[redacted]')
$text=[regex]::Replace($text,'[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}','[account-email]')
$text=[regex]::Replace($text,'https?://[^\s"\\]+','[redacted-url]')
$text=[regex]::Replace($text,'(?i)Bearer\s+[A-Za-z0-9._~+/-]+','Bearer [redacted]')
$destination=Join-Path ([Environment]::GetFolderPath('Desktop')) ('GeminiAccounts-provider-errors-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.json')
[IO.File]::WriteAllText($destination,$text,[Text.UTF8Encoding]::new($false))
Write-Output ('Saved: '+$destination)
