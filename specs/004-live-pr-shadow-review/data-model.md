# Data Model: Live PR Shadow Review

## `RepositoryIntegration`

Explicit opt-in for `owner/name`, baseline provider, baseline wait policy and
private publication policy. No repository is live-enabled by inference.

## `LivePRSnapshot`

Immutable `repository`, `pr_number`, `base_sha`, `head_sha` and `diff_sha256`.
The tuple `(repository, pr_number, base_sha, head_sha)` is the observation key.
The captured diff artifact is addressed by its digest and is never refreshed for
an existing observation.

## `LivePRObservation`

One operational-only record for a snapshot. Its revision identity never changes;
its lifecycle is `queued`, `running_challengers`, `complete`,
`baseline_incomplete` or `challenger_failed`. It is not a Corpus item and cannot
produce a Gold score.

## `LiveChallengerAttempt`

One gito or PR-Agent execution with copied Base/Head SHA, terminal state,
duration and error. Failures are records, not zero findings.

## `LiveChallengerResult`

An immutable terminal attempt plus normalized findings. A successful result
always carries a findings set (which may be empty); a failure carries no
findings at all. It is written once per `(observation, challenger)` and the
private renderer reads only these captured artifacts, never mutable PR refs.

## `CodeRabbitSnapshot`

Normalized CodeRabbit findings plus the exact `head_sha` that CodeRabbit
reviewed and a capture timestamp. The store rejects the snapshot unless this
SHA equals the observation Head SHA, accepts only `coderabbit` findings and
writes the artifact once. Replays return the original stored baseline rather
than replacing it.

## `ResourceLease`

The local `local-94gb-gpu` resource has capacity one. A worker atomically
acquires a durable token before it runs any pending challenger, renews it when
needed and releases only its own token. Expired tokens are reclaimed by the
next worker, so a crashed process cannot permanently block the queue. The
initial SQLite implementation coordinates workers on the same GPU host behind
an interface that can later receive the PostgreSQL control-plane adapter.

## Storage boundary

The initial store is append-only filesystem state for testable idempotency. A
later control-plane feature migrates it to PostgreSQL/objects without changing
the snapshot identity or serial-execution contract.
