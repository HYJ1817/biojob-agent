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

## Phase 1 data core

- Checked at: 2026-08-11
- Product branch: `biojob-main`
- Verified product commit: `285421a6db77a6d52b2da64b264156db6c4c0ec0`

| Area | Exact command | Result |
|---|---|---|
| Complete BioJob suite | `& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 4 tests/biojob -q` | PASS (exit 0) — 4 files, 200 passed, 0 failed |
| Nine retained Windows regressions | `& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 4 tests/acp/test_ping_suppression.py tests/acp_adapter/test_acp_images.py tests/agent/lsp/test_install_and_lint_fixes.py tests/agent/lsp/test_workspace.py tests/agent/test_codex_app_server_persist.py tests/agent/test_compression_review_76354.py tests/agent/test_file_safety_sandbox_mirror.py tests/agent/test_image_routing.py tests/agent/test_proxy_and_url_validation.py -q` | PASS on the final rerun after the locked `dev+acp` sync (exit 0) — 9 files, 90 passed, 0 failed, 1 skipped |
| Hermes desktop build | `npm --prefix apps/desktop run build` | PASS (exit 0) — 14,970 modules transformed; renderer and Electron bundles produced; npm/Vite emitted non-fatal configuration/deprecation warnings |
| Windows capabilities | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/baseline/check-capabilities.ps1` | PASS (exit 0) — 6 of 6 checks passed; 79 skills found |
| Locked default environment sync | `uv sync --locked` | PASS (exit 0) — 249 packages resolved; local `hermes-agent` built; 91 packages removed and 1 installed to match the default lock selection; `uv.lock` unchanged |
| Installed-package import | `& .\.venv\Scripts\python.exe -c "import biojob; print(biojob.__file__)"` | PASS after the final locked `dev+acp` sync (exit 0) — `C:\A\biojob-agent\biojob\__init__.py` |
| Restore reproducible locked verification environment | `uv sync --locked --extra dev --extra acp` | PASS (exit 0) — 249 packages resolved; 1 package installed (`agent-client-protocol==0.9.0`) after the earlier dev-only restore had installed 17 packages; `uv.lock` unchanged |
| BioJob API plus real dashboard auth | `& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_api.py tests/hermes_cli/test_dashboard_auth_middleware.py -q` | PASS on the final rerun after the locked `dev+acp` sync (exit 0) — 2 files, 69 passed, 0 failed |
| Independent schema credential-column audit | PowerShell here-string encoded to Base64, then executed with `& .\.venv\Scripts\python.exe -c "import base64; exec(base64.b64decode('$encodedBiojobSchemaCheck'))"` | PASS on the corrected run (exit 0) — 16 tables inspected, 0 credential-shaped columns, explicit connection close, temporary directory removed |

The exact readable source and PowerShell wrapper used for the successful schema audit were:

```powershell
$biojobSchemaCheck = @'
import os
import tempfile
from pathlib import Path

from biojob.database import BioJobDatabase

needles = ("api_key", "token", "cookie", "password", "secret")
with tempfile.TemporaryDirectory() as temp_dir:
    temp_path = Path(temp_dir)
    os.environ["HERMES_HOME"] = temp_dir
    db = BioJobDatabase(temp_path / "biojob" / "biojob.db")
    db.initialize()
    conn = db.connect()
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
        )]
        flagged = []
        for table in tables:
            for row in conn.execute(
                "SELECT name FROM pragma_table_info(?)", (table,)
            ):
                column = row[0]
                if any(needle in column.lower() for needle in needles):
                    flagged.append(f"{table}.{column}")
        print(f"TABLE_COUNT={len(tables)}")
        print("TABLES=" + ",".join(tables))
        print("FLAGGED=" + (",".join(flagged) if flagged else "none"))
        if flagged:
            raise SystemExit(1)
    finally:
        conn.close()
    print("SCHEMA_CREDENTIAL_COLUMNS=PASS")
if temp_path.exists():
    raise SystemExit("temporary directory was not cleaned")
print("TEMP_DIRECTORY_CLEANUP=PASS")
'@
$encodedBiojobSchemaCheck = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($biojobSchemaCheck)
)
& .\.venv\Scripts\python.exe -c "import base64; exec(base64.b64decode('$encodedBiojobSchemaCheck'))"
```

Two preliminary schema-audit invocations failed operationally and are not hidden: the first exited 1 with a `SyntaxError` after PowerShell stripped quotes from a directly passed here-string; the second completed the 16-table scan with no flagged columns but exited 1 because the audit used the SQLite transaction context manager without explicitly closing the connection, so Windows could not remove the temporary database. The corrected invocation above explicitly closed the connection and passed cleanup. The failed attempt's dedicated temporary directory was verified to be under the operating-system temp root and removed after the process released its handle.

The first API-plus-auth invocation after the required default `uv sync --locked` also exited 1 before test collection because that default sync removed the optional pytest packages. An intermediate `uv sync --locked --extra dev` installed 17 packages and restored pytest, but it omitted the `acp` extra; a quality recheck in that intermediate environment therefore had two ACP files fail during collection while the remaining Windows tests reported 81 passed and 1 skipped. That dev-only environment was not accepted as reproducible.

The final environment was restored with `uv sync --locked --extra dev --extra acp`, which resolved 249 packages and installed the one still-missing package, `agent-client-protocol==0.9.0`, without changing `uv.lock`. In that final environment, the exact nine-file Windows command was rerun successfully with 90 passed, 1 skipped, and 0 failed; the API-plus-auth command was rerun successfully with 69 passed and 0 failed; and the installed-package `biojob` import was reconfirmed. The initial API collection failure and the intermediate ACP collection failures were environment-selection failures, not product test failures.

### Delivered boundary

Migration 1 creates 16 tables: `schema_migrations` plus 15 BioJob domain tables. The data core stores profile facts with explicit confirmation and visibility rules, and only confirmed facts are exposed to matching or resume consumers. Jobs retain three independently clickable URLs for the detail page, application page, and employer careers page. Applications use an auditable forward-only state machine with append-only application events and mutation audit records; no transition infers that an application was submitted.

The local router exposes 10 `/api/biojob` endpoints for dashboard counts, profile facts, jobs, preparation, and events. When mounted on the real Hermes dashboard, those routes remain behind the existing dashboard authentication middleware. The schema audit confirmed that no column name contains `api_key`, `token`, `cookie`, `password`, or `secret`.

Phase 1 does not include job fetching, job matching, resume generation, Excel output, a BioJob GUI, automatic application submission, or credential storage.

### Retained upstream exceptions

The focused Phase 1 gates do not supersede or repair the existing upstream baseline exceptions. The complete Hermes Python suite remains **NOT CLEAN** at the recorded baseline (stopped at 34.1% after 9,669 passes and 85 failures), and the Electron unit suite remains **NOT CLEAN** at the recorded baseline (982 passed, 20 failed, 2 skipped, with 2 suites unable to load). Nothing in this Phase 1 appendix represents those complete upstream suites as passing.
