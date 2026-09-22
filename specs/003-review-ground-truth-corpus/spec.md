# Feature Specification: Versioned Ground-Truth Review Corpus

**Feature Branch**: `003-review-ground-truth-corpus`
**Created**: 2026-09-22
**Status**: Draft
**Input**: Establish an extensible, reproducible review corpus of known-bug PRs
for comparing CodeRabbit, gito, PR-Agent and future reviewers. Cases may come
from approved public sources, de-identified own repositories, synthetic projects
or a combination. The corpus must be fair across model/harness configurations and
must provide decision-grade Ground Truth without exposing it to review runners.

## Clarifications

### Session 2026-09-22

- The corpus is the decision-grade review-quality suite. Continuous live PR
  observations use CodeRabbit as operational baseline but never replace this
  Ground Truth.
- Every corpus item is a frozen PR-shaped pair of Base and Head revisions. The
  Head contains zero to three independently reviewable known defects.
- Goldlabels and reproducers are physically separated from public runner input.
  They are available only to curator/evaluator infrastructure after a runner
  exits.
- The public development/calibration corpus repository is
  `haexhub/llm-benchmark-review-corpus`; the protected holdout Oracle repository
  is `haexhub/llm-benchmark-review-oracle` and remains private.
- Sources may be public, internal/de-identified or synthetic. Every item records
  provenance, licence/approval, reproducibility and contamination status.
- The initial release has `development`, `calibration` and protected `holdout`
  partitions. Calibration is non-ranking and checks adapters after tool updates.
- Review utility is more than comment count: correctness, actionability,
  severity calibration, redundancy and reviewer attention burden are measured.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Publish a reproducible labelled review item (Priority: P1)

A curator creates an item from an approved source, freezes Base and Head commits,
defines its public runner manifest and protects its defect labels/reproducers.
The item is accepted only if a validator proves that it can be rebuilt and its
known defects have evidence.

**Why this priority**: Without trustworthy, reproducible known positives and
negatives, reviewer ranking measures output similarity instead of quality.

**Independent Test**: Validate a fixture whose Base/Head SHA, public manifest,
protected label, reproducer and approval record are known; validation rejects any
missing or inconsistent component.

**Acceptance Scenarios**:

1. **Given** an approved source snapshot, **When** a curator publishes an item,
   **Then** its public manifest contains a content digest and immutable Base/Head
   SHAs, while its protected Gold data is absent from runner input.
2. **Given** a labelled defect, **When** corpus validation runs, **Then** its
   reproducer proves the intended behavior on the pinned Head revision and its
   scope exists in that revision.

---

### User Story 2 - Release a balanced benchmark suite (Priority: P1)

An evaluator selects a suite version that covers realistic languages, defect
classes, severity, diff sizes and clean PR controls. The system reports coverage
gaps rather than presenting a narrow corpus as a universal result.

**Why this priority**: An easily guessed or homogeneous synthetic suite creates
overfitting and misleading rankings.

**Independent Test**: Generate coverage from a fixture-only v1 suite and verify
counts by source, partition, language, category, severity, diff size, difficulty
and clean-control status.

**Acceptance Scenarios**:

1. **Given** a proposed v1 suite, **When** it is released, **Then** it has at
   least 24 items, 20% clean controls and documented coverage across selected
   Python and TypeScript/Nuxt strata.
2. **Given** an uncovered category or source imbalance, **When** a curator views
   the coverage report, **Then** it is shown as a gap and the release requires a
   recorded exception or remains draft.

---

### User Story 3 - Score reviewer findings against Ground Truth (Priority: P1)

An evaluator maps normalized findings from one review attempt to Gold defects or
explicit non-matches. The result separates factual detection from the usefulness
of communicating the finding.

**Why this priority**: A reviewer can find the right defect with a bad comment,
or write polished but false comments; both dimensions matter operationally.

**Independent Test**: Evaluate a fixture result containing a true positive,
wrong-line true defect, duplicate, false positive, unknown plausible finding and
unmatched Gold defect; assert the expected metrics and audit queue entries.

**Acceptance Scenarios**:

1. **Given** a finding mapping to a Gold defect, **When** evaluation completes,
   **Then** recall/precision and severity-weighted metrics use the Gold severity,
   not a tool's self-declared severity.
2. **Given** an unmatched finding, **When** it is plausible or high impact,
   **Then** it is presented blind for frontier-judge triage and, according to
   policy, human adjudication instead of being silently considered correct.

---

### User Story 4 - Keep adapters and holdout trustworthy over time (Priority: P2)

When a tool/harness/model integration changes, an operator runs its calibration
partition before it can contribute to a ranking. Curators can retire contaminated
or flaky holdout items without rewriting released history.

**Why this priority**: This is a long-running study; unobserved tool drift and
benchmark leakage would otherwise invalidate trends.

**Independent Test**: Change a fixture's expected output schema and prove a
candidate fails calibration; mark a holdout item contaminated and verify past
results remain reproducible but future decision-grade reports exclude it.

**Acceptance Scenarios**:

1. **Given** a changed candidate version, **When** its calibration items fail,
   **Then** it cannot enter a scored holdout execution plan.
