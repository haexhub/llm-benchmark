# Benchmark-Plattform – Ausführungsindex

Diese Pläne wurden gegen Commit `b764f88` am 2026-09-22 geschrieben. Sie
überführen den vorhandenen, dateibasierten PR-Review-Prototypen in eine
reproduzierbare Benchmark-Plattform für Review-Tools und Coding-Agenten.

Der Nutzer hat einen vollständigen Plan angefragt; deshalb sind die fünf
höchstpriorisierten, voneinander abhängigen Vorhaben direkt ausgearbeitet.
Kein Plan ersetzt den bestehenden Feature-Slice
`specs/001-pr-review-benchmark`; dieser bleibt als historischer Spike und als
Adapter-Smoke-Test erhalten.

## Reihenfolge und Status

| # | Plan | Status | Abhängigkeit | Ergebnis |
|---|---|---|---|---|
| 001 | [Benchmark-Vertrag und SpecKit-Foundation](001-benchmark-contracts-speckit.md) | DONE | – | Gemeinsame Begriffe, Metriken, Sicherheits- und Datenverträge |
| 002 | [Gelabelten Review-Korpus bauen](002-ground-truth-review-corpus.md) | TODO | 001 | Versionierte PRs mit versteckter Ground Truth |
| 003 | [Reproduzierbare Run-Engine und Adapter etablieren](003-run-engine-resource-lease.md) | TODO | 001 | PostgreSQL-Provenance, Ein-Slot-GPU-Queue, faire Tool-Adapter |
| 004 | [Coding-Task-Harness hinzufügen](004-coding-task-harness.md) | TODO | 001, 003 | Isolierte Coding-Tasks für Modelle und Agenten |
| 005 | [Control Plane und Nuxt-Dashboard liefern](005-api-nuxt-dashboard.md) | TODO | 002, 003, 004 | Aufgaben anlegen/starten und Ergebnisse vergleichen |

```text
001 Contracts / SpecKit
 ├── 002 Review corpus + gold labels
 └── 003 Run engine + adapters + GPU lease
       └── 004 Coding task harness
002 + 003 + 004
       └── 005 API + Nuxt dashboard
```

## Festgelegte Leitplanken

- **Zwei Suiten, nicht eine vermischte Rangliste:** Der gelabelte,
  versionierte Korpus entscheidet über Qualität. Historische PRs samt
  CodeRabbit-Kommentaren bleiben ein separater explorativer Realitäts-Report.
- **Ground Truth statt CodeRabbit-Overlap:** „unique“ bedeutet heute nicht
  „richtig“. Review-Qualität wird gegen Defektlabels und Coding-Qualität zuerst
  gegen versteckte Tests bewertet.
- **Ein lokaler Inference-Slot:** Alle Kandidaten, die den 94-GB-GPU-Endpunkt
  benutzen, teilen einen exklusiven Resource Lease. Queue-Wartezeit und
  Ausführungszeit werden getrennt gespeichert.
- **Keine überschriebenen Ergebnisse:** Jeder Versuch ist ein immutable
  `Attempt` mit Tool-/Harness-Version, Modell, Konfigurations-/Prompt-Hash,
  Artefakthashes, Telemetrie und Status.
- **Gleiche Arbeitsbasis:** Jeder Review-Kandidat erhält denselben
  deterministisch erzeugten Base/Head-Worktree. Agenten arbeiten pro Attempt
  in einem neuen, eingeschränkten Worktree.
- **Kein verdeckter Vorteil:** Sichtbare Aufgabenbeschreibung, erlaubte
  Commands, Netzwerkzugriff, Zeitbudget und Modellparameter stehen im
  Benchmark-Manifest; versteckte Tests und Goldlabels sind Runnern unzugänglich.
- **Kein intransparenter Gesamtscore:** Dashboard und API zeigen Qualität,
  Zuverlässigkeit, Latenz und Kosten als Pareto-Ansicht. Ein gewichtetes Ranking
  ist optional, versioniert und seine Gewichte sind sichtbar.

## Berücksichtigte, aber nicht als eigener Plan ausgeführte Befunde

| Befund | Entscheidung |
|---|---|
| `src/benchmark/pipeline.py` startet gito und pr-agent parallel | In Plan 003 als globaler GPU-Lease gelöst; die aktuelle CLI darf bis dahin nur als unfaire Spike-Ausführung gelten. |
| Gito-/PR-Agent-Aufrufe sind unpinned und Gitos `--path`-Annahme ist veraltet | Plan 003 führt Capability-Probes und einen Versions-/Image-Lock als Registry-Pflicht ein. |
| Der aktuelle Summary-Report setzt `runtime_seconds=0.0` | Plan 003 ersetzt den Report nicht punktuell, sondern liefert eine echte Telemetrie- und Score-Pipeline. |
| Manuelles LLM-Matching ist nur Zeilen-Overlap ±3 | Plan 002 macht menschlich validierte Goldlabels zur Wahrheit; Matching bleibt nur ein Review-Hilfsmittel. |

## Vor dem ersten Implementierungsplan

1. Eine verantwortliche Person für Goldlabels und Adjudication benennen.
2. Festlegen, ob Artefakte ausschließlich auf interner Infrastruktur bleiben
   müssen und wie lange sie aufbewahrt werden.
3. Einen dedizierten Service-Account bzw. ein isoliertes Runner-Netzwerk für
   Git- und Modellzugriff bereitstellen. Keine persönlichen Tokens in
   Benchmark-Manifeste übernehmen.
4. Jede Stufe in einem eigenen SpecKit-Feature spezifizieren und erst nach
   Abnahme des jeweiligen `spec.md` implementieren.
