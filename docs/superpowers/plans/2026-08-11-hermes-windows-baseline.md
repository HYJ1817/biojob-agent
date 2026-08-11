# Hermes Windows Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 BioJob Agent 仓库安全建立在固定的 Hermes Agent 上游提交之上，并在 Windows 上证明原始 Agent、Provider、Skills、定时任务和桌面打包链路可重复运行。

**Architecture:** 阶段 0 不实现任何求职功能。先从固定 Hermes 提交创建 `biojob-main` 分支，把已经批准的规格与计划带入该分支；随后增加最小的来源记录、许可证记录和 Windows 基线检查脚本，运行上游测试并生成可审计的基线报告。所有 BioJob 领域代码留到阶段 1。

**Tech Stack:** Git、PowerShell 5.1+、Python（版本遵循 Hermes `pyproject.toml`）、Node.js 22.22+、npm、Hermes Agent、Electron、React、Vitest、Playwright、electron-builder

---

## 范围与完成条件

本计划只覆盖设计文档第 21 节的“阶段 0：上游固定与可运行基线”。完成条件如下：

1. `biojob-main` 基于 Hermes 固定提交 `c0106e50e7ecedb3ce34e785d949725dc4e0e457`。
2. 设计文档和本计划存在于新分支，且 Hermes 上游历史可追溯。
3. `UPSTREAM_HERMES.md` 与 `THIRD_PARTY_NOTICES.md` 明确来源、版本、许可证和同步边界。
4. Windows 工具链检查可重复运行并输出机器可读结果。
5. Hermes Python 测试、桌面端检查和 Windows 打包命令全部通过。
6. Hermes 的模型配置、Skills、后台任务和桌面入口已通过无凭据基线检查。
7. `docs/baseline/hermes-windows-baseline.md` 记录实际环境、命令、结果和安装包名称。
8. 不新增 `biojob/` 业务包，不修改 Provider 和 Agent 循环，不实现岗位或简历功能。

## 预期文件结构

阶段 0 只新增或修改以下文件：

```text
UPSTREAM_HERMES.md                          # 固定上游与同步策略
THIRD_PARTY_NOTICES.md                      # 第三方项目和许可证边界
.gitignore                                  # 忽略本地虚拟环境与基线日志
scripts/baseline/check-prerequisites.ps1    # Windows 工具链检查
scripts/baseline/check-capabilities.ps1     # Hermes 入口与能力表面检查
tests/baseline/check-prerequisites.Tests.ps1# 版本比较和解析自测
docs/baseline/hermes-windows-baseline.md    # 实际通过结果
docs/superpowers/specs/...                  # 已批准设计，仅更新状态
docs/superpowers/plans/...                  # 本计划
```

`artifacts/baseline/` 和 `.venv/` 是本地生成物，不提交。

### Task 1: 从固定 Hermes 提交建立产品分支

**Files:**
- Preserve: `docs/superpowers/specs/2026-08-11-biojob-agent-design.md`
- Preserve: `docs/superpowers/plans/2026-08-11-hermes-windows-baseline.md`
- Modify: Git refs and remotes only

- [ ] **Step 1: 验证规划分支干净并创建恢复标签**

Run:

