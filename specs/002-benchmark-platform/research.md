# Research — Platform Foundation

## R1 — Existing spike is not a decision-grade run store `[Certain]`

`runs/<repo>/<pr>/` derives state from mutable files and `--force` overwrites
them. `src/benchmark/reports/summary.py` currently reports zero runtime. The
platform therefore needs immutable Attempts and separate artifacts before it can
rank model/tool versions.

## R2 — One local inference slot `[Certain]`

The available 94 GB GPU RAM permits one local model test at a time. The current
`pipeline.do_run` starts gito and PR-Agent concurrently, while observed large
PR runs took roughly 5–25 minutes. The platform treats this capacity as
`local-94gb-gpu=1`; queue wait is not inference latency.

## R3 — Review Ground Truth replaces CodeRabbit as quality baseline `[Certain]`

CodeRabbit overlap measures similarity to historical CodeRabbit comments, not
truth. A labelled review corpus with executable reproducers enables precision,
recall, severity-weighted recall, duplicate rate and false-positive rate.
CodeRabbit is retained only as a marked legacy realism panel.

## R4 — Candidate adapters require capability pinning `[Certain]`

The existing wrappers invoke unpinned `uv tool run --from` packages. Current
Gito documentation exposes local worktree/path workflows, while older spike
research recorded a missing implementation. PR-Agent, Hermes and OpenCode also
evolve their CLI/API contracts. Candidate registration must capture exact
version/image, sanitized capability probe and output schema fingerprint.

## R5 — Technology decision `[Approved for feature planning]`

Keep Python for normalizers/workers and adopt FastAPI for the internal typed API.
Use PostgreSQL for transactions, attempt state and resource leases, and internal
S3-compatible storage for larger immutable artifacts. Nuxt 3 + Tailwind consume
generated API types. This is a staged evolution, not a rewrite of the current
CLI.

## R6 — Fair execution rule `[Approved]`

Every review candidate receives an identical deterministic Base/Head worktree;
every coding candidate receives a fresh task worktree/session. Hidden material
is excluded from runner mounts. Three scored attempts per cell and an excluded
warm-up are the initial default; ordering is persisted and counterbalanced.
