---
name: "iterate issues"
description: "Review verified RTI Doctor findings one at a time and record user decisions"
argument-hint: "Optional finding ID, category, or 'next'"
agent: "agent"
---

Review RTI Doctor findings one at a time. Requested scope: ${input:scope:next}.

Sources of truth:

- `tools/rti_doctor/docs/CODE_REVIEW_2026-08-07.md`
- `tools/rti_doctor/docs/DESIGN_DECISIONS.md`
- Current source and focused tests when a finding needs revalidation.

Workflow:

1. Read the decision log first. Do not revisit a finding with a recorded decision unless the user asks to reconsider it.
2. Select exactly one unresolved finding matching the requested scope. If the scope is `next`, choose the highest-priority verified finding. Do not batch findings.
3. Recheck the finding against current source before presenting it. If it is stale, unsupported, or only partly established, say so plainly and do not ask for a product decision until the missing fact is confirmed.
4. Present only this format:

   ```markdown
   ## <ID>: <short title>

   **Problem**
   <Plain-language description of the current behavior, impact, and evidence.>

   **Option 1: <name>**
   <What changes, benefits, costs, compatibility impact.>

   **Option 2: <name>**
   <What changes, benefits, costs, compatibility impact.>

   **Option 3: <name>**
   <What changes, benefits, costs, compatibility impact.>

   **Recommendation**
   <One option and the concrete reason it best fits this codebase.>

   **Decision needed**
   Choose Option 1, 2, 3, or provide a different decision.
   ```

5. Stop and wait for the user's decision. Do not modify product code while deciding.
6. After an explicit user decision, immediately update `tools/rti_doctor/docs/DESIGN_DECISIONS.md` with the ID, date, problem summary, selected option, rationale, consequences, and follow-up work. Do not record a recommendation as a decision.
7. Confirm the logged decision briefly, then offer the next unresolved finding. Do not move to it until the user asks.

Decision-log rules:

- Preserve prior entries; never rewrite or remove a decision without explicit user instruction.
- Record alternatives that were rejected only when they materially explain the decision.
- Link each entry to the review finding and affected source files.
- Mark findings needing external DDS or runtime evidence as `Deferred` rather than forcing a design choice.