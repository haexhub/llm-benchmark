---
description: "Task list for PR-Review Benchmark implementation"
---

# Tasks: PR-Review Benchmark

**Input**: Design documents from `/specs/001-pr-review-benchmark/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Included per user story (Foundational + US1). Parser- und Matcher-Logik werden unit-getestet; Judge-Client integration-getestet mit Fake.

**Organization**: Nach User Stories aus spec.md; MVP = US1. Nach jeder Story-Checkpoint läuft etwas Vorführbares.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Kann parallel ausgeführt werden (andere Datei, keine Abhängigkeiten auf unerledigte Tasks)
- **[Story]**: [US1]–[US4] gemäß spec.md
- Dateipfade sind absolut zum Repo-Root `~/Projekte/llm-benchmark/`

## Path Conventions

Single-Project-Layout aus plan.md:

- Source: `src/benchmark/…`
- Tests: `tests/unit/`, `tests/integration/`, `tests/fixtures/`
- Config: `config/repos.yaml`, `.env`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Projekt-Skeleton, Dependencies, Basis-Dateien

- [X] T001 Erzeuge Projekt-Skeleton (Verzeichnisse `src/benchmark/`, `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `config/`, `runs/`, `reports/`) mit `.gitkeep` in leeren Ordnern; `runs/` und `reports/` in `.gitignore` aufnehmen
- [X] T002 Erzeuge `pyproject.toml` mit uv-Layout, Python 3.12+, Dependencies gemäß plan.md (typer, python-dotenv, pyyaml, pydantic, httpx, anthropic, openai, rich, pytest, pytest-asyncio) und CLI-Entry-Point `benchmark = "benchmark.cli:app"`
- [X] T003 [P] `uv sync` ausführen; verifizieren dass `uv run python -c "import benchmark"` (nach T004) läuft
- [X] T004 Erzeuge Package-Skeleton `src/benchmark/__init__.py` (nur `__version__ = "0.1.0"`) und `src/benchmark/__main__.py` (delegiert an `cli.app`)
- [X] T005 [P] Erzeuge `.env.example` mit allen Env-Vars aus quickstart.md (TOOL_LLM_*, JUDGE_LLM_*, GH_TOKEN, LOG_LEVEL) — jeweils mit Kommentar-Zeile und leerem Default
- [X] T006 [P] Erzeuge `config/repos.yaml` als Minimal-Stub mit einem auskommentierten Beispiel-Repo
- [X] T007 [P] Erzeuge `.gitignore` (`.env`, `.venv/`, `runs/`, `reports/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.pyc`)
- [X] T008 [P] Erzeuge `README.md` mit Ein-Zeiler-Beschreibung und Verweis auf `specs/001-pr-review-benchmark/quickstart.md`

**Checkpoint (Phase 1)**: `uv sync` läuft, `uv run python -c "import benchmark"` erfolgreich, `.env.example` und `config/repos.yaml` liegen.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Datenmodelle, Config-Loader, Logging und CLI-Skelett — Voraussetzung für jede User Story.

**⚠️ CRITICAL**: Ohne Phase 2 kann keine US starten.

- [X] T009 [P] Implementiere alle pydantic-Modelle aus [data-model.md](data-model.md) in `src/benchmark/models.py`: `RepoConfig`, `Finding`, `MatchCandidate`, `JudgeVerdict`, `Match`, `ManualReview`, `PerToolStats`. Validierung strikt (Literals, `line_end >= line_start`, uuid-Format).
- [X] T010 [P] Implementiere `src/benchmark/config.py`: `load_env()` (python-dotenv), `load_repos(path)` → `list[RepoConfig]` (pyyaml + pydantic-Validierung), `require_env(name)` mit klarem Fehler.
- [X] T011 [P] Implementiere Logging-Setup in `src/benchmark/__init__.py` oder `src/benchmark/logging.py`: `setup_logging(level: str | None = None)` liest `LOG_LEVEL` env oder CLI-Flag, richtet stdlib-`logging` mit Rich-Handler ein.
- [X] T012 Implementiere CLI-Skelett `src/benchmark/cli.py`: `typer.Typer()` mit Subkommandos `check`, `fetch`, `run`, `match`, `report`, `all` — alle raise `NotImplementedError`. Globale Optionen aus [contracts/cli.md](contracts/cli.md) (`--config`, `--runs-dir`, `--reports-dir`, `--log-level`, `--repo`, `--pr`, `--force`).
- [X] T013 [P] Unit-Test `tests/unit/test_config.py`: `load_env` findet vorhandene `.env`, `load_repos` parst valides YAML, invalides YAML → Pydantic-ValidationError.
- [X] T014 [P] Unit-Test `tests/unit/test_models.py`: Round-trip JSON ↔ Pydantic für `Finding`, `Match`, `ManualReview`; ungültige Enums werden abgelehnt; `line_end < line_start` schlägt fehl.
- [X] T015 Implementiere `benchmark check` (Subkommando in `cli.py`): validiert `.env`-Vollständigkeit, führt `gh auth status`, `gh --version`, `curl $TOOL_LLM_BASE_URL/models`, `uv tool run --from pr-agent pr-agent --help`, `uv tool run --from gito.bot gito --help` und Judge-Dummy-Request aus; farbige `✓`/`✗`-Ausgabe via rich; Exit 0/1.

