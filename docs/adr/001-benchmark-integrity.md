# ADR 001: Benchmark Integrity and Resource Policy

**Status**: Accepted, 2026-09-22

## Context

The initial PR-review spike compares output overlap with CodeRabbit and runs
gito/PR-Agent concurrently. This is insufficient for a durable ranking and
violates the one-local-model hardware constraint.

## Decision

- Decision-grade rankings use independent versioned Ground Truth; historical
  CodeRabbit overlap is a distinct legacy/realism observation.
- Each evaluation is an immutable Attempt with versioned manifest/artifacts.
- Runners use fresh isolated worktrees and never receive protected oracle data.
- `local-94gb-gpu` has capacity one; queue wait and running time are distinct.
- Quality, reliability, latency and cost remain separate metrics. Weighted ranks
  require an explicit versioned policy and disclosed weights.

## Consequences

PostgreSQL-backed leases and artifact provenance precede a dashboard. Existing
file-based runs remain readable but cannot be promoted to scored attempts without
their missing provenance. Benchmarks take longer under serialization, but their
latency and failure measurements become interpretable.
