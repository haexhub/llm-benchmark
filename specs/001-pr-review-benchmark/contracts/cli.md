# CLI-Kontrakt — `benchmark`

Der Nutzer interagiert ausschließlich per Kommandozeile: `python -m benchmark <subcommand>` (oder `uv run benchmark <subcommand>` wenn als Entry-Point installiert). Alle Subkommandos sind idempotent: existierende Output-Dateien werden übersprungen, `--force` erzwingt Neuberechnung.

## Globale Optionen

| Option | Default | Wirkung |
|---|---|---|
| `--config PATH` | `config/repos.yaml` | Alternatives Repo-YAML |
| `--runs-dir PATH` | `runs/` | Alternatives Runs-Verzeichnis |
| `--reports-dir PATH` | `reports/` | Alternatives Reports-Verzeichnis |
| `--log-level LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` — kann auch per Env `LOG_LEVEL` |
| `--repo OWNER/NAME` | (alle) | Auf ein Repo einschränken |
| `--pr N` | (alle) | Auf einen PR einschränken (setzt `--repo` voraus) |
| `--force` | false | Existierende Outputs überschreiben |

## Subkommando: `check`

**Zweck**: Sanity-Check der Umgebung, bevor Batch-Runs gestartet werden.

**Prüft**:
- `.env` vorhanden und geladen; alle Pflicht-Variablen gesetzt
- `gh auth status` läuft durch
- `TOOL_LLM_BASE_URL/models` antwortet und listet den konfigurierten `TOOL_LLM_MODEL`
- `pr-agent --help` und `gito --help` sind erreichbar
- Judge-Endpunkt antwortet auf einen Dummy-Request

**Exit-Code**: 0 wenn alles OK, 1 bei mindestens einem Fehlschlag; Ausgabe pro Prüfpunkt mit Symbol (`✓`/`✗`).

## Subkommando: `fetch`

**Zweck**: PR-Diff und CodeRabbit-Baseline pro (Repo, PR) einsammeln.

**Aktionen**:
1. Für jede aktive `(Repo, PR)`: `runs/<owner>__<repo>/<pr#>/` anlegen wenn fehlt.
2. `diff.patch` per `gh pr diff <n>` schreiben wenn nicht existent.
3. CR-Kommentare per drei `gh api` Aufrufe (`pulls/N/comments`, `pulls/N/reviews`, `issues/N/comments`) ziehen, auf `coderabbitai[bot]` filtern, mit CR-Parser in `coderabbit.json` verwandeln.

**Fehlerverhalten**: Ein einzelner API-Fehler markiert den PR als "fetch failed" in `failed.log`, restlicher Batch läuft weiter.

## Subkommando: `run`

**Zweck**: gito und pr-agent für jeden PR ausführen und Findings normalisieren.

**Aktionen**:
1. Pro `(Repo, PR)` ohne existierendes `gito.json` und `pr-agent.json`: beide Tools als Subprozesse nebenläufig starten (`ThreadPoolExecutor(2)`).
2. Stdout/Stderr in temp-Datei, dann parsen → `gito.json` bzw. `pr-agent.json` schreiben.
3. Timeout pro Tool: 10 min. Auf Timeout → `failed.log`-Eintrag, restlicher Batch weiter.

**Voraussetzung**: `fetch` ist gelaufen (`diff.patch` und `coderabbit.json` müssen existieren; sonst error early).

## Subkommando: `match`

**Zweck**: Findings-Paare bewerten (Cross-Tool + Intra-Tool-Dedup) und Match-Klassifikation schreiben.

**Aktionen**:
1. Pro `(Repo, PR)` alle drei Findings-Listen laden.
2. Structural-Match: pro Datei alle Paare mit Zeilen-Overlap ±3 sammeln (cross-tool + intra-tool).
3. Judge-Aufruf pro Paar; Ergebnisse in `matches.json`.
4. Klassifikation ableiten: `same`, `different`, `uncertain` (siehe data-model).

**Voraussetzung**: `run` ist gelaufen. Manuelle Reviews (`manual_review.json`) werden nicht im `match`-Schritt gelesen, sondern erst im `report`.

## Subkommando: `report`

**Zweck**: Menschenlesbare Reports rendern.

**Aktionen**:
1. Pro `(Repo, PR)` `matches.json` und `manual_review.json` (wenn vorhanden) laden; manuelle Entscheidungen überstimmen `classification`.
2. Per-PR-Report nach `reports/per_pr/<owner>__<repo>__<pr#>.md` schreiben — 3-Spalten-Tabelle CR|gito|pr-agent mit gematchten Zeilen aligned.
3. Aggregat: `PerToolStats` pro (Repo, Tool) rechnen; `reports/summary.md` + `reports/summary.csv` schreiben.

**Voraussetzung**: `match` ist gelaufen. Wenn nicht, erzeuge nur die Reports für die PRs, die bereits gematcht sind, und warne über die Auslassungen.

## Subkommando: `review`

**Zweck**: Interaktive Sichtung der als `uncertain` klassifizierten Matches. Erzeugt/aktualisiert `manual_review.json` pro (Repo, PR) — kein Hand-Editieren notwendig.

**Aktionen**:
1. Pro `(Repo, PR)` alle Matches mit `classification == "uncertain"` sammeln, für die noch kein `ManualReview`-Eintrag existiert.
2. Nacheinander präsentieren: Datei/Zeilen-Anker beider Findings, anonymisierte Finding-Texte (kein Tool-Name), Judge-Reason.
3. Prompt: `[s]ame / [d]ifferent / [u]nclear / s[k]ip`. Optional Note.
4. Nach jedem Ok: sofortiges Append in `manual_review.json` (atomar), damit Ctrl+C nichts verliert.
5. Am Ende Vorschlag: `benchmark report --repo X --pr N` erneut laufen lassen, damit die manuellen Entscheidungen einfließen.

**Voraussetzung**: `match` ist gelaufen.

**Optionen**:
- `--include-confident` — auch Matches mit hoher Konfidenz zeigen (Stichproben-Sichtung)
- `--reviewer NAME` — Feldwert für `manual_review.json`; Default aus `git config user.email` oder Env `USER`

## Subkommando: `all`

**Zweck**: `fetch` → `run` → `match` → `report` in Sequenz, mit Progress-Bar pro Phase.

**Verhalten**: Bricht bei Env-Check-Fehler ab, sonst läuft es alle vier Phasen durch. Jeder Ausfall in Einzel-PRs bleibt Warning, nie Abbruch. Report berücksichtigt PRs auch dann, wenn nur ein Teil der Phasen für sie durchging (mit klarer Kennzeichnung).

## Exit-Codes

| Code | Bedeutung |
|---|---|
| 0 | Erfolg (alle Phasen sauber, ODER Teil-Erfolg mit dokumentierten `failed.log`-Einträgen) |
| 1 | Env-Check fehlgeschlagen (`check`) oder Konfiguration ungültig |
| 2 | Nicht-behebbarer Batch-Fehler (Judge-Endpunkt gesamt offline etc.) |
| 130 | SIGINT/Ctrl+C — schreibt geöffnete Zwischenstände fertig, dann Abbruch |
