# BioJob Resume and Tracker Delivery Plan

## Goal

Deliver an offline-capable, evidence-locked resume and application-tracker workflow inside the BioJob desktop app.

## Product rules

- Imported `.docx` and `.pdf` files are copied into the BioJob data directory and extracted into **pending** facts only.
- A generated resume is allowed only for a job whose application status is `preparing`.
- Resume content may use only `confirmed` facts visible to `resume` or `both`; pending, rejected, private, and conflicted facts must never appear.
- Every resume version is immutable, content-hashed, persisted, and traceable to the exact fact IDs used.
- The application workbook contains `投递总表`, `候选岗位`, `本周行动`, and `数据字典`, with clickable JD/apply/careers/match/resume links.
- Exports are local-only and never auto-apply or transmit personal data.

## Implementation

1. Add exact-pinned document dependencies and safe document extract/generation helpers.
2. Add repository and service operations for profile documents and resume versions.
3. Add strict FastAPI request models and routes for document import, resume generation/listing, and tracker export.
4. Add desktop API types and controls for importing a base resume, reviewing pending facts, generating a targeted Word resume, exporting Excel, and revealing files.
5. Verify through red/green tests, complete BioJob regression, DOCX rendering, workbook structural/visual inspection, desktop tests, lint, typecheck, and production build.

## Verification commands

- Python tests only through `scripts/run_tests.sh`.
- Desktop focused tests: `npm run test:ui -- src/app/biojob`.
- Desktop static checks: `npm run typecheck` and `npm run lint -- --quiet`.
- Production build: `npm run build`.
- Render a generated DOCX to PNG and inspect every page.
- Import/render the generated XLSX with the spreadsheet artifact runtime and inspect sheet names, links, formulas, and representative ranges.