```powershell
Set-Location 'C:\A\biojob-agent'
git status --short --branch
$dirty = git status --porcelain
if ($dirty) { throw "Planning branch is not clean:`n$dirty" }
if (git tag --list planning-2026-08-11) {
    $tagged = (git rev-parse planning-2026-08-11).Trim()
    $master = (git rev-parse master).Trim()
    if ($tagged -ne $master) { throw 'Existing planning tag does not point to master.' }
} else {
    git tag planning-2026-08-11 master
}
git show --no-patch --oneline planning-2026-08-11
```

Expected: 工作区无未提交文件；标签指向包含设计和阶段 0 计划的 `master` 最新提交。若标签已存在，先运行 `git show --no-patch planning-2026-08-11`，确认它指向同一规划提交后继续，不删除或移动标签。

- [ ] **Step 2: 添加并获取 Hermes 上游固定提交**

Run:

```powershell
$upstreamUrl = 'https://github.com/NousResearch/hermes-agent.git'
$pinnedSha = 'c0106e50e7ecedb3ce34e785d949725dc4e0e457'
if (-not @(git remote | Where-Object { $_ -eq 'upstream' })) {
    git remote add upstream $upstreamUrl
}
$actualUpstreamUrl = (git remote get-url upstream).Trim()
if ($actualUpstreamUrl -ne $upstreamUrl) {
    throw "Unexpected upstream URL: $actualUpstreamUrl"
}
git fetch upstream $pinnedSha
git cat-file -e "$pinnedSha^{commit}"
git show --no-patch --format='%H %cI %s' $pinnedSha
```

Expected: `upstream` URL 完全等于官方仓库；`git cat-file` 退出码为 0；输出提交 SHA 与 `$pinnedSha` 完全一致。

- [ ] **Step 3: 从固定提交创建产品分支并带入规划文档**

Run:

```powershell
$pinnedSha = 'c0106e50e7ecedb3ce34e785d949725dc4e0e457'
git switch -c biojob-main $pinnedSha
git checkout planning-2026-08-11 -- docs/superpowers/specs docs/superpowers/plans
git status --short
git -c user.name='Codex' -c user.email='codex@local' commit -m "docs: add BioJob design and baseline plan"
```

Expected: 当前分支为 `biojob-main`；提交只增加 `docs/superpowers/specs/` 和 `docs/superpowers/plans/`。

- [ ] **Step 4: 验证上游祖先关系和恢复路径**

Run:

```powershell
$pinnedSha = 'c0106e50e7ecedb3ce34e785d949725dc4e0e457'
git merge-base --is-ancestor $pinnedSha HEAD
if ($LASTEXITCODE -ne 0) { throw 'Pinned Hermes commit is not an ancestor of biojob-main.' }
git show --no-patch --oneline planning-2026-08-11
git log --oneline --decorate -3
```

Expected: 祖先检查通过；规划标签仍可访问；最新提交是 BioJob 文档提交，其父历史来自固定 Hermes 提交。

### Task 2: 记录上游来源与许可证边界

**Files:**
- Create: `UPSTREAM_HERMES.md`
- Create: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: 创建上游固定说明**

Create `UPSTREAM_HERMES.md` with exactly:

```markdown
# Hermes Upstream Baseline

- Upstream repository: https://github.com/NousResearch/hermes-agent
- Upstream branch: `main`
- Pinned commit: `c0106e50e7ecedb3ce34e785d949725dc4e0e457`
- Baseline selected: 2026-08-11
- Product branch: `biojob-main`
- Planning recovery tag: `planning-2026-08-11`

## Import method

`biojob-main` is created directly from the pinned Hermes commit. BioJob planning documents are then copied from the local planning tag in a separate commit. This preserves the Hermes ancestry and keeps the pre-import planning history recoverable.

## Local modification boundary

BioJob-specific backend code must live under `biojob/`, desktop code under `apps/desktop/src/features/biojob/`, and domain skills under `skills/biojob-*/`. Changes to the Hermes provider runtime, agent loop, gateway, session model, or permission system require a separate design amendment.

## Upstream sync policy

1. Fetch `upstream/main` without merging.
2. Review upstream Provider and security changes first.
3. Create a temporary sync branch from `biojob-main`.
4. Merge or cherry-pick the selected upstream range on the temporary branch.
5. Run Hermes upstream tests and the BioJob regression suite.
6. Merge the temporary branch only after both suites pass.

Never force-push `biojob-main` to imitate the upstream branch. Never update the pinned baseline record without a reviewed commit.
```

- [ ] **Step 2: 创建第三方许可证记录**

Create `THIRD_PARTY_NOTICES.md` with exactly:

```markdown
# Third-Party Notices

This file records projects that are bundled, adapted, or used as design references by BioJob Agent. Inclusion here does not imply endorsement by the original authors.

| Project | Source | License | Phase 0 status | Intended boundary |
|---|---|---|---|---|
| Hermes Agent | https://github.com/NousResearch/hermes-agent | MIT | Bundled as the pinned product baseline | Preserve copyright and license text; keep the general runtime separable from BioJob domain code |
| OpenCode | https://github.com/anomalyco/opencode | MIT | Reference only | Study server, Provider, event, and permission design; no code copied in Phase 0 |
| FindJobs-Agent | https://github.com/he-yufeng/FindJobs-Agent | MIT | Planned evaluation | Reuse or adapt only clearly identified job-normalization modules in a later phase with attribution |
| resume-tailor-plugin | https://github.com/olegvg/resume-tailor-plugin | MIT | Planned evaluation | Adapt its workflow into BioJob skills in a later phase with attribution |
| OpenMinis | https://github.com/OpenMinis/OpenMinis | GPLv3 | Reference only | Do not copy GPL implementation code into BioJob Agent; use only publicly observable design ideas and protocols |

