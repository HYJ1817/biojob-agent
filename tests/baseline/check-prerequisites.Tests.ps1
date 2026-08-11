$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\..\scripts\baseline\check-prerequisites.ps1'
. $scriptPath

if (-not (Test-VersionAtLeast -Actual 'v24.14.0' -Minimum '22.22.0')) {
    throw 'Expected Node 24.14.0 to satisfy Node 22.22.0.'
}

if (Test-VersionAtLeast -Actual 'v22.21.9' -Minimum '22.22.0') {
    throw 'Expected Node 22.21.9 to fail Node 22.22.0.'
}

$pythonVersion = ConvertTo-NormalizedVersion -Value 'Python 3.13.5'
if ($pythonVersion.ToString() -ne '3.13.5') {
    throw "Unexpected Python version parse: $pythonVersion"
}

$npmVersion = ConvertTo-NormalizedVersion -Value '11.9.0'
if ($npmVersion.ToString() -ne '11.9.0') {
    throw "Unexpected npm version parse: $npmVersion"
}

Write-Host 'Prerequisite helper tests: PASS'
