# Phase 0 Research — PR-Review Benchmark

Klärt die zum Zeitpunkt der Planung offenen Punkte aus `plan.md → Technical Context`. Konfidenz-Tags nach globaler CLAUDE.md-Konvention: `[Certain]` = gerade verifiziert, `[Likely]` = starke Ableitung, `[Guessing]` = Lücke.

## R1 — pr-agent CLI-Aufruf und Konfiguration `[Certain]` (verifiziert 2026-09-11 live gegen haexmas/holzi PR #27)

**Frage**: Wie ruft man `pr-agent` gegen einen konkreten PR mit einem benutzerdefinierten OpenAI-kompatiblen Endpunkt auf, und wo landen die Findings?

**Entscheidung (final, verifiziert)**: `--pr_url` + `--json-output` ist **nicht kombinierbar** — pr-agent bricht mit `error: --json-output is only supported in plain-diff mode (--stdin or --diff-file)` ab. Wir nutzen ausschließlich den Diff-Modus, mit dem `diff.patch` aus dem fetch-Schritt:

```
uv tool run --from pr-agent pr-agent \
  --diff-file <diff.patch> --json-output <out.json> review
```

Env (`build_pragent_env` in `tools/pr_agent.py`):
- `OPENAI__API_BASE` / `OPENAI_API_BASE` = `TOOL_LLM_BASE_URL`
- `OPENAI__KEY` / `OPENAI_API_KEY` = `TOOL_LLM_API_KEY`
- `CONFIG__MODEL` = `openai/<TOOL_LLM_MODEL>` — **immer** mit `openai/`-Präfix voranstellen, unabhängig davon ob der Modellname selbst schon einen Slash enthält. Ein ursprünglicher Bugfix-Versuch prüfte `"/" in tool_model` um das Präfix zu überspringen — das brach für HuggingFace-Namenskonventionen wie `Qwen/Qwen3.8-27B-FP8`, deren Slash Teil des Modellnamens ist, nichts mit LiteLLM's Provider-Präfix zu tun hat. Ohne das Präfix meldet litellm `BadRequestError: LLM Provider NOT provided`.
- `CONFIG__CUSTOM_MODEL_MAX_TOKENS` = `TOOL_LLM_MAX_TOKENS` (aus `/v1/models` → `max_model_len`) — pflicht für jedes selbst gehostete Modell, sonst `Model … is not defined in MAX_TOKENS` und der Call schlägt fehl bevor er das Netzwerk erreicht.
- `CONFIG__FALLBACK_MODELS='[]'` — pflicht: pr-agents Default-Fallback-Liste enthält einen Platzhalter-Modellnamen (`gpt-5.6-terra` in der installierten Version), der gegen einen selbst gehosteten Endpunkt nie existiert und den echten Fehler hinter einer zweiten, ebenfalls fehlschlagenden Anfrage versteckt.
- `CONFIG__PUBLISH_OUTPUT=false` — verhindert das Posten als GitHub-Kommentar.

**Wichtig — Exit-Code ist kein Erfolgsindikator**: Schlägt der LLM-Call intern fehl (z.B. Model-Fehler), gibt `pr-agent` trotzdem **Exit-Code 0** zurück und druckt nur "Failed to review PR" auf stdout — keine JSON-Datei wird geschrieben. Unser Wrapper verlässt sich daher nicht auf den Return-Code allein, sondern prüft zusätzlich `raw_out.exists()`.

**Rationale**: Alle Werte wurden gegen den echten itemis-Qwen-Endpunkt und PR #27 (36 Dateien) sowie einen synthetischen Mini-Diff verifiziert; beide liefen erfolgreich durch.

**Alternativen abgelehnt**: wie ursprünglich — Bibliothek-Einbindung (Kopplung an interne Klassen), GitHub-Action (kein lokaler Diff-Modus).

## R2 — gito CLI-Aufruf und Konfiguration `[Certain]` (verifiziert 2026-09-11)