Hermes names, logos, icons, and other branding are not part of the BioJob product identity. BioJob must use its own name and visual assets before distribution.
```

- [ ] **Step 3: 验证固定 SHA 和许可证关键字**

Run:

```powershell
rg -n 'c0106e50e7ecedb3ce34e785d949725dc4e0e457|biojob-main|planning-2026-08-11' UPSTREAM_HERMES.md
rg -n 'Hermes Agent.*MIT|OpenCode.*MIT|OpenMinis.*GPLv3|Reference only' THIRD_PARTY_NOTICES.md
git diff --check
```

Expected: 两个文件均命中所有关键记录；`git diff --check` 无输出。

- [ ] **Step 4: 提交来源和许可证文档**

Run:

```powershell
git add UPSTREAM_HERMES.md THIRD_PARTY_NOTICES.md
git -c user.name='Codex' -c user.email='codex@local' commit -m "docs: record Hermes baseline and third-party licenses"
```

Expected: 新提交只包含两个文档。

### Task 3: 添加可重复的 Windows 前置条件检查

**Files:**
- Create: `tests/baseline/check-prerequisites.Tests.ps1`
- Create: `scripts/baseline/check-prerequisites.ps1`
- Modify: `.gitignore`

- [ ] **Step 1: 写版本解析失败测试**

Create `tests/baseline/check-prerequisites.Tests.ps1` with:

```powershell
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
```

- [ ] **Step 2: 运行测试并确认因实现缺失而失败**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\baseline\check-prerequisites.Tests.ps1
```

Expected: FAIL because `scripts/baseline/check-prerequisites.ps1` does not exist.

- [ ] **Step 3: 实现前置条件检查脚本**

Create `scripts/baseline/check-prerequisites.ps1` with:

```powershell
[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$OutputPath = (Join-Path $RepositoryRoot 'artifacts\baseline\prerequisites.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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

    $output = (& $Command @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "$Command returned exit code $LASTEXITCODE"
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
```

- [ ] **Step 4: 运行自测和真实环境检查**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\baseline\check-prerequisites.Tests.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\baseline\check-prerequisites.ps1
```

Expected: helper tests print `Prerequisite helper tests: PASS`; real check prints a table and `Prerequisite check: PASS`.

- [ ] **Step 5: 忽略本地产物并提交检查脚本**

Add these exact lines to the repository `.gitignore` if they are not already covered:

```gitignore
/.venv/
/artifacts/baseline/
```

Run:

```powershell
git diff --check
git add .gitignore scripts/baseline/check-prerequisites.ps1 tests/baseline/check-prerequisites.Tests.ps1
git -c user.name='Codex' -c user.email='codex@local' commit -m "test: add Windows baseline prerequisite checks"
```

Expected: commit contains one test, one script, and the two ignore rules.

### Task 4: 安装上游依赖并运行 Hermes 后端测试

**Files:**
- Read: `AGENTS.md`
- Read: `pyproject.toml`
- Read: `package.json`
- Generate locally: `.venv/`
- Generate locally: `node_modules/`
- Generate locally: `artifacts/baseline/`

- [ ] **Step 1: 阅读上游仓库指令并确认计划命令没有冲突**

Run:

```powershell
Get-Content -Raw -Encoding UTF8 -LiteralPath AGENTS.md
Get-Content -Raw -Encoding UTF8 -LiteralPath pyproject.toml
Get-Content -Raw -Encoding UTF8 -LiteralPath package.json
```

Expected: 确认上游要求的 Python、Node、安装和测试命令。若 `AGENTS.md` 明确禁止本计划中的某个命令，停止执行并先修订本计划；不得绕过仓库指令。

- [ ] **Step 2: 使用锁文件安装 Node 依赖**

Run:

```powershell
if (-not (Test-Path -LiteralPath package-lock.json)) {
    throw 'Hermes baseline requires the committed package-lock.json.'
}
npm ci
```

Expected: exit code 0; the command uses the committed lock file and does not modify `package-lock.json`.

- [ ] **Step 3: 创建隔离 Python 环境并安装 Hermes**

Run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\hermes.exe --version
```

Expected: all commands exit 0; final command prints the Hermes version. `.venv/` remains untracked.

