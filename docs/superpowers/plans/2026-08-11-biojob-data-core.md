# BioJob Data Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 local data core for BioJob Agent: a migrated SQLite store, confirmed personal facts, auditable application state transitions, and authenticated-dashboard REST endpoints.

**Architecture:** Add a standalone `biojob` Python package that owns paths, schema migrations, repositories, and domain services. The existing Hermes FastAPI dashboard mounts one thin BioJob router; handlers run SQLite work in a thread and never store credentials. SQLite remains the source of truth under `HERMES_HOME/biojob/biojob.db`, with foreign keys, WAL, transactions, soft deletion, and append-only audit/event records.

**Tech Stack:** Python 3.11, stdlib `sqlite3`, Pydantic/FastAPI already bundled by Hermes, pytest through `scripts/run_tests.sh`, PowerShell/Git on Windows

---

## Scope and file map

Create or modify only these product files:

```text
biojob/__init__.py                    public package exports
biojob/paths.py                       HERMES_HOME-scoped database path
biojob/schema.py                      ordered migration definitions
biojob/database.py                    connections and atomic migrations
biojob/domain.py                      enums, validation, transition graph
biojob/repository.py                  parameterized SQLite reads/writes
biojob/service.py                     transactions, audit, domain operations
biojob/api_models.py                  request/response validation models
hermes_cli/web_routers/biojob.py      thin async FastAPI adapter
hermes_cli/web_server.py              mount the BioJob router
pyproject.toml                        package `biojob` in installations
tests/biojob/test_database.py         path, pragmas, and migration tests
tests/biojob/test_profile_facts.py    personal fact safety tests
tests/biojob/test_applications.py     job and state-machine tests
tests/biojob/test_api.py              FastAPI contract tests
docs/baseline/hermes-windows-baseline.md  Phase 1 verification appendix
```

Phase 1 does not fetch websites, call an LLM, import a resume, generate Excel, or add desktop screens. It may create a job through the API so the state machine can be exercised before Phase 2 adds source adapters.

### Task 1: SQLite path and migration runner

**Files:**
- Create: `biojob/__init__.py`
- Create: `biojob/paths.py`
- Create: `biojob/schema.py`
- Create: `biojob/database.py`
- Modify: `pyproject.toml:415-416`
- Test: `tests/biojob/test_database.py`

- [x] **Step 1: Write failing database tests**

Create tests that require the database path to follow the active `HERMES_HOME`, create every designed table, enable foreign keys, use WAL, and apply migration 1 exactly once:

```python
from biojob.database import BioJobDatabase
from biojob.paths import biojob_database_path


EXPECTED_TABLES = {
    "schema_migrations", "profile_facts", "profile_documents", "companies",
    "sources", "source_runs", "jobs", "job_sources", "job_snapshots",
    "job_matches", "candidate_decisions", "applications",
    "application_events", "resume_versions", "scheduled_tasks", "audit_log",
}


def test_default_database_path_is_scoped_to_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert biojob_database_path() == tmp_path / "biojob" / "biojob.db"


def test_initialize_creates_schema_and_pragmas(tmp_path):
    db = BioJobDatabase(tmp_path / "biojob.db")
    db.initialize()
    with db.connect() as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        assert EXPECTED_TABLES <= tables
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0] == 1
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
```

- [x] **Step 2: Run the file and verify RED**

Run:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 1 tests/biojob/test_database.py -q
```

Expected: FAIL because the `biojob` package does not exist.

- [x] **Step 3: Implement the path, schema, and migration runner**

Implement these public interfaces:

```python
# biojob/paths.py
from pathlib import Path
from hermes_constants import get_hermes_home

def biojob_data_dir() -> Path:
    return get_hermes_home() / "biojob"

def biojob_database_path() -> Path:
    return biojob_data_dir() / "biojob.db"
