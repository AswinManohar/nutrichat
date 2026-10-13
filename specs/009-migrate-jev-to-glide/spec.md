# Feature Specification: Move routing judgments from TypeSafe Jev to Fastino GLiDE

**Feature Branch**: `009-migrate-jev-to-glide` · **Created**: 2026-10-13 · **Status**: Draft

**Input**: "i want to move from jev to fastino glide model."

> Written during `/speckit-plan` from the one-line input above, because no
> `/speckit-specify` run preceded it. It restates the request as testable
> requirements and carries over the guarantees of
> [001-jev-intent-routing](../001-jev-intent-routing/spec.md). Review it before
> `/speckit-tasks`.

## What changes for users

Nothing visible. A fresh chat message is still routed to meal logging or to the
coach by a calibrated judgment, with Gemini as the safety net. Only the service
that answers the judgment changes.

## User Story 1 - Messages keep landing in the right place (P1)

A user sends "greek yogurt" or "is oatmeal good for cholesterol?" and gets a
meal card or a coaching reply exactly as today.

**Acceptance**

1. **Given** the routing evaluation set, **When** it runs against GLiDE,
   **Then** accuracy is no lower than Jev's recorded result (100%, PR #27).
2. **Given** a question that also reports food ("I had pizza, was that bad?"),
   **When** the coach replies, **Then** the offer to log still appears.

## User Story 2 - The chat is no slower (P1)

**Acceptance**

1. **Given** the production container, **When** the routing request is timed,
   **Then** it meets the same bar as Jev did (p50 < 300 ms, p95 < 800 ms).
2. **Given** GLiDE is slow, warming up, out of credit or down, **When** a
   message arrives, **Then** Gemini routes it within the existing wait limit.

## User Story 3 - One judgment provider (P2)

The operator configures one key and one model. The TypeSafe SDK, key and model
name are gone from code, config and docs.

## Requirements

- **FR-001**: Every fresh text message MUST be judged by Fastino GLiDE
  (`POST /v1/systemone`) with the same three questions and the same decision
  rule as today.
- **FR-002**: All guarantees of spec 001 MUST still hold: FR-005 (no usage
  credit spent on routing), FR-006/007 (bounded wait, no retries on the reply
  path, Gemini decides when the judgment is unavailable), FR-008 (works with no
  key configured), FR-010 (path and probabilities recorded), FR-015 (only the
  message text is sent).
- **FR-003**: Decision thresholds MUST be re-derived from GLiDE's scores on the
  evaluation set. Jev's thresholds MUST NOT be assumed to transfer.
- **FR-004**: GLiDE's response time MUST be measured from the production
  hosting location before any user traffic is routed by it.
- **FR-005**: The `typesafe-sdk` dependency, `TYPESAFE_API_KEY` and
  `jev-latest` MUST be removed once no reference remains.
- **FR-006**: Each recorded routing decision MUST say which model judged it, so
  records from before and after the move can be told apart.
- **FR-007**: Token usage of each judgment MUST be recorded, so cost per 1,000
  messages can be read from production traces.
- **FR-008**: The memory save decision (`agent/memory_judge.py` on
  `feat/preference-memory`, issue #61) MUST use the same GLiDE client. It is
  ported after this feature merges, not inside it.

## Success Criteria

- **SC-001**: Routing gate on GLiDE over 5 runs: at least 95% correct and no
  worse than Jev's recorded result on the same 88 cases (100%, PR #27).
- **SC-002**: From the Railway `web` container at concurrency 1: p50 < 300 ms
  and p95 < 800 ms. No-go if p50 > 500 ms.
- **SC-003**: With GLiDE unreachable, 100% of turns complete and none waits
  longer than the configured limit.
- **SC-004**: At least 90% of fresh messages are decided by the judgment alone
  (not the Gemini second opinion), as under Jev.
- **SC-005**: `grep -ri typesafe` over source, config and current docs returns
  nothing outside historical spec folders.

## Out of scope

- New judgment questions or changes to question wording beyond what GLiDE's
  request validation forces.
- GLiNER, fine-tuning, or any other Fastino product.
- Changing the Gemini safety net.

## Assumptions

- The owner has a funded Fastino account; the key is provided as
  `FASTINO_API_KEY` in Railway and local `.env`, never in the repository.
- GLiDE pricing is $0.15 per million input tokens with free output (docs, read
  2026-10-13).
