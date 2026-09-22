# Plan 002: Baue einen versionierten Review-Korpus mit Ground Truth

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b764f88..HEAD -- specs docs review-corpus src tests plans`
> If the approved contracts from Plan 001 differ materially, stop and refresh
> this plan before implementing a corpus.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: `plans/001-benchmark-contracts-speckit.md`
- **Category**: direction
- **Planned at**: commit `b764f88`, 2026-09-22

## Why this matters

The present system compares gito and pr-agent with CodeRabbit observations.
`specs/001-pr-review-benchmark/spec.md:101-105` calls a challenger finding
"unique" when it does not overlap CodeRabbit; it does not establish whether the
finding is true. A decision-grade reviewer ranking needs known positives and
known negatives, frozen source revisions and labels that a runner cannot see.

This plan creates that primary quality suite. It deliberately preserves
historical PRs as a separate realism panel, rather than discarding the useful
existing CodeRabbit integration.

## Current state

- `config/repos.yaml:1-12` selects a live GitHub PR (`haexmas/holzi#27`), so
  inputs depend on external history/access.
- `tests/fixtures/` contains parser outputs, not reviewable repositories or
  labelled defects.
- `src/benchmark/matching/structural.py:15-45` only proposes same-file,
  near-line matches; `matching/judge.py` determines equivalence with an LLM.
- `src/benchmark/reports/summary.py:113-128` calculates overlap/unique/missed
  values, not precision or recall against labels.
- Plan 001 defines `SuiteVersion`, `BenchmarkItem`, `DefectLabel` and the
  visibility boundary that this corpus must implement.

Match documentation convention from the existing German SpecKit feature.
Fixtures must be unambiguously owned or license-compatible; do not copy private
production repositories or real credentials into this repository.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Baseline checks | `uv run pytest && uv run ruff check .` | Existing suite passes |
| Validate metadata | `uv run python -m benchmark.corpus validate review-corpus/v1` | Every public/hidden manifest and reproducer validates |
| Verify fixture revision | `git -C review-corpus/v1/<item>/repo rev-parse HEAD` | Equals the manifest head SHA |
| Execute gold reproducer | `uv run python -m benchmark.corpus verify --suite review-corpus/v1 --item <id>` | Expected defect fails/reproduces before fix and passes after reference fix |
| Run corpus tests | `uv run pytest tests/corpus` | All metadata, visibility and repro tests pass |

The `benchmark.corpus` commands and `tests/corpus` are introduced in this plan;
define their exact interface first in the corresponding SpecKit feature.

## Scope

**In scope**:

- New SpecKit feature `003-review-ground-truth-corpus/**`
- `review-corpus/v1/**` (or a private internal data repository if Plan 001's
  retention decision requires it)
- Corpus-manifest validation and tests under `src/benchmark/corpus/**` and
  `tests/corpus/**`
- ADR documenting corpus provenance, label visibility and update policy

**Out of scope**:

- Dashboard work, run scheduler and Coding-agent execution
- Altering tool prompts to expose labels or building an LLM-only evaluator
- Rewriting existing `src/benchmark/tools/**` adapters
- Adding more than a deliberately small, balanced v1 corpus

## Git workflow

- Branch: create through SpecKit as `003-review-ground-truth-corpus`.
- Use focused commits: corpus contract, one fixture family, validator/tests,
  evaluator mapping. Do not mix source fixtures with unrelated refactors.
- Do not publish a fixture repository externally unless provenance and license
  review explicitly allow it.

## Steps

### Step 1: Specify the corpus before authoring defects

Create the new SpecKit feature. Its specification must define a `review` suite
and `v1` content digest, public runner inputs and protected curator inputs.
Write measurable acceptance criteria: reproducible checkout, every positive
defect has an executable reproducer, clean controls emit no expected defect,
and labels are inaccessible from a runner worktree/container.

Define a small v1 matrix before writing code: initially 24–36 PR fixtures,
each with 0–3 independently verifiable defects. Stratify at least by Python
and TypeScript, correctness/security/performance/error handling, severity,
diff-size bucket and difficulty. Include 20–30% clean negative controls. Keep
the first corpus to stacks the team can actually label and run.

**Verify**: the SpecKit checklist is complete and the corpus matrix shows a
count for every selected stratum plus negative controls.

### Step 2: Establish the fixture layout and visibility boundary

For each item, construct an owned small seed project (or an approved public
source snapshot) and freeze two revisions: `base_sha` and `head_sha`, where
`head_sha` is the intentionally buggy PR state. The runner receives only the
public manifest, the worktree and generic task policy.

Use this layout, with storage location adapted only if the approved retention
decision requires an internal separate repository:

