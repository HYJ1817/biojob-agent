# BioJob Source Coverage and Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the brittle five-page prototype with proxy-compatible, multi-query job discovery, official verification portals, batch summaries, and clear Chinese provenance UX.

**Architecture:** Keep fetching behind `SafeHttpClient`, adding immutable reviewed-host policy for TUN synthetic DNS. Use `search_feed` for discovery and non-runnable `portal` sources for official verification; derive verification status from source provenance without creating a second job store.

**Tech Stack:** Python, httpx, SQLite, FastAPI/Pydantic, React, TypeScript, Vitest, Electron, pytest through `scripts/run_tests.sh`.

---

## File map

- Create `biojob/sources/search_feed.py` for public search-feed parsing and deterministic relevance screening.
- Modify `biojob/sources/http.py`, `feed.py`, and `catalog.py` for network policy, shared feed parsing, defaults, and reviewed hosts.
- Modify `biojob/discovery.py`, `service.py`, and `repository.py` for trust injection, reconciliation, batch summaries, and provenance.
- Modify `hermes_cli/web_routers/biojob.py` and focused API tests for batch execution.
- Modify `apps/desktop/src/app/biojob/{api,types,copy,index}.ts(x)` and tests for grouped Chinese UX.
- Modify `docs/BIOJOB_WINDOWS_GUIDE.md` and version metadata for v0.1.2.

### Task 1: Reviewed-host network policy

**Files:**
- Modify: `tests/biojob/test_sources.py`
- Modify: `biojob/sources/http.py`

- [ ] **Step 1: Write failing tests**

Add a resolver returning `198.18.0.58`. Prove an ordinary source is rejected, an exact reviewed host is accepted, an unreviewed host and cross-host redirect are rejected, and normal private/loopback protections remain. Add syntax-only link tests rejecting control characters, credentials, malformed ports, `file:`, and missing hosts.

```python
with pytest.raises(SourceSecurityError):
    safe.get("https://jobs.example.test/feed")
assert safe.get(
    "https://jobs.example.test/feed",
    reviewed_hosts=frozenset({"jobs.example.test"}),
).text == "ok"
```

- [ ] **Step 2: Run and verify RED**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_sources.py -q
```

Expected: failures because `reviewed_hosts` and `validate_external_link` are absent.

- [ ] **Step 3: Implement minimal policy**

Add `_TUN_SYNTHETIC_NETWORK = ipaddress.ip_network("198.18.0.0/15")`, a shared strict HTTP URL syntax parser, `validate_external_link`, and `get(url, *, reviewed_hosts=frozenset())`. Normalize hosts using IDNA/case folding. Permit the synthetic range only when the current hostname exactly matches a reviewed host; apply the same rule after every redirect. Keep all existing body, timeout, redirect, private-address, user-info, and control-character checks.

- [ ] **Step 4: Run GREEN and commit**

Run the Step 2 command; expected: all source tests pass.

```powershell
git add biojob/sources/http.py tests/biojob/test_sources.py
git commit -m "fix(biojob): support reviewed sources behind TUN DNS"
```

### Task 2: Search-feed adapter and expanded catalog

**Files:**
- Create: `biojob/sources/search_feed.py`
- Modify: `biojob/sources/feed.py`
- Modify: `biojob/sources/__init__.py`
- Modify: `biojob/sources/catalog.py`
- Modify: `tests/biojob/test_sources.py`
- Modify: `tests/biojob/test_discovery_runs.py`

- [ ] **Step 1: Write failing adapter tests**

Cover RSS and Atom, search redirect unwrapping, tracking-parameter removal, source-domain preservation, company/title splitting, and fallback company `待核验 · <host>`. Assert positive terms for production/process, QA/QC, cell/lab, fermentation/microbiology and exclusion of 博士后、高级经理、医药销售.

```python
assert jobs[0] == RawJob(
    company_name="齐鲁制药",
    title="生物工艺工程师（2027校招）",
    detail_url="https://jobs.example.test/graduate/123",
    jd_text="本科；负责发酵生产和GMP记录。",
    published_at="2026-08-13",
    recruitment_type="校招（待核验）",
)
```

- [ ] **Step 2: Write failing catalog behavior tests**

Assert at least eight enabled `search_feed` sources cover all four directions, Shandong, nearby major cities, school career sites, and targeted company results. Assert five or more HTTPS `portal` sources are disabled/non-runnable. Replace exact catalog-count snapshots with these behavior contracts.

- [ ] **Step 3: Run and verify RED**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_sources.py tests/biojob/test_discovery_runs.py -q
```

