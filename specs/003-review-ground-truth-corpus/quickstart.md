# Quickstart — Review Corpus

Start with synthetic pilot fixtures only. Do not copy internal source into this
repository until source approval and the protected Oracle store are available.

```bash
git switch 003-review-ground-truth-corpus
uv run pytest
uv run ruff check .
```

Before an item is released, a curator must verify its source/approval, run its
reproducer three consecutive times and inspect the assembled runner input for
Oracle leakage. The planned validation command is:

```bash
uv run benchmark corpus validate review-corpus/review-v1
```

That command will be implemented in T004–T008; it is not available yet.
