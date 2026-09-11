# Phase 1 Data Model — PR-Review Benchmark

Alle Entities werden als pydantic-Modelle in `src/benchmark/models.py` implementiert und als JSON auf Disk persistiert. Kein DB-Schema, keine Migrations.

## Entity: RepoConfig

Konfigurations-Datensatz aus `config/repos.yaml`. Kein Persistenz-Artefakt der Pipeline, nur Eingabe.

| Feld | Typ | Beschreibung |
|---|---|---|
| `owner` | str | GitHub-Org oder User (z.B. `your-org`) |
| `name` | str | Repo-Name |
| `pr_numbers` | list[int] | Konkrete PR-Nummern zum Benchmarken |

**Validierung**: `owner` und `name` non-empty; `pr_numbers` non-empty und alle > 0.

**YAML-Beispiel**:
```yaml
repos:
  - owner: your-user
    name: some-repo
    pr_numbers: [12, 13, 27, 42, ...]
```

## Entity: PRRun

Repräsentiert einen Lauf für einen (Repo, PR)-Pair. Ist kein persistiertes Objekt an sich, sondern die logische Klammer um alle Dateien im PR-Ordner. Hauptzweck: die zusammengehörigen Findings-Listen laden.

**Verzeichnis**: `runs/<owner>__<repo>/<pr#>/`

**Enthält**:
- `diff.patch` (raw text, aus `gh pr diff`)
- `coderabbit.json` (list[Finding])
- `gito.json` (list[Finding])
- `pr-agent.json` (list[Finding])
- `matches.json` (Matches, automatisch)
- `manual_review.json` (optional, überschreibt matches.json bei Aggregation)
- `failed.log` (optional, bei Tool-Ausfall)

**Zustände**:
- `initialized` — nur Verzeichnis existiert
- `diff_fetched` — `diff.patch` vorhanden
- `cr_scraped` — `coderabbit.json` vorhanden (kann leer sein bei Edge-Case "kein CR-Review")
- `tools_run` — alle drei `*.json` vorhanden (`gito`/`pr-agent` können `failed.log`-Marker haben statt Content)
- `matched` — `matches.json` vorhanden
- `reported` — im aktuellen Report enthalten

Zustände werden aus Datei-Existenz abgeleitet, nicht persistiert.

## Entity: Finding

Ein einzelner Review-Kommentar eines Tools zu einer Codestelle. Kernentität; wird von allen drei Parsern (CR, gito, pr-agent) produziert.

| Feld | Typ | Beschreibung |
|---|---|---|
| `id` | str | UUIDv4, stabil pro Finding innerhalb einer Datei; für Match-Referenzen |
| `tool` | Literal[`"coderabbit"`, `"gito"`, `"pr-agent"`] | Ursprungs-Tool |
| `file` | str | Datei-Pfad relativ zum Repo-Root |
| `line_start` | int | 1-basiert; für File-Level-Findings 0 |
| `line_end` | int | ≥ line_start |
| `severity` | Literal[`"critical"`, `"major"`, `"minor"`, `"nit"`, `"info"`] | Normalisiert |
| `category` | Literal[`"bug"`, `"security"`, `"perf"`, `"style"`, `"test"`, `"doc"`, `"other"`, `"unknown"`] | Normalisiert |
| `title` | str | Kurzfassung, ≤ 200 Zeichen |
| `body` | str | Volltext des Kommentars, Markdown erlaubt |
| `suggestion` | str \| None | Optional: code-Vorschlag, falls Tool einen bereitstellt |
| `raw` | dict | Ursprüngliche Tool-Ausgabe (für Debugging und Nachverfolgung) |

**Validierung**:
- `line_end >= line_start`
- `line_start >= 0`
- `file` non-empty
- `severity` und `category` gehören zu den Enums
- `title` ≤ 200 Zeichen (harte Grenze, um Report-Tabellen lesbar zu halten)

**Severity-Normalisierung** (siehe `contracts/finding.schema.json` für Mapping-Tabelle):
- CR `⚠️ Potential issue` → `major`
- CR `🛠️ Refactor suggestion` → `minor`
- CR `🧹 Nitpick` → `nit`
- CR `✅ Verification` → `info`
- pr-agent numeric severity 5/4 → `critical`/`major`, 3 → `minor`, 2/1 → `nit`
- gito → abhängig von tatsächlicher Ausgabe-Struktur (siehe research R2, wird bei Setup konkretisiert)

## Entity: MatchCandidate

Ein struktureller Match-Kandidat (Datei+Zeilen-Overlap ±3), noch nicht semantisch bewertet.

