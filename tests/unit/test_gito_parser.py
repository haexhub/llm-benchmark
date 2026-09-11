from __future__ import annotations

import json
from pathlib import Path

from benchmark.tools.gito import parse_gito_json

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_gito_report() -> None:
    payload = json.loads((FIXTURES / "gito_code-review-report.json").read_text())
    findings = parse_gito_json(payload)
    assert len(findings) == 2
    assert all(f.tool == "gito" for f in findings)
    handlers = [f for f in findings if f.file == "src/api/handlers.py"][0]
    assert handlers.line_start == 144
    assert handlers.line_end == 156
    assert handlers.severity == "major"  # severity=4 → major
    assert handlers.suggestion is not None


def test_severity_map() -> None:
    for raw, expected in [(5, "critical"), (4, "major"), (3, "minor"), (2, "nit"), (1, "info"), (None, "minor")]:
        payload = {"issues": {"a.py": [{"id": 1, "title": "x", "details": "y", "severity": raw, "affected_lines": [{"start_line": 1, "end_line": 1}]}]}}
        findings = parse_gito_json(payload)
        assert findings[0].severity == expected, f"severity {raw} → {findings[0].severity} != {expected}"


def test_category_from_tags() -> None:
    payload = {"issues": {"a.py": [{"id": 1, "title": "x", "details": "y", "severity": 3, "tags": ["security"], "affected_lines": [{"start_line": 1, "end_line": 1}]}]}}
    assert parse_gito_json(payload)[0].category == "security"


def test_empty_report() -> None:
    assert parse_gito_json({"issues": {}}) == []
    assert parse_gito_json({}) == []


def test_issue_without_affected_lines_yields_file_level_finding() -> None:
    payload = {"issues": {"a.py": [{"id": 1, "title": "x", "details": "y", "severity": 3}]}}
    findings = parse_gito_json(payload)
    assert len(findings) == 1
    assert findings[0].line_start == 0
    assert findings[0].line_end == 0
