# Implementation Plan: Live PR Shadow Review

## Delivery order

1. Persist immutable, idempotent PR revision observations.
2. Execute gito and PR-Agent in stable order under a shared one-slot resource
   lease.
3. Capture an immutable diff/CodeRabbit baseline tied to the stored SHA pair.
4. Add GitHub event intake and private comparison rendering.
5. Use the durable local Run Engine lease for the one GPU host; supply a
   PostgreSQL-backed implementation when workers span hosts.

## Constitution check

- **Provenance**: Base/Head SHA and diff digest identify every observation.
- **Ground Truth**: CodeRabbit is operational-only, never Gold truth.
- **Isolation**: Challengers consume the captured snapshot, not mutable refs.
- **Resource honesty**: one `local-94gb-gpu` lease serializes local execution
  across workers and processes.
- **Security**: live output stays private; no PR comments are posted.
