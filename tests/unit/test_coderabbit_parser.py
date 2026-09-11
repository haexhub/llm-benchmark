from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.coderabbit.parser import parse_cr

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_full_cr_body_yields_findings() -> None:
    body = (FIXTURES / "cr_review_full.md").read_text()
    findings = parse_cr([{"body": body, "id": 1}])
    assert len(findings) >= 3
    tools = {f.tool for f in findings}
    assert tools == {"coderabbit"}
    # At least the "Potential issue" block was picked up as major/bug
    labeled = [f for f in findings if f.severity == "major"]
    assert labeled, "expected at least one major-severity finding from ⚠️ Potential issue"
    assert any(f.file.endswith(".py") for f in findings)
    # Line anchors extracted (142-158)
    assert any(f.line_start == 142 and f.line_end == 158 for f in findings)


def test_parse_empty_cr_body_returns_empty() -> None:
    body = (FIXTURES / "cr_review_empty.md").read_text()
    findings = parse_cr([{"body": body, "id": 2}])
    assert findings == []


def test_parse_unknown_prefix_falls_through_gracefully() -> None:
    # No CR prefix at all — should return [], not raise.
    findings = parse_cr([{"body": "just a random comment", "id": 3}])
    assert findings == []


def test_line_level_comment_uses_hint_when_no_body_anchor() -> None:
    findings = parse_cr(
        [
            {
                "body": "**⚠️ Potential issue**\n\nBad thing here.",
                "path": "src/foo.py",
                "line": 42,
                "id": 4,
            }
        ]
    )
    assert len(findings) == 1
    assert findings[0].file == "src/foo.py"
    assert findings[0].line_start == 42


def test_multiple_blocks_in_one_comment() -> None:
    body = """
`src/a.py`

`10-12`: **⚠️ Potential issue**

First issue

`src/a.py`

`20`: **🧹 Nitpick**

Second issue
"""
    findings = parse_cr([{"body": body, "id": 5}])
    assert len(findings) == 2
    severities = {f.severity for f in findings}
    assert severities == {"major", "nit"}


@pytest.mark.parametrize(
    "prefix, expected_severity",
    [
        ("Potential issue", "major"),
        ("Refactor suggestion", "minor"),
        ("Nitpick", "nit"),
        ("Verification", "info"),
    ],
)
def test_prefix_to_severity_mapping(prefix: str, expected_severity: str) -> None:
    body = f"`src/a.py`\n\n`1-2`: **{prefix}**\n\nSome content"
    findings = parse_cr([{"body": body, "id": 6}])
    assert len(findings) == 1
    assert findings[0].severity == expected_severity
