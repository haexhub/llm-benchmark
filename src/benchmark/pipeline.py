"""High-level pipeline: iterate (Repo, PR) combos through fetch → run → match → report."""
from __future__ import annotations

import concurrent.futures
import json
import logging
from collections.abc import Iterable
from pathlib import Path

from benchmark.coderabbit.parser import parse_cr
from benchmark.github.fetch import fetch_cr_comments, fetch_diff, fetch_pr_refs
from benchmark.matching.aggregator import apply_manual_reviews, load_manual_reviews
from benchmark.matching.dedup import dedup_intra_tool
from benchmark.matching.judge import JudgeClient, make_judge
from benchmark.matching.structural import candidates
from benchmark.models import Classification, Finding, Match, RepoConfig
from benchmark.reports.per_pr import render_per_pr
from benchmark.tools.gito import (
    GITO_REPORT_FILENAME,
    parse_gito_json,
    run_gito_on_pr,
)
from benchmark.tools.pr_agent import parse_pragent_json, run_pragent_on_diff

log = logging.getLogger("benchmark.pipeline")

# 30 min: verified live that gito needs ~15-25 min for a 36-file PR against
# the itemis Qwen endpoint (one LLM call per file, no internal parallelism —
# see research.md R9). The original 600s (10 min) killed both gito and
# pr-agent mid-review on that PR with rc=-1 (timeout), not a code bug.
TOOL_TIMEOUT_SECONDS = 1800
UNCERTAIN_CONFIDENCE_THRESHOLD = 0.6


def pr_dir(runs_dir: Path, repo: RepoConfig, pr: int) -> Path:
    return runs_dir / repo.slug / str(pr)


def _filter(active_repo: str | None, active_pr: int | None, repos: Iterable[RepoConfig]):
    for r in repos:
        if active_repo and f"{r.owner}/{r.name}" != active_repo:
            continue
        for n in r.pr_numbers:
            if active_pr is not None and n != active_pr:
                continue
            yield r, n


def do_fetch(repos: list[RepoConfig], runs_dir: Path, *, force: bool, active_repo: str | None, active_pr: int | None) -> None:
    for repo, pr in _filter(active_repo, active_pr, repos):
        base = pr_dir(runs_dir, repo, pr)
        base.mkdir(parents=True, exist_ok=True)
        patch_path = base / "diff.patch"
        cr_path = base / "coderabbit.json"

        if not patch_path.exists() or force:
            try:
                patch_path.write_text(fetch_diff(repo.owner, repo.name, pr))
                log.info("fetched diff for %s#%d", repo.slug, pr)
            except Exception as exc:  # noqa: BLE001
                _log_fail(base, "fetch:diff", exc)
                continue
        if not cr_path.exists() or force:
            try:
                raw = fetch_cr_comments(repo.owner, repo.name, pr)
                findings = parse_cr(raw)
                cr_path.write_text(_dump_findings(findings))
                log.info("scraped %d CR-findings for %s#%d", len(findings), repo.slug, pr)
            except Exception as exc:  # noqa: BLE001
                _log_fail(base, "fetch:coderabbit", exc)


def do_run(repos: list[RepoConfig], runs_dir: Path, *, force: bool, active_repo: str | None, active_pr: int | None) -> None:
    for repo, pr in _filter(active_repo, active_pr, repos):
        base = pr_dir(runs_dir, repo, pr)
        if not base.exists():
            log.warning("skip %s#%d: fetch not run yet", repo.slug, pr)
            continue

        tasks: dict[str, callable] = {}
        gito_target = base / "gito.json"
        pragent_target = base / "pr-agent.json"

        if not gito_target.exists() or force:
            def _do_gito(_r=repo, _p=pr, _b=base, _t=gito_target):
                return _run_gito(_r, _p, _b, _t)

            tasks["gito"] = _do_gito
        if not pragent_target.exists() or force:
            def _do_pragent(_b=base, _t=pragent_target):
                return _run_pragent(_b, _t)

            tasks["pr-agent"] = _do_pragent

        if not tasks:
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
            futures = {ex.submit(fn): name for name, fn in tasks.items()}
            # as_completed (not futures.items()) so a fast failure is logged
            # immediately instead of waiting behind a slower sibling task —
            # gito can take 10x longer than pr-agent for the same PR, and
            # iterating in submission order would delay (or on external kill,
            # lose) a fast task's failed.log entry until gito's turn came up.
            for fut in concurrent.futures.as_completed(futures):
                name = futures[fut]
                try:
                    fut.result()
                    log.info("%s completed for %s#%d", name, repo.slug, pr)
                except Exception as exc:  # noqa: BLE001
                    _log_fail(base, f"run:{name}", exc)