**Frage**: Wie ruft man `gito` (PyPI-Paket `gito.bot`) lokal gegen einen PR mit einem benutzerdefinierten LLM-Endpunkt auf?

**Entscheidung (final, verifiziert)**: Der ursprünglich angenommene Aufruf `gito review --url <pr-url> --pr <n>` **funktioniert nicht** — `--url` wird direkt an `git clone` durchgereicht; eine PR-URL ist kein clonbares Repo (`fatal: repository '.../pull/27' not found`). `--path` (lokales Repo referenzieren) ist im gito-Code selbst als `# @todo: implement` markiert — nicht nutzbar.

Der einzig funktionierende Weg: gito lokal **in einem bereits ausgecheckten Klon** laufen lassen (sein "kein `--url`" / "lokales Repo am cwd"-Pfad, der Rolle die es normalerweise in CI übernimmt):

```bash
git clone --quiet https://github.com/<owner>/<repo>.git <clone_dir>
git -C <clone_dir> fetch --quiet origin refs/pull/<n>/head:pr-<n>-head
uv tool run --from gito.bot gito review \
  --what pr-<n>-head --against <base_sha> --no-merge-base \
  --out <out_dir> --no-post-comment   # cwd = <clone_dir>
```

`refs/pull/<n>/head` funktioniert von GitHub für *jede* PR (auch von Forks), ohne dass man den Fork als Remote kennen muss. `base_sha`/`head_ref` kommen aus `gh api repos/{owner}/{repo}/pulls/{n}` (`fetch_pr_refs` in `github/fetch.py`).

**Env (`build_gito_env` in `tools/gito.py`)** — gito nutzt **microcore**, nicht LiteLLM-Konventionen:
- `LLM_API_TYPE=openai` (explizit setzen, sonst Fallback auf CLI-Modus)
- `LLM_API_BASE` = `TOOL_LLM_BASE_URL`
- `LLM_API_KEY` = `TOOL_LLM_API_KEY`
- `MODEL` = `TOOL_LLM_MODEL` **ohne** Provider-Präfix — ein `openai/`-Präfix (richtig für pr-agent/LiteLLM) bricht hier: microcore versucht dann buchstäblich `openai/Qwen/Qwen3.8-27B-FP8` als Modellnamen aufzulösen und schlägt mit `NotFoundError` fehl.

**JSON-Output**: `<out_dir>/code-review-report.json` (Konstante `GITO_REPORT_FILENAME`), Struktur `{"issues": {"<file>": [{"title", "details", "severity": 1-5, "tags": [...], "affected_lines": [{"start_line", "end_line", "proposal"}]}]}}`.

**Performance-Beobachtung**: gito reviewt Dateien einzeln (ein LLM-Call pro Datei, keine interne Parallelisierung) — für PR #27 (36 Dateien) bedeutete das 36 sequenzielle Calls à 5–90s gegen den itemis-Qwen-Endpunkt, macht Gesamtlaufzeiten von 15–25 Minuten für große PRs plausibel. Das ist eine Charakteristik von gito selbst (nicht unser Wrapper) und relevant für SC-001/SC-002 bei großen PRs — siehe R9.

**Alternativen abgelehnt**: `--url`+`--pr` (bricht, s.o.), `--path` (unimplementiert in gito selbst), Bibliothek-Einbindung.

## R3 — CodeRabbit Review-Kommentar-Struktur `[Certain]` (verifiziert 2026-09-11 gegen haexmas/holzi PR #26/#27, live von GitHub gezogen)

**Frage**: Wie sind CR-Kommentare auf einem PR strukturiert und wie zieht man sie zuverlässig ab?

**Wichtige Korrektur**: Das ursprünglich angenommene Format (`**⚠️ Potential issue**`-Header etc.) existiert in der aktuellen CodeRabbit-Version **nicht mehr**. Reale Struktur, verifiziert an 12 echten Findings:

