[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $RepositoryRoot 'artifacts\baseline\prerequisites.json'
}

function ConvertTo-NormalizedVersion {
    param([Parameter(Mandatory)][string]$Value)

    $match = [regex]::Match($Value, '\d+(?:\.\d+){1,3}')
    if (-not $match.Success) {
        throw "No semantic version found in: $Value"
    }
    return [version]$match.Value
}

function Test-VersionAtLeast {
    param(
        [Parameter(Mandatory)][string]$Actual,
        [Parameter(Mandatory)][string]$Minimum
    )

    return ((ConvertTo-NormalizedVersion -Value $Actual) -ge (ConvertTo-NormalizedVersion -Value $Minimum))
}

function Get-ToolVersion {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @('--version')
    )

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $resolved) {
        throw "Required command not found: $Command"
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = (& $Command @Arguments 2>$null | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "$Command returned exit code $exitCode"
    }
    return $output
}

function Invoke-PrerequisiteCheck {
    $desktopPackagePath = Join-Path $RepositoryRoot 'apps\desktop\package.json'
    $pyprojectPath = Join-Path $RepositoryRoot 'pyproject.toml'
    if (-not (Test-Path -LiteralPath $desktopPackagePath)) {
        throw "Missing Hermes desktop package: $desktopPackagePath"
    }
    if (-not (Test-Path -LiteralPath $pyprojectPath)) {
        throw "Missing Hermes Python project: $pyprojectPath"
    }

    $desktopPackage = Get-Content -Raw -LiteralPath $desktopPackagePath | ConvertFrom-Json
    $nodeMinimumMatch = [regex]::Match([string]$desktopPackage.engines.node, '\d+(?:\.\d+){1,2}')
    if (-not $nodeMinimumMatch.Success) {
        throw 'Unable to read the minimum Node version from apps/desktop/package.json.'
    }

    $pyproject = Get-Content -Raw -LiteralPath $pyprojectPath
    $pythonMinimumMatch = [regex]::Match($pyproject, 'requires-python\s*=\s*"[^0-9]*(\d+(?:\.\d+){1,2})')
    if (-not $pythonMinimumMatch.Success) {
        throw 'Unable to read requires-python from pyproject.toml.'
    }

    $nodeRaw = Get-ToolVersion -Command 'node'
    $npmRaw = Get-ToolVersion -Command 'npm'
    $gitRaw = Get-ToolVersion -Command 'git'
    $pythonRaw = Get-ToolVersion -Command 'python'

    $driveName = [IO.Path]::GetPathRoot($RepositoryRoot).TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName
    $freeGiB = [math]::Round($drive.Free / 1GB, 2)

    $checks = @(
        [pscustomobject]@{ Name = 'node'; Actual = $nodeRaw; Minimum = $nodeMinimumMatch.Value; Passed = (Test-VersionAtLeast -Actual $nodeRaw -Minimum $nodeMinimumMatch.Value) },
        [pscustomobject]@{ Name = 'npm'; Actual = $npmRaw; Minimum = 'present'; Passed = $true },
        [pscustomobject]@{ Name = 'git'; Actual = $gitRaw; Minimum = 'present'; Passed = $true },
        [pscustomobject]@{ Name = 'python'; Actual = $pythonRaw; Minimum = $pythonMinimumMatch.Groups[1].Value; Passed = (Test-VersionAtLeast -Actual $pythonRaw -Minimum $pythonMinimumMatch.Groups[1].Value) },
        [pscustomobject]@{ Name = 'free-disk-gib'; Actual = $freeGiB; Minimum = 8; Passed = ($freeGiB -ge 8) }
    )

    $result = [pscustomobject]@{
        CheckedAt = (Get-Date).ToString('o')
        RepositoryRoot = $RepositoryRoot
        Passed = -not ($checks.Passed -contains $false)
        Checks = $checks
    }

    $outputDirectory = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath $OutputPath
    $checks | Format-Table -AutoSize

    if (-not $result.Passed) {
        throw "Prerequisite check failed. See $OutputPath"
    }

    Write-Host "Prerequisite check: PASS ($OutputPath)"
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-PrerequisiteCheck
}