**Checkpoint (Phase 2)**: `uv run benchmark check` läuft und meldet zeilenweise Status. `uv run pytest tests/unit/test_config.py tests/unit/test_models.py` grün.

---

## Phase 3: User Story 1 — Baseline für einen einzelnen PR bekommen (Priority: P1) 🎯 MVP

**Goal**: End-to-end Vertikalschnitt: `benchmark all --repo X --pr N` erzeugt für einen konfigurierten PR alle drei Findings-Listen, matcht sie und rendert den Per-PR-Report.

**Independent Test**: Für ein konfiguriertes Repo mit einer PR-Nummer den Batch starten, danach `reports/per_pr/<owner>__<repo>__<pr#>.md` öffnen. Enthält 3-Spalten-Tabelle mit mindestens einem gematchten und einem unique Finding.

### Fixtures für User Story 1

- [X] T016 [P] [US1] Erzeuge `tests/fixtures/cr_review_full.md` — echter CR-Review-Body-Text (Copy aus einem realen PR) mit allen vier Präfix-Typen (⚠️/🛠️/🧹/✅)
- [X] T017 [P] [US1] Erzeuge `tests/fixtures/cr_review_empty.md` — CR-Post ohne Findings (Sonderfall)
- [X] T018 [P] [US1] Erzeuge `tests/fixtures/pragent_stdout.txt` — realer pr-agent-Output (aus einem manuellen Test-Run gezogen, siehe T024)
- [X] T019 [P] [US1] Erzeuge `tests/fixtures/gito_output.json` (oder `.txt`) — realer gito-Output; Format hängt von T023-Verifikation ab

### Unit-Tests (schreiben → fehlschlagen → implementieren)

- [X] T020 [P] [US1] `tests/unit/test_coderabbit_parser.py`: parst `cr_review_full.md` in ≥ 3 Findings mit korrekten severities; parst `cr_review_empty.md` in `[]`; unbekanntes Präfix wird zu `category=unknown`, nicht Exception
- [X] T021 [P] [US1] `tests/unit/test_pragent_parser.py`: parst `pragent_stdout.txt` in ≥ 1 Finding mit korrektem `file`, `line_start`, `severity`
- [X] T022 [P] [US1] `tests/unit/test_gito_parser.py`: parst `gito_output.*` in ≥ 1 Finding
- [X] T023 [P] [US1] `tests/unit/test_structural_match.py`: Findings gleicher Datei mit Line-Overlap ±3 → Kandidat; ohne Overlap → kein Kandidat; ±4 → kein Kandidat (Grenze scharf)

### Implementation — Ingest & Fetch

- [X] T024 [US1] Verifiziere `pr-agent` CLI-Syntax gegen `uv tool run --from pr-agent pr-agent --help` und dokumentiere den finalen Aufruf inline in [research.md](research.md) R1
- [X] T025 [US1] Verifiziere `gito` CLI-Syntax gegen `uv tool run --from gito.bot gito --help` und dokumentiere in [research.md](research.md) R2
- [X] T026 [US1] Implementiere `src/benchmark/github/fetch.py`: `fetch_diff(owner, repo, pr)` (`gh pr diff N --repo owner/repo`) und `fetch_cr_comments(owner, repo, pr)` (drei `gh api`-Calls, gefiltert auf `coderabbitai[bot]`); jeweils rohe Rückgabe (bytes/list[dict])
- [X] T027 [US1] Implementiere `src/benchmark/coderabbit/parser.py`: `parse_cr(raw_comments) -> list[Finding]` splittet Markdown-Body an CR-Präfix-Headern, mappt auf `Finding`-Schema; Severity-Mapping-Tabelle wie in [data-model.md](data-model.md)
- [X] T028 [US1] Implementiere `src/benchmark/tools/base.py`: `run_cli(cmd: list[str], timeout: int, env: dict) -> CompletedProcess` mit sauberem Timeout-Handling und stdout/stderr-Capture
- [X] T029 [P] [US1] Implementiere `src/benchmark/tools/pr_agent.py`: `run_pragent(pr_url, config) -> list[Finding]` — Subprozess-Call + Stdout-Parser
- [X] T030 [P] [US1] Implementiere `src/benchmark/tools/gito.py`: `run_gito(pr_url, config) -> list[Finding]` — Subprozess-Call + Output-Parser (JSON oder Markdown je nach T025)

