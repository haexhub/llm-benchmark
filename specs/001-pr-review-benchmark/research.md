# Phase 0 Research — PR-Review Benchmark

Klärt die zum Zeitpunkt der Planung offenen Punkte aus `plan.md → Technical Context`. Konfidenz-Tags nach globaler CLAUDE.md-Konvention: `[Certain]` = gerade verifiziert, `[Likely]` = starke Ableitung, `[Guessing]` = Lücke.

## R1 — pr-agent CLI-Aufruf und Konfiguration

**Frage**: Wie ruft man `pr-agent` gegen einen konkreten PR mit einem benutzerdefinierten OpenAI-kompatiblen Endpunkt auf, und wo landen die Findings?

**Entscheidung**: `uv tool run --from pr-agent pr-agent --pr_url <url> review`. Konfiguration ausschließlich via Environment mit dem `CONFIG__`/`OPENAI__`/`GITHUB__`-Präfix, das pr-agent aus `.env` liest. Findings kommen als Markdown-Review-Body auf stdout und werden zusätzlich als GitHub-Comment gepostet — wir *unterdrücken* das Posten (`--config.publish_output=false` oder Äquivalent, wird an `pr-agent --help` verifiziert) und parsen den Markdown-Body.

**Rationale**: pr-agent ist LiteLLM-basiert und akzeptiert `OPENAI__API_BASE` = benutzerdefinierter Endpunkt sowie `CONFIG__MODEL` = `openai/<qwen-id>`. Kein Fork nötig. Env-basierte Konfig passt sauber zur `.env`-Vorgabe.

**Alternativen abgelehnt**:
- Direkt pr-agent als Python-Bibliothek einbinden (`from pr_agent.agent import PRAgent`) → koppelt uns an interne pr-agent-Klassen, die sich zwischen Releases ändern. CLI-Grenze ist stabiler.
- GitHub-Action laufen lassen → braucht Bot-Installation, widerspricht dem "lokal gegen Diff"-Beschluss aus dem Brainstorming.

**Konfidenz**: `[Likely]` für die exakten Env-Var-Namen. Muss zum Setup-Zeitpunkt gegen `pr-agent --help` und die Doku (github.com/qodo-ai/pr-agent) endverifiziert werden; ggf. Anpassung im `run_pragent.py`-Wrapper.

## R2 — gito CLI-Aufruf und Konfiguration

**Frage**: Wie ruft man `gito` (PyPI-Paket `gito.bot`) lokal gegen einen PR mit einem benutzerdefinierten LLM-Endpunkt auf?

**Entscheidung**: `uv tool run --from gito.bot gito review <pr-url>` (Kommando-Name laut PyPI-Beschreibung: `gito`). Modell + Endpunkt über `OPENAI_API_BASE`, `OPENAI_API_KEY` (LiteLLM-Konvention) und `--model openai/<qwen-id>` bzw. den in gito vorgesehenen Weg (`gito.toml` oder ähnliches). Findings entweder als JSON via `--format json` oder als Markdown; präferiert JSON.

**Rationale**: gito.bot nutzt LiteLLM, dieselben Env-Vars wie pr-agent funktionieren. Beide Tools an einer Environment-Konfig aufhängen reduziert Divergenz.

**Alternativen abgelehnt**:
- Als Bibliothek einbinden → gleiche Argumente wie bei pr-agent.
- Nur den Bot-Modus (GitHub App) → keine lokale Reproduzierbarkeit.

**Konfidenz**: `[Guessing]` für die exakte Subkommando-Struktur und ob `--format json` existiert. Ist der Punkt mit dem größten Verifikations-Bedarf zum Setup-Zeitpunkt — die Doku steht auf gito.bot. Fallback: Markdown parsen wenn kein JSON-Modus vorhanden ist.

## R3 — CodeRabbit Review-Kommentar-Struktur

**Frage**: Wie sind CR-Kommentare auf einem PR strukturiert und wie zieht man sie zuverlässig ab?

