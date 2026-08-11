# BioJob Discovery and Candidate Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not use subagents for this project; the user explicitly requested inline execution.

**Goal:** Add resilient job-source ingestion, normalization, deduplication, rule-based screening, and a reviewable candidate pool that only creates a formal application after explicit user confirmation.

**Architecture:** Keep SQLite as the sole source of truth. Source adapters produce untrusted `RawJob` values; a source runner validates and normalizes them before a transactional service upserts jobs, source links, immutable snapshots, deterministic match evidence, and pending candidate decisions. Source failures are isolated per run, and the existing formal application workflow remains unchanged for user-created jobs.

**Tech Stack:** Python 3.11+, SQLite migrations, `httpx`, stdlib HTML/XML/JSON parsing with size limits, FastAPI/Pydantic v2, pytest through `scripts/run_tests.sh`.

---

## Product boundary

Phase 2 includes:

- manual URL/JD candidate import;
- a bounded public-page adapter that reads JSON-LD `JobPosting` and safe job links;
- a bounded RSS/Atom adapter for user-configured public discovery feeds;
- five preconfigured official employer landing sources: 齐鲁制药、荣昌生物、绿叶制药、华熙生物、康龙化成;
- source health, run history, candidate decisions, deterministic screening, and link-preserving deduplication;
- local HTTP endpoints for the future desktop candidate pool.

Phase 2 does not automate login, bypass anti-bot controls, submit applications, call an LLM, generate resumes, add Excel, or add the desktop GUI. An official landing source may report a healthy zero-result run when the public page contains no machine-readable jobs; it must never invent jobs from marketing copy.

## Task 1: Migration 2 for source configuration and deduplication

**Files:**
- Modify: `biojob/schema.py`
- Test: `tests/biojob/test_discovery_database.py`

- [x] **Step 1: Write failing migration tests**

Create a version-1 database by executing only migration 1, then initialize with current migrations. Assert migration 2 is applied once, existing rows survive, and the following additions exist:

```text
sources.config_json TEXT NOT NULL DEFAULT '{}'
sources.description TEXT
jobs.dedup_key TEXT
```

Assert a partial unique index named `idx_jobs_active_dedup_key` enforces one non-deleted job per non-null `dedup_key`, while soft-deleted historical rows do not block a replacement.

- [x] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_discovery_database.py -q
```

Expected: failure because migration 2 and the new columns do not exist.

- [x] **Step 3: Implement migration 2**

Append `(2, sql)` to `MIGRATIONS`. Use `ALTER TABLE` only for the new nullable/defaulted columns and create the partial unique index. Do not rewrite migration 1.

- [x] **Step 4: Verify GREEN and regressions**

Run the new file plus `tests/biojob/test_database.py`.

- [x] **Step 5: Commit**

Commit as `feat(biojob): migrate discovery source metadata`.

## Task 2: Candidate ingestion and decision service

**Files:**
- Modify: `biojob/domain.py`
- Modify: `biojob/repository.py`
- Modify: `biojob/service.py`
- Test: `tests/biojob/test_candidates.py`

- [x] **Step 1: Write failing candidate lifecycle tests**

Use a real temporary database. Require `ingest_candidate()` to create or merge a job without creating an `applications` row, attach a source link and snapshot, insert a deterministic `job_matches` row, and record a latest `candidate_decisions.decision='pending'` row.

Required public service contracts:

```python
service.ingest_candidate(raw_job, source_id=source_id, actor="source:qilu")
service.list_candidates(decision="pending", query=None, direction=None, city=None)
service.get_candidate(job_id)
service.decide_candidate(job_id, "kept", actor="user", note=None)
service.decide_candidate(job_id, "ignored", actor="user", note="学历不符")
```

`kept` creates the initial `considering` application and event exactly once in the same transaction. `ignored`, `later`, and `error` do not create an application. Repeating the same terminal decision is a conflict; a user may move `later` back to `pending` through an explicit new decision.

- [x] **Step 2: Verify RED**

Run `tests/biojob/test_candidates.py`; expected failure is missing candidate methods/types.

- [x] **Step 3: Implement normalization, matching, and deduplication**

Add focused domain types:

```python
class CandidateDecision(StrEnum):
    PENDING = "pending"
    KEPT = "kept"
    IGNORED = "ignored"
    LATER = "later"
    ERROR = "error"

@dataclass(frozen=True)
class RawJob:
    company_name: str
    title: str
    detail_url: str
    city: str | None = None
    jd_text: str | None = None
    apply_url: str | None = None
    careers_url: str | None = None
    external_id: str | None = None
    published_at: str | None = None
    deadline_at: str | None = None
    recruitment_type: str | None = None