### Implementation — Matching

- [X] T031 [US1] Implementiere `src/benchmark/matching/structural.py`: `candidates(findings_a, findings_b, tolerance=3) -> list[MatchCandidate]`
- [X] T032 [US1] Implementiere `src/benchmark/matching/judge.py`: `JudgeClient`-Protocol mit `evaluate_pair(a, b) -> JudgeVerdict`; zwei konkrete Implementierungen — `AnthropicJudge` (via `anthropic`-SDK) und `OpenAICompatJudge` (via `openai`-SDK); Factory `make_judge()` liest `JUDGE_LLM_PROVIDER` aus Env
- [X] T032a [US1] Implementiere Blind-Präsentation in `src/benchmark/matching/judge.py` (FR-009): Judge-Prompt sieht Finding-Paare als anonyme Labels `A`/`B`, keine Tool-Namen; A/B-Zuordnung wird deterministisch per Hash des PR-Identifiers randomisiert (nicht per Match-ID, damit dieselben Findings über Re-Runs stabile Rollen behalten); Judge-Response wird nach dem Call in die ursprüngliche Finding-Identität zurückgemappt
- [X] T033 [P] [US1] `tests/integration/test_judge_client.py`: `FakeJudge` erzeugen, `evaluate_pair` liefert vorbereitete Antwort; realer Anthropic-Client-Test steht hinter `@pytest.mark.live` (opt-in, nicht CI-default)
- [X] T033a [P] [US1] `tests/unit/test_judge_blind.py`: der an den Judge übergebene Prompt enthält keine Tool-Namen; A/B-Rollen sind für den gleichen (pr_id, finding_pair) über wiederholte Aufrufe stabil; unterschiedliche pr_ids führen zu unterschiedlichen A/B-Zuordnungen (Signal-Test, kein exakter Match)
- [X] T034 [US1] Implementiere `src/benchmark/matching/aggregator.py`: `classify(findings, matches, manual_reviews=None) -> dict[finding_id, Classification]` mit den Kategorien `agreed_with_cr`, `unique_to_tool`, `missed_from_cr`; `uncertain`-Bucket bei confidence<0.6
- [X] T035 [US1] Implementiere `src/benchmark/matching/dedup.py`: `dedup_intra_tool(findings) -> tuple[deduped, dup_count]` nutzt denselben `JudgeClient` wie `judge.py`
- [X] T036 [P] [US1] `tests/unit/test_aggregator.py`: Klassifikations-Logik mit vorgefertigten Findings + Matches; `manual_reviews` überstimmen automatische `classification`
- [X] T037 [P] [US1] `tests/unit/test_dedup.py`: mit `FakeJudge` — zwei ähnliche Findings desselben Tools werden zu einem gefaltet, `dup_count=1`

### Implementation — CLI-Wiring & Reports

- [X] T038 [US1] Implementiere `benchmark fetch` in `cli.py`: iteriert `RepoConfig`, ruft `fetch.py`, schreibt `runs/<owner>__<repo>/<pr#>/diff.patch` und `coderabbit.json`; idempotent (überspringt existierende); `--force` überschreibt; Fehler → `failed.log`
- [X] T039 [US1] Implementiere `benchmark run` in `cli.py`: pro PR startet gito + pr-agent nebenläufig via `ThreadPoolExecutor(max_workers=2)`, schreibt `gito.json` und `pr-agent.json`; 10-min-Timeout pro Tool; idempotent
- [X] T040 [US1] Implementiere `benchmark match` in `cli.py`: lädt drei Findings-Listen, ruft structural → judge → dedup → aggregator, schreibt `matches.json` gemäß [contracts/matches.schema.json](contracts/matches.schema.json)
- [X] T041 [US1] Implementiere `src/benchmark/reports/per_pr.py`: `render_per_pr(pr_run) -> str` erzeugt 3-Spalten-Markdown-Tabelle (CR|gito|pr-agent) mit gematchten Zeilen aligned, Uniques mit leeren Nachbarzellen, Judge-Konfidenz klein daneben
- [X] T042 [US1] Implementiere `benchmark report` in `cli.py` (Minimum-Version für US1): iteriert PR-Runs, ruft `render_per_pr`, schreibt `reports/per_pr/<owner>__<repo>__<pr#>.md`
- [X] T043 [US1] Implementiere `benchmark all` in `cli.py`: sequenziell fetch → run → match → report für die aktiven `(Repo, PR)`s, mit rich-Progress-Bar pro Phase