**Entscheidung**: Drei GitHub-API-Endpunkte kombinieren, alles gefiltert auf `user.login == "coderabbitai[bot]"`:
1. `GET /repos/{owner}/{repo}/pulls/{n}/comments` — line-level Review-Kommentare (haben `path`, `line`, `body`, ggf. `original_line`).
2. `GET /repos/{owner}/{repo}/pulls/{n}/reviews` — Review-Summaries (haben `body` ohne Line-Anker).
3. `GET /repos/{owner}/{repo}/issues/{n}/comments` — general issue-comments (CR postet dort Summary-Blöcke + Nitpicks).

CR-Body-Format innerhalb der Kommentare enthält strukturierte Markdown-Blöcke mit ASCII-/Emoji-Präfixen: `⚠️ Potential issue`, `🛠️ Refactor suggestion`, `🧹 Nitpick`, `✅ Verification`, `💡 Suggestion`. Parser splittet an diesen Headern; jedes Block-Segment wird ein Finding.

**Rationale**: Line-comments allein reichen nicht, weil CR Summary-artige Übersichten häufig als issue-comment postet. Die drei Endpunkte gemeinsam sind die vollständige Sicht.

**Alternativen abgelehnt**:
- CodeRabbit CLI (`.coderabbit/`-Verzeichnis existiert beim Nutzer) verwenden, um Findings neu zu erzeugen → verändert die Baseline, der Sinn ist aber der Vergleich gegen die *historische* CR-Sicht.
- Nur `pulls/{n}/comments` scrapen → verpasst Summary-Blöcke systematisch.

**Konfidenz**: `[Likely]` für die Präfix-Struktur (CR-Formate ändern sich gelegentlich). Der Parser muss robust gegenüber unbekannten Blöcken sein (fallback: ganzer Body als ein Finding mit Kategorie `unknown`). Fixtures pro CR-Format-Variante werden Teil der Test-Suite.

## R4 — Verifikation des Qwen-Modell-Identifiers

**Frage**: Wie stellen wir sicher, dass der Modell-Name gegen den lokalen Endpunkt korrekt ist (User schrieb "Qwen3.8-27B-FP8", was vermutlich ein Tippfehler ist)?

**Entscheidung**: Zum Setup-Zeitpunkt ein einmaliger `curl $TOOL_LLM_BASE_URL/models -H "Authorization: Bearer $TOOL_LLM_API_KEY"`. Ergebnis wird manuell in `.env` als `TOOL_LLM_MODEL=<id>` gepflegt. `benchmark check` (ein CLI-Subkommando) macht diesen Roundtrip zusätzlich als Sanity-Check und weigert sich weiterzumachen, wenn das konfigurierte Modell nicht in der `/models`-Liste steht.

**Rationale**: OpenAI-kompatible Endpunkte listen ihre Modelle über `/v1/models`. Ein einmaliger Setup-Schritt reicht; ein regelmäßiger Check verhindert, dass Batch-Runs mit falschem Modell durchrasseln und stundenlang HTTP 400 werfen.

**Alternativen abgelehnt**:
- Modell hart im Code hinterlegen → widerspricht FR-004 (Endpunkt/Modell wählbar).
- `/models` bei jedem PR-Run neu ziehen → unnötiger Traffic.

**Konfidenz**: `[Certain]` — OpenAI-Kompatibilitäts-Spec ist stabil.

## R5 — Judge-Client (Anthropic Claude Sonnet vs. OpenAI-kompat)

**Frage**: Welches SDK für den Judge, wenn wir Sonnet als Default und einfache Austauschbarkeit wollen?

**Entscheidung**: Ein dünner Judge-Adapter mit zwei Backends: `anthropic-native` (via `anthropic`-SDK, verwendet `claude-sonnet-4-5`) und `openai-compat` (via `openai`-SDK gegen beliebigen OpenAI-kompatiblen Endpunkt). Auswahl per Env-Var `JUDGE_LLM_PROVIDER=anthropic|openai`. Der Judge-Prompt selbst ist identisch, nur das Transport-SDK unterscheidet sich. Response-Format `JsonSchema` für strukturierte Antworten (`same: bool, confidence: float, reason: str`).

**Rationale**: Anthropic-natives SDK gibt uns direkt die neueste Sonnet-Version mit Structured Outputs. Für "ChatGPT Luna" oder andere OpenAI-kompatible Anbieter (inkl. eines evtl. eigenen Endpunkts) reicht das OpenAI-SDK. Zwei kurze Adapter sind einfacher zu warten als eine Abstraktionsschicht ala LiteLLM, und schließen die Verantwortung ein.

