# Review Corpus Data Model

## Public corpus package

```text
review-corpus/<suite>/<version>/
  suite.yaml                         # public release metadata + content digest
  items/<item-id>/
    manifest.yaml                    # public Base/Head, source and taxonomy
    repo.bundle                       # immutable fixture Git history
    policy.md                         # visible runner policy
```

This public package lives in
[`haexhub/llm-benchmark-review-corpus`](https://github.com/haexhub/llm-benchmark-review-corpus).

`manifest.yaml` contains opaque item ID, partition, clean/seeded status, source
class, approval reference, Base/Head SHA, language, diff-size and difficulty
bucket. It never contains labels, reference fixes, reproducer commands or hidden
paths.

## Protected Oracle package

```text
corpus-oracle/<suite>/<version>/<item-id>/
  ground-truth.yaml                  # DefectLabel list
  reproducers/<defect-id>/            # deterministic executable evidence
  approvals.yaml                      # two reviewers/adjudication
  reference/                          # optional reference evidence/fix
  curator-notes.md
```

This protected package lives in the private
[`haexhub/llm-benchmark-review-oracle`](https://github.com/haexhub/llm-benchmark-review-oracle)
repository.

The Oracle lives in access-controlled internal storage and is not a Git remote,
volume or environment mounted for a runner. The evaluator retrieves it only after
an Attempt has ended.

## Entities

| Entity | Required fields |
|---|---|
| `ReviewCorpusItem` | ID, suite/version, partition, source/approval, Base/Head SHA, public digest, taxonomy, status |
| `DefectLabel` | opaque ID, item ID, category, gold severity, affected scope, impact, reproducer ID, provenance, approval state |
| `ReproducerResult` | label ID, item revision, image/environment digest, command result, duration, evidence artifact |
| `FindingAssessment` | finding ID, outcome, matching evidence, evaluator version, usefulness assessment, adjudication link |
| `UsefulnessAssessment` | correctness source, actionability 0–2, severity calibration, redundancy, attention cost, blind judge/human version |
| `CoverageMatrix` | suite version and counts by partition/source/language/category/severity/diff-size/difficulty/clean status |
| `CalibrationResult` | candidate version, calibration item/version, input/output contract result, timestamp/artifact |

`FindingAssessment.outcome` is `matched`, `duplicate`, `false_positive`,
`insufficient_evidence` or `unmatched_gold`. `insufficient_evidence` is never
silently converted to a true or false positive.

## Protected reproducer contract

A protected reproducer receives the materialized public Head fixture root as
its first argument. Exit code `0` means the labelled defect was reproduced on
that revision; a non-zero exit means evidence is absent or invalid. The
post-run evaluator executes it with network isolation and a read-only fixture;
the review runner never receives the script or its output paths.