**Checkpoint (US1 / MVP)**: `uv run benchmark all --repo <owner>/<name> --pr <n>` produziert alle Dateien in `runs/…/<pr#>/` sowie den `reports/per_pr/…md`. SC-001 (< 5 min pro PR) validiert. Manuell öffnen: die Tabelle zeigt Findings der drei Tools nebeneinander, mindestens ein gematchtes Paar.

---

## Phase 4: User Story 2 — Aggregatvergleich über viele PRs (Priority: P1)

**Goal**: Nach einem Batch-Run erzeugt `benchmark report` zusätzlich `reports/summary.md` und `reports/summary.csv` mit den Kennzahlen pro Repo × Tool.

**Independent Test**: Nach `benchmark all` für ein Repo mit ≥2 PRs beide Dateien öffnen, alle geforderten Spalten sichtbar (findings_after_dedup, findings_raw, overlap_with_cr, unique_to_tool, missed_from_cr, avg_severity_score, category_breakdown, failed_pr_count).

### Tests

- [X] T044 [P] [US2] `tests/unit/test_summary_stats.py`: aus vorbereiteten `PRRun`-Fixtures die `PerToolStats` berechnen; erwartete Zahlen für ein 3-PR-Mini-Szenario prüfen (inkl. failed_pr edge case)

### Implementation

- [X] T045 [US2] Implementiere `src/benchmark/reports/summary.py`: `build_stats(pr_runs) -> list[PerToolStats]` aggregiert über Repo × Tool; `render_summary_md(stats) -> str` und `render_summary_csv(stats) -> str`
- [X] T046 [US2] Erweitere `benchmark report` in `cli.py`: nach `render_per_pr` sammelt es `stats`, schreibt `reports/summary.md` und `reports/summary.csv` (immer, auch bei 1 PR)
- [X] T047 [US2] Erweitere `benchmark all` in `cli.py`: Progress-Bar pro Phase (`rich.progress`) — "Fetch (2/40)", "Run (2/40)", "Match (2/40)", "Report"

**Checkpoint (US2)**: `reports/summary.md` und `reports/summary.csv` liegen nach jedem Report-Lauf; im Terminal sieht der Nutzer den Batch-Fortschritt.

---

## Phase 5: User Story 3 — Manuelle Sichtung unsicherer Matches (Priority: P2)

**Goal**: Ein Nutzer kann in `runs/<owner>__<repo>/<pr#>/manual_review.json` Entscheidungen hinterlegen, die im nächsten `benchmark report`-Lauf die automatische Judge-Klassifikation überschreiben und im Summary-Report sichtbar werden.

**Independent Test**: `manual_review.json` mit einer Entscheidung anlegen, `benchmark report` erneut laufen, im Per-PR-Report sieht man das Match mit Kennzeichnung "manuell bestätigt/verworfen" statt Judge-Konfidenz; im Summary steht die Anzahl manuell entschiedener Matches.

### Tests

- [X] T048 [P] [US3] `tests/unit/test_manual_override.py`: Aggregator lädt vorhandenes `manual_review.json`, überschreibt entsprechende Match-Classifications, ignoriert nicht referenzierte Matches; `match_id` ohne Bezug → klare Warnung, kein Crash

### Implementation