2. **Given** a released holdout item found to be leaked or flaky, **When** it is
   retired, **Then** the system records the reason and replacement suite version
   without altering prior manifests or scores.

## Edge Cases

- A real internal PR cannot be fully de-identified or approved for retention:
  it is rejected; create an approved synthetic analogue if useful.
- A source licence forbids redistribution: retain only an approved internal
  reference or exclude it from the corpus.
- A defect needs production infrastructure or network data to reproduce: it is
  quarantined until a deterministic local reproducer exists.
- A clean control attracts a valid extra finding: it enters the unknown-finding
  adjudication flow, not an automatic false-positive bucket.
- A reviewer finds the same defect in another file or line range: Gold mapping
  may match it if adjudication confirms the same causal defect.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The corpus MUST store each item as immutable Base and Head revision
  pair with public manifest digest, language, diff-size/difficulty metadata and
  source provenance.
- **FR-002**: Every item MUST be classified as `development`, `calibration` or
  `holdout`, and as `clean` or `seeded`; released holdout content is immutable.
- **FR-003**: An item source MUST be one of `public`, `internal_deidentified` or
  `synthetic`, with recorded licence/approval and contamination status.
- **FR-004**: Protected Gold labels, reproducers, reference fixes and curator
  notes MUST be physically excluded from all runner worktrees, archives, Git
  object access and process environments.
- **FR-005**: Every Gold defect MUST have opaque ID, category, gold severity,
  affected scope, impact rationale, executable reproducer, provenance and an
  auditable curator self-review (curator ID, timestamp and evidence digest) or
  recorded adjudication.
- **FR-006**: The corpus validator MUST verify revision integrity, content
  digests, public/protected separation, label uniqueness, scope consistency and
  deterministic reproducer outcome.
- **FR-007**: A released v1 suite MUST have at least 24 items, 20% clean
  controls, Python and TypeScript/Nuxt coverage, and recorded category/severity/
  diff-size/difficulty/source distribution.
- **FR-008**: The system MUST map findings to `matched`, `duplicate`,
  `false_positive`, `insufficient_evidence` or `unmatched_gold`, with mapping
  evidence and evaluator version persisted.
- **FR-009**: The system MUST compute review recall, severity-weighted recall,
  precision, F1, duplicate rate, false positives per PR/KLOC and completion rate
  from Gold labels and terminal attempt states.
- **FR-010**: The system MUST separately score review usefulness through a
  versioned blind rubric: actionability, severity calibration, redundancy and
  reviewer attention burden. A frontier judge MAY perform blinded rubric triage,
  but human adjudication and executable/Gold evidence determine correctness.
- **FR-011**: The system MUST retain raw finding count for diagnosis but report
  useful high-value findings at fixed review attention cut-offs; comments alone
  MUST NOT improve a candidate score.
- **FR-012**: New or changed candidate adapters MUST pass the calibration
  partition under their declared CapabilityProfile before they enter holdout
  results.
- **FR-013**: Holdout leakage, source exposure, nondeterminism or invalid
  reproducers MUST retire an item from future decision-grade suite versions while
  preserving past artifacts, decision history and exclusion reason.

### Key Entities

- **ReviewCorpusItem**: Public PR-shaped fixture with pinned Base/Head commits
  and taxonomy metadata.
- **CorpusOracle**: Protected item material: Gold labels, reproducers, reference
  evidence, reviewer approvals and curator notes.
- **DefectLabel**: One independently reviewable known defect with opaque ID and
  executable evidence.
- **CoverageMatrix**: Counts and gaps across partition, source, language,
  category, severity, diff size, difficulty and clean controls.
- **FindingAssessment**: Mapping/evidence from a normalized reviewer finding to
  Ground Truth plus usefulness rubric result.
- **CalibrationResult**: Non-ranking conformance result for a CandidateVersion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `corpus validate` accepts 100% of released items and rejects a
  missing SHA, duplicate defect ID, unapproved source, leaked Oracle path, scope
  mismatch or non-deterministic reproducer.
- **SC-002**: 100% of released Gold defects run a deterministic reproducer
  successfully three consecutive times on their pinned Head revision.
- **SC-003**: Runner input inspection finds zero protected Oracle files, labels,
  reference fixes or secrets for 100% of released items.
- **SC-004**: v1 coverage report contains at least 24 items, at least five clean
  controls and non-zero documented counts for every selected stratum; gaps are
  visible rather than excluded from reports.
- **SC-005**: Fixture evaluations calculate the expected recall, precision,
  duplicate, false-positive and usefulness values for all five mapping outcomes.
- **SC-006**: A changed/unprobed candidate is blocked from decision-grade holdout
  results until its calibration suite passes and is persisted.

## Assumptions

- Protected Oracle data is held in an access-controlled internal corpus-oracle
  store/repository, separate from public runner inputs and artifact mounts.
- The first v1 release may initially favor synthetic and approved de-identified
  fixtures while the team builds provenance/reviewer processes for real history.
- A single curator owns Gold-label review and records their ID, timestamp and
  evidence digest; no LLM judge is a substitute for that ownership.
- The later Run Engine supplies fresh worktrees and an Artifact store; this
  feature specifies corpus contracts and validation before large-scale execution.
