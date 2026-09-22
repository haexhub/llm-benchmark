# Research — Review Corpus

## R1 — Separate Oracle storage `[Approved]`

The platform constitution forbids runners from seeing hidden data. A `hidden/`
directory inside a shared corpus repository is insufficient because Git history,
container mounts and archives can expose it. Public fixture packages and protected
Oracle material are separate physical stores with different service credentials:
the public `haexhub/llm-benchmark-review-corpus` repository and private
`haexhub/llm-benchmark-review-oracle` repository.

## R2 — Sources and realism `[Approved]`

Public, internal/de-identified and synthetic cases are valid inputs. Their source
class is a coverage dimension, not a quality distinction. Every case must be a
PR-shaped Base/Head pair with a deterministic local reproducer; non-reproducible
real incidents are not Gold items.

## R3 — v1 scope `[Approved]`

Release no fewer than 24 items, including at least five clean controls. Start
with Python and TypeScript/Nuxt, and cover correctness, security, performance,
error handling, tests and configuration where evidence is available. Report gaps
instead of pretending equal representation.

## R4 — Usefulness judgement `[Approved]`

Gold labels/humans decide factual correctness. A fixed blind frontier judge can
triage actionability, clarity and severity calibration but has no access to tool
identity. High-impact, disputed and sampled unknown cases require human
adjudication. The judge prompt/model/version is evaluator provenance.

## R5 — Contamination `[Approved]`

Development fixtures may be visible to adapter authors. Calibration fixtures are
non-ranking. Holdout fixtures are access controlled; if their source, prompt or
training exposure becomes known, retire them in a new suite version and retain
the exclusion reason.