```

`biojob/schema.py` exposes `MIGRATIONS: Sequence[tuple[int, str]]`. Migration 1 creates all 15 domain tables plus `schema_migrations`. Every primary key is text, timestamps are UTC ISO-8601 text, JSON fields are text, and these constraints are mandatory:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_facts (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','conflicted')),
    visibility TEXT NOT NULL CHECK(visibility IN ('matching','resume','both','private')),
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, fact_key)
);
CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    company_type TEXT,
    city TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL,
    direction TEXT,
    city TEXT,
    recruitment_type TEXT,
    education_requirement TEXT,
    major_requirement TEXT,
    jd_text TEXT,
    detail_url TEXT,
    apply_url TEXT,
    careers_url TEXT,
    published_at TEXT,
    deadline_at TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK(lifecycle_status IN ('open','closed','unknown')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
    status TEXT NOT NULL CHECK(status IN (
        'considering','preparing','applied','assessment','interview',
        'offer','rejected','withdrawn','expired'
    )),
    applied_at TEXT,
    next_follow_up_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS application_events (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    actor TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
```

Migration 1 also creates the remaining tables with these exact columns and references:

```sql
CREATE TABLE IF NOT EXISTS profile_documents (
    id TEXT PRIMARY KEY, document_type TEXT NOT NULL, original_name TEXT NOT NULL,
    local_path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, adapter_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, health_status TEXT NOT NULL DEFAULT 'unknown',
    last_checked_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_runs (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
    cursor_json TEXT NOT NULL DEFAULT '{}', result_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT, started_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS job_sources (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    source_id TEXT REFERENCES sources(id), external_id TEXT,
    detail_url TEXT, apply_url TEXT, careers_url TEXT,
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1, UNIQUE(job_id, detail_url)
);
CREATE TABLE IF NOT EXISTS job_snapshots (
    id TEXT PRIMARY KEY, job_source_id TEXT NOT NULL REFERENCES job_sources(id),
    content_hash TEXT NOT NULL, raw_jd TEXT NOT NULL, fetched_at TEXT NOT NULL,
    UNIQUE(job_source_id, content_hash)
);
CREATE TABLE IF NOT EXISTS job_matches (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    score REAL NOT NULL CHECK(score >= 0 AND score <= 100), recommendation TEXT NOT NULL,
    evidence_json TEXT NOT NULL, model_provider TEXT, model_name TEXT,
    rule_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_decisions (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    decision TEXT NOT NULL CHECK(decision IN ('pending','kept','ignored','later','error')),
    actor TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume_versions (
    id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id), file_path TEXT NOT NULL,
    facts_json TEXT NOT NULL, template_name TEXT NOT NULL,
    content_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY, task_type TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
    schedule_json TEXT NOT NULL, last_run_at TEXT, next_run_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

No credential column is permitted. `BioJobDatabase.connect()` sets `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`, and WAL. `initialize()` creates the parent directory and applies each unapplied migration inside one `BEGIN IMMEDIATE` transaction.

Add `biojob` and `biojob.*` to `[tool.setuptools.packages.find].include`.

- [x] **Step 4: Verify GREEN and commit**

Run the same test file, then:

```powershell
git add biojob pyproject.toml tests/biojob/test_database.py
git -c user.name='Codex' -c user.email='codex@local' commit -m "feat(biojob): add migrated SQLite data store"
```

Expected: database tests pass and the commit contains only Task 1 files.

### Task 2: Personal fact master

**Files:**
- Create: `biojob/domain.py`
- Create: `biojob/repository.py`
- Create: `biojob/service.py`
- Test: `tests/biojob/test_profile_facts.py`

- [x] **Step 1: Write failing personal-fact tests**

Cover creation as pending, explicit confirmation, visibility filtering, uniqueness, and audit rows:

```python
def test_unconfirmed_fact_is_excluded_from_resume_facts(service):
    fact = service.create_profile_fact(
        category="laboratory",
        fact_key="cell_culture",
        value={"skill": "细胞培养", "level": "performed"},
        source_type="user",
        visibility="both",
        actor="user",
    )
    assert fact["status"] == "pending"
    assert service.list_usable_facts("resume") == []


def test_confirmed_fact_is_visible_and_audited(service):
    fact = service.create_profile_fact(
        category="laboratory",
        fact_key="cck8",
        value={"skill": "CCK-8细胞活性检测"},
        source_type="user",
        visibility="both",
        actor="user",
    )
    confirmed = service.set_profile_fact_status(fact["id"], "confirmed", actor="user")
    assert confirmed["confirmed_at"] is not None
    assert [item["id"] for item in service.list_usable_facts("resume")] == [fact["id"]]
    assert service.list_audit_log(entity_id=fact["id"])[-1]["action"] == "profile_fact.confirmed"
