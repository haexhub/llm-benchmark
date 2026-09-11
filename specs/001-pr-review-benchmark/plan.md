# Implementation Plan: PR-Review Benchmark

**Branch**: `001-pr-review-benchmark` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-pr-review-benchmark/spec.md`

## Summary

Pipeline zum Vergleich von drei AI-PR-Reviewern (CodeRabbit als Baseline, gito.bot und pr-agent als Challenger, beide gegen dasselbe lokal gehostete Qwen-Modell) über 5 Repos × 40+ PRs. Findings werden in ein einheitliches JSON-Schema überführt, per struktureller Heuristik (Datei + Zeilen-Overlap ±3) und externem LLM-Judge (Anthropic Claude Sonnet, austauschbar) paarweise auf semantische Äquivalenz geprüft, und in Per-PR- sowie Aggregat-Reports zusammengefasst. Alle drei Ergebnisse fließen als reine Dateien unter `runs/<repo>/<pr#>/` ab; manuelle Sichtungsentscheidungen leben in einer eigenen `manual_review.json` pro PR und überstimmen automatische Judge-Entscheidungen bei Re-Runs.

Technischer Kernansatz: Python-CLI (uv-verwaltet), `gh` CLI + `pr-agent` + `gito` als Subprozesse (bewusste CLI-Grenze — keine Bibliotheks-Integration, um Tool-Grenzen sauber zu halten), Judge-Anbindung über das `anthropic`-SDK (oder `openai`-SDK je nach Endpunkt), Persistenz reine Dateien.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: `typer` (CLI-Framework), `python-dotenv` (Env-Loading), `pyyaml` (Config), `pydantic` (Finding-Schema-Validierung), `httpx` (GitHub-API + LLM-HTTP), `anthropic` und `openai` (Judge-Clients, konfigurationsabhängig), `rich` (Progress-Ausgabe), stdlib `asyncio`/`concurrent.futures` (Tool-Parallelisierung innerhalb einer PR-Iteration)
**External CLIs**: `gh` (GitHub CLI, bereits beim Nutzer installiert), `pr-agent` (via `uv tool run --from pr-agent`), `gito` (via `uv tool run --from gito.bot`)
**Storage**: Dateisystem — JSON pro (Repo, PR) unter `runs/<repo>/<pr#>/`; keine DB.
**Testing**: pytest + pytest-asyncio; Fokus auf Parser-Tests (CR-Markdown-Blöcke, pr-agent-Stdout, gito-Ausgabe) und Matcher-Tests (structural + Judge-Integration mit gemockten LLM-Responses). Kein E2E gegen echten Qwen im Test-Setup.
**Target Platform**: Linux (Nutzer-Umgebung: Pop!_OS 7.1.5-76070105-generic). Nicht plattformunabhängig gedacht, aber MacOS sollte funktionieren.
**Project Type**: CLI-Tool (Single-Project-Layout)
**Performance Goals**: Ein PR-Run vollständig (CR-Scrape + gito + pr-agent + Match) < 5 min bei reaktivem LLM-Endpunkt (SC-001). Batch über 200 PRs ohne blockierende Ausfälle (SC-002). Innerhalb eines PRs laufen gito und pr-agent nebenläufig (2 parallele Subprozesse), zwischen PRs strikt sequenziell (Rate-Limit-Schutz).
**Constraints**: GitHub-API-Limit 5000 req/h pro Token → mit ~4 Calls/PR bei 200 PRs = ~800 Calls, unkritisch. Qwen-Endpunkt ist der Engpass, keine parallelen PR-Runs. Judge-Kosten Ziel < 5 USD Gesamt-Benchmark.
**Scale/Scope**: 5 Repos, initial 40+ PRs pro Repo (~200+ Runs), erweiterbar. Pro Run ~50 KB JSON-Output. Kein Multi-User, kein Netzwerk-Service.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Constitution-Status**: Die Datei `.specify/memory/constitution.md` enthält nur Template-Platzhalter — es wurden noch keine Projekt-Prinzipien ratifiziert (`/speckit-constitution` wurde nicht aufgerufen).

**Bewertung**: Kein GATE-Verstoß möglich, da keine ratifizierten Regeln existieren. Als Ersatz gilt die globale CLAUDE.md des Nutzers (Simplicity First, Surgical Changes, Goal-Driven Execution, Accuracy Over Agreement). Diese sind hier eingehalten:

