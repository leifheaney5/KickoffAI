# Opta-style analytics — plan location

The audit, architecture, migration strategy, phases, risks and execution order
required by §91 live in **[../MASTER_PLAN.md](../MASTER_PLAN.md)**.

It is at the repository root because that is where every other plan in this
project lives (`PRODUCT_VISION.md`, `EYE_PLAN.md`, `CLUB_PLAN.md`,
`HARDWARE_PROPOSAL.md`), and splitting the master plan away from its siblings
would make it harder to find, not easier.

Section mapping:

| §91 requires | Master plan section |
|---|---|
| Current architecture | 2. Current state audit |
| Existing capabilities | 2. (reusable as-is) |
| Missing capabilities | 2. + 3. |
| Schema changes | 4. Target architecture · Phase 1 |
| Migration strategy | Phase 1 (Alembic) |
| Implementation phases | 6. Phases |
| Risks | 9. Risks |
| Technical debt | 2. + 9. |
| Recommended execution order | 11. Immediate execution order |
