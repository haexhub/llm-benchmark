# Implementation Plan: Live PR Shadow Review

## Delivery order

1. Persist immutable, idempotent PR revision observations.
2. Serialize gito and PR-Agent through one local challenger scheduler.
3. Capture an immutable diff/CodeRabbit baseline tied to the stored SHA pair.
4. Add GitHub event intake and private comparison rendering.
5. Replace the process-local scheduler with the shared transactional GPU lease
   when the Run Engine feature is delivered.

## Constitution check

- **Provenance**: Base/Head SHA and diff digest identify every observation.
- **Ground Truth**: CodeRabbit is operational-only, never Gold truth.
- **Isolation**: Challengers consume the captured snapshot, not mutable refs.
- **Resource honesty**: one scheduler lock serializes local execution.
- **Security**: live output stays private; no PR comments are posted.
