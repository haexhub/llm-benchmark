# Feature Specification: Live PR Shadow Review

**Feature Branch**: `004-live-pr-shadow-review`  
**Created**: 2026-09-22  
**Status**: Implemented
**Input**: Run gito and PR-Agent for every opted-in PR alongside CodeRabbit,
using one immutable PR revision and serialized local execution.

## User Scenarios & Testing

### User Story 1 - Preserve one comparable observation per PR revision (Priority: P1)

For every opened or synchronized PR in an opted-in repository, the operator gets
one immutable observation containing repository, PR number, Base SHA and Head
SHA. CodeRabbit, gito and PR-Agent results are always attached only to that
observation.

**Why this priority**: Comparisons are invalid if reviews from different commits
are mixed.

**Independent Test**: Submit two events for the same PR with different Head
SHAs and verify two distinct observations; retrying either event creates none.

**Acceptance Scenarios**:

1. **Given** an opted-in repository and PR Head `H`, **When** its event arrives,
   **Then** the system creates exactly one `live_pr_shadow` observation for its
   repository, PR, Base SHA and `H`.
2. **Given** Head `H2` after `H`, **When** its event arrives, **Then** `H2`
   receives a new observation and does not overwrite `H`.

---

### User Story 2 - Run local challengers serially (Priority: P1)

The operator sees gito and PR-Agent evaluate the exact captured PR snapshot,
one after the other, because the shared local GPU resource has capacity one.

**Why this priority**: Concurrent local execution would distort results and can
exhaust the available 94 GB GPU RAM.

**Independent Test**: Queue both challengers using test doubles that record
their active interval; verify no overlap and that each result retains the same
Base/Head SHA.

**Acceptance Scenarios**:

1. **Given** a queued live observation, **When** it is processed, **Then** gito
   and PR-Agent receive the exact stored snapshot and never execute concurrently.
2. **Given** one challenger fails, **When** it exits, **Then** its failure and
   timing are retained and the other challenger can still run.

---

### User Story 3 - Compare CodeRabbit as an operational baseline (Priority: P2)

When CodeRabbit output becomes available for the captured Head SHA, the operator
can inspect a private three-way comparison. CodeRabbit is a baseline for live
operations, never Gold Ground Truth or a benchmark score.

**Independent Test**: Attach a mocked CodeRabbit snapshot to an observation and
verify all three normalized finding sets reference the same Head SHA.

**Acceptance Scenarios**:

1. **Given** CodeRabbit is present for Head `H`, **When** baseline capture
   completes, **Then** the observation is `complete` after challengers finish.
2. **Given** CodeRabbit is absent after the wait window, **When** challengers
   finish, **Then** the observation is `baseline_incomplete`, not scored as
   Gold evaluation.

## Edge Cases

- An event for a repository without explicit opt-in is ignored.
- A duplicate event is idempotent.
- A later Head SHA never consumes prior challenger outputs.
- A challenger failure, timeout or unparsable output is retained as a failed
  attempt, never as a zero-finding review.
- New PR activity can queue another observation while an older one finishes;
  neither may run a local challenger concurrently with another observation.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST persist immutable live observations keyed by
  repository, PR number, Base SHA and Head SHA.
- **FR-002**: Repository participation MUST be explicit configuration.
- **FR-003**: Challenger attempts MUST use the observation's captured snapshot,
  never freshly fetched mutable PR refs.
- **FR-004**: All local challenger attempts MUST execute through one serialized
  queue in this feature; no two may overlap.
- **FR-005**: CodeRabbit snapshots MUST record the Head SHA they represent and
  be rejected when it differs from the observation.
- **FR-006**: States MUST distinguish `queued`, `running_challengers`,
  `complete`, `baseline_incomplete` and `challenger_failed`.
- **FR-007**: Live observations and comparisons MUST be private by default;
  no challenger posts PR comments in this feature.
- **FR-008**: Live results MUST be marked operational and MUST NOT enter the
  Ground-Truth scorecards.

### Key Entities

- **RepositoryIntegration**: Explicit repository opt-in and baseline policy.
- **LivePRObservation**: Immutable PR revision plus baseline/challenger state.
- **LiveAttempt**: One challenger execution, exact snapshot identity, timings,
  terminal result and artifact reference.
- **CodeRabbitSnapshot**: Normalized baseline findings tied to one Head SHA.

## Success Criteria

- **SC-001**: Duplicate events create zero duplicate observations in automated
  tests.
- **SC-002**: Two challenger attempts never overlap in automated tests.
- **SC-003**: Every stored challenger result has the observation's exact Base
  and Head SHA.
- **SC-004**: A missing CodeRabbit baseline is visibly `baseline_incomplete`
  and never represented as a Gold score.

## Assumptions

- GitHub webhook plumbing can call a Python event-ingest interface; a CLI/manual
  caller is sufficient for the initial testable slice.
- Existing gito and PR-Agent adapters remain the command executors, but are
  invoked from a serialized scheduler rather than the legacy parallel pipeline.
- PostgreSQL/control-plane migration is a later Run Engine feature; this slice
  starts with versioned local state to establish the immutable contract.
