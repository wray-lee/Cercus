# Agent Instructions & Guidelines

## Git Identity & Commit Boundary (CRITICAL)
- **Author / Committer**: MUST be `wray-lee <i@wray7.top>` (verified GitHub primary email).
- **Rule**: Never override local `.git/config` with secondary or unlinked emails (e.g. `wray.lee@outlook.com`).
- **Verification**: Always ensure `git config user.email` returns `i@wray7.top` before committing.

## Architectural Boundaries & Domain Model
- See `CONTEXT.md` for domain model, ubiquitous language, and system topology.
- See `BOUNDARY.md` for process isolation and global constraints.
