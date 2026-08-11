# BioJob Matching and Desktop Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user explicitly prohibited subagents, so execution stays inline.

**Goal:** Deliver an offline-first, evidence-backed undergraduate job matcher and a dedicated BioJob desktop workbench for reviewing candidates, managing applications, facts, sources, and provider setup.

**Architecture:** Keep SQLite and domain rules authoritative in the Python backend and expose a narrow authenticated REST surface. Add BioJob as a contributed desktop route/sidebar destination so it remains isolated from the Hermes chat core. Matching is deterministic and explainable; configured Hermes providers remain available for later resume drafting without storing credentials in BioJob SQLite.

**Tech Stack:** Python 3.11+, SQLite, FastAPI/Pydantic, React 19, TypeScript, TanStack Query, Tailwind 4, Vitest/Testing Library, existing Hermes Electron bridge and design primitives.

---

## File map

- `biojob/matching.py`: pure hard-rule and weighted evidence matcher.
- `biojob/repository.py`: match insert/latest-read queries.
- `biojob/service.py`: transactional match generation/read contract.
- `biojob/api_models.py`: strict match request shape.
- `hermes_cli/web_routers/biojob.py`: match endpoints.
- `tests/biojob/test_matching.py`: matcher and persistence behavior.
- `tests/biojob/test_matching_api.py`: authenticated HTTP contract.
- `apps/desktop/src/app/biojob/types.ts`: renderer DTOs.
- `apps/desktop/src/app/biojob/api.ts`: typed REST boundary through `window.hermesDesktop.api`.
- `apps/desktop/src/app/biojob/query.ts`: query keys and invalidation rules.
- `apps/desktop/src/app/biojob/index.tsx`: workbench route shell.
- `apps/desktop/src/app/biojob/*.tsx`: overview, candidate, application, fact, source, and detail views.
- `apps/desktop/src/app/biojob/register.tsx`: route/sidebar contributions.
- `apps/desktop/src/app/biojob/*.test.ts(x)`: DTO, API, navigation, state, and interaction tests.
- `apps/desktop/src/app/contrib/controller.tsx`: one side-effect import for the core contribution.
- `apps/desktop/src/i18n/{en,ja,zh,zh-hant}.ts`: all BioJob user-facing strings.

### Task 1: Pure evidence matcher

- [ ] Add tests proving: PhD/master-only, mandatory full-time experience, excluded direction, wrong cohort, and closed/expired jobs block; “preferred” language is only a risk.
- [ ] Run `scripts/run_tests.sh tests/biojob/test_matching.py` and confirm RED because `biojob.matching` is absent.
- [ ] Implement `match_job(job, confirmed_facts)` returning `{score, level, recommendation, blocked, hard_rules, dimensions, gaps, confidence, rule_version}` with weights 25/20/25/10/10/10 and no unsupported evidence.
- [ ] Re-run and confirm GREEN; commit `feat(biojob): add evidence-backed job matcher`.

### Task 2: Persist and expose latest match

- [ ] Add repository/service tests proving match generation uses only confirmed matching-visible facts, stores immutable reports, returns newest first, and fails closed on corrupt JSON.
- [ ] Run the focused Python test and confirm RED for missing service methods.
- [ ] Implement `insert_job_match`, `get_latest_job_match`, `list_job_matches`, `match_job`, and `get_latest_match`; write audit metadata without JD/fact contents.
- [ ] Add `POST /api/biojob/jobs/{job_id}/match` and `GET /api/biojob/jobs/{job_id}/match`, validate provider/model labels as optional metadata only, and map missing reports to 404.
- [ ] Run BioJob matching/API tests and confirm GREEN; commit `feat(biojob): persist and expose match reports`.

### Task 3: Typed desktop data boundary

- [ ] Add Vitest tests for every endpoint path, body, query encoding, and non-mutating DTO normalization.
- [ ] Run the focused UI test and confirm RED because `app/biojob/api.ts` is absent.
- [ ] Implement DTOs and API functions for dashboard, candidates, jobs, facts, sources/runs, decisions, status changes, and match reports through the existing Electron API bridge.
- [ ] Re-run focused tests and typecheck; commit `feat(desktop): add BioJob API client`.

### Task 4: Register a dedicated workspace destination

- [ ] Add route tests proving `/biojob` is a contributed full page, never parsed as a chat session, and has a sidebar destination labelled from i18n.
- [ ] Confirm RED before registration.
- [ ] Register the route and sidebar contribution from the desktop controller and lazy-load the workbench.
- [ ] Add matching strings to all four locales and confirm route tests GREEN; commit `feat(desktop): register BioJob workspace`.

### Task 5: Workbench overview and resilient states

- [ ] Add component tests for loading, empty, API error with retry, dashboard counts, due follow-ups, and provider-settings deep link.
- [ ] Confirm RED before components exist.
- [ ] Implement a flat three-region workbench: compact section rail, actual workflow content in the first viewport, and contextual detail; reuse `Loader`, `ErrorState`, `EmptyState`, `Button`, `SearchField`, and design tokens.
- [ ] Add reduced-motion-safe entrance and responsive single-column fallback without raw colors or nested cards.
- [ ] Confirm focused tests and visual build GREEN; commit `feat(desktop): add BioJob overview`.

### Task 6: Candidate review and manual import

- [ ] Add tests for search/filter, detail/apply/careers links, keep/later/ignore decisions, optimistic rollback, and strict manual import.
- [ ] Confirm RED, then implement list/detail/import interactions and authoritative refresh after mutations.
- [ ] Confirm focused tests GREEN; commit `feat(desktop): add candidate review workflow`.

### Task 7: Application board and match report

- [ ] Add tests for lifecycle columns, legal next-state actions, follow-up editing, notes, clickable links, match run, evidence dimensions, hard blocks, gaps, and missing-JD guidance.
- [ ] Confirm RED, then implement application table/board and evidence report without auto-apply behavior.
- [ ] Confirm focused tests GREEN; commit `feat(desktop): add application and match workspace`.

### Task 8: Facts and sources

- [ ] Add tests for pending/confirmed/rejected facts, visibility labels, source enable/run state, per-source failure isolation, and no credential fields.
- [ ] Confirm RED, then implement fact review and source status/run screens.
- [ ] Confirm focused tests GREEN; commit `feat(desktop): add facts and source controls`.

### Task 9: Phase verification and documentation

- [ ] Run focused BioJob Python tests only via `scripts/run_tests.sh`, then BioJob + auth regression.
- [ ] Run focused Vitest, TypeScript typecheck, lint, and production desktop build.
- [ ] Start the local desktop backend with a temporary `HERMES_HOME`, exercise create/import/match/decision/status endpoints through the real server, and record exact counts.
- [ ] Update this checklist, the baseline report, and the user-facing design status; commit and push Phase 3.

## Self-review

- Spec coverage: hard gating, weighted evidence, confirmed-fact boundary, candidate/application/facts/sources UI, links, provider entry, resilient states, and auth are each assigned.
- Placeholder scan: no deferred implementation or unspecified error-handling steps remain.
- Type consistency: backend uses `match_job/get_latest_match`; renderer uses `BioJobMatchReport`; `/jobs/{id}/match` is the sole match endpoint pair.
