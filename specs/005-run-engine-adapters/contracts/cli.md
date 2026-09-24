# CLI-Kontrakt — `benchmark runengine`

Neues Sub-App analog zu `benchmark corpus` und `benchmark live` (siehe
`specs/001-pr-review-benchmark/contracts/cli.md` für die Konvention). Alle
Kommandos sind idempotent bezüglich bereits vorhandener Datensätze; nichts
wird überschrieben (Principle I).

## Globale Optionen (geerbt von `benchmark`)

| Option | Default | Wirkung |
|---|---|---|
| `--config PATH` | `config/repos.yaml` | unverändert |
| `--runs-dir PATH` | `runs/` | Pfad zur `run-engine.sqlite3` (Resource-Lease, wiederverwendet aus Feature 004) |
| `--log-level LEVEL` | `INFO` | unverändert |

Zusätzlich per Env (`.env`, wie bestehend via `config.py`):

| Variable | Pflicht | Zweck |
|---|---|---|
| `RUNENGINE_DATABASE_URL` | ja | PostgreSQL-DSN für den Katalog |
| `RUNENGINE_S3_ENDPOINT_URL` / `_BUCKET` / `_ACCESS_KEY` / `_SECRET_KEY` | ja | S3-kompatibler Artifact-Store (lokal: RustFS aus `docker-compose.yml`) |
| `NOVEL_DEFECT_JUDGE_MODEL` | nein (Fallback `JUDGE_LLM_MODEL`) | Modell für FR-009a (z. B. Claude Opus 5) |

## Subkommando: `runengine candidate-register`

**Zweck**: Eine Kandidaten-Version (gito oder pr-agent) registrieren und ihren Capability-Probe laufen lassen (FR-012).

**Argumente**: `--slug {gito|pr-agent}`, `--tool-version STR`, `--model STR` (aus `TOOL_LLM_MODEL`, wenn nicht gesetzt).

**Aktionen**:
1. Probe wie im bestehenden `check()`-Kommando (Tool-`--help`, Endpoint-Ping).
2. Ergebnis als `candidate_version`-Zeile persistieren; `capability_probe_status = passed|failed`.

**Exit-Code**: 1 wenn Probe fehlschlägt (Zeile bleibt `failed`, ist damit für `plan create` gesperrt).

## Subkommando: `runengine plan-create`

**Zweck**: Ein `ExecutionPlan` für einen Corpus-Suite-Version + Kandidaten + Repetitionen erstellen (FR-001, US1).

**Argumente**: `--suite-dir PATH` (z. B. `review-corpus/review-v1`), `--candidate SLUG` (mehrfach, min. 1), `--repetitions N` (Default 3), `--retry-cap N` (Default 3, FR-013a).

**Aktionen**:
1. Der Server berechnet den Idempotency-Key aus der authentifizierten Actor-ID sowie (Suite-Digest, sortierte Kandidaten-IDs, Repetitionen, Retry-Cap, Score-Policy-Version). Ein vom Client gelieferter Key dient nur als Vorabprüfung.
2. Existiert für denselben Actor ein Plan mit demselben serverseitig berechneten Key → diesen zurückgeben, nichts Neues anlegen. Ein anderer Actor erhält einen eigenen Plan.
3. Sonst: `execution_plan`-Zeile plus einen `attempt`-Eintrag pro (Kandidat × Item × Repetition) in Status `queued` anlegen.

**Exit-Code**: 0, gibt Plan-ID aus.

## Subkommando: `runengine plan-run`

**Zweck**: Alle `queued` Attempts eines Plans abarbeiten (US1, US2).

**Argumente**: `PLAN_ID` (positional), `--suite-dir PATH` (derselbe lokale Checkout, den `plan-create` schon validiert hat — der Plan speichert nur den content_digest, nicht den lokalen Pfad, daher muss er hier erneut angegeben werden), `--oracle-dir PATH` (optional; protected Oracle-Verzeichnis — ohne diese Option läuft der Attempt durch, wird aber NICHT evaluiert, d.h. keine `evaluation`-Zeilen, kein Score).

**Aktionen**:
1. Pro Attempt: `SqliteResourceLeaseStore.acquire("local-94gb-gpu", ...)` (dieselbe Lease-Datei wie `benchmark run` und `benchmark live run`).
2. Fixture materialisieren (nur öffentliche Bundle-Dateien, `benchmark.corpus.materialize_review_input`), Kandidat ausführen, Rohausgabe + normalisierte Findings als Artifacts in S3 ablegen.
3. Bei transientem Fehler: neuen Retry-Attempt anlegen bis `retry_cap` (FR-013a). Bei Schema-Drift: Attempt `invalid`, kein Retry (FR-013).
4. Nach Erfolg (US3): `evaluator.py` klassifiziert Findings gegen Oracle-Labels (FR-009); `unmatched_gold`-Findings gehen an `evaluate_novel_finding` (FR-009a); `plausible_novel_defect` wird als `gold_label_candidate` gespeichert (FR-009b).
5. Lease freigeben, egal ob Erfolg oder Fehler.

**Exit-Code**: 0 auch wenn einzelne Attempts fehlgeschlagen sind (siehe `attempt-list` für Details); nur bei Infrastruktur-Fehlern (DB/S3 unerreichbar) ≠ 0.

## Subkommando: `runengine attempt-list` / `runengine attempt-show ATTEMPT_ID`

**Zweck**: Attempt-Status und Terminal-Reason inspizieren (US1, US3).

## Subkommando: `runengine score-show --plan PLAN_ID`

**Zweck**: Pro Kandidat: recall/precision/F1/false-positive-rate/duplicate-rate/completion-rate mit Sample-Count und Spannweite, getrennt operative Metriken (Queue-Wait, Laufzeit, Tokens, Kosten), plus separates Panel `plausible_novel_defect`-Count (FR-009a/FR-010/FR-011, US3).

## Subkommando: `runengine gold-candidates-export --plan PLAN_ID`

**Zweck**: Alle `proposed` `gold_label_candidate`-Zeilen im Format ausgeben, das 003s Kurator-Pipeline konsumiert (FR-009b). Schreibt selbst keine Gold-Labels.
