# Quickstart — Platform Foundation

This feature changes contracts and documentation only; it does not start a
database, worker or dashboard yet.

```bash
git switch 002-benchmark-platform
uv run pytest
uv run ruff check .
```

Read in order:

1. [Constitution](../../.specify/memory/constitution.md)
2. [Specification](spec.md)
3. [Data model](data-model.md)
4. [Attempt manifest contract](contracts/attempt-manifest.schema.json)
5. [Implementation plan](plan.md)
6. [Task list](tasks.md)

The next implementation feature is `003-review-ground-truth-corpus`; do not
start dashboard or worker code before its SpecKit feature and Plan 004's
resource/provenance contracts are approved.