**Alternativen abgelehnt**:
- Nur LiteLLM als Judge-Client → zusätzliche Abhängigkeit, deren Ausfälle wir dann debuggen müssten.
- Anthropic-only → verletzt FR-008 (Judge muss austauschbar sein).

**Konfidenz**: `[Certain]` — beide SDKs sind stabil, Structured Outputs sind bei beiden verfügbar.

## R6 — Test-Strategie für Matcher

**Frage**: Wie testen wir den Judge-integrierten Matcher, ohne bei jedem Testlauf echte LLM-Kosten oder Nichtdeterminismus zu erzeugen?

**Entscheidung**: Der Judge-Client wird hinter ein Protocol/ABC gekapselt (`JudgeClient` mit einer Methode `evaluate_pair(a, b) -> JudgeVerdict`). In Tests wird eine `FakeJudge` injiziert, die vorbereitete Antworten pro Paar-Signatur liefert. Structural-Match-Logik wird pur ohne LLM getestet (nur file/line-Overlap). Judge-Integrations-Test läuft *einmalig* gegen den echten Endpunkt in einem opt-in `-m live` Marker (nicht CI-default).

**Rationale**: Fokus der Unit-Tests bleibt auf Logikfehlern (Overlap-Toleranz, Aggregations-Klassifikation, Intra-Tool-Dedup). Echte LLM-Aufrufe wären langsam, teuer, flaky.

**Alternativen abgelehnt**:
- Snapshot-Tests gegen echte Judge-Responses → Snapshots werden bei Modellupdates ständig invalid.
- HTTP-Recording (vcrpy) → funktioniert, aber schwerer zu warten als ein flaches Fake.

**Konfidenz**: `[Certain]`.

## R7 — Parallelisierung innerhalb einer PR-Iteration

**Frage**: Wie starten wir gito und pr-agent für einen PR nebenläufig, ohne Async-Komplexität?

**Entscheidung**: `concurrent.futures.ThreadPoolExecutor` mit `max_workers=2`. Beide Tools laufen als Subprozess, das Warten ist I/O-gebunden — Threads reichen, kein asyncio nötig. Timeout pro Tool 10 min hart. Innerer Judge-Loop bleibt synchron (sequenziell), weil dessen HTTP-Roundtrips per PR moderat sind (~10 Paare × wenige 100 ms).

**Rationale**: 2 Subprozesse in Threads ist trivial und debuggbar. asyncio würde bedeuten, jeden Layer async zu machen, was für 2 nebenläufige Aufgaben pro PR overkill ist.

**Alternativen abgelehnt**:
- asyncio + `asyncio.create_subprocess_exec` → OK, aber zieht Async-Contagion durch die Codebase.
- Sequenziell (Tool nach Tool) → verdoppelt die Wall-Clock-Zeit ohne Grund.

**Konfidenz**: `[Certain]`.

## R8 — Idempotenz und Re-Run-Verhalten

**Frage**: FR-018 verlangt idempotente Wiederholung — wie wird das umgesetzt?

**Entscheidung**: Jeder Schritt (`fetch`, `run`, `match`, `report`) prüft für jeden (Repo, PR) die Existenz der jeweiligen Output-Datei und überspringt bei vorhandenem Ergebnis. Ein Force-Flag (`--force`) macht Neuberechnung erzwingbar. Für `manual_review.json`: existiert die Datei, überschreibt sie die Match-Klassifikation in der Aggregations-Phase, aber automatische Matches werden *nicht* überschrieben — die manuellen leben strikt getrennt.

**Rationale**: Datei-basierte Idempotenz ist trivial und lesbar. Kein Journal, kein Migrations-System. Manuelle Reviews überstimmen automatische = die einzige "Konflikt"-Regel, und die ist im Aggregator eine Zeile Code.

**Alternativen abgelehnt**:
- Hash-basierte Cache-Keys → für Dateisystem-Layout mit "1 Datei pro PR + Tool" overkill.
- Alles immer neu berechnen → widerspricht SC-006.

**Konfidenz**: `[Certain]`.