- [X] T049 [US3] Erweitere `src/benchmark/matching/aggregator.py`: `load_manual_reviews(pr_dir) -> list[ManualReview]` (schema-validiert), Aggregator übersteuert `Match.classification` gemäß `ManualReview.decision`
- [X] T050 [US3] Erweitere `src/benchmark/reports/per_pr.py`: gematchte Zellen tragen einen Marker `⚙️ manuell` statt Judge-Konfidenz, wenn ein ManualReview existiert
- [X] T051 [US3] Erweitere `src/benchmark/reports/summary.py`: neue Spalte / Sektion "manuell bestätigt", "manuell verworfen" pro Repo × Tool im Summary
- [X] T051a [US3] Implementiere `src/benchmark/review/interactive.py`: iteriert über uncertain-Matches, präsentiert anonymisierte Finding-Texte + Datei/Zeilen-Kontext + Judge-Reason, promptet `[s]ame/[d]ifferent/[u]nclear/s[k]ip` (via `rich.prompt`), schreibt jeden Eintrag atomar in `manual_review.json` (Append + atomic replace via temp-file). `--include-confident` und `--reviewer` Optionen gemäß [contracts/cli.md](contracts/cli.md).
- [X] T051b [US3] Wire `benchmark review` in `cli.py`; ruft `interactive.py` auf. Bei bereits vollständig gesichteten PRs freundliche Meldung, kein Prompt.
- [X] T051c [P] [US3] `tests/unit/test_interactive_review.py`: mit gemocktem `rich.prompt` alle vier Antwort-Pfade durchspielen; nach Ctrl+C (KeyboardInterrupt) ist der bisherige Fortschritt in `manual_review.json` persistiert.

**Checkpoint (US3)**: `benchmark review --repo X --pr N` führt interaktiv durch alle uncertain-Matches; anschließend `benchmark report` reflektiert die Entscheidungen. SC-004 (< 20% Widerspruch bei manuellen Sichtungen) messbar aus dem Summary.

---

## Phase 6: User Story 4 — Tool-Konfiguration wechseln (Priority: P3)

**Goal**: LLM-Endpoints (Tool und Judge) sowie Judge-Provider (Anthropic vs OpenAI-compat) sind rein per `.env` austauschbar; Repos/PRs rein per `config/repos.yaml`.

**Independent Test**: `JUDGE_LLM_PROVIDER=anthropic` → `benchmark check` grün → einen bereits gematchten PR mit `--force match` neu bewerten, Judge-Entscheidungen ändern sich nachvollziehbar. Danach `JUDGE_LLM_PROVIDER=openai` und alternative Judge-Env-Vars → gleiches Verhalten ohne Codeänderung.

### Tests

- [X] T052 [P] [US4] `tests/unit/test_judge_factory.py`: `make_judge()` liefert `AnthropicJudge` bei `JUDGE_LLM_PROVIDER=anthropic`, `OpenAICompatJudge` bei `openai`, Fehlermeldung bei unbekanntem Provider

### Implementation

- [X] T053 [US4] Verifiziere/festige Judge-Factory in `src/benchmark/matching/judge.py` (bereits aus T032 vorhanden); ergänze klare Fehlermeldungen wenn Env-Vars für den gewählten Provider fehlen
- [X] T054 [US4] Erweitere `benchmark check` in `cli.py`: prüft *beide* LLM-Konfigurationen (TOOL_LLM + JUDGE_LLM) getrennt und weist auf fehlende Werte hin — für die jeweils aktive Provider-Wahl
- [X] T055 [US4] Dokumentiere den Provider-Swap in [quickstart.md](quickstart.md) als eigene Sektion "Judge-Provider wechseln"

