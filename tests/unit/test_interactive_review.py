from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from rich.console import Console

from benchmark.models import Finding, JudgeVerdict, Match, RepoConfig
from benchmark.review.interactive import run_review


def _write_findings(path: Path, findings: list[Finding]) -> None:
    payload = {"schema_version": "1", "findings": [json.loads(f.model_dump_json()) for f in findings]}
    path.write_text(json.dumps(payload))


def _write_matches(path: Path, matches: list[Match]) -> None:
    payload = {"schema_version": "1", "matches": [json.loads(m.model_dump_json()) for m in matches]}
    path.write_text(json.dumps(payload))


def _f(tool, fid):
    return Finding(
        id=fid, tool=tool, file="a.py", line_start=10, line_end=10,
        severity="major", category="bug", title="t", body="b",
    )


def _uncertain_verdict():
    return JudgeVerdict(same=False, confidence=0.4, reason="unsure", judge_model="m", prompt_hash="0" * 64)


@pytest.fixture
def setup_pr(tmp_path: Path):
    """Create one PR-run with one uncertain match."""
    repo = RepoConfig(owner="alice", name="proj", pr_numbers=[42])
    base = tmp_path / repo.slug / "42"
    base.mkdir(parents=True)
    cr_id, g_id = uuid4(), uuid4()
    _write_findings(base / "coderabbit.json", [_f("coderabbit", cr_id)])
    _write_findings(base / "gito.json", [_f("gito", g_id)])
    _write_findings(base / "pr-agent.json", [])
    match = Match(a_id=cr_id, b_id=g_id, structural_overlap_lines=1,
                  verdict=_uncertain_verdict(), classification="uncertain")
    _write_matches(base / "matches.json", [match])
    return tmp_path, repo, base, match


def test_same_decision_persists(setup_pr) -> None:
    runs_dir, repo, base, match = setup_pr
    answers = iter(["s", ""])  # decision, note
    prompt_fn = lambda msg, choices: next(answers)
    console = Console(file=io.StringIO(), force_terminal=False)

    run_review(
        [repo], runs_dir,
        console=console,
        active_repo=None, active_pr=None,
        include_confident=False, reviewer="test@x",
        prompt_fn=prompt_fn,
    )

    manual = json.loads((base / "manual_review.json").read_text())
    assert manual["schema_version"] == "1"
    assert len(manual["reviews"]) == 1
    assert manual["reviews"][0]["decision"] == "same"
    assert manual["reviews"][0]["reviewer"] == "test@x"


def test_skip_does_not_persist(setup_pr) -> None:
    runs_dir, repo, base, match = setup_pr
    answers = iter(["k"])
    prompt_fn = lambda msg, choices: next(answers)
    console = Console(file=io.StringIO(), force_terminal=False)

    run_review(
        [repo], runs_dir,
        console=console,
        active_repo=None, active_pr=None,
        include_confident=False, reviewer="test@x",
        prompt_fn=prompt_fn,
    )
    assert not (base / "manual_review.json").exists()


def test_quit_stops_processing(setup_pr) -> None:
    runs_dir, repo, base, match = setup_pr
    answers = iter(["q"])
    prompt_fn = lambda msg, choices: next(answers)
    console = Console(file=io.StringIO(), force_terminal=False)

    run_review(
        [repo], runs_dir,
        console=console,
        active_repo=None, active_pr=None,
        include_confident=False, reviewer="test@x",
        prompt_fn=prompt_fn,
    )
    assert not (base / "manual_review.json").exists()


def test_different_and_unclear(setup_pr) -> None:
    runs_dir, repo, base, match = setup_pr
    # extend with a second uncertain match to test multiple answers in one session
    cr2, g2 = uuid4(), uuid4()
    findings_path = base / "coderabbit.json"
    payload = json.loads(findings_path.read_text())
    payload["findings"].append(json.loads(_f("coderabbit", cr2).model_dump_json()))
    findings_path.write_text(json.dumps(payload))
    gito_path = base / "gito.json"
    payload = json.loads(gito_path.read_text())
    payload["findings"].append(json.loads(_f("gito", g2).model_dump_json()))
    gito_path.write_text(json.dumps(payload))
    matches_path = base / "matches.json"
    payload = json.loads(matches_path.read_text())
    m2 = Match(a_id=cr2, b_id=g2, structural_overlap_lines=1,
               verdict=_uncertain_verdict(), classification="uncertain")
    payload["matches"].append(json.loads(m2.model_dump_json()))
    matches_path.write_text(json.dumps(payload))

    answers = iter(["d", "reason1", "u", "reason2"])
    prompt_fn = lambda msg, choices: next(answers)
    console = Console(file=io.StringIO(), force_terminal=False)

    run_review(
        [repo], runs_dir,
        console=console,
        active_repo=None, active_pr=None,
        include_confident=False, reviewer="test@x",
        prompt_fn=prompt_fn,
    )
    manual = json.loads((base / "manual_review.json").read_text())
    decisions = {r["decision"] for r in manual["reviews"]}
    assert decisions == {"different", "unclear"}


def test_already_reviewed_match_is_skipped(setup_pr) -> None:
    runs_dir, repo, base, match = setup_pr
    (base / "manual_review.json").write_text(
        json.dumps({
            "schema_version": "1",
            "reviews": [{
                "match_id": str(match.id),
                "decision": "same",
                "reviewer": "someone",
                "ts": "2026-09-01T12:00:00+00:00",
            }]
        })
    )
    answers = iter(["s"])  # should not be called
    called = []

    def prompt_fn(msg, choices):
        called.append(msg)
        return next(answers)

    console = Console(file=io.StringIO(), force_terminal=False)
    run_review(
        [repo], runs_dir,
        console=console,
        active_repo=None, active_pr=None,
        include_confident=False, reviewer="test@x",
        prompt_fn=prompt_fn,
    )
    assert called == []  # nothing to review


def test_include_confident_shows_all(setup_pr) -> None:
    runs_dir, repo, base, match = setup_pr
    # Overwrite match to be classification=same, confidence 0.9
    payload = json.loads((base / "matches.json").read_text())
    payload["matches"][0]["classification"] = "same"
    payload["matches"][0]["verdict"]["confidence"] = 0.9
    (base / "matches.json").write_text(json.dumps(payload))

    answers = iter(["s", ""])
    prompt_fn = lambda msg, choices: next(answers)
    console = Console(file=io.StringIO(), force_terminal=False)

    run_review(
        [repo], runs_dir,
        console=console,
        active_repo=None, active_pr=None,
        include_confident=True, reviewer="test@x",
        prompt_fn=prompt_fn,
    )
    manual = json.loads((base / "manual_review.json").read_text())
    assert len(manual["reviews"]) == 1