```

Normalization must use Unicode NFKC, collapse whitespace, normalize common full-width punctuation, and build `dedup_key` from canonical company, title, city, and recruitment type. Preserve original display text and all source URLs.

The deterministic screener returns score 0–100 plus JSON evidence. Positive terms include 生物工艺、生产、发酵、细胞培养、QA、QC、质量、GMP、实验员 and 本科/应届; hard-gap terms include 博士、仅限硕士、药物合成、医药销售 and 临床项目经理. A hard gap lowers recommendation but never silently deletes a candidate.

All job/source/snapshot/match/decision/audit mutations share one `BEGIN IMMEDIATE` transaction. A repeated source snapshot with the same content hash is idempotent. Cross-source duplicates merge into one job and retain separate `job_sources` rows.

- [x] **Step 4: Cover corruption and concurrency**

Add tests for source-level duplicate refresh, cross-source merge, changed JD snapshot creation, concurrent duplicate ingestion, kept decision atomicity, illegal repeat decisions, soft-deleted replacements, and malformed persisted decision/match JSON failing closed with `DomainDataCorruptionError`.

- [x] **Step 5: Verify and commit**

Run all Task 1–2 tests and existing BioJob tests. Commit as `feat(biojob): add reviewable candidate lifecycle`.

## Task 3: Source adapter framework

**Files:**
- Create: `biojob/sources/__init__.py`
- Create: `biojob/sources/base.py`
- Create: `biojob/sources/http.py`
- Create: `biojob/sources/manual.py`
- Create: `biojob/sources/public_page.py`
- Create: `biojob/sources/feed.py`
- Test: `tests/biojob/test_sources.py`

- [x] **Step 1: Write failing adapter contract tests**

Define a synchronous adapter protocol because source runs execute in worker threads:

```python
class JobSourceAdapter(Protocol):
    adapter_type: str
    def fetch(self, config: Mapping[str, object]) -> list[RawJob]: ...
