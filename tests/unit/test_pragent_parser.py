from __future__ import annotations

import json
from pathlib import Path

from benchmark.tools.pr_agent import parse_pragent_json

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_full_pragent_output() -> None:
    payload = json.loads((FIXTURES / "pragent_output.json").read_text())
    findings = parse_pragent_json(payload)
    assert len(findings) == 3
    tools = {f.tool for f in findings}
    assert tools == {"pr-agent"}
    files = {f.file for f in findings}
    assert "src/api/handlers.py" in files
    assert "src/models/user.py" in files


def test_severity_is_major_by_default() -> None:
    payload = json.loads((FIXTURES / "pragent_output.json").read_text())
    findings = parse_pragent_json(payload)
    assert all(f.severity == "major" for f in findings)


def test_category_inference_from_content() -> None:
    payload = {
        "review": {
            "key_issues_to_review": [
                {"relevant_file": "a.py", "issue_header": "Security", "issue_content": "SQL injection", "start_line": 1, "end_line": 1},
                {"relevant_file": "b.py", "issue_header": "Perf", "issue_content": "N+1 query", "start_line": 1, "end_line": 1},
                {"relevant_file": "c.py", "issue_header": "Style", "issue_content": "naming", "start_line": 1, "end_line": 1},
            ]
        }
    }
    findings = parse_pragent_json(payload)
    cats = {f.file: f.category for f in findings}
    assert cats["a.py"] == "security"
    assert cats["b.py"] == "perf"
    assert cats["c.py"] == "style"


def test_empty_review_returns_empty() -> None:
    assert parse_pragent_json({"review": {"key_issues_to_review": []}}) == []
    assert parse_pragent_json({}) == []


def test_end_before_start_gets_normalized() -> None:
    payload = {
        "review": {
            "key_issues_to_review": [
                {"relevant_file": "a.py", "issue_header": "x", "issue_content": "y", "start_line": 20, "end_line": 5}
            ]
        }
    }
    findings = parse_pragent_json(payload)
    assert findings[0].line_start == 20
    assert findings[0].line_end == 20  # clamped to start
