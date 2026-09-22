# Quickstart: Live PR Shadow Review

The current slice is intentionally offline and uses mocked event/challenger
inputs. It establishes immutable PR identities and serial execution before any
GitHub webhook is enabled.

```bash
uv run pytest tests/live
uv run ruff check src/benchmark/live tests/live
```

Do not add a repository to live processing until its explicit opt-in, retention
policy and credentials are configured. Live observations are operational-only
and never replace Corpus Gold scoring.
