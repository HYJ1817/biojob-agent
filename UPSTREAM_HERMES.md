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