- [ ] **Step 4: 运行 Python 上游测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code 0 and no failed tests. Warnings are allowed only if they are already present on the pinned upstream commit and are captured in the final report.

- [ ] **Step 5: 验证安装未污染版本控制**

Run:

```powershell
git status --short
git diff -- package-lock.json
```

Expected: `.venv/`、`node_modules/` 和基线日志不出现；`package-lock.json` 无差异；没有需要提交的依赖安装产物。

### Task 5: 运行桌面测试并构建 Windows 安装包

**Files:**
- Read: `apps/desktop/package.json`
- Generate locally: `apps/desktop/dist/`
- Generate locally: `apps/desktop/release/`
- Generate locally: test output under upstream-defined directories

- [ ] **Step 1: 验证桌面脚本与固定基线一致**

Run:

```powershell
$desktop = Get-Content -Raw -LiteralPath apps\desktop\package.json | ConvertFrom-Json
$requiredScripts = @('typecheck', 'test', 'check', 'build', 'dist:win', 'test:desktop:all')
foreach ($name in $requiredScripts) {
    if (-not $desktop.scripts.$name) { throw "Missing desktop script: $name" }
}
$requiredScripts | ForEach-Object { "$_ = $($desktop.scripts.$_)" }
```

Expected: all six scripts are printed and none is missing.

- [ ] **Step 2: 运行桌面端完整检查**

Run:

```powershell
npm --prefix apps/desktop run check
```

Expected: typecheck、lint、UI tests、platform tests 和 desktop tests 全部退出 0。

- [ ] **Step 3: 构建桌面端**

Run:

```powershell
npm --prefix apps/desktop run build
```

Expected: exit code 0; `apps/desktop/dist/` 存在；构建日志无 TypeScript 或 Vite 错误。

- [ ] **Step 4: 生成 Windows 安装包**

Run:

```powershell
npm --prefix apps/desktop run dist:win
$artifacts = Get-ChildItem -Recurse -File -LiteralPath apps\desktop\release |
    Where-Object { $_.Extension -in @('.exe', '.msi') }
if (-not $artifacts) { throw 'No Windows installer artifacts found.' }
$artifacts | Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize
```

Expected: exit code 0 and at least one `.exe` or `.msi` artifact with non-zero size.

- [ ] **Step 5: 使用上游桌面测试完成无人工点击的启动验证**

Run:

```powershell
npm --prefix apps/desktop run test:desktop:all
```

Expected: exit code 0. This is the automated launch baseline; no provider credential or external model call is required in Phase 0.

### Task 6: 验证 Hermes 能力入口但不调用付费模型

**Files:**
- Create: `scripts/baseline/check-capabilities.ps1`

- [ ] **Step 1: 创建能力表面检查脚本**

Create `scripts/baseline/check-capabilities.ps1` with:

```powershell
[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$OutputPath = (Join-Path $RepositoryRoot 'artifacts\baseline\capabilities.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
```

- [ ] **Step 2: 运行能力检查**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\baseline\check-capabilities.ps1
```

Expected: five CLI checks and `skills-present` all show `Passed = True`; no API Key is requested and no external model call is made.

- [ ] **Step 3: 检查脚本质量并提交**

Run:

```powershell
git diff --check
git add scripts/baseline/check-capabilities.ps1
git -c user.name='Codex' -c user.email='codex@local' commit -m "test: add Hermes capability baseline check"
```

Expected: commit only contains the capability script.

### Task 7: 生成并提交 Windows 基线报告

**Files:**
- Create: `docs/baseline/hermes-windows-baseline.md`

- [ ] **Step 1: 重新运行所有自有基线检查**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\baseline\check-prerequisites.Tests.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\baseline\check-prerequisites.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\baseline\check-capabilities.ps1
```

Expected: all three commands print PASS and exit 0.

- [ ] **Step 2: 验证完整上游检查和安装包仍然存在**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/desktop run check
$installers = @(Get-ChildItem -Recurse -File -LiteralPath apps\desktop\release |
    Where-Object { $_.Extension -in @('.exe', '.msi') })
if ($installers.Count -eq 0) { throw 'Windows installer artifacts are missing.' }
```

Expected: Python and desktop checks exit 0; at least one installer remains.

- [ ] **Step 3: 用实际环境值生成无占位符报告**

Run:

```powershell
$pinnedSha = 'c0106e50e7ecedb3ce34e785d949725dc4e0e457'
git merge-base --is-ancestor $pinnedSha HEAD
if ($LASTEXITCODE -ne 0) { throw 'Pinned SHA is no longer an ancestor.' }

