# BioJob Agent Runtime Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make packaged BioJob Agent use and validate an app-owned runtime so an existing legacy Hermes installation can never cause the `/api/health` 401 startup failure.

**Architecture:** Extract home selection and BioJob-only migration into small Electron modules, then wire their results into the existing bootstrap/runtime ladder in `main.ts`. Packaged BioJob builds use an app-specific home; test/dev callers retain explicit sandbox overrides. Runtime acceptance adds a BioJob capability probe, while migration copies only the legacy `biojob` subtree through a temporary sibling and never deletes the source.

**Tech Stack:** Electron, TypeScript, Node `fs`/`path`, Vitest, existing Hermes bootstrap scripts, PowerShell/NSIS Windows packaging.

---

## File map

- Create `apps/desktop/electron/biojob-home.ts`: pure cross-platform BioJob home resolution.
- Create `apps/desktop/electron/biojob-home.test.ts`: path precedence and isolation contracts.
- Create `apps/desktop/electron/biojob-migration.ts`: idempotent BioJob-only directory migration.
- Create `apps/desktop/electron/biojob-migration.test.ts`: real-filesystem migration, failure cleanup, and sensitive-file exclusion.
- Create `apps/desktop/electron/biojob-runtime-capability.ts`: runtime capability validation using an injected probe.
- Create `apps/desktop/electron/biojob-runtime-capability.test.ts`: rejects importable legacy Hermes and accepts BioJob runtime.
- Modify `apps/desktop/electron/main.ts`: consume the modules before runtime/bootstrap resolution and log the selected home safely.
- Modify `apps/desktop/scripts/test-desktop.mjs`: assert packaged launch isolation from a seeded legacy Hermes home.
- Modify `docs/BIOJOB_WINDOWS_GUIDE.md`: installation, data, migration, recovery, and uninstall paths.
- Modify `apps/desktop/package.json`: bump patch version for the fixed Windows artifact.

### Task 1: App-owned BioJob home resolver

**Files:**
- Create: `apps/desktop/electron/biojob-home.ts`
- Create: `apps/desktop/electron/biojob-home.test.ts`
- Modify: `apps/desktop/electron/main.ts`

- [ ] **Step 1: Write the failing resolver tests**

```ts
test('packaged Windows BioJob uses an app-owned home instead of HERMES_HOME', () => {
  const actual = resolveBioJobHome({
    platform: 'win32',
    env: { LOCALAPPDATA: 'C:\\Users\\test\\AppData\\Local', HERMES_HOME: 'D:\\OldHermes' },
    packaged: true,
    userDataOverride: null,
    homeDir: 'C:\\Users\\test'
  })
  assert.equal(actual, 'C:\\Users\\test\\AppData\\Local\\BioJob Agent')
})

test('desktop sandbox override stays isolated and deterministic', () => {
  const actual = resolveBioJobHome({
    platform: 'win32', env: {}, packaged: true,
    userDataOverride: 'D:\\sandbox', homeDir: 'C:\\Users\\test'
  })
  assert.equal(actual, 'D:\\sandbox\\biojob-home')
})
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm --workspace apps/desktop exec vitest run --project electron electron/biojob-home.test.ts`

Expected: FAIL because `biojob-home.ts` does not exist.

- [ ] **Step 3: Implement the resolver**

```ts
export interface BioJobHomeOptions {
  platform: NodeJS.Platform
  env: NodeJS.ProcessEnv
  packaged: boolean
  userDataOverride?: string | null
  homeDir: string
}

export function resolveBioJobHome(options: BioJobHomeOptions): string {
  if (options.userDataOverride) return path.join(path.resolve(options.userDataOverride), 'biojob-home')
  if (!options.packaged && options.env.BIOJOB_HOME) return path.resolve(options.env.BIOJOB_HOME)
  if (options.platform === 'win32' && options.env.LOCALAPPDATA) {
    return path.join(options.env.LOCALAPPDATA, 'BioJob Agent')
  }
  if (options.platform === 'darwin') {
    return path.join(options.homeDir, 'Library', 'Application Support', 'BioJob Agent', 'runtime')
  }
  return path.join(options.env.XDG_DATA_HOME || path.join(options.homeDir, '.local', 'share'), 'biojob-agent')
}
```

- [ ] **Step 4: Run the resolver tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Wire `main.ts` to use `resolveBioJobHome` and remove packaged inheritance of registry/process `HERMES_HOME`**

