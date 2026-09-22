# Implementation Plan: Ground-Truth Review Corpus

**Branch**: `003-review-ground-truth-corpus` | **Date**: 2026-09-22 | **Spec**: [spec.md](spec.md)

## Summary

Create a small, versioned v1 review corpus before changing production runners.
Use public fixture packages and protected internal Oracle storage, validate every
Base/Head pair and reproducer, then build evaluation/mapping tests. The future
Run Engine consumes the corpus; it does not define corpus truth.

## Technical Context

**Language/Version**: Python 3.12+ validation/evaluation tools.  
**Storage**: Public fixture Git bundles under approved corpus storage; protected
Oracle in access-controlled internal store; resulting artifacts use future object
storage.  
**Testing**: pytest plus deterministic fixture/reproducer tests; no live model
calls.  
**Constraints**: runners never mount Oracle data; held-out tasks need source and
contamination review; current public repository must not receive private code.

## Constitution Check

| Principle | Compliance |
|---|---|
| Immutable provenance | Base/Head SHA, content and environment digests are required. |
| Independent Ground Truth | Oracle labels/reproducers remain independent from candidates; an auditable single-curator self-review is required. |
| Equal isolation | Oracle is physically absent from all runner inputs. |
| Transparent scores | Gold correctness and usefulness rubric are separately persisted. |
| Secure operation | Internal source/Oracle require protected storage and scoped credentials. |

## Structure

```text
specs/003-review-ground-truth-corpus/
review-corpus/<suite>/<version>/       # public manifests and fixture Git bundles
corpus-oracle/<suite>/<version>/       # protected external/internal store, not repo
src/benchmark/corpus/                  # validator, coverage and evaluator helpers
tests/corpus/                          # schema, isolation, reproducer and mapping tests
```

## Delivery order

1. Define protected-storage access and curator approval process.
2. Implement schemas, validator and runner-input isolation test with synthetic
   pilot fixtures.
3. Implement Gold mapping/usefulness evidence and coverage report.
4. Curate/review v1 items; release only after all reproducers pass repeatedly.
5. Hand the released suite to the Run Engine feature for actual tool execution.
