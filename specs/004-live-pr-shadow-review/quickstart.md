# Quickstart: Live PR Shadow Review

The current slice is intentionally offline and uses mocked event/challenger
inputs. It establishes immutable PR identities and serial execution before any
GitHub webhook is enabled.

```bash
uv run pytest tests/live
uv run ruff check src/benchmark/live tests/live
```

The current private renderer consumes only the immutable observation, its
captured CodeRabbit snapshot and persisted challenger results. It does not
post to GitHub and labels every view as operational-only rather than a Gold
benchmark score.

The `PullRequestEventAdapter` is the boundary for a verified GitHub
`pull_request` webhook: it accepts only `opened`, `reopened` and `synchronize`
events from configured repositories and captures the Base/Head SHA pair in the
payload. HTTP signature verification belongs to the deployment endpoint that
invokes this adapter; this package deliberately does not expose one yet.

Workers that execute gito or PR-Agent must construct `LiveShadowRunner` with a
shared `SqliteResourceLeaseStore` database path on the GPU host. The runner
does not execute a pending local challenger until it holds the
`local-94gb-gpu` lease.

Do not add a repository to live processing until its explicit opt-in, retention
policy and credentials are configured. Live observations are operational-only
and never replace Corpus Gold scoring.
