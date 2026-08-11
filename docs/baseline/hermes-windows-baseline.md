# Hermes Windows Baseline Report

- Result: OPERATIONAL WITH UPSTREAM TEST EXCEPTIONS
- Checked at: 2026-08-11 19:37:13 +08:00
- Repository: `C:\A\biojob-agent`
- Product branch: `biojob-main`
- Baseline verification commit: `5b1c0a710ca1d74261cf1f5f0b2bbfda21f40c17`
- Hermes pinned commit: `c0106e50e7ecedb3ce34e785d949725dc4e0e457`
- Node: `v24.14.0`
- npm: `11.9.0`
- Python: `3.11.15`
- Hermes: `Hermes Agent v0.20.0 (2026.8.3)`

## Verified commands

| Area | Command | Result |
|---|---|---|
| Prerequisite helpers | `powershell.exe -File tests\baseline\check-prerequisites.Tests.ps1` | PASS |
| Windows prerequisites | `powershell.exe -File scripts\baseline\check-prerequisites.ps1` | PASS |
| Targeted Windows compatibility regressions | `scripts/run_tests.sh` against the modified ACP, LSP, state, image, proxy, and path files | PASS — 90 tests |
| Hermes Python suite | `scripts/run_tests.sh -j 12 -q` | NOT CLEAN — stopped at 34.1% after 9,669 passes and 85 failures |
| Desktop typecheck and lint | first stage of `npm --prefix apps/desktop run check` | PASS — 0 lint errors, 88 upstream warnings |
| Desktop UI suite | `vitest run --project ui` | PASS — 3,680 tests in 413 files |
| Electron unit suite | `vitest run --project electron` | NOT CLEAN — 982 passed, 20 failed, 2 skipped; 2 suites could not load |
| Hermes desktop build | `npm --prefix apps/desktop run build` | PASS |
| Windows packaging | `npm --prefix apps/desktop run dist:win` | PASS |
| Packaged desktop baseline | `npm --prefix apps/desktop run test:desktop:all` | PASS |
| Provider, cron, desktop, and skill surfaces | `powershell.exe -File scripts\baseline\check-capabilities.ps1` | PASS — 79 skills found |

## Windows artifacts

- `apps/desktop/release/Hermes-0.17.0-win-x64.exe` — 118,255,873 bytes — SHA-256 `BD79046F113DB5603B90C6ED8A8CF31DE4A060B0AD124F7755520404DADF83D6`
- `apps/desktop/release/Hermes-0.17.0-win-x64.msi` — 132,704,374 bytes — SHA-256 `5D2FA41183B8B019CD04A4BDEEC9319060AE1C210E61EB0123E1B4D4CD4DE2D6`
- Unpacked application: `apps/desktop/release/win-unpacked/Hermes.exe`

These private local artifacts are unsigned development builds. Windows can show an unknown-publisher warning when they are installed.

## Upstream test exceptions

The pinned Hermes tree builds and packages successfully on native Windows, but its complete test inventory is not yet partitioned cleanly by host operating system. The observed failures cluster around:

- POSIX-only APIs and assumptions, including `termios`, Unix permission bits, `/etc`, Bash scripts, Unix-domain SSH control sockets, and WSL path simulation;
- tests that override `HOME` without also overriding Windows `USERPROFILE`;
- symlink tests on a Windows account without Developer Mode or symlink privilege;
- assertions that compare `/`-separated paths or unescaped native paths against Windows paths and file URLs;
- Windows cleanup races where a child process or SQLite/file handle is still open.

These failures are recorded as upstream baseline debt. They are not represented as passing, and the stricter Phase 0 criterion requiring every upstream test to be green remains unmet. Product work should keep the targeted Windows regression set and the successful build/package checks as required gates until the upstream suite is fully classified.

## Baseline boundary

No BioJob domain feature is implemented in this baseline. No paid model request, recruitment-site login, auto-application action, or API credential was required. The next implementation phase may add BioJob code only inside the domain boundaries documented in `UPSTREAM_HERMES.md`.