def _run_gito(repo: RepoConfig, pr: int, base: Path, target: Path) -> None:
    refs = fetch_pr_refs(repo.owner, repo.name, pr)
    clone_dir = base / "gito-clone"
    out_dir = base / "gito-workdir"
    result = run_gito_on_pr(
        repo.owner, repo.name, pr, refs["base_sha"], refs["head_ref"], clone_dir, out_dir,
        timeout=TOOL_TIMEOUT_SECONDS,
    )
    if not result.ok:
        raise RuntimeError(f"gito CLI failed rc={result.returncode}: {result.stderr[:400]}")
    report_path = out_dir / GITO_REPORT_FILENAME
    if not report_path.exists():
        raise RuntimeError(f"gito produced no report at {report_path}")
    with report_path.open() as fh:
        payload = json.load(fh)
    findings = parse_gito_json(payload)
    target.write_text(_dump_findings(findings))


def _run_pragent(base: Path, target: Path) -> None:
    diff_file = base / "diff.patch"
    raw_out = base / "pr-agent-raw.json"
    result = run_pragent_on_diff(diff_file, raw_out, timeout=TOOL_TIMEOUT_SECONDS)
    if not result.ok:
        raise RuntimeError(f"pr-agent CLI failed rc={result.returncode}: {result.stderr[:400]}")
    if not raw_out.exists():
        raise RuntimeError(f"pr-agent produced no JSON output at {raw_out}")
    with raw_out.open() as fh:
        payload = json.load(fh)
    findings = parse_pragent_json(payload)
    target.write_text(_dump_findings(findings))


def do_match(repos: list[RepoConfig], runs_dir: Path, *, force: bool, active_repo: str | None, active_pr: int | None, judge: JudgeClient | None = None) -> None:
    judge = judge or make_judge()
    for repo, pr in _filter(active_repo, active_pr, repos):
        base = pr_dir(runs_dir, repo, pr)
        matches_path = base / "matches.json"
        if matches_path.exists() and not force:
            continue
        try:
            findings_by_tool = _load_findings(base)
        except FileNotFoundError as exc:
            log.warning("skip match for %s#%d: %s", repo.slug, pr, exc)
            continue

        pr_context = f"{repo.owner}/{repo.name}#{pr}"

        # Intra-tool dedup first (updates gito/pr-agent lists)
        for tool_name in ("gito", "pr-agent"):
            group = findings_by_tool.get(tool_name, [])
            deduped, dup = dedup_intra_tool(group, judge, pr_context=pr_context)
            findings_by_tool[tool_name] = deduped
            if dup:
                log.info("dedup: dropped %d duplicates from %s in %s", dup, tool_name, pr_context)

        # Cross-tool matches (CR × each tool)
        cr = findings_by_tool.get("coderabbit", [])
        all_matches: list[Match] = []
        for tool_name in ("gito", "pr-agent"):
            tool = findings_by_tool.get(tool_name, [])
            cands = candidates(cr, tool, same_tool_ok=False)
            for cand in cands:
                a = next(f for f in cr if f.id == cand.a_id)
                b = next(f for f in tool if f.id == cand.b_id)
                try:
                    verdict = judge.evaluate_pair(a, b, pr_context=pr_context)
                except Exception as exc:  # noqa: BLE001
                    log.warning("judge failed on %s/%s in %s: %s", a.id, b.id, pr_context, exc)
                    continue
                classification = _classify(verdict)
                all_matches.append(
                    Match(
                        a_id=cand.a_id,
                        b_id=cand.b_id,
                        structural_overlap_lines=cand.structural_overlap_lines,
                        verdict=verdict,
                        classification=classification,
                    )
                )

        _dump_matches(matches_path, all_matches)
        log.info("wrote %d matches for %s#%d", len(all_matches), repo.slug, pr)