$nodeVersion = (node --version).Trim()
$npmVersion = (npm --version).Trim()
$pythonVersion = (& .\.venv\Scripts\python.exe --version 2>&1 | Out-String).Trim()
$hermesVersion = (& .\.venv\Scripts\hermes.exe --version 2>&1 | Out-String).Trim()
$checkedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss K')
$installerLines = (Get-ChildItem -Recurse -File -LiteralPath apps\desktop\release |
    Where-Object { $_.Extension -in @('.exe', '.msi') } |
    ForEach-Object { "- $($_.FullName.Substring((Get-Location).Path.Length + 1)) ($($_.Length) bytes)" }) -join "`n"

$report = @"
# Hermes Windows Baseline Report

- Result: PASS
- Checked at: $checkedAt
- Repository: C:\A\biojob-agent
- Product branch: biojob-main
- Hermes pinned commit: $pinnedSha
- Node: $nodeVersion
- npm: $npmVersion
- Python: $pythonVersion
- Hermes: $hermesVersion

## Verified commands

| Area | Command | Result |
|---|---|---|
| Prerequisite helpers | powershell.exe -File tests\baseline\check-prerequisites.Tests.ps1 | PASS |
| Windows prerequisites | powershell.exe -File scripts\baseline\check-prerequisites.ps1 | PASS |
| Hermes Python suite | .\.venv\Scripts\python.exe -m pytest -q | PASS |
| Hermes desktop suite | npm --prefix apps/desktop run check | PASS |
| Hermes desktop build | npm --prefix apps/desktop run build | PASS |
| Windows packaging | npm --prefix apps/desktop run dist:win | PASS |
| Packaged desktop tests | npm --prefix apps/desktop run test:desktop:all | PASS |
| Provider, cron, desktop and skill surfaces | powershell.exe -File scripts\baseline\check-capabilities.ps1 | PASS |

## Windows artifacts

$installerLines

## Baseline boundary

No BioJob domain feature is implemented in this baseline. No paid model request, recruitment-site login, auto-application action, or API credential is required for these checks.
"@

New-Item -ItemType Directory -Force -Path docs\baseline | Out-Null
$report | Set-Content -Encoding UTF8 -LiteralPath docs\baseline\hermes-windows-baseline.md
```

Expected: report contains concrete versions, concrete installer paths and only PASS rows; it contains no `TBD`, `TODO`, placeholder brackets or secrets.

- [ ] **Step 4: 执行最终文档和仓库检查**

Run:

```powershell
rg -n 'Result: PASS|Hermes pinned commit|Windows artifacts|No BioJob domain feature' docs/baseline/hermes-windows-baseline.md
$bad = rg -n 'TBD|TODO|FIXME|<actual>|<version>|API[_ -]?KEY|Bearer ' docs/baseline/hermes-windows-baseline.md
if ($LASTEXITCODE -eq 0) { throw "Unexpected placeholder or secret-like text:`n$bad" }
git diff --check
git status --short
```

Expected: required report sections are present; placeholder/secret scan finds nothing; only the baseline report is untracked or modified.

- [ ] **Step 5: 提交基线报告并核对阶段 0 完成条件**

Run:

```powershell
git add docs/baseline/hermes-windows-baseline.md
git -c user.name='Codex' -c user.email='codex@local' commit -m "docs: record passing Hermes Windows baseline"
git status --short --branch
git log --oneline --decorate -6
```

Expected: working tree clean; latest commit records passing baseline; 前序提交分别记录能力检查、前置条件、许可证和规划文档。

## 阶段 0 结束检查

执行人员在结束前逐项确认：

- [ ] `biojob-main` 仍以固定 Hermes SHA 为祖先。
- [ ] `planning-2026-08-11` 标签可恢复导入前文档仓库。
- [ ] 没有修改 Hermes Provider、Agent 循环、Gateway 或权限实现。
- [ ] 没有导入 OpenMinis GPLv3 代码。
- [ ] Python 和桌面上游测试均通过。
- [ ] Windows 安装包存在且桌面测试通过。
- [ ] 模型、Gateway、Cron、Desktop 和 Skills 入口存在。
- [ ] 工作区干净，凭据与生成日志未被提交。
- [ ] 阶段 1 尚未开始；下一份计划必须以本基线的真实目录和测试结果为依据。