1. **Line-level Kommentare** (`pulls/{n}/comments`) sind die primäre, zuverlässige Quelle — `path`/`line`/`original_line` kommen direkt als API-Felder, nicht aus dem Body geparst. Jeder echte Finding-Body enthält eine maschinenlesbare Markierung `<!-- cr-indicator-types:X -->` (X ∈ `potential_issue`, `refactor_suggestion`, `nitpick`, `verification`, `suggestion`) — Kommentare ohne diese Markierung sind menschliche Antworten/Meta-Chatter (z.B. "✅ Addressed in commit …" hat zwar `path`, aber i.d.R. auch die Markierung, weil es dieselbe Comment-ID fortschreibt; ein reiner Reply-Kommentar ohne Markierung wird korrekt übersprungen).
2. Body-Struktur pro Finding: `_<Kategorie>_ | _<Severity>_ | _<Effort>_` (z.B. `_🩺 Stability & Availability_ | _🟠 Major_ | _⚡ Quick win_`), gefolgt von optionalen `<details>`-Blöcken (statische Analyse-Skripte, KI-Agent-Prompt — beide werden weggefiltert), dann `**Bold-Titel.**` + Fließtext.
3. **Review-Summaries** (`pulls/{n}/reviews`) sind zu 95% ein reines Duplikat der Line-Kommentare (als "Actionable comments posted: N" + gebündelter KI-Prompt) — **das würde bei naiver Übernahme zu Doppelzählung führen**. Die einzige echte Zusatzinformation ist der Abschnitt **"Outside diff range comments (N)"**: Findings, die GitHub nicht als Line-Kommentar anhängen kann, weil sie außerhalb des Diffs liegen. Dieser Abschnitt wird separat geparst (verschachteltes `<details><summary><blockquote>`-Markup, Datei- und Zeilenangabe stehen inline im Text: `` `152-165`: _Kategorie_ | ... ``).
4. **Issue-level Kommentare** (`issues/{n}/comments`) sind reine PR-Meta-Information (Walkthrough-Zusammenfassung, "Review finished"-Antworten) — nie Findings.

**Severity-Mapping**: nicht per Emoji (Emoji-Sets variieren), sondern per Substring-Match auf das Wort nach dem zweiten `_..._`-Block: "critical"/"blocker"→critical, "major"→major, "minor"→minor, "trivial"/"nit"→nit. Fällt keine Severity-Zeile, wird der `cr-indicator-types`-Wert als Default verwendet.

**Kategorie-Mapping**: über den gemeinsamen `benchmark/categorize.py`-Helper (`infer_category`), der auch von pr-agent genutzt wird — Keyword-Scan über Kategorie-Text + Body.

**Rationale**: Alle Annahmen aus der Planungsphase (Alt-Format mit `⚠️/🛠️/🧹/✅`-Präfixen) waren zum Zeitpunkt der Implementierung bereits veraltet — CodeRabbit hat sein Ausgabeformat seither geändert. Das bestätigt den in der ursprünglichen Konfidenz-Einschätzung vermerkten Risiko-Punkt ("CR-Formate ändern sich gelegentlich").

