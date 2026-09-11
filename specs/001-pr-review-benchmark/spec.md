# Feature Specification: PR-Review Benchmark

**Feature Branch**: `001-pr-review-benchmark`
**Created**: 2026-09-10
**Status**: Draft
**Input**: User description: Benchmark AI-basierter PR-Reviewer (gito.bot, pr-agent) gegen die vorhandene CodeRabbit-Baseline auf mehreren eigenen Repos, um zu sehen was jedes Tool relativ zur CR-Baseline zusätzlich findet oder verpasst. Beide Challenger-Tools laufen gegen ein lokales Qwen-Modell; Zielgruppe ist der Nutzer selbst als Entscheider für ein mögliches Self-Hosted-Setup.

## Clarifications

### Session 2026-09-10

- Q: Darf der externe Judge (default Claude Sonnet) Finding-Texte + Code-/Diff-Ausschnitte aus den Baseline-Repos sehen? → A: Ja, kein Code-Redacting nötig — die 5 Baseline-Repos enthalten keine sensiblen Geschäftsdaten.
- Q: Wie werden manuelle Sichtungsentscheidungen für unsichere Matches persistiert, so dass sie Re-Runs überleben? → A: Pro PR-Lauf eine dedizierte Datei mit den manuellen Entscheidungen neben den Tool-Ausgaben; der Aggregator übersteuert automatische Judge-Entscheidungen anhand dieser Datei.
- Q: Wie geht die Pipeline mit Intra-Tool-Duplikaten um (ein Tool meldet denselben Defekt zweimal)? → A: Duplikate zusammenfassen mit der gleichen Judge-Heuristik wie beim Cross-Tool-Matching; die Roh-Anzahl vor Dedup wird zusätzlich im Aggregat ausgewiesen (Signal "Tool X ist geschwätzig").
- Q: Wie sieht die UX für die manuelle Sichtung unsicherer Matches aus? → A: Eigener interaktiver CLI-Assistent (`benchmark review`), der uncertain-Matches einzeln mit Kontext präsentiert und die `manual_review.json` selbst schreibt. Kein Hand-Editieren von Timestamps/UUIDs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Baseline für einen einzelnen PR bekommen (Priority: P1)

Ich picke einen konkreten PR aus einem meiner Repos, den CodeRabbit bereits reviewed hat. Ich stoße die Pipeline an und bekomme innerhalb weniger Minuten eine Übersichtstabelle mit den Findings aller drei Reviewer (CodeRabbit, gito.bot, pr-agent) nebeneinander, so dass ich für diesen einen PR sofort sehen kann welche Defekte sich überschneiden und welche nur ein Tool gefunden hat.

**Why this priority**: Das ist der kleinstmögliche vollständige Vertikalschnitt und liefert bereits echten Erkenntnisgewinn für die Tool-Auswahl. Wenn das für einen PR funktioniert, ist der Rest reine Skalierung.

**Independent Test**: Für einen einzigen Repo/PR die Pipeline durchlaufen und den Per-PR-Report öffnen. Erfolgreich, wenn der Report drei Findings-Listen enthält und mindestens ein Beispiel eines übereinstimmenden Findings sowie mindestens ein Beispiel eines nur von einem Tool gefundenen Findings zeigt.

**Acceptance Scenarios**:

1. **Given** ein konfiguriertes Repo mit einem gültigen PR-Link, für den CodeRabbit-Kommentare existieren, **When** ich die Pipeline für genau diesen PR starte, **Then** wird ein Per-PR-Report erzeugt, der die Findings aller drei Reviewer strukturiert nebeneinander zeigt.
2. **Given** derselbe PR wird zweimal hintereinander analysiert, **When** ich beide Report-Versionen vergleiche, **Then** sind die Findings-Listen inhaltlich stabil genug, dass die Anzahl der Findings pro Tool sich um nicht mehr als eine sinnvolle Toleranz (LLM-inhärent) unterscheidet und dieselben Datei-/Zeilen-Anker abgedeckt werden.

---

### User Story 2 - Aggregatvergleich über viele PRs (Priority: P1)