```

Tests use an injected `httpx.MockTransport`; no test calls the public internet.

- [x] **Step 2: Verify RED**

Expected: imports fail because `biojob.sources` does not exist.

- [x] **Step 3: Implement bounded HTTP and manual adapters**

`SafeHttpClient` must permit only `http`/`https`, reject userinfo and local/private/link-local destinations after DNS resolution, use a 15-second timeout, cap redirects at 5, cap response bodies at 2 MiB, and send an honest BioJob user agent. Redirect targets are revalidated. Tests cover loopback IPv4/IPv6, DNS rebinding through injected resolver, oversized bodies, redirects, timeouts, and content types.

`ManualJobAdapter` accepts already supplied structured data and performs no network request.

- [x] **Step 4: Implement public-page parsing**

`PublicPageAdapter` may create candidates only from:

- valid schema.org JSON-LD objects with `@type: JobPosting`; or
- anchors whose visible text/title and URL path contain a job/recruit/career signal.

It must strip scripts/styles, cap extracted text, resolve relative URLs against the validated final URL, reject `javascript:` links, and never treat a generic landing-page paragraph as a job. JSON-LD fields map title, organization, location, description, dates, and application URL into `RawJob`.

- [x] **Step 5: Implement feed parsing**

`FeedJobAdapter` accepts RSS 2.0 or Atom under a 2 MiB limit. Reject `DOCTYPE` and `ENTITY` before parsing. Each item/entry needs a title and validated absolute link. Description is treated as untrusted JD/snippet text with tags removed and a 50,000-character cap.

- [x] **Step 6: Verify and commit**

Run `tests/biojob/test_sources.py` and all previous Phase 2 files. Commit as `feat(biojob): add bounded job source adapters`.

## Task 4: Source catalog and isolated run orchestration

**Files:**
- Create: `biojob/sources/catalog.py`
- Create: `biojob/discovery.py`
- Modify: `biojob/repository.py`
- Modify: `biojob/service.py`
- Test: `tests/biojob/test_discovery_runs.py`

- [x] **Step 1: Write failing source/run tests**

Required service contracts:

```python
service.ensure_default_sources()
service.list_sources()
service.create_source(name, adapter_type, config, actor="user")
service.update_source(source_id, enabled=False, actor="user")
service.run_source(source_id, actor="user")
service.list_source_runs(source_id=None)
```

The default catalog uses these reviewed public entry points and stable names:

```python
DEFAULT_SOURCES = (
    ("齐鲁制药招聘", "public_page", "https://www.qilu-pharma.com/position.html", True),
    ("荣昌生物招聘", "public_page", "https://www.remegen.cn/index.php?cid=45&v=listing", True),
    ("绿叶制药招聘", "public_page", "https://www.luye.cn/lvye/joinUs.php", True),
    ("华熙生物招聘", "public_page", "https://www.hotjob.cn/wt/HXSW/web/index?brandCode=1", True),
    ("康龙化成校园招聘", "public_page", "https://app.mokahr.com/m/campus-recruitment/pharmaron/74162", True),
    ("公开搜索发现（实验）", "feed", "https://www.bing.com/search?format=rss&q=生物制药+校园招聘+QA+QC+工艺", False),
)
```

The catalog records that dynamic/WAF-protected landing pages may return zero or fail without making the overall run fail. Defaults are upserted by stable names and never overwrite a user's enabled/config changes.

- [x] **Step 2: Verify RED**

Expected: missing catalog and run orchestration.

- [x] **Step 3: Implement run lifecycle**

A run inserts `source_runs.status='running'`, invokes only the adapter registered for `adapter_type`, ingests each valid result independently, then finishes as `completed` with `result_count`. One malformed item increments an error summary without discarding valid siblings. Network/adapter failure marks only that run `failed`, updates source health, and leaves other sources runnable. Cancellation is not exposed until background scheduling exists.

Do not hold a SQLite write transaction during network I/O. Persist start, perform fetch, then transact each bounded ingestion and final run update.

- [x] **Step 4: Add deterministic registry tests**

Unknown adapter types are validation errors. Config is strict JSON with no credentials, cookies, headers, or arbitrary local paths. Default employer URLs must be `https` and source list responses expose no database path.

- [x] **Step 5: Verify and commit**

Run all Phase 2 tests and existing BioJob suite. Commit as `feat(biojob): orchestrate isolated discovery runs`.

## Task 5: Candidate and source HTTP API

**Files:**
- Modify: `biojob/api_models.py`
- Modify: `hermes_cli/web_routers/biojob.py`
- Test: `tests/biojob/test_discovery_api.py`

- [x] **Step 1: Write failing API tests**

Add these authenticated local routes:

```text
GET    /api/biojob/candidates
GET    /api/biojob/candidates/{job_id}
POST   /api/biojob/candidates/import
POST   /api/biojob/candidates/{job_id}/decision
GET    /api/biojob/sources
POST   /api/biojob/sources
PATCH  /api/biojob/sources/{source_id}
POST   /api/biojob/sources/{source_id}/run
GET    /api/biojob/source-runs
```

Tests cover manual import, a duplicate import retaining links, pending list, keep-to-application, ignore/later decisions, filters, missing IDs, disabled/unknown sources, a failed adapter isolated to one run, and dashboard candidate/source counts.

- [x] **Step 2: Verify RED**

Expected: 404 for the new routes.

- [x] **Step 3: Implement strict models and thin handlers**

Reuse the existing strict non-finite JSON base model, URL validation, `asyncio.to_thread`, domain error mapping, and generic 500 redaction. Source config accepts only adapter-specific public fields:

```text
public_page: url, company_name, careers_url
feed: url, company_name?, careers_url?
manual: no persisted network config
```

No API key, Cookie, Authorization header, proxy credential, or local file path is accepted.

- [x] **Step 4: Verify real auth boundary**

Confirm the new routes are not in `PUBLIC_API_PATHS` and unauthenticated access through the real dashboard app is rejected.

- [x] **Step 5: Verify and commit**

Run all BioJob tests plus `tests/hermes_cli/test_dashboard_auth_middleware.py`. Commit as `feat(biojob): expose candidate discovery API`.

## Task 6: Phase 2 verification and handoff

**Files:**
- Modify: `docs/baseline/hermes-windows-baseline.md`
- Modify: `docs/superpowers/plans/2026-08-12-biojob-discovery-candidates.md`

- [x] **Step 1: Run Phase 2 gates**

Run the complete BioJob suite, the nine retained Windows regressions, desktop build, capability check, and a schema scan that confirms no credential-shaped columns or source config keys.

- [x] **Step 2: Run a live non-mutating source smoke test**

Against a temporary `HERMES_HOME`, run each enabled default public landing source once. Record result counts and health honestly. A zero-result or failed anti-bot source is acceptable only when isolated and clearly reported; no login or bypass is attempted.

- [x] **Step 3: Update verification records**

Append a `Phase 2 discovery and candidates` section with exact commands, test counts, source smoke results, and the explicit no-auto-apply boundary. Mark completed checklist items.

- [x] **Step 4: Commit and push**

Verify the pinned Hermes commit remains an ancestor, no `.db`/credentials are tracked, and the worktree is clean after committing as `docs: record BioJob discovery verification`. Push `biojob-main`.

## Phase 2 completion criteria

- A source failure cannot roll back or block another source run.
- A fetched job never becomes a formal application without `decision='kept'` from the user.
- Cross-source duplicates preserve all source/detail/apply/careers links and immutable changed snapshots.
- Candidate results include deterministic evidence and never invent missing JD facts.
- Five official employer landing sources are present, editable, disableable, and health-visible.
- Manual import works without any provider key or internet access.
- New routes inherit dashboard authentication and reject credential-shaped source configuration.
- All Phase 1 behavior and retained Windows gates remain green.
