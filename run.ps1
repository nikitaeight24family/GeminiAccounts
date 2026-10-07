param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -c "import sys; sys.exit(sys.version_info < (3,12))"
    if ($LASTEXITCODE -ne 0) {throw 'Python 3.12 or newer is required. You can also use the standalone release.'}
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {throw 'Could not create the Python environment.'}
}
$stamp=(Get-FileHash -LiteralPath 'requirements-cli.txt').Hash
$stampPath=Join-Path $PSScriptRoot '.venv\requirements.stamp'
if (-not (Test-Path -LiteralPath $stampPath) -or (Get-Content -LiteralPath $stampPath -Raw) -ne $stamp) {
    & $python -m pip install -r requirements-cli.txt
    if ($LASTEXITCODE -ne 0) {throw 'Dependency installation failed.'}
    [IO.File]::WriteAllText($stampPath,$stamp)
}
& $python console.py @Arguments
exit $LASTEXITCODE