| Feld | Typ | Beschreibung |
|---|---|---|
| `a_id` | str | Finding.id der linken Seite |
| `b_id` | str | Finding.id der rechten Seite |
| `a_tool` | str | Redundant, aber praktisch für Reports |
| `b_tool` | str | Redundant, aber praktisch für Reports |
| `structural_overlap_lines` | int | Anzahl gemeinsam überdeckter Zeilen |

Wird nicht dauerhaft persistiert; nur In-Memory-Zwischenstufe vor Judge-Aufruf.

## Entity: JudgeVerdict

Antwort des Judge-Modells für ein Kandidatenpaar.

| Feld | Typ | Beschreibung |
|---|---|---|
| `same` | bool | Bezeichnen beide Findings denselben Defekt? |
| `confidence` | float | 0.0–1.0 |
| `reason` | str | Kurzbegründung des Judge |
| `judge_model` | str | z.B. `claude-sonnet-4-5` — für Nachvollziehbarkeit |
| `prompt_hash` | str | sha256 des rohen Prompts — Regressionsdiagnose |

## Entity: Match

Vollständiger Match-Datensatz nach Judge-Bewertung. Wird in `matches.json` persistiert.

| Feld | Typ | Beschreibung |
|---|---|---|
| `id` | str | UUIDv4 |
| `a_id` | str | Finding.id A |
| `b_id` | str | Finding.id B |
| `structural_overlap_lines` | int | aus MatchCandidate |
| `verdict` | JudgeVerdict | siehe oben |
| `classification` | Literal[`"same"`, `"different"`, `"uncertain"`] | abgeleitet: `same`=True→`same`, confidence<0.6→`uncertain`, sonst `different` |

**Beziehungen**: Ein Finding kann in mehreren Matches auftauchen (z.B. CR-Finding matcht sowohl mit gito als auch mit pr-agent). Beim Aggregation wird das aufgelöst.

## Entity: ManualReview

Menschliche Überstimmung einer Match-Klassifikation. In `manual_review.json` pro PR persistiert.

| Feld | Typ | Beschreibung |
|---|---|---|
| `match_id` | str | Referenz auf Match.id |
| `decision` | Literal[`"same"`, `"different"`, `"unclear"`] | Menschliche Entscheidung |
| `note` | str \| None | Optionaler Kommentar |
| `reviewer` | str | Freitextfeld — E-Mail-Adresse oder Name |
| `ts` | datetime | ISO-8601 mit Zeitzone |

**Validierung**:
- `match_id` muss in `matches.json` existieren
- `reviewer` non-empty

Ist der Aggregator gestartet und `manual_review.json` existiert, überstimmt jede darin enthaltene Entscheidung die entsprechende Match.classification. Findings, für die keine ManualReview existiert, behalten die automatische Klassifikation.

## Entity: PerToolStats

Aggregat-Datenstruktur für den Summary-Report — pro Repo und pro Tool.

| Feld | Typ | Beschreibung |
|---|---|---|
| `repo` | str | `<owner>/<name>` |
| `tool` | str | `coderabbit`/`gito`/`pr-agent` |
| `findings_raw` | int | Vor Intra-Tool-Dedup |
| `findings_after_dedup` | int | Nach Intra-Tool-Dedup |
| `overlap_with_cr` | int | Anzahl Findings, die sich mit CR decken (nur für gito/pr-agent sinnvoll) |
| `unique_to_tool` | int | Anzahl einzigartige Findings |
| `missed_from_cr` | int | CR-Findings, die dieses Tool verpasst hat (nur für gito/pr-agent sinnvoll) |
| `avg_severity_score` | float | Numerisch: critical=5..info=1; für Vergleich |
| `category_breakdown` | dict[str, int] | Kategorie → Anzahl |
| `failed_pr_count` | int | Anzahl PRs mit Tool-Ausfall in diesem Repo |
| `total_pr_count` | int | Anzahl PRs im Repo (Nenner) |
| `runtime_seconds` | float | Summe Tool-Wall-Clock über alle PRs im Repo |

Wird In-Memory berechnet und in `reports/summary.csv` + `reports/summary.md` gerendert; nicht separat persistiert.

## Datenfluss

```
config/repos.yaml
        │
        ▼
   fetch  ───────►  runs/<repo>/<pr#>/diff.patch  +  coderabbit.json
        │
        ▼
   run    ───────►  runs/<repo>/<pr#>/gito.json   +  pr-agent.json  (+ failed.log)
        │
        ▼
   match  ───────►  runs/<repo>/<pr#>/matches.json     ◄── manual_review.json (wenn vorhanden)
        │
        ▼
   report ───────►  reports/per_pr/*.md  +  reports/summary.md  +  reports/summary.csv
```

Jeder Pfeil ist ein CLI-Subkommando. Jede Stufe ist idempotent bezüglich existierender Output-Dateien (`--force` überschreibt).