- **Simplicity First**: Keine DB, kein Framework, keine Web-UI, keine Vorbereitung für den zukünftigen Coding-Task-Benchmark (YAGNI). Nur die für die 4 User Stories benötigten Bausteine.
- **Surgical Changes**: N/A für Greenfield-Projekt.
- **Goal-Driven Execution**: Success Criteria SC-001 bis SC-006 sind messbar; Tasks werden in Phase 2 daran gehängt.
- **Accuracy Over Agreement**: Alle Tech-Entscheidungen in `research.md` mit Alternativen dokumentiert.

**Ergebnis**: PASS (mit Vorbehalt: sollte eine Constitution nachträglich ratifiziert werden, muss dieser Plan gegen sie neu bewertet werden).

## Project Structure

### Documentation (this feature)

```text
specs/001-pr-review-benchmark/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output — JSON schemas + CLI subcommand contracts
│   ├── finding.schema.json
│   ├── manual_review.schema.json
│   └── cli.md
├── checklists/
│   └── requirements.md  # aus /speckit-specify
└── tasks.md             # Phase 2 output — /speckit-tasks
```

### Source Code (repository root)

```text
llm-benchmark/
├── .env.example              # Vorlage — kopiert nach .env, dann Werte setzen
├── pyproject.toml            # uv-managed, deklariert Deps + Entry-Points
├── uv.lock
├── config/
│   └── repos.yaml            # Liste (Repo × PR-Nummern)
├── runs/                     # gitignored — die eigentliche Datenlage
│   └── <owner>__<repo>/<pr#>/
│       ├── diff.patch
│       ├── coderabbit.json
│       ├── gito.json
│       ├── pr-agent.json
│       ├── matches.json           # automatischer Judge-Output
│       ├── manual_review.json     # überstimmt matches.json bei Re-Runs
│       └── failed.log             # nur wenn Tool-Ausfall
├── reports/                  # gitignored — Ausgabe von `report` subcommand
│   ├── per_pr/<owner>__<repo>__<pr#>.md
│   ├── summary.md
│   └── summary.csv
├── src/
│   └── benchmark/
│       ├── __init__.py
│       ├── __main__.py           # `python -m benchmark …`
│       ├── cli.py                # typer entrypoint (fetch/run/match/report)
│       ├── config.py             # .env + repos.yaml Loader
│       ├── models.py             # pydantic Finding, PRRun, Match, Report
│       ├── github/
│       │   ├── __init__.py
│       │   └── fetch.py          # gh CLI Wrapper: PR-Liste, .patch, CR-Comments
│       ├── coderabbit/
│       │   ├── __init__.py
│       │   └── parser.py         # CR-Markdown → Finding[]
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py           # gemeinsames Subprozess-Handling + Timeout
│       │   ├── pr_agent.py       # pr-agent CLI Wrapper + Output-Parser
│       │   └── gito.py           # gito CLI Wrapper + Output-Parser
│       ├── matching/
│       │   ├── __init__.py
│       │   ├── structural.py     # file+line overlap Kandidaten
│       │   ├── judge.py          # Anthropic/OpenAI Judge-Client
│       │   ├── dedup.py          # Intra-Tool-Duplikat-Erkennung (nutzt judge)
│       │   └── aggregator.py     # matches → per-Finding Klassifikation
│       ├── review/
│       │   ├── __init__.py
│       │   └── interactive.py    # `benchmark review` — interaktive Sichtung uncertain-Matches
│       └── reports/
│           ├── __init__.py
│           ├── per_pr.py         # Markdown-Rendering für einen PR
│           └── summary.py        # Markdown + CSV Aggregat
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── test_config.py
    │   ├── test_coderabbit_parser.py
    │   ├── test_pragent_parser.py
    │   ├── test_gito_parser.py
    │   ├── test_structural_match.py
    │   └── test_aggregator.py
    ├── integration/
    │   ├── test_judge_client.py       # gegen Mock-HTTP-Server
    │   └── test_cli_smoke.py          # `benchmark --help` sanity
    └── fixtures/                       # eingefrorene CR-Kommentare, gito/pr-agent Outputs
        ├── cr_review_full.md
        ├── cr_review_empty.md
        ├── pragent_stdout.txt
        └── gito_output.json
```

**Structure Decision**: Single-Project-Layout. Die logische Trennung passiert in `src/benchmark/` per Modul (`github/`, `coderabbit/`, `tools/`, `matching/`, `reports/`) und ist bewusst flach — keine Framework-Schichten. Der spätere zweite Benchmark-Typ (Coding-Tasks) wird als *separates Projektverzeichnis* daneben aufgesetzt, nicht als Modul dazu (Simplicity, keine vorzeitige Abstraktion). `runs/` und `reports/` werden gitignored, weil sie Datenlage sind, nicht Code.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Keine Verstöße (Constitution enthält keine Regeln).