def do_report(repos: list[RepoConfig], runs_dir: Path, reports_dir: Path, *, force: bool, active_repo: str | None, active_pr: int | None) -> None:
    from benchmark.reports.summary import (
        build_stats,
        load_pr_snapshot,
        render_summary_csv,
        render_summary_md,
    )

    per_pr_dir = reports_dir / "per_pr"
    per_pr_dir.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for repo, pr in _filter(active_repo, active_pr, repos):
        base = pr_dir(runs_dir, repo, pr)
        out_path = per_pr_dir / f"{repo.slug}__{pr}.md"
        if (base / "matches.json").exists():
            try:
                findings_by_tool = _load_findings(base)
                matches = _load_matches(base / "matches.json")
                manual = load_manual_reviews(base / "manual_review.json")
                if manual:
                    matches = apply_manual_reviews(matches, manual)
                if not out_path.exists() or force:
                    md = render_per_pr(repo.owner, repo.name, pr, findings_by_tool, matches)
                    out_path.write_text(md)
                    log.info("wrote report %s", out_path)
                snap = load_pr_snapshot(base, repo.slug, pr)
                if snap is not None:
                    snapshots.append(snap)
            except Exception as exc:  # noqa: BLE001
                log.error("report failed for %s#%d: %s", repo.slug, pr, exc)
        else:
            log.warning("skip report for %s#%d: match not run", repo.slug, pr)

    if snapshots:
        stats = build_stats(snapshots)
        (reports_dir / "summary.md").write_text(render_summary_md(stats))
        (reports_dir / "summary.csv").write_text(render_summary_csv(stats))
        log.info("wrote summary for %d PR-run(s) → %s/summary.{md,csv}", len(snapshots), reports_dir)


def _classify(verdict) -> Classification:
    if verdict.confidence < UNCERTAIN_CONFIDENCE_THRESHOLD:
        return "uncertain"
    return "same" if verdict.same else "different"


def _load_findings(base: Path) -> dict[str, list[Finding]]:
    result: dict[str, list[Finding]] = {}
    for tool_name, filename in [
        ("coderabbit", "coderabbit.json"),
        ("gito", "gito.json"),
        ("pr-agent", "pr-agent.json"),
    ]:
        path = base / filename
        if not path.exists():
            result[tool_name] = []
            continue
        with path.open() as fh:
            payload = json.load(fh)
        result[tool_name] = [Finding.model_validate(item) for item in payload.get("findings", [])]
    return result


def _dump_findings(findings: list[Finding]) -> str:
    payload = {
        "schema_version": "1",
        "findings": [json.loads(f.model_dump_json()) for f in findings],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _dump_matches(path: Path, matches: list[Match]) -> None:
    payload = {
        "schema_version": "1",
        "matches": [json.loads(m.model_dump_json()) for m in matches],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _load_matches(path: Path) -> list[Match]:
    with path.open() as fh:
        payload = json.load(fh)
    return [Match.model_validate(item) for item in payload.get("matches", [])]


def _log_fail(base: Path, phase: str, exc: Exception) -> None:
    msg = f"{phase}: {type(exc).__name__}: {exc}\n"
    log.error("failed %s in %s: %s", phase, base, exc)
    with (base / "failed.log").open("a") as fh:
        fh.write(msg)
