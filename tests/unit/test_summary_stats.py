from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from benchmark.models import Finding, JudgeVerdict, Match
from benchmark.reports.summary import (
    build_stats,
    load_pr_snapshot,
    render_summary_csv,
    render_summary_md,
)


def _write_findings(path: Path, findings: list[Finding], raw_count: int | None = None) -> None:
    payload = {
        "schema_version": "1",
        "findings": [json.loads(f.model_dump_json()) for f in findings],
    }
    if raw_count is not None:
        payload["findings_raw_count"] = raw_count
    path.write_text(json.dumps(payload))


def _write_matches(path: Path, matches: list[Match]) -> None:
    path.write_text(
        json.dumps({
            "schema_version": "1",
            "matches": [json.loads(m.model_dump_json()) for m in matches],
        })
    )


def _f(tool, fid, start=10, end=None, severity="major", category="bug"):
    return Finding(
        id=fid,
        tool=tool,
        file="a.py",
        line_start=start,
        line_end=end if end is not None else start,
        severity=severity,
        category=category,
        title="t",
        body="b",
    )


def _verdict():
    return JudgeVerdict(same=True, confidence=0.9, reason="x", judge_model="m", prompt_hash="0" * 64)


def test_build_stats_basic(tmp_path: Path) -> None:
    base = tmp_path / "alice__repo" / "42"
    base.mkdir(parents=True)
    cr_id = uuid4()
    g_id = uuid4()
    cr = [_f("coderabbit", cr_id, start=10)]
    gito = [_f("gito", g_id, start=10)]
    _write_findings(base / "coderabbit.json", cr)
    _write_findings(base / "gito.json", gito, raw_count=2)  # simulate 1 dedup
    _write_findings(base / "pr-agent.json", [])
    match = Match(a_id=cr_id, b_id=g_id, structural_overlap_lines=1, verdict=_verdict(), classification="same")
    _write_matches(base / "matches.json", [match])

    snap = load_pr_snapshot(base, "alice__repo", 42)
    assert snap is not None
    stats = build_stats([snap])
    by_tool = {s.tool: s for s in stats}
    assert by_tool["coderabbit"].findings_after_dedup == 1
    assert by_tool["gito"].findings_raw == 2
    assert by_tool["gito"].findings_after_dedup == 1
    assert by_tool["gito"].overlap_with_cr == 1
    assert by_tool["gito"].unique_to_tool == 0
    assert by_tool["pr-agent"].findings_after_dedup == 0


def test_build_stats_failed_tool(tmp_path: Path) -> None:
    base = tmp_path / "alice__repo" / "43"
    base.mkdir(parents=True)
    (base / "coderabbit.json").write_text('{"schema_version":"1","findings":[]}')
    # gito.json missing + failed.log flags it
    (base / "failed.log").write_text("run:gito: RuntimeError: timeout\n")
    (base / "pr-agent.json").write_text('{"schema_version":"1","findings":[]}')
    _write_matches(base / "matches.json", [])

    snap = load_pr_snapshot(base, "alice__repo", 43)
    assert snap is not None
    assert "gito" in snap.failed_tools

    stats = build_stats([snap])
    by_tool = {s.tool: s for s in stats}
    assert by_tool["gito"].failed_pr_count == 1
    assert by_tool["gito"].total_pr_count == 1


def test_render_summary_md_contains_all_tools(tmp_path: Path) -> None:
    base = tmp_path / "x__y" / "1"
    base.mkdir(parents=True)
    (base / "coderabbit.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "gito.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "pr-agent.json").write_text('{"schema_version":"1","findings":[]}')
    _write_matches(base / "matches.json", [])
    snap = load_pr_snapshot(base, "x__y", 1)
    md = render_summary_md(build_stats([snap]))
    assert "| x__y | coderabbit |" in md
    assert "| x__y | gito |" in md
    assert "| x__y | pr-agent |" in md


def test_render_summary_csv_parseable(tmp_path: Path) -> None:
    import csv
    import io
    base = tmp_path / "x__y" / "1"
    base.mkdir(parents=True)
    (base / "coderabbit.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "gito.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "pr-agent.json").write_text('{"schema_version":"1","findings":[]}')
    _write_matches(base / "matches.json", [])
    snap = load_pr_snapshot(base, "x__y", 1)
    csv_text = render_summary_csv(build_stats([snap]))
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == [
        "repo", "tool", "findings_after_dedup", "findings_raw", "overlap_with_cr",
        "unique_to_tool", "missed_from_cr", "avg_severity_score", "failed_pr_count",
        "total_pr_count", "categories",
    ]
    assert len(rows) == 4  # header + 3 tools