Nachdem für alle konfigurierten Repos (5 Repos × 40+ PRs) einzelne Reports vorliegen, will ich einen Aggregat-Report der mir pro Repo × Tool die zentralen Metriken zeigt: Wie viele Findings hat das Tool insgesamt produziert, wie viele decken sich mit CR, wie viele sind einzigartig, wie viele CR-Findings hat es verpasst, und wie verteilen sich Kategorien und Schweregrade. Das ist die eigentliche Entscheidungsgrundlage.

**Why this priority**: Ohne diesen Report ist der Benchmark inhaltlich wertlos — Einzel-PR-Reports allein tragen keine Aussage, weil LLM-Reviewer stark zwischen PRs varrieren. Erst das Aggregat zeigt Muster.

**Independent Test**: Nach einem Batch-Run über mindestens ein vollständiges Repo den Aggregat-Report öffnen. Erfolgreich, wenn er alle geforderten Metriken pro (Repo, Tool) enthält und in Markdown und CSV vorliegt.

**Acceptance Scenarios**:

1. **Given** die Pipeline lief erfolgreich für 40 PRs eines Repos, **When** ich den Aggregat-Report öffne, **Then** sehe ich für jedes der drei Tools die Anzahl Findings, die Überlappung mit CR, die einzigartigen Findings, die verpassten CR-Findings, den durchschnittlichen Schweregrad und ein Kategorien-Breakdown.
2. **Given** in einem Repo ist ein Tool in mehreren PRs fehlgeschlagen (LLM-Timeout, HTTP-Fehler), **When** ich den Aggregat-Report öffne, **Then** sind diese fehlgeschlagenen PRs explizit ausgewiesen und nicht als "0 Findings" mit den erfolgreichen PRs vermischt.

---

### User Story 3 - Manuelle Sichtung unsicherer Matches (Priority: P2)

Der automatische Vergleich zweier Findings ("beschreibt Tool A und Tool B denselben Defekt?") ist nicht immer eindeutig. Für Grenzfälle möchte ich schnell eine kuratierte Liste bekommen, in der ich per Auge entscheiden kann, ob zwei Findings semantisch dasselbe meinen oder nicht — inklusive Kontextausschnitt aus dem betroffenen Code.

**Why this priority**: Ohne diese Sichtungsschleife trägt die Aggregat-Metrik "Overlap mit CR" ein systematisches Bias-Risiko. Aber sie ist nachgelagert — die Zahlen sind auch vorher schon indikativ.

**Independent Test**: Für ein Repo eine Sichtungsliste öffnen und mindestens einen unsicheren Match aufflächen, korrigieren, danach den Aggregat-Report neu erzeugen. Erfolgreich, wenn manuelle Korrekturen im Aggregat sichtbar werden.

**Acceptance Scenarios**:

1. **Given** die Pipeline ist gelaufen und der Matcher hat Kandidatenpaare mit niedriger Konfidenz erzeugt, **When** ich die Sichtungsliste öffne, **Then** sehe ich pro Kandidatenpaar beide Finding-Texte anonymisiert (ohne Tool-Namen), den Datei-/Zeilen-Kontext und die Möglichkeit "same/different/unclear" zu markieren.
2. **Given** ich habe manuelle Entscheidungen getroffen, **When** ich den Aggregat-Report neu erzeuge, **Then** fließen meine Entscheidungen in die Overlap-/Unique-Zählung ein und der Report weist aus, wieviele Matches manuell bestätigt oder verworfen wurden.

---

### User Story 4 - Tool-Konfiguration wechseln (Priority: P3)

Ich möchte einzelne Bausteine austauschen können ohne die Pipeline umbauen zu müssen: das LLM-Modell hinter gito und pr-agent (heute Qwen, morgen vielleicht ein anderes lokales Modell), den Endpunkt (bei uns intern), und das Judge-Modell (heute Claude Sonnet, evtl. später ChatGPT). Ebenso welche Repos und welche PRs Teil des Benchmarks sind.