Keep `HERMES_DESKTOP_USER_DATA_DIR` as the highest-precedence test sandbox and log only the resolved path.

- [ ] **Step 6: Run targeted desktop tests and commit**

Run: `npm --workspace apps/desktop exec vitest run --project electron electron/biojob-home.test.ts electron/windows-user-env.test.ts electron/backend-env.test.ts`

Commit: `fix(desktop): isolate BioJob runtime home`

### Task 2: Safe BioJob-only data migration

**Files:**
- Create: `apps/desktop/electron/biojob-migration.ts`
- Create: `apps/desktop/electron/biojob-migration.test.ts`
- Modify: `apps/desktop/electron/main.ts`

- [ ] **Step 1: Write failing real-filesystem tests**

Cover these assertions using `fs.mkdtempSync`:

```ts
assert.equal(result.status, 'migrated')
assert.equal(fs.readFileSync(path.join(targetHome, 'biojob', 'biojob.sqlite3'), 'utf8'), 'db')
assert.equal(fs.existsSync(path.join(targetHome, 'config.yaml')), false)
assert.equal(fs.existsSync(path.join(targetHome, '.env')), false)
assert.equal(fs.existsSync(path.join(legacyHome, 'biojob', 'biojob.sqlite3')), true)
```

Add separate tests for `no-source`, `target-exists`, and an injected copy failure leaving neither the target nor a `.migrating-*` directory.

- [ ] **Step 2: Run and verify RED**

Run: `npm --workspace apps/desktop exec vitest run --project electron electron/biojob-migration.test.ts`

Expected: FAIL because migration module is absent.

- [ ] **Step 3: Implement atomic, idempotent migration**

Expose:

```ts
export function migrateLegacyBioJobData(options: {
  legacyHome: string
  targetHome: string
  copyDirectory?: typeof fs.cpSync
}): { status: 'migrated' | 'no-source' | 'target-exists'; source: string; target: string }
```

Create the target root, copy only `<legacyHome>/biojob` into a unique sibling temporary directory, rename the temporary directory to `<targetHome>/biojob`, and remove only the temporary directory on failure. Never remove or rename the source.

- [ ] **Step 4: Run migration tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass and temporary roots are cleaned by tests.

- [ ] **Step 5: Invoke migration before backend discovery**

On Windows, derive legacy source as `%LOCALAPPDATA%\hermes`; skip when source and target normalize to the same path. Convert migration failure into the existing recoverable boot error and write a redacted log line.

- [ ] **Step 6: Run combined tests and commit**

Run: `npm --workspace apps/desktop exec vitest run --project electron electron/biojob-home.test.ts electron/biojob-migration.test.ts`

Commit: `feat(desktop): migrate legacy BioJob data safely`

### Task 3: Reject a legacy runtime that lacks BioJob capability

**Files:**
- Create: `apps/desktop/electron/biojob-runtime-capability.ts`
- Create: `apps/desktop/electron/biojob-runtime-capability.test.ts`
- Modify: `apps/desktop/electron/main.ts`
- Modify: `apps/desktop/electron/active-runtime-state.ts`
- Modify: `apps/desktop/electron/active-runtime-state.test.ts`

- [ ] **Step 1: Write failing capability tests**

```ts
test('an importable legacy Hermes runtime is not usable for BioJob', async () => {
  const result = await probeBioJobRuntimeCapability(async () => ({ code: 1, stdout: '', stderr: 'No module named biojob' }))
  assert.deepEqual(result, { usable: false, reason: 'biojob-module-missing' })
})

test('a runtime with BioJob module is usable', async () => {
  const result = await probeBioJobRuntimeCapability(async () => ({ code: 0, stdout: 'BIOJOB_RUNTIME_OK', stderr: '' }))
  assert.equal(result.usable, true)
})
```

Update active-runtime tests so `runtimeUsable=true` plus `bioJobCapable=false` yields `shouldUseActiveRuntime=false`.

- [ ] **Step 2: Run and verify RED**

Run: `npm --workspace apps/desktop exec vitest run --project electron electron/biojob-runtime-capability.test.ts electron/active-runtime-state.test.ts`

Expected: FAIL because the capability probe/signature is absent.

- [ ] **Step 3: Implement and wire the capability probe**

Probe the selected runtime's Python with `-c "import biojob; print('BIOJOB_RUNTIME_OK')"`, bounded by the existing backend-probe timeout. Extend active-runtime classification to require both the generic import probe and BioJob capability.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Verify bootstrap recovery**

