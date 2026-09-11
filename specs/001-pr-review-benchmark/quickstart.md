# Quickstart — PR-Review Benchmark

Ziel: In wenigen Minuten die Pipeline für einen einzelnen (Repo, PR) durchlaufen und den Per-PR-Report öffnen. Danach in einem zweiten Schritt auf einen Batch skalieren.

## Voraussetzungen

- Python 3.12+
- `uv` installiert (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `gh` (GitHub CLI) installiert und authentifiziert (`gh auth status` grün)
- Lesender Netzwerkzugang zu `https://your-llm-endpoint.example.com/v1` (Qwen)
- Judge-Zugang (Anthropic API-Key oder OpenAI-kompatibler Endpunkt)

## Setup (einmalig)

```bash
cd ~/Projekte/llm-benchmark

# Deps installieren (uv liest pyproject.toml + uv.lock)
uv sync

# .env aus Vorlage anlegen
cp .env.example .env
# → dann .env öffnen und die Werte setzen:
#   TOOL_LLM_BASE_URL=https://your-llm-endpoint.example.com/v1
#   TOOL_LLM_API_KEY=…
#   TOOL_LLM_MODEL=…       (aus /v1/models bestätigt)
#   JUDGE_LLM_PROVIDER=anthropic
#   JUDGE_LLM_API_KEY=sk-ant-…
#   JUDGE_LLM_MODEL=claude-sonnet-4-5
#   GH_TOKEN=…              (falls gh-Auth nicht reicht)

# Sanity-Check der Umgebung
uv run benchmark check
```

`check` schlägt alarm, wenn eine der drei Endpunkte / gh-Auth / eines der Tools nicht sauber antwortet.

## Repo-Konfiguration

```bash
# config/repos.yaml editieren — mindestens ein Repo + ein PR
cat > config/repos.yaml <<'YAML'
repos:
  - owner: your-user
    name: sample-repo
    pr_numbers: [42]
YAML
```

## Erster Lauf (Single-PR-Smoke-Test)

```bash
# Nur diesen einen PR alle vier Phasen durchlaufen lassen
uv run benchmark all --repo your-user/sample-repo --pr 42
```

Erwartetes Ergebnis:
- `runs/your-user__sample-repo/42/` enthält `diff.patch`, `coderabbit.json`, `gito.json`, `pr-agent.json`, `matches.json`
- `reports/per_pr/your-user__sample-repo__42.md` enthält die 3-Spalten-Tabelle
- `reports/summary.md` und `reports/summary.csv` enthalten Zahlen für dieses eine Repo × drei Tools

## Batch (alle konfigurierten Repos & PRs)

```bash
uv run benchmark all
```

Wall-Clock-Erwartung: ~2 Minuten pro PR bei responsivem Qwen; Judge-Kosten grob 1–2 USD gesamt für 200 PRs.

## Manuelle Sichtung unsicherer Matches

Nach `match` finden sich unsichere Kandidaten in den `matches.json`-Dateien (classification=`uncertain`). Der interaktive Sichtungsmodus führt dich durch alle offenen Punkte:

```bash
uv run benchmark review --repo your-user/sample-repo --pr 42
```

Pro uncertain-Match zeigt er beide Finding-Texte anonymisiert (kein Tool-Name), Datei/Zeilen-Kontext und die Judge-Begründung, und fragt `[s]ame / [d]ifferent / [u]nclear / s[k]ip`. Jede Entscheidung wird sofort in `runs/<owner>__<repo>/<pr#>/manual_review.json` gespeichert (auch bei Ctrl+C sicher).

Direktes Hand-Editieren dieser Datei bleibt möglich — Schema siehe [contracts/manual_review.schema.json](contracts/manual_review.schema.json).

Anschließend Report neu erzeugen:

```bash
uv run benchmark report --repo your-user/sample-repo --pr 42
```

Der Aggregat-Report weist danach aus, wieviele Matches manuell bestätigt oder verworfen wurden.

## Wiederholte Läufe

`fetch`, `run`, `match`, `report` sind alle idempotent — sie überspringen (Repo, PR)-Kombinationen, für die die jeweilige Output-Datei bereits vorliegt.

```bash
# Nur den report neu erzeugen (Findings + matches bleiben)
uv run benchmark report

# Ein einzelnes PR-Ergebnis neu berechnen
uv run benchmark all --repo your-user/sample-repo --pr 42 --force
```

## Judge-Provider wechseln

Der Judge ist per `.env` austauschbar — kein Code-Change nötig.

**Anthropic (Default)**:
```
JUDGE_LLM_PROVIDER=anthropic
JUDGE_LLM_API_KEY=sk-ant-…
JUDGE_LLM_MODEL=claude-sonnet-4-5
```

**Beliebiger OpenAI-kompatibler Endpunkt** (eigenes Modell, Azure, Groq, eigenes Angebot, …):
```
JUDGE_LLM_PROVIDER=openai
JUDGE_LLM_BASE_URL=https://api.openai.com/v1
JUDGE_LLM_API_KEY=sk-…
JUDGE_LLM_MODEL=gpt-4o-mini
```

Danach:
```bash
uv run benchmark check                    # verifiziert die aktive Provider-Config
uv run benchmark match --force            # bewertet vorhandene Matches mit neuem Judge
uv run benchmark report --force
```

Judge-Ergebnisse (Konfidenz, Reasoning) landen in `runs/…/matches.json` und werden bei jedem Re-Match überschrieben — die Historie geht dabei verloren; wenn du zwei Judges vergleichen willst, ziehe zuerst eine Kopie der `matches.json`.

## Fehlerdiagnose

- `benchmark check` zuerst — 90% aller Probleme fallen dort auf.
- Für einen einzelnen PR-Ausfall: `runs/<repo>/<pr#>/failed.log` lesen.
- Log-Level hochziehen: `LOG_LEVEL=DEBUG uv run benchmark …`