**Why this priority**: Nice-to-have für den Erst-Durchlauf. Wird aber schnell wichtig, sobald ich Modelle vergleichen will oder neue Repos aufnehme.

**Independent Test**: Judge-Modell auf ein anderes umkonfigurieren, Pipeline für einen bereits gelaufenen PR erneut starten und prüfen ob die Matching-Ergebnisse nachvollziehbar variieren.

**Acceptance Scenarios**:

1. **Given** die zentrale Konfiguration ist gesetzt, **When** ich das zu benchmarkende Modell auf einen anderen Endpunkt umstelle, **Then** funktioniert der nächste Pipeline-Lauf ohne weitere Codeänderungen.
2. **Given** ich füge ein neues Repo mit PR-Nummern der Konfiguration hinzu, **When** ich die Pipeline starte, **Then** wird nur dieses neue Material verarbeitet und die Reports werden entsprechend erweitert.

---

### Edge Cases

- Ein PR hat keine CodeRabbit-Kommentare (obwohl in der Konfig gelistet): wird explizit als "keine CR-Baseline" markiert; das Tripel wird trotzdem generiert damit gito/pr-agent-Findings sichtbar sind, aber in Overlap-Metriken nicht als "CR-Miss" gezählt.
- Ein Challenger-Tool (gito oder pr-agent) crasht oder produziert leere Ausgabe: der PR wird als "Tool-Ausfall" geloggt und beim Aggregat separat ausgewiesen (nicht als "0 Findings" gewertet).
- CodeRabbit hat sehr viele Nitpicks/Verifications-Kommentare für einen PR: der Report muss diese als eigene Kategorie/Severity ausweisen können, damit sie die Overlap-Metrik nicht verzerren.
- Zwei Findings desselben Tools decken sich substanziell (Tool berichtet den gleichen Defekt zweimal): der Matcher fasst Intra-Tool-Duplikate mit derselben Judge-Heuristik zusammen; im Aggregat werden sowohl die deduplizierte als auch die Roh-Anzahl ausgewiesen.
- LLM-Endpunkt (Qwen) ist temporär nicht erreichbar: Retries mit Backoff; nach Erschöpfen sauberer Abbruch mit klarer Fehlermeldung und verwertbarem Teil-Ergebnis für die bereits gelaufenen PRs.
- Ein PR ist sehr groß (viele Dateien / viele Zeilen): die Pipeline muss weder crashen noch stundenlang hängen — ein sinnvoller Größenlimit oder ein Split-Verfahren ist möglich; wenn ein PR ausgelassen wird, muss der Report das sagen.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Das System MUSS für jeden konfigurierten (Repo, PR)-Pair die CodeRabbit-Findings direkt aus dem Original-GitHub-Repository beziehen, ohne die Original-Repos zu verändern.
- **FR-002**: Das System MUSS für jeden (Repo, PR)-Pair gito.bot einmalig auf den PR-Diff ansetzen und die Ausgabe erfassen.
- **FR-003**: Das System MUSS für jeden (Repo, PR)-Pair pr-agent einmalig auf den PR-Diff ansetzen und die Ausgabe erfassen.
- **FR-004**: Beide Challenger-Tools MÜSSEN gegen ein und denselben, per Konfiguration wählbaren OpenAI-kompatiblen LLM-Endpunkt laufen (Default: lokales Qwen-Modell auf https://your-llm-endpoint.example.com/v1).
- **FR-005**: Alle drei Findings-Listen (CR, gito, pr-agent) MÜSSEN in ein einheitliches, für Vergleich geeignetes Datenschema überführt werden, das mindestens folgende Felder pro Finding enthält: Tool-Identität, Datei-Pfad, Zeilenbereich, Schweregrad, Kategorie, Titel, Beschreibung, optionaler Fix-Vorschlag.
- **FR-006**: Das System MUSS Findings paarweise strukturell auf Übereinstimmung prüfen (gleiche Datei, überlappender Zeilenbereich mit einer sinnvollen Toleranz).
- **FR-007**: Für strukturell verdächtige Kandidatenpaare MUSS das System eine semantische Bewertung einholen, ob beide Findings denselben Defekt beschreiben, und ein Konfidenzmaß speichern.
- **FR-008**: Die semantische Bewertung MUSS von einem *anderen* LLM-Modell/Endpunkt kommen als dem, gegen das die Challenger-Tools laufen (Vermeidung Self-Judging-Bias). Der Judge MUSS austauschbar sein (Konfiguration).
- **FR-009**: Der Judge MUSS die Findings-Paare in einer für ihn nicht identifizierbaren Reihenfolge und ohne Angabe des Ursprungs-Tools sehen (Blind-Bewertung).
- **FR-010**: Jedes Finding jedes Challenger-Tools MUSS am Ende in eine der drei Kategorien klassifiziert werden: "deckt sich mit CR", "einzigartig für Tool", "wurde von CR gefunden aber vom Tool verpasst".
- **FR-011**: Kandidatenpaare mit niedriger Judge-Konfidenz MÜSSEN in eine dedizierte Sichtungsliste geschrieben werden, in der ein Mensch die Zuordnung überstimmen kann. Manuelle Entscheidungen MÜSSEN pro PR-Lauf getrennt von den automatisch generierten Tool-Ausgaben persistiert werden, damit die Herkunft (automatisch vs. manuell) nachvollziehbar bleibt und Re-Runs die manuellen Entscheidungen respektieren.
- **FR-011a**: Das System MUSS einen interaktiven CLI-Modus bereitstellen, der unsichere Matches einzeln präsentiert (mit Datei/Zeilen-Kontext und beiden Finding-Texten anonymisiert), eine Entscheidungsabfrage (`same`/`different`/`unclear`) durchführt und die Persistenz-Datei aus FR-011 selbst erzeugt. Manuelles Editieren der Persistenz-Datei bleibt zusätzlich möglich.
- **FR-012**: Das System MUSS pro (Repo, PR) einen Per-PR-Report in Markdown erzeugen, der die drei Findings-Listen strukturiert nebeneinander (übereinstimmende Findings aligned) darstellt.
- **FR-013**: Das System MUSS einen Aggregat-Report erzeugen, der pro Repo × Tool mindestens folgende Metriken enthält: Gesamtzahl Findings *nach* Intra-Tool-Deduplizierung, Roh-Anzahl *vor* Dedup, Anzahl Überlappung mit CR, Anzahl "einzigartig", Anzahl "von CR-Baseline verpasst", durchschnittlicher Schweregrad, Verteilung über Kategorien.
- **FR-014**: Der Aggregat-Report MUSS zusätzlich als CSV verfügbar sein, damit er außerhalb (Tabellenkalkulation, Notizsystem) weiterverarbeitet werden kann.
- **FR-015**: Alle geheimen Zugangsdaten (LLM-API-Keys, GitHub-Token) MÜSSEN über eine `.env`-Datei setzbar sein und dürfen nicht im Quellcode oder in den Reports auftauchen.
- **FR-016**: Die zu benchmarkenden Repos und PR-Nummern MÜSSEN in einer zentralen Konfigurationsdatei stehen und ohne Codeänderung erweiterbar sein.
- **FR-017**: Bei einem Tool-Ausfall (Timeout, HTTP-Fehler, leere Ausgabe) MUSS die Pipeline den betroffenen PR als "Ausfall" markieren und den Rest des Batches unbeeinflusst weiterverarbeiten. Der Ausfall MUSS im Aggregat-Report sichtbar sein und darf nicht als "0 Findings" gewertet werden.
- **FR-018**: Die Pipeline MUSS auf einer beliebigen Teilmenge (einzelner PR, einzelnes Repo, alles) startbar sein, ohne bereits vorhandene Roh-Ausgaben erneut zu erzeugen (idempotent bezüglich existierender Runs).

### Key Entities *(include if feature involves data)*

- **Repo**: Ein GitHub-Repository, für das ein Benchmark laufen soll. Attribute: Owner, Name, Liste der zu benchmarkenden PR-Nummern.
- **PR-Run**: Ein Lauf für einen (Repo, PR)-Pair. Enthält den eingefrorenen PR-Diff und je eine Findings-Liste pro Reviewer.
- **Finding**: Ein einzelner Review-Kommentar eines Tools zu einer Codestelle. Attribute: Tool, Datei, Zeilenbereich, Schweregrad, Kategorie, Titel, Beschreibung, optionaler Fix-Vorschlag.
- **Match**: Eine automatisch oder manuell festgestellte Beziehung zwischen zwei Findings unterschiedlicher Tools. Attribute: Finding A, Finding B, Konfidenz, Judge-Begründung, ggf. manuelle Bestätigung.
- **Bericht**: Menschenlesbare Zusammenfassung — Per-PR-Report und Aggregat-Report.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Für einen einzelnen konfigurierten PR läuft die vollständige Pipeline (CR-Scrape + gito + pr-agent + Matching + Per-PR-Report) in unter 5 Minuten durch, sofern der LLM-Endpunkt reagiert.
- **SC-002**: Ein Batch-Lauf über 200 PRs schließt ab, ohne dass ein Ausfall einzelner PRs den restlichen Batch stoppt; der Aggregat-Report ist danach ohne manuelle Nacharbeit erzeugt.
- **SC-003**: Nach einem Batch-Lauf kann der Nutzer aus dem Aggregat-Report für jedes Tool und jedes Repo mit einem Blick sagen: Overlap-Rate zu CR (in Prozent), Anzahl einzigartiger Findings, Anzahl verpasster CR-Findings.
- **SC-004**: Der Anteil vom Matcher als "unsicher" markierter Kandidatenpaare, für den der Nutzer nach manueller Sichtung dem automatischen Vorschlag widerspricht, liegt unter 20% (Indikator für Judge-Qualität).
- **SC-005**: Beim Wechsel des zu benchmarkenden LLM-Modells oder des Judge-Modells ist kein Codeänderungen nötig; die Konfiguration reicht.
- **SC-006**: Beim Hinzufügen eines neuen Repos in die Konfiguration und Neustart der Pipeline werden ausschließlich die neuen (Repo, PR)-Runs verarbeitet, existierende bleiben unberührt.

## Assumptions

- Der Nutzer besitzt lesenden Zugang (GitHub-Token) auf allen fünf Baseline-Repos, inklusive PR-Kommentaren des CodeRabbit-Bots.
- CodeRabbit-Findings sind hinreichend maschinenlesbar in Form seiner Review-Kommentare vorhanden (strukturierte Markdown-Blöcke); marginale Rauscheffekte durch neue Bot-Message-Formate werden akzeptiert.
- Der lokale Qwen-Endpunkt ist erreichbar und bietet ausreichend Durchsatz für ~400 Review-Läufe innerhalb weniger Stunden.
- Der externe Judge (z.B. Anthropic Claude Sonnet) ist ansprechbar und die Kosten bleiben im Rahmen weniger US-Dollar für den gesamten Benchmark.
- Die 5 Baseline-Repos enthalten keine sensiblen Geschäftsdaten; Finding-Texte und Code-/Diff-Ausschnitte dürfen im Judge-Prompt an einen externen LLM-Anbieter gehen, ohne dass ein Code-Redacting nötig wäre.
- Der Nutzer akzeptiert LLM-inhärente Nicht-Determinismen; Reproduzierbarkeit wird durch Temperature-0- und Seed-Konfiguration angestrebt, aber nicht garantiert.
- Ein zweiter Benchmark-Typ (Coding-Tasks zwischen Claude/ChatGPT/Qwen) ist geplant, ist aber ausdrücklich NICHT Teil dieser Spec und darf die Architektur dieser Spec nicht vorwegnehmen.
- Es werden keine Mirror-Repos auf GitHub angelegt; die Tools arbeiten ausschließlich lokal auf dem eingefrorenen PR-Diff.
- Der Nutzer sichtet unsichere Matches manuell in einer eigenen Nachbearbeitungs-Session; die Pipeline stellt das dafür nötige Rohmaterial bereit, entscheidet aber nicht endgültig.
