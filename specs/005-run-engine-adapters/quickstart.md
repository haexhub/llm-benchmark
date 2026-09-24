# Quickstart — Run Engine and Adapters

```bash
git switch 005-run-engine-adapters
docker compose up -d postgres minio
uv sync
uv run pytest              # hermetic unit tests only (db/live excluded by default)
uv run pytest -m db         # against the docker-compose Postgres/MinIO stack
uv run ruff check .
```

`.env` additions beyond the existing `TOOL_LLM_*`/`JUDGE_LLM_*` variables:

```bash
RUNENGINE_DATABASE_URL=postgresql://benchmark:benchmark@localhost:5433/runengine
RUNENGINE_S3_ENDPOINT_URL=http://localhost:9010
RUNENGINE_S3_BUCKET=runengine-artifacts
RUNENGINE_S3_ACCESS_KEY=...
RUNENGINE_S3_SECRET_KEY=...
NOVEL_DEFECT_JUDGE_MODEL=claude-opus-5   # optional; falls back to JUDGE_LLM_MODEL
```

Register both candidates once, then run the released corpus:

```bash
uv run benchmark runengine candidate register --slug gito --tool-version <pinned>
uv run benchmark runengine candidate register --slug pr-agent --tool-version <pinned>

uv run benchmark runengine plan create \
  --suite-dir review-corpus/review-v1 \
  --candidate gito --candidate pr-agent \
  --repetitions 3

uv run benchmark runengine plan run <plan-id>

uv run benchmark runengine score show --plan <plan-id>
uv run benchmark runengine gold-candidates export --plan <plan-id>
```

`plan create`/`plan run` are implemented in this feature's tasks; not
available before `/speckit.tasks` + implementation lands. `runengine
candidate register`'s capability probe reuses the existing `benchmark check`
reachability logic (T-numbered in tasks.md).

Every corpus item is materialized into a fresh workspace containing only its
public Base/Head fixture — never the protected `haexhub/llm-benchmark-review-
oracle` repository. Inspecting any attempt's workspace for Oracle files MUST
find none (SC-004); this is asserted by an automated test, not left to manual
review.