```

Also assert that `private` facts never appear in matching/resume queries, invalid status/visibility raises `DomainValidationError`, and a duplicate `(category, fact_key)` becomes a domain conflict rather than a raw SQLite traceback.

- [x] **Step 2: Run the file and verify RED**

Run through `scripts/run_tests.sh`; expected failure is the missing `BioJobService` behavior.

- [x] **Step 3: Implement minimal fact behavior**

Define string enums and errors in `biojob/domain.py`:

```python
class ProfileFactStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"

class FactVisibility(StrEnum):
    MATCHING = "matching"
    RESUME = "resume"
    BOTH = "both"
    PRIVATE = "private"

class DomainValidationError(ValueError):
    pass

class DomainConflictError(ValueError):
    pass

class DomainNotFoundError(LookupError):
    pass
```

`BioJobRepository` owns parameterized SQL only. `BioJobService` owns UUID generation, UTC timestamps, JSON serialization, transactions, and audit insertion. `list_usable_facts("resume")` returns only `confirmed` facts with `resume` or `both`; matching uses `matching` or `both`.

- [x] **Step 4: Verify GREEN and commit**

Run Task 1 and Task 2 test files, then commit as `feat(biojob): add confirmed profile fact master`.

### Task 3: Jobs and auditable application state machine

**Files:**
- Modify: `biojob/domain.py`
- Modify: `biojob/repository.py`
- Modify: `biojob/service.py`
- Test: `tests/biojob/test_applications.py`

- [x] **Step 1: Write failing state-machine tests**

Use a real temporary SQLite database. Require a new job to receive one `considering` application, keep all three jump links, reject illegal backward/terminal transitions, set `applied_at` only on the first move to `applied`, and append both an application event and audit row:

```python
def test_job_keeps_clickable_source_links_and_initial_application(service):
    job = service.create_job(
        company_name="荣昌生物",
        title="细胞培养技术员",
        city="烟台",
        detail_url="https://example.test/jobs/1",
        apply_url="https://example.test/apply/1",
        careers_url="https://example.test/careers",
        actor="user",
    )
    assert job["application"]["status"] == "considering"
    assert job["detail_url"].startswith("https://")
    assert job["apply_url"].startswith("https://")
    assert job["careers_url"].startswith("https://")


def test_application_transition_is_audited(service, job):
    prepared = service.transition_application(job["id"], "preparing", actor="user")
    applied = service.transition_application(job["id"], "applied", actor="user", note="官网投递")
    assert prepared["status"] == "preparing"
    assert applied["status"] == "applied"
    assert applied["applied_at"] is not None
    assert [e["new_status"] for e in service.list_application_events(job["id"])] == [
        "considering", "preparing", "applied"
    ]
```

- [x] **Step 2: Run and verify RED**

Expected: missing job/application methods.

- [x] **Step 3: Implement the transition graph and service operations**

Use this exact forward-only graph:

```python
APPLICATION_TRANSITIONS = {
    "considering": {"preparing", "withdrawn", "expired"},
    "preparing": {"applied", "rejected", "withdrawn", "expired"},
    "applied": {"assessment", "interview", "offer", "rejected", "expired"},
    "assessment": {"interview", "offer", "rejected", "expired"},
    "interview": {"offer", "rejected", "expired"},
    "offer": set(), "rejected": set(), "withdrawn": set(), "expired": set(),
}
```

`create_job()` upserts the company by canonical name, validates optional URLs to `http` or `https`, inserts the job and initial application/event in one transaction, and audits `job.created`. `transition_application()` locks with `BEGIN IMMEDIATE`, validates the graph, updates the application, appends an event, and writes `application.status_changed`. No method infers that an application was submitted.

- [x] **Step 4: Verify GREEN and commit**

Run all `tests/biojob` files and commit as `feat(biojob): add auditable application workflow`.

### Task 4: Basic BioJob dashboard API

**Files:**
- Create: `biojob/api_models.py`
- Create: `hermes_cli/web_routers/biojob.py`
- Modify: `hermes_cli/web_server.py`
- Test: `tests/biojob/test_api.py`

- [x] **Step 1: Write failing API contract tests**

Mount the router on a small FastAPI app with `HERMES_HOME=tmp_path`. Cover:

```python
def test_create_job_list_and_prepare_application(client):
    created = client.post("/api/biojob/jobs", json={
        "company_name": "齐鲁制药",
        "title": "生物工艺技术员",
        "city": "济南",
        "detail_url": "https://example.test/jobs/7",
        "apply_url": "https://example.test/apply/7",
        "careers_url": "https://example.test/campus",
    })
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert client.get("/api/biojob/jobs").json()["items"][0]["id"] == job_id
    prepared = client.post(f"/api/biojob/jobs/{job_id}/prepare-application")
    assert prepared.status_code == 200
    assert prepared.json()["application"]["status"] == "preparing"