Expected: missing `SearchFeedAdapter`, source types, and catalog entries.

- [ ] **Step 4: Implement shared parsing and adapter**

Expose immutable `FeedEntry` and `parse_feed_entries(content)` from `feed.py`, retaining DTD/entity rejection and the 500-entry limit. Implement `SearchFeedAdapter.fetch`: fetch the reviewed RSS/Atom URL, parse entries, validate result links without DNS fetches, apply deterministic relevance rules, and emit `RawJob` with `校招（待核验）`. Do not call an LLM.

- [ ] **Step 5: Implement defaults and reviewed-host lookup**

Define 8–12 encoded Bing RSS queries in `DEFAULT_SOURCES`. Model official company pages as disabled `portal` sources. Add `reviewed_hosts_for_source(source_id)` backed only by immutable catalog data; do not persist trust hosts in `config_json`.

- [ ] **Step 6: Run GREEN and commit**

Run the Step 3 command; expected: all pass.

```powershell
git add biojob/sources tests/biojob/test_sources.py tests/biojob/test_discovery_runs.py
git commit -m "feat(biojob): add broad reviewed job discovery"
```

### Task 3: Legacy reconciliation, batch summary, and provenance

**Files:**
- Modify: `biojob/discovery.py`
- Modify: `biojob/service.py`
- Modify: `biojob/repository.py`
- Modify: `tests/biojob/test_discovery_runs.py`
- Modify: `tests/biojob/test_candidates.py`

- [ ] **Step 1: Write failing reconciliation tests**

Add tests proving untouched legacy default pages become portals without losing run history, user-modified defaults are not rewritten, and repeated reconciliation is idempotent. Detect user modification from `source.updated` audit events.

- [ ] **Step 2: Write failing orchestration/provenance tests**

Prove reviewed hosts are injected into a copied runtime config and never persisted. Make `run_enabled_sources` return:

```python
{
    "runs": [...],
    "summary": {
        "completed_sources": 2,
        "failed_sources": 1,
        "new_candidates": 4,
        "merged_results": 2,
        "pending_verification": 6,
    },
}
```

Assert candidates attributed to any `search_feed` have `needs_verification is True`; manual/official-only candidates are false.

- [ ] **Step 3: Run and verify RED**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_discovery_runs.py tests/biojob/test_candidates.py -q
```

Expected: reconciliation, summary, and provenance fields are absent.

- [ ] **Step 4: Implement strict config and reconciliation**

Allow `search_feed` config keys `url`, `query_label`, optional `careers_url`; allow `portal` keys `url`, `company_name`; reject any trust-host key. Reconcile stable legacy IDs only when no user-update audit exists. Update adapter/config/description/enabled in one transaction, preserving IDs and run history.

- [ ] **Step 5: Implement run-time trust and batch metrics**

Inject `_reviewed_hosts` immediately before `adapter.fetch`. Count candidates before and after enabled runs; compute new candidates, merged successful ingestions, completed/failed sources, and pending verification. Continue after individual failures.

- [ ] **Step 6: Implement provenance query**

Extend candidate SQL with `EXISTS` joining `job_sources` to `sources` where `adapter_type='search_feed'`. Parse the SQLite integer fail-closed and expose a Boolean `needs_verification`.

- [ ] **Step 7: Run GREEN and commit**

Run the Step 3 command; expected: all pass.

```powershell
git add biojob/discovery.py biojob/service.py biojob/repository.py tests/biojob/test_discovery_runs.py tests/biojob/test_candidates.py
git commit -m "feat(biojob): summarize discovery provenance"
```

### Task 4: Batch API and grouped Chinese desktop UX

**Files:**
- Modify: `hermes_cli/web_routers/biojob.py`
- Modify: `tests/biojob/test_discovery_api.py`
- Modify: `apps/desktop/src/app/biojob/api.ts`
- Modify: `apps/desktop/src/app/biojob/api.test.ts`
- Modify: `apps/desktop/src/app/biojob/types.ts`
- Modify: `apps/desktop/src/app/biojob/copy.ts`
- Modify: `apps/desktop/src/app/biojob/index.tsx`
- Modify: `apps/desktop/src/app/biojob/index.test.tsx`

- [ ] **Step 1: Write failing API test**

Add `POST /api/biojob/sources/run-enabled` coverage: HTTP 200, ordered runs, five integer summary fields, and isolated individual failure.

- [ ] **Step 2: Write failing UI/API-client tests**

Assert “运行全部启用来源” calls the batch endpoint; automatic sources and official portals have separate headings; portals have “打开招聘页” but no run button; batch results show new/merged/pending/failure counts; known backend failures map to Chinese remediation; unverified candidates show “待核验” and “打开原页面”.

- [ ] **Step 3: Run and verify RED**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_discovery_api.py -q
npm --workspace apps/desktop exec vitest run --project ui src/app/biojob/api.test.ts src/app/biojob/index.test.tsx
```