**Alternativen abgelehnt**:
- CodeRabbit CLI neu ausführen → verändert die Baseline, wir wollen die *historische* Sicht.
- Nur `pulls/{n}/comments` scrapen → verpasst "Outside diff range"-Findings systematisch (bestätigt: mind. 1 Vorkommen in PR #26).

**Fixtures**: `tests/fixtures/cr_line_comment_potential_issue.md`, `cr_line_comment_simple.md`, `cr_review_with_outside_diff_range.md` — alle live von echten PRs gezogen, keine synthetischen Annahmen mehr.

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

## R9 — Judge-SDK-Drift und Endpunkt-Performance `[Certain]` (verifiziert 2026-09-11 im ersten Live-Smoke-Test)

**Frage**: Funktioniert der in R5 geplante Judge-Aufruf (Anthropic-SDK, `temperature=0` für Determinismus) unverändert gegen die tatsächlich installierte SDK-Version und den echten Proxy?

**Befund**: Die installierte `anthropic`-SDK-Version (1.5.0, Stand 2026-09-11) hat `temperature` komplett aus der Signatur von `Messages.create()` entfernt — der Aufruf schlägt mit `TypeError: Messages.create() got an unexpected keyword argument 'temperature'` fehl, nicht als Server-Fehler, sondern schon auf Python-Ebene. `AnthropicJudge.evaluate_pair` ruft `.create()` daher ohne `temperature` auf; Determinismus über Runs hinweg ist damit **best-effort, nicht garantiert** — besonders relevant, wenn der Judge (wie bei uns) über einen CLI-wrappenden Proxy läuft (`haex-claude-proxy`), der ohnehin keinen Sampling-Parameter durchreichen könnte.

**Live-Verifikation des vollen Judge-Pfads**: `AnthropicJudge` gegen `haex-claude-proxy` (lokal auf `:18080`, OAuth-Modus über die eigene Claude-Max-Subscription) liefert korrekte, sinnvoll begründete Verdicts (`same=true, confidence=0.97`) für ein synthetisches CR-vs-Tool-Findingpaar zum selben Bug. End-to-End funktionsfähig.

**Endpunkt-Performance-Charakteristik** (itemis-Qwen, `Qwen/Qwen3.8-27B-FP8`, `max_model_len=262144`):
- Kleine Diffs (< 2000 Tokens, 1 Datei): pr-agent ~50s, gito ~35s pro Lauf — beide finden den injizierten Bug korrekt.
- Große PRs (36 Dateien, ~42k Rohtoken vor Pruning): pr-agent pruned auf 32k Tokens und braucht **~5-6 Minuten für den einzelnen Completion-Call**; gito braucht **~15-25 Minuten** (36 sequenzielle Einzel-Calls, keine interne Parallelisierung).
- Das bedeutet: **SC-001 (< 5 min pro PR) ist für große PRs auf diesem Endpoint nicht erreichbar** — nicht durch einen Code-Bug, sondern durch die reale Kapazität/Auslastung des itemis-Qwen-Deployments bei großen Prompts. `TOOL_TIMEOUT_SECONDS = 600` (10 min) in `pipeline.py` reicht für gito bei > ~20 Dateien u.U. nicht aus; für einen großen Repo-Batch (SC-002, 40+ PRs) muss mit mehreren Stunden Gesamtlaufzeit gerechnet werden, nicht Minuten.

**Konsequenz für die Bewertung**: Dieser Befund ist selbst ein Benchmark-Ergebnis (nicht nur eine Implementierungsdummy) — falls die Praxistauglichkeit des Self-Hosted-Setups Teil der Entscheidungsgrundlage ist, gehört "Antwortzeit bei großen PRs" explizit in den Summary-Report. Aktuell wird nur die reine Finding-Qualität verglichen (SC-003), nicht die Latenz — SC-001 selbst sollte ggf. in der Spec nachträglich präzisiert werden ("< 5 min bei PRs bis N Dateien"), aber das ist eine Entscheidung für den Product-Owner, keine, die wir hier einseitig treffen.

**Zwei weitere im Live-Test gefundene und gefixte Bugs** (siehe git history für Details):
- `build_pragent_env`: `"/" in tool_model`-Heuristik zum Überspringen des `openai/`-Präfixes brach für HuggingFace-Modellnamen mit eigenem Slash (`Qwen/Qwen3.8-27B-FP8`) — jetzt immer `openai/` voranstellen (R1).
- `do_run`: Ergebnis-Sammlung iterierte `futures.items()` in Submission-Reihenfolge statt `as_completed()` — ein schnell fehlschlagender Task (z.B. pr-agent bei einem Config-Fehler) wurde erst geloggt, nachdem der langsamere Sibling-Task (gito) fertig war, im Extremfall gar nicht (externer Kill vor Sibling-Ende). Jetzt `as_completed()`-basiert, jeder Task wird sofort bei Abschluss verarbeitet.