**Checkpoint (US4)**: `.env` bearbeiten → `benchmark check` → `benchmark match --force` → sichtbar geänderte Judge-Antworten; keine Code-Änderung nötig.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T056 [P] `docs/README.md` aktualisieren mit Verweis auf spec/plan/quickstart und aktuellem Status
- [ ] T057 Performance-Sanity: einen realen PR-Run mit `time uv run benchmark all --repo X --pr N` messen, Wert in [research.md](research.md) als "beobachtete SC-001-Laufzeit" ergänzen — offen: benötigt Live-Credentials (Qwen + Judge + GH-Token)
- [X] T058 [P] `Makefile` oder `pyproject.toml [tool.uv]`-Scripts hinzufügen: `check` (ruff + pytest), `test` (nur pytest), `smoke` (benchmark check)
- [X] T059 [P] Ruff-Konfiguration + einmaliges `uv run ruff check --fix`
- [ ] T060 Quickstart-Validation: alle Schritte aus [quickstart.md](quickstart.md) durchlaufen (frische Umgebung, `cp .env.example .env`, config füllen, `benchmark check`, Single-PR-Smoke), sicherstellen dass nichts drift ist — offen: benötigt Live-Credentials
- [X] T060a [P] `tests/integration/test_idempotency.py` (FR-018 + SC-006): fixture-basierten Fake-Run für Repo A anlegen, alle vier Output-Dateien präsentieren; `benchmark all` erneut starten → keine Datei-mtime ändert sich. Danach Repo B in `repos.yaml` ergänzen und nochmal `benchmark all` → A-Dateien unangetastet, B-Dateien neu. `--force` überschreibt.
- [X] T061 [P] Wenn `LOG_LEVEL=DEBUG` gesetzt, sollen die Subprozess-Kommandos + relevante HTTP-Requests geloggt werden; Test dass sensitive Werte (API-Keys) nicht im Log auftauchen

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: keine Vorbedingung, startet sofort
- **Phase 2 (Foundational)**: braucht Phase 1
- **Phase 3 (US1 / MVP)**: braucht Phase 2 vollständig
- **Phase 4 (US2)**: braucht US1 (nutzt PR-Run-Loader + aggregator aus US1)
- **Phase 5 (US3)**: braucht US1 (aggregator wird erweitert)
- **Phase 6 (US4)**: braucht US1 (judge-Factory wird gefestigt)
- **Phase 7 (Polish)**: nach der jeweils vorführbaren US

### Innerhalb US1 (kritischer Pfad)

Fixtures (T016–T019) → Parser-Tests (T020–T022) → Parser-Impl (T027, T029, T030) → structural.py (T031) → judge.py (T032) → aggregator + dedup (T034–T035) → CLI-Wiring (T038–T043).

CLI-Verifikations-Tasks T024/T025 (gito/pr-agent `--help` prüfen) müssen VOR den Tool-Wrappern T029/T030 fertig sein, weil ihr Ergebnis die exakten Kommandos festlegt.

### Parallel Opportunities

**Innerhalb Phase 1**: T003, T005, T006, T007, T008 parallel (unabhängige Dateien).
**Innerhalb Phase 2**: T009, T010, T011 parallel; T013 + T014 parallel.
**Innerhalb US1**:
- T016, T017, T018, T019 alle parallel (Fixtures)
- T020, T021, T022, T023 parallel (Test-Dateien)
- T029 und T030 parallel (verschiedene Tool-Wrapper)
- T033, T036, T037 parallel (verschiedene Test-Dateien)

---

## Parallel Example: Fixtures + Parser-Tests für US1

```bash
# Fixtures anlegen (aus realen PRs abgezogen):
Task: "Erzeuge tests/fixtures/cr_review_full.md aus einem realen CR-Kommentar"
Task: "Erzeuge tests/fixtures/pragent_stdout.txt via manuellem pr-agent-Testlauf"
Task: "Erzeuge tests/fixtures/gito_output.json via manuellem gito-Testlauf"

# Parser-Tests parallel schreiben:
Task: "tests/unit/test_coderabbit_parser.py"
Task: "tests/unit/test_pragent_parser.py"
Task: "tests/unit/test_gito_parser.py"
Task: "tests/unit/test_structural_match.py"
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1 + Phase 2 abschließen — Foundation steht.
2. Phase 3 (US1) abschließen — end-to-end für 1 PR läuft.
3. **STOP & DEMO**: `benchmark all --repo X --pr N` → Per-PR-Report öffnen; SC-001 messen.

### Incremental Delivery

1. **MVP** (US1) → 1 PR, Per-PR-Report
2. + **US2** → Batch, Summary-Report ← die eigentliche Entscheidungsbasis
3. + **US3** → manuelle Sichtung
4. + **US4** → Provider-Swap
5. **Polish** — nach jeder US oder am Ende

### Suggested MVP Scope

Phasen 1 + 2 + US1 (T001–T043) → funktionierendes End-to-End für 1 PR. Der Rest (US2–US4, Polish) kann inkrementell nach jedem Demo-Zwischenschritt kommen.

---

## Notes

- [P] = andere Datei, keine Abhängigkeiten
- [Story] verknüpft Task mit User Story für Rückverfolgbarkeit
- Tests VOR Implementierung schreiben und rot sehen (per US1 explizit vorgesehen)
- Nach jeder US-Checkpoint commiten (kleine Commits, sprechende Messages)
- Bei T024/T025 (gito/pr-agent CLI-Verifikation): wenn die Doku vom research.md abweicht, [research.md](research.md) direkt updaten und die Änderung im Commit erwähnen