def test_dashboard_counts_application_states(client):
    response = client.get("/api/biojob/dashboard")
    assert response.status_code == 200
    assert response.json()["application_counts"]["preparing"] == 1
```

Also cover profile fact create/confirm, `404` for missing entities, `409` for duplicate facts or illegal transitions, `422` for invalid URLs/input, job patching of notes/follow-up/status, and soft-delete exclusion.

- [x] **Step 2: Run and verify RED**

Expected: router import or route lookup failure.

- [x] **Step 3: Implement models and thin async handlers**

Provide these routes:

```text
GET    /api/biojob/dashboard
GET    /api/biojob/profile-facts
POST   /api/biojob/profile-facts
PATCH  /api/biojob/profile-facts/{fact_id}
GET    /api/biojob/jobs
POST   /api/biojob/jobs
GET    /api/biojob/jobs/{job_id}
PATCH  /api/biojob/jobs/{job_id}
POST   /api/biojob/jobs/{job_id}/prepare-application
GET    /api/biojob/jobs/{job_id}/events
```

Pydantic request models reject blank company/title/category/key, accept only `http`/`https` job links, and cap free text fields. Every handler calls `BioJobService` via `asyncio.to_thread`. Map `DomainNotFoundError` to 404, `DomainConflictError` and illegal transitions to 409, and validation errors to 422. Do not return SQLite errors or filesystem paths.

Mount with:

```python
from hermes_cli.web_routers import biojob as _biojob_routes
app.include_router(_biojob_routes.router)
```

- [x] **Step 4: Verify GREEN and dashboard integration**

Run `tests/biojob/test_api.py` and one existing dashboard-auth test file to confirm `/api/biojob/*` remains protected by the existing auth middleware when mounted on the real app.

- [x] **Step 5: Commit**

Commit as `feat(biojob): expose local data core API`.

### Task 5: Phase 1 verification and documentation

**Files:**
- Modify: `docs/baseline/hermes-windows-baseline.md`
- Modify: `docs/superpowers/plans/2026-08-11-biojob-data-core.md`

- [x] **Step 1: Run the complete BioJob suite**

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh -j 4 tests/biojob -q
```

Expected: all BioJob files pass with no failures.

- [x] **Step 2: Run installation, packaging, and targeted upstream gates**

Run the nine Windows regression files recorded in the baseline, `npm --prefix apps/desktop run build`, and `powershell.exe -File scripts/baseline/check-capabilities.ps1`. Confirm `python -c "import biojob"` works from the synced `.venv` after `uv sync --locked`.

- [x] **Step 3: Inspect the created SQLite schema for secret-shaped columns**

Create a temporary database, query `pragma_table_info` for every table, and fail if a column name contains `api_key`, `token`, `cookie`, `password`, or `secret`.

- [x] **Step 4: Update the baseline report and plan checkboxes**

Append exact commands and counts under a `Phase 1 data core` section. Preserve the existing upstream-test exceptions and do not change their status to passing.

- [ ] **Step 5: Final repository verification and commit**

Run `git diff --check`, verify the pinned Hermes commit remains an ancestor, ensure no database or credentials are tracked, then commit as `docs: record BioJob data core verification` and push `biojob-main`.

## Phase 1 completion criteria

- A fresh `HERMES_HOME` creates the complete version-1 schema atomically.
- Confirmed facts are the only facts available to matching/resume consumers.
- Every mutation writes an audit row; every application status change writes an event.
- Illegal or backward application transitions are rejected.
- Job detail, application, and careers links survive API round trips.
- BioJob API routes work through the Hermes dashboard and inherit its authentication boundary.
- No credential-shaped field exists in the BioJob database.
- Phase 1 tests and the retained Windows regression/build gates pass.
- No Phase 2 discovery, matching, resume, Excel, or GUI feature is included.