Run: `npm --workspace apps/desktop exec vitest run --project electron electron/backend-probes.test.ts electron/bootstrap-runner.test.ts electron/bootstrap-repair-guard.test.ts electron/active-runtime-state.test.ts electron/biojob-runtime-capability.test.ts`

Commit: `fix(desktop): require BioJob-capable backend runtime`

### Task 4: Packaged legacy-Hermes regression scenario

**Files:**
- Modify: `apps/desktop/scripts/test-desktop.mjs`

- [ ] **Step 1: Add a failing packaged test scenario**

Seed a temporary `%LOCALAPPDATA%\hermes\hermes-agent` containing a runnable legacy marker and set `HERMES_HOME` to that legacy root. Launch the packaged app with its temporary user-data directory. Assert the backend environment and bootstrap log point under `%LOCALAPPDATA%\BioJob Agent`, and that the legacy sentinel remains byte-identical.

- [ ] **Step 2: Run and verify RED**

Run: `npm --workspace apps/desktop run test:desktop:existing`

Expected: FAIL because the existing scenario currently resolves the legacy Hermes root.

- [ ] **Step 3: Complete the test harness integration and verify GREEN**

Run the Step 2 command. Expected: packaged app reaches ready state, BioJob `/api/profile` returns 200, WebSocket probe succeeds, and the legacy sentinel is unchanged.

- [ ] **Step 4: Commit**

Commit: `test(desktop): cover legacy Hermes isolation`

### Task 5: Documentation, version, regression, and Windows artifacts

**Files:**
- Modify: `docs/BIOJOB_WINDOWS_GUIDE.md`
- Modify: `apps/desktop/package.json`
- Modify: lockfile if the version is represented there

- [ ] **Step 1: Update user documentation**

Document `%LOCALAPPDATA%\BioJob Agent\biojob`, automatic copy-only migration from `%LOCALAPPDATA%\hermes\biojob`, unchanged old Hermes, recovery buttons, and the new installer filename/hash placeholders only after artifacts exist.

- [ ] **Step 2: Bump version to `0.1.1` and run static checks**

Run: `npm --workspace apps/desktop run typecheck`

Run: `npm --workspace apps/desktop run lint`

Run: `git diff --check`

Expected: all exit 0.

- [ ] **Step 3: Run desktop and BioJob regression suites**

Run: `npm --workspace apps/desktop run test:desktop:platforms`

Run: `npm --workspace apps/desktop run test:ui`

Run Python BioJob tests only through the repository wrapper: `bash scripts/run_tests.sh tests/biojob`

Expected: all pass with no flaky report.

- [ ] **Step 4: Build Windows portable and NSIS artifacts**

Run: `npm --workspace apps/desktop run dist:win:nsis`

Calculate SHA-256 with `Get-FileHash`; update the guide with exact filename, byte size, and hash, then rerun `git diff --check`.

- [ ] **Step 5: Verify the actual packaged artifact in an isolated legacy-Hermes fixture**

Run the packaged existing/fresh scenarios against temporary roots. Confirm startup, `GET /api/health`, a BioJob endpoint, WebSocket auth, and unchanged legacy sentinel. Inspect the final logs for secret redaction.

- [ ] **Step 6: Commit and publish**

Commit: `release: prepare BioJob Agent 0.1.1`

Push the branch, create/update GitHub release `v0.1.1`, upload the installer and checksum, then confirm the release download URL and asset size.

### Task 6: Restore this Windows machine and hand off

**Files:**
- No repository source changes unless verification exposes a defect.

- [ ] **Step 1: Snapshot current external state read-only**

Record the old Hermes checkout commit and hash a sentinel subset. Confirm no BioJob process is running.

- [ ] **Step 2: Install BioJob Agent 0.1.1**

Launch the new installer with user approval. Do not delete or mutate `%LOCALAPPDATA%\hermes`.

- [ ] **Step 3: Verify real installed behavior**

Confirm the app uses `%LOCALAPPDATA%\BioJob Agent`, backend becomes ready without 401, BioJob API returns 200, UI opens, and old Hermes checkout commit/sentinel hashes are unchanged.

- [ ] **Step 4: Provide installation and first-use instructions**

Link the release, installer, checksum, guide, and explain first startup, provider/API setup, BioJob navigation, and data backup path.
