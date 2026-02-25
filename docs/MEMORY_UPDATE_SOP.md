# Memory Update SOP

## Purpose
This SOP keeps handoff memory consistent, safe, and machine-readable after each milestone.

## Update Trigger
- Default trigger: after each milestone (feature rollout, migration, major fix, production config change).

## Files In Scope
- `docs/HANDOFF_GLOBAL_MEMORY.md`
- `docs/NODE_*.md`
- `docs/MEMORY_INDEX.json`

## Required Section Shape (Markdown)
Each memory markdown file must keep these sections:
1. `Snapshot Baseline`
2. `Operational Commands`
3. `Known Risks And Gotchas`
4. `Milestone Changelog`

## Sensitive Data Rule (Partial Masking)
- Never store full plaintext password/token/secret.
- Mask pattern: keep short prefix and suffix only, middle replaced with `***`.
- Never include full DSN with embedded password.
- In public docs, use masked domain/IP placeholders.

## Update Steps
1. Update baseline facts in `HANDOFF_GLOBAL_MEMORY.md` if architecture or interfaces changed.
2. Update node file (`NODE_*.md`) with node-specific runtime/migration/process changes.
3. Append exactly one milestone entry in both global and node changelog sections.
4. Update `MEMORY_INDEX.json`:
   - `last_updated_at_utc`
   - `recent_milestones[0]`
   - any changed capabilities/endpoints/known risks
5. Run validation checklist.

## Validation Checklist
- Structure
  - [ ] all required files exist
  - [ ] markdown files include required section headers
  - [ ] `MEMORY_INDEX.json` is valid JSON
- Consistency
  - [ ] paths in `MEMORY_INDEX.json` exist
  - [ ] latest milestone date aligns between global and node docs
  - [ ] endpoint names in docs match current API implementation
- Security
  - [ ] no obvious full secret-like assignment in docs
  - [ ] no unmasked real production domain/IP literals in public docs

## Suggested Verification Commands
- JSON validity:
  - `python -m json.tool docs/MEMORY_INDEX.json > /dev/null`
- Required headers check:
  - `rg -n "^## (Snapshot Baseline|Operational Commands|Known Risks And Gotchas|Milestone Changelog)" docs/*.md`
- Sensitivity scan:
  - `rg -n "(?i)(api[_-]?key|bot[_-]?token|jwt[_-]?secret)\\s*[:=]\\s*\\S+" docs .env.example`

## Ownership
- Primary maintainer: active implementation agent for current milestone.
- Reviewer: operator who owns production rollout.
