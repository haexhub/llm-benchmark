# Score Policy Contract

Every policy has an immutable ID/version and defines modality-specific metrics.
It MUST name its suite/evaluator compatibility, formulas, missing-data handling,
confidence-interval method and optional weights. A policy may not compare review
and coding scores numerically.

- **Review primary metrics**: recall, severity-weighted recall, precision, F1,
  false positives per PR/KLOC, duplicate rate, completion rate and useful
  high-value findings at fixed attention cut-offs.
- **Review usefulness rubric**: correctness source (Gold label, executable
  evidence or human adjudication), actionability (location, mechanism and next
  action), severity calibration, redundancy and attention burden. Blind frontier
  judges score only the rubric's communication/actionability dimensions; they
  never become the sole truth for correctness.
- **Review v1 useful-high-value KPI**: a primary `matched` finding with
  actionability `2`, calibrated severity and no redundancy. Report its count
  and count divided by the sum of assessed attention-cost units; do not replace
  recall, precision or actual token/time telemetry with this KPI.
- **Coding primary metrics**: hidden acceptance/regression pass rate, completion
  rate and permitted partial test score.
- **Operational metrics**: queue wait, setup, runner and evaluator p50/p95,
  actual tokens, tool calls and estimated/API cost where available. Safety
  ceilings guard against runaway work but are not normalized SLA budgets.
- **Weighted rank**: optional, off by default; dashboard/API must return the
  exact policy and weights with every rank.
