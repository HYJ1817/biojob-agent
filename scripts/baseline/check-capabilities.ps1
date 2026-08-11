[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $RepositoryRoot) {
    $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $RepositoryRoot 'artifacts\baseline\capabilities.json'
}

$hermes = Join-Path $RepositoryRoot '.venv\Scripts\hermes.exe'
if (-not (Test-Path -LiteralPath $hermes)) {
    throw "Hermes executable not found: $hermes"
}

$checks = @(
    [pscustomobject]@{ Name = 'root-help'; Arguments = @('--help'); RequiredText = @('model', 'gateway', 'cron', 'desktop') },
    [pscustomobject]@{ Name = 'model-help'; Arguments = @('model', '--help'); RequiredText = @('model') },
    [pscustomobject]@{ Name = 'gateway-help'; Arguments = @('gateway', '--help'); RequiredText = @('gateway') },
    [pscustomobject]@{ Name = 'cron-help'; Arguments = @('cron', '--help'); RequiredText = @('cron') },
    [pscustomobject]@{ Name = 'desktop-help'; Arguments = @('desktop', '--help'); RequiredText = @('desktop') }
)

$results = foreach ($check in $checks) {
    $output = (& $hermes @($check.Arguments) 2>&1 | Out-String).Trim()
    $exitCode = $LASTEXITCODE
    $missing = @($check.RequiredText | Where-Object { $output -notmatch [regex]::Escape($_) })
    [pscustomobject]@{
        Name = $check.Name
        ExitCode = $exitCode
        MissingText = $missing
        Passed = ($exitCode -eq 0 -and $missing.Count -eq 0)
    }
}

$skillFiles = @(Get-ChildItem -Recurse -File -Filter SKILL.md -Path (Join-Path $RepositoryRoot 'skills') -ErrorAction SilentlyContinue)
$results += [pscustomobject]@{
    Name = 'skills-present'
    ExitCode = 0
    MissingText = @()
    Passed = ($skillFiles.Count -gt 0)
}

$result = [pscustomobject]@{
    CheckedAt = (Get-Date).ToString('o')
    Passed = -not ($results.Passed -contains $false)
    SkillFileCount = $skillFiles.Count
    Checks = $results
}

$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -LiteralPath $OutputPath
$results | Format-Table -AutoSize

if (-not $result.Passed) {
    throw "Capability check failed. See $OutputPath"
}

Write-Host "Capability check: PASS; skills found: $($skillFiles.Count)"