```text
review-corpus/v1/
  suite.yaml                         # public suite ID, version, digest, policy
  <item-id>/
    public.yaml                       # title, language, base/head SHA, budget class
    repo/                             # git fixture, base and head commits
    hidden/
      ground-truth.yaml               # DefectLabel list; never mounted for runner
      reproducers/<defect-id>/         # executable verification + reference evidence
      curator-notes.md
```

The public manifest may name language and diff-size bucket but not a defect
category, exact expectation or hidden test path. Do not rely on `.gitignore` as
the security boundary; runner containers/checkout packaging must explicitly
exclude `hidden/`.

**Verify**: build a runner input archive/worktree and assert `find <runner-input>
-path '*hidden*' -print` produces no output; a curator validation job can read
all label files.

### Step 3: Write high-quality labels and executable evidence

For every defect in `ground-truth.yaml`, record only the Plan-001 contract:
stable opaque ID, category, gold severity, impact statement, affected file/scope,
source/revision, a reproducer identifier and label version. Avoid putting the
ideal review wording into labels. Require the reproducer to demonstrate the
failure or a deterministic static invariant; record why the defect is reviewable
from the available diff/context.

Each fixture must be independently reviewed by two maintainers who do not see
the candidate outputs. Resolve disagreement in an append-only adjudication
record with reviewer IDs (pseudonymous identifiers are sufficient), date and
decision. Add at least one label-independent reference test for each positive.

**Verify**: `benchmark.corpus validate` refuses missing reproduction evidence,
duplicate defect IDs, line scopes outside the pinned revision, and positives
without two-reviewer/adjudication metadata.

### Step 4: Implement deterministic validation and evaluator input mapping

Implement a validator that computes suite/item digests from canonical public
and hidden manifests, verifies SHA ancestry and runs every reproducer in a
network-disabled, time-limited environment. It must output structured results,
not only Markdown.

Implement the evaluation input boundary: a normalised candidate `Finding` can
be proposed against a `DefectLabel`, but the final evaluator records
`matched`, `false_positive`, `duplicate`, `insufficient_evidence` or
`unmatched_gold`. Automatic matching is triage only. For all seeded defects and
a sampled subset of candidate findings, present blinded content to two human
adjudicators; calculate and save their agreement. Do not score a finding merely
because an LLM says it matches.

**Verify**: tests cover a true positive, a wrong-line same defect, a duplicate,
a false positive, an unmatched gold defect, a clean-control finding and an
adjudication disagreement.

### Step 5: Publish v1 score definitions and a baseline report

Calculate per candidate/version and stratum: defect recall, severity-weighted
recall, precision, F1, false positives per PR and per KLOC, duplicate rate,
completion rate and p50/p95 times. Keep findings with `insufficient_evidence`
visible and exclude them from a score only according to a versioned, documented
policy. Render a corpus-coverage report that shows gaps rather than hiding
small sample sizes.

Import the present CodeRabbit data only as `legacy observation` if desired. Its
dashboard/report title must say it is an historical-overlap view and must never
join the ground-truth ranking table.

**Verify**: a fixture-only fake candidate produces known recall/precision values
and the report labels ground-truth and legacy panels distinctly.

## Test plan

- Manifest schema tests: required fields, opaque IDs, SHA consistency, digest
  changes on content changes and no public label leakage.
- Reproducer tests: every positive reliably proves the intended behavior in the
  pinned buggy revision; negative controls are clean.
- Evaluation tests: one-to-one mapping, duplicate handling, false-positive
  accounting and human override/audit trail.
- Full test command: `uv run pytest tests/corpus && uv run pytest && uv run ruff check .`.

## Done criteria

- [ ] A reviewed, versioned v1 corpus exists with an approved stratification
  matrix and clean controls.
- [ ] All runner packages/worktrees exclude Gold Truth and hidden reproducers.
- [ ] Every label has reproducible evidence and a human approval trail.
- [ ] Corpus validation and all reproducer tests pass deterministically.
- [ ] Ground-truth precision/recall reports exist; CodeRabbit overlap is
  visibly separated as an observational panel.
- [ ] `plans/README.md` marks Plan 002 as DONE.

## STOP conditions

- A potential fixture contains internal code, personal data, credentials or an
  unapproved license.
- A reproducible test cannot demonstrate the alleged defect; remove it or mark
  it as an unscored research item rather than creating a gold label.
- A runner can inspect hidden paths through Git history, mounted volumes,
  archives or environment variables.
- There is no second reviewer/adjudicator for a high-severity label.

## Maintenance notes

Never edit a released `v1` item in place: make `v1.1` or `v2` with a new
digest. Monitor the corpus for contamination—once task fixtures circulate in
training data or agents' memories, retire them from the primary holdout and
record the reason. Keep exploratory production PRs outside the primary suite.