Expected: missing endpoint, client, types, and controls.

- [ ] **Step 4: Implement endpoint and client**

Add a static `/sources/run-enabled` route before `/{source_id}/run`. Add:

```ts
export const runEnabledSources = () =>
  call<BioJobBatchRun>({ body: {}, method: 'POST', path: '/api/biojob/sources/run-enabled' })
```

- [ ] **Step 5: Implement grouped UX**

Split on `adapter_type === 'portal'`. Put the batch button in `PageHeading`. Render portal URLs with `target="_blank" rel="noreferrer"` and never call `runSource`. Show a compact batch summary, refresh authoritative data, map error fragments to Chinese actions, and display candidate verification badges without blocking links or review decisions.

- [ ] **Step 6: Run GREEN, typecheck, and commit**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_discovery_api.py -q
npm --workspace apps/desktop exec vitest run --project ui src/app/biojob/api.test.ts src/app/biojob/index.test.tsx
npm --workspace apps/desktop run typecheck
```

Expected: all exit 0.

```powershell
git add hermes_cli/web_routers/biojob.py tests/biojob/test_discovery_api.py apps/desktop/src/app/biojob
git commit -m "feat(desktop): make job discovery understandable"
```

### Task 5: Regression and live-source smoke

**Files:**
- Modify only focused files when a reproduced failure requires it.

- [ ] **Step 1: Run all BioJob and desktop checks**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob -q
npm --workspace apps/desktop run test:ui
npm --workspace apps/desktop run typecheck
npm --workspace apps/desktop run lint
git diff --check
```

Expected: tests/typecheck/diff check pass; no new lint diagnostics beyond the recorded baseline.

- [ ] **Step 2: Exercise live sources in the current TUN environment**

Use the project interpreter with a temporary `HERMES_HOME` and run enabled defaults once. Do not print credentials. At least one reviewed feed must complete; zero current results is acceptable, but reviewed sources must not fail with `source hostname must resolve only to public addresses`.

- [ ] **Step 3: Correct only evidence-backed live defects**

If a provider blocks or changes format, add a regression fixture first, then disable or correct that individual source. Rerun Step 1. Commit only focused changes as `fix(biojob): harden live discovery sources`.

### Task 6: v0.1.2 release, installation, and verification

**Files:**
- Modify: `docs/BIOJOB_WINDOWS_GUIDE.md`
- Modify: `apps/desktop/package.json`
- Modify: synchronized lockfile version entries

- [ ] **Step 1: Update guide and version**

Document source groups, “运行全部”, “待核验”, original links, platform login expectations, TUN compatibility, and no automatic submission. Bump only the BioJob desktop patch version from 0.1.1 to 0.1.2.

- [ ] **Step 2: Restore complete dependencies and verify**

```powershell
uv sync --locked --extra all --extra dev
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob -q
npm --workspace apps/desktop run test:ui
npm --workspace apps/desktop run typecheck
npm --workspace apps/desktop run lint
git diff --check
```

- [ ] **Step 3: Build and hash Windows installer**

```powershell
npm --workspace apps/desktop run dist:win:nsis
```

Record exact filename, byte size, and SHA-256 from `Get-Item` and `Get-FileHash` in the guide; rerun `git diff --check`.

- [ ] **Step 4: Commit, push, and publish**

Commit `release: prepare BioJob Agent 0.1.2`, push `biojob-main`, create GitHub release `v0.1.2`, upload the installer, and verify remote size/digest match local.

- [ ] **Step 5: Install and verify this Windows account**

Close only BioJob Agent, preserve `%LOCALAPPDATA%\BioJob Agent\biojob\biojob.db` and `%LOCALAPPDATA%\hermes`, install v0.1.2, then verify backend 200, old data retained, at least eight enabled discovery sources, grouped portals, no reviewed-source TUN rejection, clickable source links, and verification badges. Release any UI automation session immediately after verification.

- [ ] **Step 6: Hand off**

Provide download URL, installer filename, SHA-256, installed executable path, and four Chinese steps: run sources, verify original page, keep the candidate, track the application.
