$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$Python = Get-Command py -ErrorAction SilentlyContinue
if ($Python) {
    & py -3 scripts/betagent.py install @args
} else {
    & python scripts/betagent.py install @args
}
